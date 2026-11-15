#!/usr/bin/env python3
"""Execute PPDU TX rate and retry accounting against QSDK 358 and host-cmn semantics."""
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
#include <string.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)<<(l))&(~0U>>(31-(h))))
#define FIELD_GET(m,v) (((v)&(m))>>__builtin_ctz(m))
#define ath11k_warn(...) ((void)0)
#define max_t(t,a,b) ((t)(a)>(t)(b)?(t)(a):(t)(b))
enum {HTT_PPDU_STATS_TAG_USR_RATE=11,HTT_PPDU_STATS_TAG_USR_COMPLTN_COMMON=12,HTT_PPDU_STATS_TAG_USR_COMPLTN_ACK_BA_STATUS=13};
#define HTT_PPDU_STATS_NON_QOS_TID 16
#define HTT_PPDU_STATS_ACK_BA_INFO_NUM_MSDU_M GENMASK(24,9)
#define HTT_PPDU_STATS_ACK_BA_INFO_TID_NUM GENMASK(31,25)
#define HTT_USR_CMPLTN_IS_AMPDU(v) (((v)>>8)&1)
#define HTT_USR_CMPLTN_LONG_RETRY(v) ((v)&0xf)
#define HTT_USR_CMPLTN_SHORT_RETRY(v) (((v)>>4)&0xf)
#define HTT_USR_RATE_PREAMBLE(v) (((v)>>0)&0xf)
#define HTT_USR_RATE_BW(v) (((v)>>4)&0xf)
#define HTT_USR_RATE_NSS(v) (((v)>>8)&0xf)
#define HTT_USR_RATE_MCS(v) (((v)>>12)&0xf)
#define HTT_USR_RATE_GI(v) (((v)>>16)&0xf)
#define HTT_USR_RATE_DCM(v) (((v)>>20)&1)
#define HTT_USR_RATE_PPDU_TYPE(v) ((v)&0xf)
#define HTT_USR_RATE_MU_GRPID(v) ((v)&0xff)
#define HTT_USR_RATE_USR_POS(v) (((v)>>8)&0xff)
enum {WMI_RATE_PREAMBLE_OFDM,WMI_RATE_PREAMBLE_CCK,WMI_RATE_PREAMBLE_HT,WMI_RATE_PREAMBLE_VHT,WMI_RATE_PREAMBLE_HE};
#define ATH11K_HE_MCS_MAX 11
#define ATH11K_VHT_MCS_MAX 9
#define ATH11K_HT_MCS_MAX 7
enum {RATE_INFO_FLAGS_MCS=1,RATE_INFO_FLAGS_VHT_MCS=2,RATE_INFO_FLAGS_SHORT_GI=4,RATE_INFO_FLAGS_HE_MCS=8};
struct lock {bool held;};
static void spin_lock_bh(struct lock *l){assert(!l->held);l->held=true;}
static void spin_unlock_bh(struct lock *l){assert(l->held);l->held=false;}
static void rcu_read_lock(void){}
static void rcu_read_unlock(void){}
struct rate_info {u16 legacy;u8 mcs,nss,bw,he_gi,he_dcm,he_ru_alloc,flags;};
struct ath11k_sta {struct rate_info txrate,last_txrate;u64 tx_duration;u32 ppdu_tx_retries;};
struct ieee80211_sta {struct ath11k_sta drv_priv;};
struct ath11k_peer {struct ieee80211_sta *sta;};
struct ath11k_base {struct lock base_lock;};
struct ath11k_per_peer_tx_stats {u32 succ_bytes,retry_bytes,failed_bytes,duration;u16 succ_pkts,retry_pkts,failed_pkts,ru_start,ru_tones;u8 ba_fails,ppdu_type,mu_grpid,mu_pos;bool is_ampdu;};
struct ath11k {struct ath11k_base *ab;struct ath11k_per_peer_tx_stats peer_tx_stats;};
struct htt_ppdu_stats_user_rate {u32 info0,info1,rate_flags;u16 ru_start,ru_end;};
struct htt_ppdu_stats_usr_cmpltn_cmn {u8 status,tid_num;u16 sw_peer_id;u32 ack_rssi;u16 mpdu_tried,mpdu_success;u32 flags;};
struct htt_ppdu_stats_usr_cmpltn_ack_ba_status {u32 ppdu_id,info,success_bytes;};
struct htt_ppdu_user_stats {u16 peer_id;u32 tlv_flags;bool rate_stats_updated,delay_ba;struct htt_ppdu_stats_user_rate rate;struct htt_ppdu_stats_usr_cmpltn_cmn cmpltn_cmn;struct htt_ppdu_stats_usr_cmpltn_ack_ba_status ack_ba;};
struct htt_ppdu_stats_common {u32 fes_duration_us;};
struct htt_ppdu_stats {struct htt_ppdu_stats_common common;struct htt_ppdu_user_stats user_stats[4];};
static struct ath11k_base ab;static struct ath11k ar={.ab=&ab};
static struct ieee80211_sta sta;static struct ath11k_peer peer={.sta=&sta};
static struct ath11k_peer *ath11k_peer_find_by_id(struct ath11k *a,u16 id){(void)a;assert(ab.base_lock.held);return id==7?&peer:NULL;}
static struct ath11k_sta *ath11k_sta_to_arsta(struct ieee80211_sta *s){return &s->drv_priv;}
static int ath11k_mac_hw_ratecode_to_legacy_rate(u8 mcs,u8 pre,u8 *idx,u16 *rate){(void)pre;*idx=mcs;*rate=60;return 0;}
static u8 ath11k_mac_he_gi_to_nl80211_he_gi(u8 g){return g;}
static u8 ath11k_mac_phy_he_ru_to_nl80211_he_ru_alloc(u16 r){return (u8)r;}
static u8 ath11k_mac_bw_to_mac80211_bw(u8 bw){return bw;}
'''

CASES = r'''
static u32 rate(u8 pre,u8 bw,u8 nss,u8 mcs){return pre|(u32)(bw+2)<<4|(u32)(nss-1)<<8|(u32)mcs<<12;}
static void ppdu(u8 tid,bool ack_ba,bool cmpltn,u16 tried,u16 success,bool delay_ba,u32 flags){
 struct htt_ppdu_stats s={0};struct htt_ppdu_user_stats *u=&s.user_stats[0];
 u->peer_id=7;u->tlv_flags=BIT(HTT_PPDU_STATS_TAG_USR_RATE);u->rate.rate_flags=flags;u->delay_ba=delay_ba;
 if(cmpltn){u->tlv_flags|=BIT(HTT_PPDU_STATS_TAG_USR_COMPLTN_COMMON);u->cmpltn_cmn.tid_num=tid;u->cmpltn_cmn.mpdu_tried=tried;u->cmpltn_cmn.mpdu_success=success;}
 if(ack_ba){u->tlv_flags|=BIT(HTT_PPDU_STATS_TAG_USR_COMPLTN_ACK_BA_STATUS);u->ack_ba.info=(u32)tid<<25|(u32)success<<9;}
 s.common.fes_duration_us=100;
 ath11k_update_per_peer_tx_stats(&ar,&s,0);
 assert(!ab.base_lock.held);
 if(!cmpltn&&!ack_ba)assert(!u->rate_stats_updated);
 else if(tid<HTT_PPDU_STATS_NON_QOS_TID){
  assert(u->rate_stats_updated);
  ath11k_update_per_peer_tx_stats(&ar,&s,0);
 }
}
int main(void){
 struct ath11k_sta *a=&sta.drv_priv;
 ppdu(0,true,true,10,7,false,rate(WMI_RATE_PREAMBLE_VHT,2,2,7));
 assert(a->txrate.flags==RATE_INFO_FLAGS_VHT_MCS&&a->txrate.mcs==7&&a->txrate.nss==2);
 assert(a->ppdu_tx_retries==3&&a->tx_duration==100);
 ppdu(17,true,true,1,1,false,rate(WMI_RATE_PREAMBLE_OFDM,0,1,0));
 assert(a->txrate.flags==RATE_INFO_FLAGS_VHT_MCS&&!a->txrate.legacy&&a->tx_duration==100);
 ppdu(16,false,true,4,0,false,rate(WMI_RATE_PREAMBLE_CCK,0,1,1));
 assert(a->txrate.mcs==7&&a->ppdu_tx_retries==3);
 ppdu(5,false,true,6,0,false,rate(WMI_RATE_PREAMBLE_VHT,2,1,3));
 assert(a->txrate.mcs==3&&a->txrate.nss==1&&a->ppdu_tx_retries==9);
 ppdu(5,true,true,8,0,true,rate(WMI_RATE_PREAMBLE_VHT,2,1,4));
 assert(a->txrate.mcs==4&&a->ppdu_tx_retries==9);
 ppdu(0,true,true,3,5,false,rate(WMI_RATE_PREAMBLE_VHT,2,1,5));
 assert(a->ppdu_tx_retries==9);
 ppdu(0,false,false,0,0,false,rate(WMI_RATE_PREAMBLE_OFDM,0,1,0));
 assert(a->txrate.mcs==5&&!a->txrate.legacy);
 assert(nss_retries(a,0,0)==9&&nss_retries(a,4,20)==24);
 a->ppdu_tx_retries=0;assert(nss_retries(a,4,20)==24);
 puts("PASS actual PPDU TX accounting: management and non-QoS PPDUs keep the data rate, MPDU retries from completion TLVs, delayed BA excluded, NSS/host retry maximum without double counting");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('ppdu_extract', Path(__file__).with_name('test-nss-control.py'))
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    ath11k = args.backports / 'drivers/net/wireless/ath/ath11k'
    dp_rx = (ath11k / 'dp_rx.c').read_text().replace(
        'static void\nath11k_update_per_peer_tx_stats(', 'static void ath11k_update_per_peer_tx_stats(')
    update = extract.function(dp_rx, 'ath11k_update_per_peer_tx_stats')
    update = update.replace('\n#ifdef CPTCFG_ATH11K_DEBUGFS_STA', '\n#if 0')
    stats = extract.function((ath11k / 'nss.c').read_text(), 'ath11k_nss_update_sta_stats')
    begin = stats.index('\tsinfo->tx_retries =')
    end = stats.index(';', begin) + 1
    retries = ('struct nss_peer_stats {u32 tx_retries;};struct sta_status {u32 retry_count;};\n'
               'struct sinfo_t {u32 tx_retries;};\n'
               'static u32 nss_retries(struct ath11k_sta *arsta,u32 host,u32 nss){\n'
               'struct ieee80211_sta *sta=(struct ieee80211_sta *)arsta;struct sinfo_t s,*sinfo=&s;\n'
               'struct {struct {struct sta_status status_stats;} deflink;} st={.deflink.status_stats.retry_count=host},*stainfo=&st;\n'
               'struct nss_peer_stats ns={.tx_retries=nss};struct {struct {struct nss_peer_stats *nss_stats;} nss;} pr={.nss.nss_stats=&ns},*peer=&pr;\n'
               + stats[begin:end] + '\nreturn sinfo->tx_retries;\n}\n')
    with tempfile.TemporaryDirectory(prefix='ppdu-tx-retries-') as directory:
        test, binary = Path(directory) / 'test.c', Path(directory) / 'test'
        test.write_text(SHIM + update + retries + CASES)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g',
                        '-Wall', '-Wextra', '-Werror', '-Wno-unused-variable',
                        '-Wno-unused-but-set-variable', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                        str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15,
                       env={**os.environ, 'UBSAN_OPTIONS': 'halt_on_error=1'})


if __name__ == '__main__':
    main()
