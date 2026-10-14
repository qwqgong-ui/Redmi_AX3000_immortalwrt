#!/usr/bin/env python3
"""Run descriptor -> QoS reconstruction -> mac80211 CCMP replay checks."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    'nss_mcast', Path(__file__).with_name('test-nss-multicast.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int ieee80211_rx_result;
enum hal_encrypt_type { HAL_ENCRYPT_TYPE_CCMP };
#define RX_FLAG_DECRYPTED (1U << 0)
#define RX_FLAG_IV_STRIPPED (1U << 1)
#define RX_FLAG_PN_VALIDATED (1U << 2)
#define RX_FLAG_MIC_STRIPPED (1U << 3)
#define RX_FLAG_SKIP_MONITOR (1U << 4)
#define RX_FLAG_DUP_VALIDATED (1U << 5)
#define RX_FLAG_ALLOW_SAME_PN (1U << 6)
#define IEEE80211_QOS_CTL_TID_MASK 15
#define IEEE80211_QOS_CTL_A_MSDU_PRESENT 128
#define IEEE80211_QOS_CTL_MESH_CONTROL_PRESENT 256
#define IEEE80211_QOS_CTL_LEN 2
#define IEEE80211_NUM_TIDS 16
#define IEEE80211_RX_AMSDU 1
#define IEEE80211_CCMP_HDR_LEN 8
#define IEEE80211_CCMP_PN_LEN 6
#define IEEE80211_KEY_FLAG_SPP_AMSDU 1
#define AES_BLOCK_SIZE 16
#define RX_CONTINUE 0
#define RX_DROP_U_SHORT_CCMP 1
#define RX_DROP_U_OOM 2
#define RX_DROP_U_REPLAY 3
#define RX_DROP_U_MIC_FAIL 4
#define RX_DROP_U_SHORT_CCMP_MIC 5
#define GFP_ATOMIC 0
#define WARN_ON_ONCE(x) (x)
#define unlikely(x) (x)
#define DP_RX_BUFFER_SIZE 2048
#define EINVAL 22
#define EIO 5
struct hal_rx_desc { u8 tid, pn[6]; bool qos; };
struct ath11k_skb_rxcb {
 struct hal_rx_desc *rx_desc; u8 tid; bool is_mcbc;
 bool is_frag, is_first_msdu, is_last_msdu;
};
struct ieee80211_rx_status { unsigned flag, rx_flags; };
struct sk_buff {
 struct ath11k_skb_rxcb cb;
 struct ieee80211_rx_status status;
 _Alignas(8) u8 storage[256]; u8 *data; size_t len; unsigned priority;
};
struct ieee80211_hdr { u16 frame_control; u8 rest[22]; };
struct napi_struct { int unused; };
struct sk_buff_head { int unused; };
struct rx_attention { int unused; };
struct ath11k_base { struct { unsigned hal_desc_sz; } hw_params; };
struct ath11k { struct ath11k_base *ab; };
struct ieee80211_key {
 struct { unsigned flags; } conf;
 union { struct { u8 rx_pn[17][6]; unsigned replays; void *tfm; } ccmp; } u;
};
struct ieee80211_rx_data {
 struct sk_buff *skb; struct ieee80211_key *key; void *sta;
 int security_idx, seqno_idx; struct { u8 pn[6]; } ccm_gcm;
};
#define ATH11K_SKB_RXCB(s) (&(s)->cb)
#define IEEE80211_SKB_RXCB(s) (&(s)->status)
static bool ieee80211_is_data_qos(u16 fc) { return fc == 0x88; }
static bool ieee80211_is_data(u16 fc) { return fc == 0x08 || fc == 0x88; }
static bool ieee80211_is_mgmt(u16 fc) { (void)fc; return false; }
static bool ieee80211_is_robust_mgmt_frame(struct sk_buff *skb) { (void)skb; return false; }
static bool ieee80211_is_frag(struct ieee80211_hdr *hdr) { (void)hdr; return false; }
static unsigned ieee80211_hdrlen(u16 fc) { return ieee80211_is_data_qos(fc) ? 26 : 24; }
static u8 *ieee80211_get_qos_ctl(struct ieee80211_hdr *hdr) { return (u8 *)hdr + 24; }
static size_t skb_headroom(struct sk_buff *skb) { return skb->data - skb->storage; }
static int pskb_expand_head(struct sk_buff *skb, int n, int tail, int flags)
{ (void)skb; (void)n; (void)tail; (void)flags; assert(0); return -1; }
static u8 *skb_push(struct sk_buff *skb, size_t n)
{ assert(skb_headroom(skb) >= n); skb->data -= n; skb->len += n; return skb->data; }
static u8 *skb_pull(struct sk_buff *skb, size_t n)
{ assert(skb->len >= n); skb->data += n; skb->len -= n; return skb->data; }
static u8 *skb_put(struct sk_buff *skb, size_t n)
{ u8 *end = skb->data + skb->len; assert(end + n <= skb->storage + sizeof(skb->storage)); skb->len += n; return end; }
static bool pskb_may_pull(struct sk_buff *skb, size_t n) { return skb->len >= n; }
static int skb_linearize(struct sk_buff *skb) { (void)skb; assert(0); return -1; }
static int pskb_trim(struct sk_buff *skb, size_t n)
{ assert(n <= skb->len); skb->len = n; return 0; }
static int ath11k_dp_rx_crypto_param_len(struct ath11k *ar, enum hal_encrypt_type type)
{ (void)ar; (void)type; return 8; }
static void ath11k_dp_rx_desc_get_crypto_header(struct ath11k_base *ab,
 struct hal_rx_desc *desc, u8 *hdr, enum hal_encrypt_type type)
{ (void)ab; (void)type; ccmp_pn2hdr(hdr, desc->pn, 1); }
static u16 ath11k_dp_rxdesc_get_mpdu_frame_ctrl(struct ath11k_base *ab, struct hal_rx_desc *desc)
{ (void)ab; return desc->qos ? 0x88 : 0x08; }
static void ath11k_dp_rx_desc_get_dot11_hdr(struct ath11k_base *ab,
 struct hal_rx_desc *desc, struct ieee80211_hdr *hdr)
{ (void)ab; (void)desc; memset(hdr->rest, 0, sizeof(hdr->rest)); hdr->rest[2] = 1; }
static bool ath11k_dp_rx_h_msdu_start_mesh_ctl_present(struct ath11k_base *ab,
 struct hal_rx_desc *desc) { (void)ab; (void)desc; return false; }
static __attribute__((unused)) u8 ath11k_dp_rx_h_mpdu_start_tid(struct ath11k_base *ab, struct hal_rx_desc *desc)
{ (void)ab; return desc->tid; }
static void ath11k_dp_rx_h_ppdu(struct ath11k *ar, struct hal_rx_desc *desc,
 struct ieee80211_rx_status *status) { (void)ar; (void)desc; (void)status; }
static unsigned ath11k_dp_rx_h_msdu_start_msdu_len(struct ath11k_base *ab, struct hal_rx_desc *desc)
{ (void)ab; (void)desc; return 20; }
static void ath11k_dp_rx_null_q_desc_sg_drop(struct ath11k *ar, unsigned len, struct sk_buff_head *list)
{ (void)ar; (void)len; (void)list; assert(0); }
static struct rx_attention *ath11k_dp_rx_get_attention(struct ath11k_base *ab, struct hal_rx_desc *desc)
{ (void)ab; return (void *)desc; }
static bool ath11k_dp_rx_h_attn_msdu_done(struct rx_attention *attention)
{ (void)attention; return true; }
static void ath11k_warn(struct ath11k_base *ab, const char *text)
{ (void)ab; (void)text; assert(0); }
static void __skb_queue_purge(struct sk_buff_head *list) { (void)list; assert(0); }
static bool ath11k_dp_rx_h_msdu_end_first_msdu(struct ath11k_base *ab, struct hal_rx_desc *desc)
{ (void)ab; (void)desc; return true; }
static bool ath11k_dp_rx_h_msdu_end_last_msdu(struct ath11k_base *ab, struct hal_rx_desc *desc)
{ (void)ab; (void)desc; return true; }
static u8 ath11k_dp_rx_h_msdu_end_l3pad(struct ath11k_base *ab, struct hal_rx_desc *desc)
{ (void)ab; (void)desc; return 0; }
static void ccmp_special_blocks(struct sk_buff *skb, u8 *pn, u8 *b, u8 *aad, bool spp)
{ (void)skb; (void)pn; (void)b; (void)aad; (void)spp; assert(0); }
static int ieee80211_aes_ccm_decrypt(void *tfm, u8 *b, u8 *aad, u8 *data, int len, u8 *mic)
{ (void)tfm; (void)b; (void)aad; (void)data; (void)len; (void)mic; assert(0); return -1; }
'''

PIPELINE = r'''
static void ath11k_dp_rx_h_mpdu(struct ath11k *ar, struct sk_buff *skb,
 struct hal_rx_desc *desc, struct ieee80211_rx_status *status, bool *fast, bool from_nss)
{
 (void)desc; (void)from_nss; assert(!*fast && skb->cb.is_mcbc);
 status->flag |= RX_FLAG_DECRYPTED | RX_FLAG_MIC_STRIPPED;
 ath11k_get_dot11_hdr_from_rx_desc(ar, skb, &skb->cb, status, HAL_ENCRYPT_TYPE_CCMP);
}
static int result, security_idx, seqno_idx;
static unsigned delivered_flags;
static struct ieee80211_key key;
static void ath11k_dp_rx_deliver_msdu(struct ath11k *ar, struct napi_struct *napi,
 struct sk_buff *skb, struct ieee80211_rx_status *status)
{
 (void)ar; (void)napi;
 skb->status = *status; delivered_flags = status->flag;
 struct ieee80211_rx_data rx = { .skb = skb, .key = &key, .sta = &key };
 ieee80211_parse_qos(&rx); security_idx = rx.security_idx; seqno_idx = rx.seqno_idx;
 result = ieee80211_crypto_ccmp_decrypt(&rx, 8);
}
'''

CASES = r'''
static void receive(struct ath11k *ar, bool qos, u8 tid, u8 poison, unsigned pn,
 int expected)
{
 struct hal_rx_desc desc = { .qos = qos, .tid = tid,
  .pn = {0, 0, 0, 0, (pn >> 8) & 255, pn & 255} };
 struct sk_buff skb = { .cb = { .rx_desc = &desc, .tid = poison, .is_mcbc = true } };
 skb.data = skb.storage + 128; skb.len = 20;
 ath11k_dp_rx_from_nss(ar, &skb, NULL);
 assert(skb.cb.tid == tid);
 assert(security_idx == (qos ? tid : 0));
 assert(seqno_idx == (qos ? tid : IEEE80211_NUM_TIDS));
 assert(result == expected);
 assert(delivered_flags & RX_FLAG_SKIP_MONITOR);
 assert(!(delivered_flags & (RX_FLAG_PN_VALIDATED | RX_FLAG_DUP_VALIDATED)));
}
int main(void)
{
 struct ath11k_base ab = { .hw_params.hal_desc_sz = 32 }; struct ath11k ar = { .ab = &ab };
 for (unsigned tid = 0; tid < 16; tid++) {
  memset(&key, 0, sizeof(key));
  receive(&ar, true, tid, 0xff, 1, RX_CONTINUE);
  assert(key.u.ccmp.rx_pn[tid][5] == 1);
 }
 memset(&key, 0, sizeof(key));
 receive(&ar, true, 0, 6, 100, RX_CONTINUE);
 receive(&ar, true, 6, 0, 1, RX_CONTINUE);
 receive(&ar, true, 0, 6, 101, RX_CONTINUE);
 receive(&ar, true, 6, 0, 2, RX_CONTINUE);
 receive(&ar, true, 6, 0, 2, RX_DROP_U_REPLAY);
 receive(&ar, true, 6, 0, 1, RX_DROP_U_REPLAY);
 assert(key.u.ccmp.replays == 2);
 memset(&key, 0, sizeof(key));
 receive(&ar, false, 15, 6, 1, RX_CONTINUE);
 assert(key.u.ccmp.rx_pn[0][5] == 1);
 for (unsigned tid = 0; tid < 16; tid++) {
  struct sk_buff skb = { .cb = { .tid = 0xff, .is_mcbc = true } };
  skb.data = skb.storage + 96;
  struct hal_rx_desc *desc = (void *)skb.data;
  *desc = (struct hal_rx_desc) { .qos = true, .tid = tid, .pn = {0, 0, 0, 0, 0, 1} };
  skb.cb.rx_desc = desc;
  struct ieee80211_rx_status status = {0}; struct sk_buff_head list = {0};
  memset(&key, 0, sizeof(key));
  assert(ath11k_dp_rx_h_null_q_desc(&ar, &skb, &status, &list) == 0);
  ath11k_dp_rx_deliver_msdu(&ar, NULL, &skb, &status);
  assert(security_idx == (int)tid && result == RX_CONTINUE);
  assert(seqno_idx == (int)tid);
  assert(key.u.ccmp.rx_pn[tid][5] == 1);
 }
 puts("NSS MCBC and host NULL queue: descriptor TID, QoS reconstruction, independent CCMP PN windows and replay rejection passed");
 return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    args = parser.parse_args()
    dp = (args.backports / 'drivers/net/wireless/ath/ath11k/dp_rx.c').read_text()
    wpa = (args.backports / 'net/mac80211/wpa.c').read_text()
    rx = (args.backports / 'net/mac80211/rx.c').read_text()
    pn = module.function(wpa, 'ccmp_pn2hdr') + module.function(wpa, 'ccmp_hdr2pn')
    typedefs, helpers = SHIM.split('static bool ieee80211_is_data_qos', 1)
    program = typedefs + pn + 'static bool ieee80211_is_data_qos' + helpers
    program += module.function(dp, 'ath11k_get_dot11_hdr_from_rx_desc')
    program += module.function(rx, 'ieee80211_parse_qos')
    program += '\nieee80211_rx_result\n' + module.function(wpa, 'ieee80211_crypto_ccmp_decrypt')
    program += PIPELINE + module.function(dp, 'ath11k_dp_rx_from_nss')
    program += module.function(dp, 'ath11k_dp_rx_h_null_q_desc') + CASES
    with tempfile.TemporaryDirectory(prefix='nss-mcbc-tid-') as temp:
        path = Path(temp) / 'mcbc-tid.c'
        path.write_text(program)
        binary = path.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
            '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
