#!/usr/bin/env python3
"""Execute MU PPDU updates when another user's peer has lost its STA."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
typedef uint32_t u32;
#define ath11k_warn(...) ((void)0)
enum { HAL_RX_SU_MU_CODING_MAX=2, IEEE80211_NUM_TIDS=16,
 HAL_RX_PREAMBLE_MAX=8, HAL_RX_RECEPTION_TYPE_MAX=6, HAL_RX_MAX_NSS=8,
 HAL_RX_MAX_MCS_HE=11, HAL_RX_GI_MAX=4, HAL_RX_BW_MAX=5,
 HAL_RX_RECEPTION_TYPE_MU_OFDMA=2, HAL_RX_RECEPTION_TYPE_MU_OFDMA_MIMO=3,
 HAL_RX_PREAMBLE_11AX=4, HAL_MAX_UL_MU_USERS=4 };
struct rates {unsigned nss_count[8],he_mcs_count[12],gi_count[4],bw_count[5];};
struct ath11k_rx_peer_stats {
 unsigned num_msdu,tcp_msdu_count,udp_msdu_count,other_msdu_count;
 unsigned coding_count[2],tid_count[17],pream_cnt[8],reception_type[6];
 unsigned stbc_count,beamformed_count,ampdu_msdu_count,non_ampdu_msdu_count;
 unsigned num_mpdu_fcs_ok,num_mpdu_fcs_err,dcm_count,ru_alloc_cnt[8],rx_duration;
 struct rates pkt_stats,byte_stats;
};
struct ath11k_sta {struct ath11k_rx_peer_stats *rx_stats;unsigned rssi_comb,rx_duration;};
struct ieee80211_sta {struct ath11k_sta drv_priv;};
struct ath11k_peer {struct ieee80211_sta *sta;};
struct ath11k_base {struct {bool enabled;} nss;};
struct ath11k {struct ath11k_base *ab;};
struct hal_rx_user_status {
 unsigned ast_index,tcp_msdu_count,tcp_ack_msdu_count,udp_msdu_count,other_msdu_count;
 unsigned tid,preamble_type,mpdu_cnt_fcs_ok,mpdu_cnt_fcs_err,ul_ofdma_ru_size;
 unsigned nss,mpdu_ok_byte_count,mcs;
};
struct hal_rx_mon_ppdu_info {
 struct hal_rx_user_status userstats[HAL_MAX_UL_MU_USERS];
 unsigned rssi_comb,ldpc,reception_type,is_stbc,beamformed,dcm,rx_duration,gi,bw,num_users;
};
static bool locked,extended;
static unsigned rate_updates,table_updates;
static struct ath11k_peer peers[2];
static struct ath11k_sta *ath11k_sta_to_arsta(struct ieee80211_sta *sta){assert(locked&&sta);return &sta->drv_priv;}
static struct ath11k_peer *ath11k_peer_find_by_ast(struct ath11k *ar,unsigned ast){
 (void)ar;assert(locked);return ast==11?&peers[0]:ast==12?&peers[1]:NULL;
}
static bool ath11k_debugfs_is_extd_rx_stats_enabled(struct ath11k *ar){(void)ar;return extended;}
static void ath11k_nss_update_sta_rxrate(struct hal_rx_mon_ppdu_info *p,struct ath11k_peer *peer,struct hal_rx_user_status *user){
 (void)p;(void)user;assert(locked&&peer->sta);rate_updates++;
}
static void ath11k_dp_rx_update_peer_rate_table_stats(struct ath11k_rx_peer_stats *stats,struct hal_rx_mon_ppdu_info *p,struct hal_rx_user_status *user,unsigned count){
 (void)p;(void)user;assert(locked&&stats&&count==10);table_updates++;
}
'''

CASES = r'''
int main(void){
 struct ath11k_base ab={0};struct ath11k ar={.ab=&ab};
 const unsigned asts[]={0,0xffff,999,12,11};
 for(unsigned nss=0;nss<2;nss++)for(unsigned ext=0;ext<2;ext++)
 for(unsigned has_stats=0;has_stats<2;has_stats++)for(unsigned i=0;i<5;i++){
  struct ath11k_rx_peer_stats stats={0};
  struct ieee80211_sta sta={.drv_priv.rx_stats=has_stats?&stats:NULL};
  struct hal_rx_mon_ppdu_info ppdu={.num_users=2,.rssi_comb=43,.ldpc=1,
   .reception_type=HAL_RX_RECEPTION_TYPE_MU_OFDMA,.is_stbc=1,.beamformed=1,
   .dcm=1,.rx_duration=97,.gi=1,.bw=2};
  peers[0].sta=&sta;peers[1].sta=NULL;ab.nss.enabled=nss;extended=ext;
  for(unsigned user=0;user<2;user++)ppdu.userstats[user]=(struct hal_rx_user_status){
   .ast_index=user?asts[i]:11,.tcp_msdu_count=1,.tcp_ack_msdu_count=2,.udp_msdu_count=3,
   .other_msdu_count=4,.tid=3,.preamble_type=HAL_RX_PREAMBLE_11AX,
   .mpdu_cnt_fcs_ok=2,.mpdu_cnt_fcs_err=1,.ul_ofdma_ru_size=1,.nss=2,.mpdu_ok_byte_count=100,.mcs=5};
  rate_updates=table_updates=0;locked=true;ath11k_dp_rx_update_peer_mu_stats(&ar,&ppdu);locked=false;
  unsigned valid=1+(asts[i]==11);
  assert(rate_updates==(nss?valid:0));
  assert(table_updates==(ext&&has_stats?valid:0));
  assert(stats.num_msdu==(ext&&has_stats?valid*10:0));
  if(ext&&has_stats){
   assert(stats.tcp_msdu_count==valid*3&&stats.udp_msdu_count==valid*3&&stats.other_msdu_count==valid*4);
   assert(stats.num_mpdu_fcs_ok==valid*2&&stats.rx_duration==valid*97&&sta.drv_priv.rx_duration==stats.rx_duration);
   assert(stats.pkt_stats.nss_count[1]==valid*10&&stats.byte_stats.nss_count[1]==valid*100);
  }
 }
 puts("PASS actual MU PPDU: live main peer with detached/missing/invalid user peer; NSS and extended stats independently enabled, absent stats, valid counter updates");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('mu_extract', Path(__file__).with_name('test-nss-control.py'))
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    source = (args.backports / 'drivers/net/wireless/ath/ath11k/dp_rx.c').read_text()
    functions = ''.join(extract.function(source, name) for name in (
        'ath11k_dp_rx_update_user_stats', 'ath11k_dp_rx_update_peer_mu_stats'))
    with tempfile.TemporaryDirectory(prefix='nss-mu-sta-') as directory:
        test, binary = Path(directory) / 'test.c', Path(directory) / 'test'
        test.write_text(SHIM + functions + CASES)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g',
                        '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                        str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15,
                       env={**os.environ, 'UBSAN_OPTIONS': 'halt_on_error=1'})


if __name__ == '__main__':
    main()
