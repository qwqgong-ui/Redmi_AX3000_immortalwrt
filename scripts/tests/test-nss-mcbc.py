#!/usr/bin/env python3
"""Execute the actual MCBC classification and validation-flag branches."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('nss_mcast', Path(__file__).with_name('test-nss-multicast.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#define RX_FLAG_FAILED_FCS_CRC (1U<<0)
#define RX_FLAG_MMIC_ERROR (1U<<1)
#define RX_FLAG_DECRYPTED (1U<<2)
#define RX_FLAG_IV_STRIPPED (1U<<3)
#define RX_FLAG_PN_VALIDATED (1U<<4)
#define RX_FLAG_MMIC_STRIPPED (1U<<5)
#define RX_FLAG_MIC_STRIPPED (1U<<6)
#define RX_FLAG_ICV_STRIPPED (1U<<7)
#define RX_FLAG_SKIP_MONITOR (1U<<8)
#define RX_FLAG_DUP_VALIDATED (1U<<9)
#define DP_RX_MPDU_ERR_FCS 1
#define DP_RX_MPDU_ERR_TKIP_MIC 2
struct hal_rx_desc { bool mcbc; unsigned char tid; };
struct ath11k_skb_rxcb { struct hal_rx_desc *rx_desc;bool is_mcbc; unsigned char tid; };
struct sk_buff { struct ath11k_skb_rxcb cb; };
struct ieee80211_rx_status { uint32_t flag; };
struct napi_struct { int unused; };
struct ath11k_base { int unused; };
struct ath11k { struct ath11k_base *ab; };
#define ATH11K_SKB_RXCB(s) (&(s)->cb)
static bool ath11k_dp_rx_h_attn_is_mcbc(struct ath11k_base *ab,struct hal_rx_desc *desc) { (void)ab;return desc->mcbc; }
static unsigned char ath11k_dp_rx_h_mpdu_start_tid(struct ath11k_base *ab,struct hal_rx_desc *desc) { (void)ab;return desc->tid; }
static unsigned delivered_flags;
static void ath11k_dp_rx_h_ppdu(struct ath11k *ar,struct hal_rx_desc *desc,struct ieee80211_rx_status *status) { (void)ar;(void)desc;(void)status; }
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--backports', type=Path, required=True)
    args = p.parse_args()
    source = (args.backports / 'drivers/net/wireless/ath/ath11k/dp_rx.c').read_text()
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    mpdu = module.function(source, 'ath11k_dp_rx_h_mpdu')
    selection = mpdu[mpdu.index('rxcb = ATH11K_SKB_RXCB(msdu);'):mpdu.index('if (rxcb->is_mcbc)')]
    flag_start = mpdu.index('rx_status->flag &=')
    validation = mpdu[flag_start:mpdu.index('ath11k_dp_rx_h_csum_offload', flag_start)]
    assert 'bool from_nss' in mpdu
    assert re.search(r'ath11k_dp_rx_h_mpdu\(ar, msdu, rx_desc, rx_status, fast_rx, false\)', source)
    assert re.search(r'ath11k_dp_rx_h_mpdu\(ar, msdu, desc, status, &fast_rx, false\)', source)
    shim = SHIM + r'''
static void ath11k_dp_rx_h_mpdu(struct ath11k *ar,struct sk_buff *msdu,
 struct hal_rx_desc *rx_desc,struct ieee80211_rx_status *rx_status,
 bool *fast_rx,bool from_nss) {
 struct ath11k_skb_rxcb *rxcb;bool fill_crypto_hdr=false,is_decrypted=true;
 unsigned err_bitmap=0;(void)fast_rx;
''' + selection + validation + r'''
}
static void ath11k_dp_rx_deliver_msdu(struct ath11k *ar,struct napi_struct *napi,
 struct sk_buff *msdu,struct ieee80211_rx_status *status) {
 (void)ar;(void)napi;(void)msdu;delivered_flags=status->flag;
}
'''
    body = module.function(source, 'ath11k_dp_rx_from_nss')
    cases = r'''
int main(void) {
 struct ath11k_base ab={0};struct ath11k ar={.ab=&ab};struct napi_struct napi={0};
 for(int from=0;from<2;from++)for(int meta=0;meta<2;meta++)for(int attention=0;attention<2;attention++) {
  struct hal_rx_desc desc={.mcbc=attention};struct sk_buff skb={.cb={.rx_desc=&desc,.is_mcbc=meta}};
  struct ieee80211_rx_status status={.flag=RX_FLAG_PN_VALIDATED|RX_FLAG_IV_STRIPPED};bool fast=false;
  bool group=from?meta:attention;
  ath11k_dp_rx_h_mpdu(&ar,&skb,&desc,&status,&fast,from);
  assert(skb.cb.is_mcbc==group);
  assert(!!(status.flag&RX_FLAG_DECRYPTED));
  assert(!!(status.flag&RX_FLAG_PN_VALIDATED)==!group);
  assert(!!(status.flag&RX_FLAG_IV_STRIPPED)==!group);
  assert(!!(status.flag&RX_FLAG_MIC_STRIPPED)==group);
  assert(!!(status.flag&RX_FLAG_ICV_STRIPPED)==group);
 }
 for(int group=0;group<2;group++) {
  struct hal_rx_desc desc={.mcbc=!group,.tid=7};struct sk_buff skb={.cb={.rx_desc=&desc,.is_mcbc=group,.tid=3}};
  ath11k_dp_rx_from_nss(&ar,&skb,&napi);
  assert(skb.cb.tid==7);
  assert(!!(delivered_flags&RX_FLAG_SKIP_MONITOR));
  assert(!!(delivered_flags&RX_FLAG_DUP_VALIDATED)==!group);
  assert(!!(delivered_flags&RX_FLAG_PN_VALIDATED)==!group);
 }
 puts("ath11k MCBC: NSS metadata, host descriptor, crypto retention, PN flags and duplicate validation passed");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='nss-mcbc-') as temp:
        path = Path(temp) / 'mcbc.c'
        path.write_text(shim + body + cases)
        binary = path.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
            '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
