#!/usr/bin/env python3
"""Exercise actual TX and AP VLAN UP entrances after a partial key install."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location("extractor", Path(__file__).with_name("test-nss-control.py"))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;typedef uint16_t u16;typedef int nss_tx_status_t;
#define READ_ONCE(x) (x)
#define smp_load_acquire(p) (*(p))
#define IEEE80211_TX_CTL_HW_80211_ENCAP 1
#define IEEE80211_TX_CTL_REQ_TX_STATUS 2
#define IEEE80211_TX_INTFL_NL80211_FRAME_TX 4
#define WMI_TLV_SERVICE_QOS_NULL_FRAME_TX_OVER_WMI 0
#define ATH11K_FLAG_MONITOR_VDEV_CREATED 0
#define ATH11K_SKB_CIPHER_SET 1
#define ATH11K_SKB_HW_80211_ENCAP 2
#define ATH11K_SKB_TX_STATUS 4
#define NL80211_IFTYPE_AP_VLAN 4
#define NL80211_IFTYPE_MESH_POINT 5
#define IEEE80211_FCTL_STYPE 0xf0
#define FIELD_GET(mask,v) (((v)&(mask))>>4)
#define GFP_ATOMIC 1
#define NSS_IF_OPEN 1
#define NSS_TX_SUCCESS 0
#define unlikely(x) (x)
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define test_bit(n,p) (!!(*(p)&(1UL<<(n))))
struct ieee80211_hdr { u16 frame_control; };
static bool ieee80211_is_data(u16 fc) { return (fc&0xc)==8; }
static bool ieee80211_is_mgmt(u16 fc) { return (fc&0xc)==0; }
static bool ieee80211_is_qos_nullfunc(u16 fc) { return fc==0xc8; }
static bool ieee80211_is_probe_resp(u16 fc) { return fc==0x50; }
struct ath11k_vif;struct ieee80211_vif { int type;struct ath11k_vif *priv; };
struct ieee80211_key_conf { u32 cipher; };
struct ieee80211_sta { int unused; };struct ath11k_sta { int unused; };
struct ieee80211_tx_control { struct ieee80211_sta *sta; };
struct ieee80211_tx_info { struct { struct ieee80211_vif *vif;struct ieee80211_key_conf *hw_key; } control;u32 flags,status_data; };
struct ath11k_skb_cb { struct ieee80211_vif *vif;u32 cipher,flags; };
struct sk_buff { void *data;struct ath11k_skb_cb cb;struct ieee80211_tx_info info; };
#define ATH11K_SKB_CB(skb) (&(skb)->cb)
#define IEEE80211_SKB_CB(skb) (&(skb)->info)
struct ath11k_mgmt_frame_stats { unsigned tx_fail_cnt[16],tx_succ_cnt[16]; };
struct ath11k_base { struct { bool enabled; } nss;struct { unsigned long svc_map[1]; } wmi_ab; };
struct ieee80211_hw { struct ath11k *priv; };
struct ath11k { struct ath11k_base *ab;struct ieee80211_hw *hw;int data_lock;unsigned long monitor_flags; };
struct ath11k_vif { struct ath11k *ar;struct ieee80211_vif *vif;struct ath11k_mgmt_frame_stats mgmt_stats;struct { bool key_failed,ext_vdev_up,created,format_ready,format_failed;struct ath11k_vif *ap_vif;u32 if_num;void *ctx; } nss; };
struct nss_if_open { int unused; };
struct nss_wifi_ext_vdev_msg { char bytes[32]; };
struct nss_wifi_vdev_msg { char bytes[32]; };
static unsigned freed,wmi_tx,nss_tx,dp_tx,open_requests;
static struct ath11k_vif *ath11k_vif_to_arvif(struct ieee80211_vif *v) { return v->priv; }
static struct ath11k_sta *ath11k_sta_to_arsta(struct ieee80211_sta *s) { (void)s;return NULL; }
static void ieee80211_free_txskb(struct ieee80211_hw *h,struct sk_buff *s) { (void)h;(void)s;freed++; }
static int ath11k_mac_tx_over_wmi(struct ath11k *a,struct sk_buff *s,bool probe) { (void)a;(void)s;(void)probe;wmi_tx++;return 0; }
static int ath11k_nss_tx(struct ath11k_vif *v,struct sk_buff *s) { (void)v;(void)s;nss_tx++;return 0; }
static int ath11k_dp_tx(struct ath11k *a,struct ath11k_vif *v,struct ath11k_sta *sta,struct sk_buff *s) { (void)a;(void)v;(void)sta;(void)s;dp_tx++;return 0; }
static void spin_lock_bh(int *l) { assert(!*l);*l=1; }
static void spin_unlock_bh(int *l) { assert(*l);*l=0; }
static void *kzalloc(size_t n,int gfp) { assert(gfp==GFP_ATOMIC);return calloc(1,n); }
static void kfree(void *p) { free(p); }
static void nss_wifi_ext_vdev_msg_init(struct nss_wifi_ext_vdev_msg *m,u32 id,int type,size_t size,void *cb,void *ctx) { (void)m;(void)id;(void)size;(void)cb;(void)ctx;assert(type==NSS_IF_OPEN); }
static int nss_wifi_ext_vdev_tx_msg_sync(void *ctx,struct nss_wifi_ext_vdev_msg *m) { (void)ctx;(void)m;open_requests++;return NSS_TX_SUCCESS; }
'''

MAIN = r'''
int main(void) {
 struct ath11k_base ab={.nss.enabled=true,.wmi_ab.svc_map={1}};
 struct ath11k ar={.ab=&ab};struct ieee80211_hw hw={.priv=&ar};ar.hw=&hw;
 struct ieee80211_vif vif={0};struct ath11k_vif av={.ar=&ar,.vif=&vif};vif.priv=&av;
 struct ieee80211_hdr hdr={.frame_control=0xc8};struct sk_buff skb={.data=&hdr,.info.control.vif=&vif};
 struct ieee80211_tx_control control={0};
 av.nss.key_failed=true;
 ath11k_mac_op_tx(&hw,&control,&skb);assert(freed==1&&!wmi_tx&&!nss_tx&&!dp_tx);
 hdr.frame_control=8;ath11k_mac_op_tx(&hw,&control,&skb);assert(freed==2&&!wmi_tx&&!nss_tx);
 skb.info.flags=IEEE80211_TX_CTL_HW_80211_ENCAP;ath11k_mac_op_tx(&hw,&control,&skb);assert(freed==3&&!nss_tx);
 skb.info.flags=0;hdr.frame_control=0xc0;ath11k_mac_op_tx(&hw,&control,&skb);assert(wmi_tx==1&&freed==3);
 av.nss.key_failed=false;hdr.frame_control=0xc8;ath11k_mac_op_tx(&hw,&control,&skb);assert(wmi_tx==2);
 hdr.frame_control=8;ath11k_mac_op_tx(&hw,&control,&skb);assert(nss_tx==1);
 struct ath11k_vif parent={.nss.key_failed=true};av.nss.ap_vif=&parent;
 ath11k_mac_op_tx(&hw,&control,&skb);assert(freed==4&&nss_tx==1);
 vif.type=NL80211_IFTYPE_AP_VLAN;av.nss.ext_vdev_up=true;
 assert(ath11k_nss_ext_vdev_up(&av)==-ESHUTDOWN&&!open_requests);
 parent.nss.key_failed=false;assert(!ath11k_nss_ext_vdev_up(&av)&&!open_requests);
 av.nss.ext_vdev_up=false;assert(!ath11k_nss_ext_vdev_up(&av)&&open_requests==1);
 ab.nss.enabled=false;av.nss.key_failed=true;hdr.frame_control=8;ath11k_mac_op_tx(&hw,&control,&skb);assert(dp_tx==1);
 puts("PASS actual key failure TX gates: QoS-null/WMI, payload, Ethernet encapsulation, teardown management, AP VLAN parent/UP and disabled NSS");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", type=Path, required=True)
    args = parser.parse_args()
    ath = args.backports / "drivers/net/wireless/ath/ath11k"
    nss, mac = (ath / "nss.c").read_text(), (ath / "mac.c").read_text()
    bodies = extractor.function(nss, "ath11k_nss_vdev_key_failed")
    bodies += extractor.function(nss, "ath11k_nss_ext_vdev_up")
    bodies += extractor.function(mac, "ath11k_mac_op_tx")
    with tempfile.TemporaryDirectory(prefix="nss-key-tx-") as temp:
        path, binary = Path(temp) / "test.c", Path(temp) / "test"
        path.write_text(SHIM + bodies + MAIN)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                        str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
