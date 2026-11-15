#!/usr/bin/env python3
"""Run the real native encapsulation and HTT exception blocks with skb helpers."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "extract_nss", Path(__file__).with_name("test-nss-control.py"))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;
#define __packed __attribute__((packed))
#define __cpu_to_le16(v) (v)
#define cpu_to_be16(v) __builtin_bswap16((u16)(v))
#define IEEE80211_QOS_CTL_LEN 2
#define IEEE80211_STYPE_QOS_DATA 0x80
#define IEEE80211_OFFLOAD_ENCAP_ENABLED 1
#define IEEE80211_TX_CTL_HW_80211_ENCAP 1
#define ETH_P_PAE 0x888e
#define HTT_META_DATA_ALIGNMENT 8
#define HTT_TCL_META_DATA_VALID_HTT 0x10
#define HAL_TCL_DATA_CMD_INFO1_TO_FW 0x20
#define FIELD_PREP(m,v) ((m)*(v))
#define ATH11K_FLAG_RAW_MODE 0
#define ATH11K_FLAG_HW_CRYPTO_DISABLED 1
#define HAL_ENCRYPT_TYPE_OPEN 0
#define test_bit(n,p) (!!(*(p)&(1UL<<(n))))
#define unlikely(v) (v)
#define ALIGN(v,n) (((v)+(n)-1)&~((n)-1))
#define atomic_inc(p) (++*(p))
enum { HAL_TCL_ENCAP_TYPE_RAW,HAL_TCL_ENCAP_TYPE_NATIVE_WIFI,
 HAL_TCL_ENCAP_TYPE_ETHERNET,HAL_TCL_ENCAP_TYPE_802_3 };
struct ieee80211_hdr { u16 frame_control;u8 rest[22]; };
struct ieee80211_tx_info { struct { unsigned flags;void *hw_key; } control; };
struct sk_buff { _Alignas(8) u8 storage[256];u8 *data;size_t len;u16 protocol;struct ieee80211_tx_info info; };
struct ieee80211_vif { unsigned offload_flags; };
struct ath11k_vif { struct ieee80211_vif *vif; };
struct ath11k_base { unsigned long dev_flags;struct { struct { unsigned misc_fail; } tx_err; } soc_stats; };
struct ath11k { struct ath11k_base *ab; };
struct hal_tx_info { unsigned encap_type,encrypt_type,pkt_offset,meta_data_flags,flags0; };
static unsigned cow_calls,fail_cow;
static bool ieee80211_is_data_qos(u16 fc) { return (fc&0x8c)==0x88; }
static bool ieee80211_is_qos_nullfunc(u16 fc) { return (fc&0xfc)==0xc8; }
static bool ieee80211_has_protected(u16 fc) { return fc&0x4000; }
static u8 *ieee80211_get_qos_ctl(struct ieee80211_hdr *h) { return (u8 *)h+24; }
static u8 *skb_pull(struct sk_buff *s,unsigned n) { assert(s->len>=n);s->data+=n;s->len-=n;return s->data; }
static u8 *skb_push(struct sk_buff *s,unsigned n) { assert(s->data>=s->storage+n);s->data-=n;s->len+=n;return s->data; }
static int skb_cow_head(struct sk_buff *s,unsigned n) { assert(s->data>=s->storage+n);cow_calls++;return cow_calls==fail_cow?-ENOMEM:0; }
'''

WRAPPER = r'''
static int transmit(struct ath11k *ar,struct ath11k_vif *arvif,
 struct sk_buff *skb,struct hal_tx_info *out) {
 struct ath11k_base *ab=ar->ab;
 struct ieee80211_tx_info *info=&skb->info;
 struct ieee80211_hdr *hdr=(void *)skb->data;
 struct hal_tx_info ti=*out;
 bool is_diff_encap=false;u8 align_pad,htt_meta_size=0;int ret;
 BLOCK
 *out=ti;return 0;
fail_remove_idr:
 return ret;
}
'''

TEST = r'''
static struct sk_buff packet(unsigned fc,bool pae,unsigned misalign) {
 struct sk_buff skb={.len=46,.protocol=pae?cpu_to_be16(ETH_P_PAE):0};
 /* The caller repairs data after returning this value object. */
 memset(skb.storage,0x5a,sizeof(skb.storage));
 memcpy(skb.storage+64+misalign,&(u16){fc},2);
 return skb;
}
int main(void) {
 struct ath11k_base ab={0};struct ath11k ar={.ab=&ab};
 struct ieee80211_vif vif={0};struct ath11k_vif av={.vif=&vif};
 for(unsigned offload=0;offload<2;offload++)for(unsigned pae=0;pae<2;pae++)
 for(unsigned null=0;null<2;null++)for(unsigned misalign=0;misalign<8;misalign+=2) {
  unsigned fc=null?0xc8:0x88;
  struct sk_buff skb=packet(fc,pae,misalign);skb.data=skb.storage+64+misalign;
  u8 original[46];memcpy(original,skb.data,sizeof(original));
  vif.offload_flags=offload;struct hal_tx_info ti={.encap_type=HAL_TCL_ENCAP_TYPE_NATIVE_WIFI};
  cow_calls=fail_cow=0;
  assert(!transmit(&ar,&av,&skb,&ti));
  bool exception=offload&&(pae||null);
  if(exception) {
   assert(ti.encap_type==HAL_TCL_ENCAP_TYPE_RAW&&ti.encrypt_type==HAL_ENCRYPT_TYPE_OPEN);
   assert(ti.flags0&HAL_TCL_DATA_CMD_INFO1_TO_FW);
   assert(ti.meta_data_flags&HTT_TCL_META_DATA_VALID_HTT);
   assert(!((uintptr_t)skb.data&7)&&cow_calls==2);
   assert(skb.len-ti.pkt_offset==46&&!memcmp(skb.data+ti.pkt_offset,original,46));
   struct htt_tx_msdu_desc_ext *desc=(void *)skb.data;
   assert(desc->valid_encrypt_type&&!desc->encrypt_type&&desc->host_tx_desc_pool);
  } else {
   assert(ti.encap_type==HAL_TCL_ENCAP_TYPE_NATIVE_WIFI&&!ti.pkt_offset&&!cow_calls);
   struct ieee80211_hdr *h=(void *)skb.data;
   assert(skb.len==44&&!(h->frame_control&IEEE80211_STYPE_QOS_DATA));
   assert(!memcmp(skb.data+24,original+26,20));
  }
 }
 /* Existing software-encryption exception is independent of offload mode. */
 struct sk_buff encrypted=packet(0x4088,false,0);encrypted.data=encrypted.storage+64;
 struct hal_tx_info ti={.encap_type=HAL_TCL_ENCAP_TYPE_NATIVE_WIFI};vif.offload_flags=0;
 cow_calls=fail_cow=0;assert(!transmit(&ar,&av,&encrypted,&ti));
 assert(ti.encap_type==HAL_TCL_ENCAP_TYPE_RAW&&(ti.flags0&HAL_TCL_DATA_CMD_INFO1_TO_FW));
 /* Neither metadata allocation failure may reach descriptor submission. */
 for(unsigned failure=1;failure<=2;failure++) {
  struct sk_buff skb=packet(0xc8,false,0);skb.data=skb.storage+64;vif.offload_flags=1;
  struct hal_tx_info out={.encap_type=HAL_TCL_ENCAP_TYPE_NATIVE_WIFI};
  fail_cow=failure;cow_calls=0;assert(transmit(&ar,&av,&skb,&out)==-ENOMEM);
  assert(out.encap_type==HAL_TCL_ENCAP_TYPE_NATIVE_WIFI&&!out.flags0&&cow_calls==failure);
 }
 puts("PASS real TX blocks/helpers: ordinary native QoS, EAPOL/QoS-null RAW exceptions, actual HTT layout/alignment, payload retention and allocation failures");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", type=Path, required=True)
    args = parser.parse_args()
    ath = args.backports / "drivers/net/wireless/ath/ath11k"
    source = (ath / "dp_tx.c").read_text()
    body = extractor.function(source, "ath11k_dp_tx")
    start, end = body.index("switch (ti.encap_type)"), body.index("ti.data_len =")
    block = body[start:end]
    descriptor = re.search(r"struct htt_tx_msdu_desc_ext \{.*?\n\}[^;]*;",
                           (ath / "dp_tx.h").read_text(), re.S).group()
    helpers = "".join(extractor.function(source, name) for name in
                      ("ath11k_dp_tx_encap_nwifi", "ath11k_dp_metadata_align_skb",
                       "ath11k_dp_prepare_htt_metadata"))
    with tempfile.TemporaryDirectory(prefix="nss-tx-exceptions-") as directory:
        root = Path(directory)
        cfile, binary = root / "tx.c", root / "tx"
        cfile.write_text(SHIM + descriptor + helpers + WRAPPER.replace("BLOCK", block) + TEST)
        subprocess.run(["cc", "-std=gnu11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie", str(cfile), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15,
                       env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})


if __name__ == "__main__":
    main()
