#!/usr/bin/env python3
"""Run the actual link-stat aggregation with sparse fields and existing totals."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef uint64_t u64;typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define BIT_ULL(n) (1ULL<<(n))
#define IEEE80211_NUM_TIDS 16
#define for_each_valid_link(s,i) for((i)=0;(i)<16;(i)++) if((s)->valid_links&BIT(i))
struct rate_info { int marker; };
struct sta_bss_parameters { unsigned dtim_period,beacon_interval,flags; };
struct cfg80211_tid_stats { u32 filled;u64 rx_msdu,tx_msdu,tx_msdu_retries,tx_msdu_failed; };
#define FIELDS \
 u64 filled,tx_bytes,rx_bytes,tx_duration,rx_duration,rx_beacon; \
 u32 tx_packets,rx_packets,tx_retries,tx_failed,rx_dropped_misc,beacon_loss_count; \
 u32 expected_throughput,rx_mpdu_count,fcs_err_count,inactive_time; \
 signed char signal,signal_avg; \
 struct rate_info txrate,rxrate; \
 struct sta_bss_parameters bss_param; \
 struct cfg80211_tid_stats *pertid;
struct link_station_info { FIELDS };
struct station_info { FIELDS struct link_station_info *links[16];unsigned valid_links; };
'''

TEST = r'''
#define FIELD(f) BIT_ULL(NL80211_STA_INFO_##f)
static struct station_info query_dispatch(struct station_info sinfo) {
 DISPATCH
 return sinfo;
}
int main(void) {
 struct link_station_info a={0},b={0},c={0};
 struct cfg80211_tid_stats at[17]={0},bt[17]={0},out[17]={0};
 struct station_info s={.valid_links=7,.links={&a,&b,&c},.tx_packets=999,.rx_packets=123,.pertid=out};
 a.filled=b.filled=FIELD(INACTIVE_TIME)|FIELD(TX_BITRATE)|FIELD(RX_BITRATE)|
  FIELD(TX_PACKETS)|FIELD(TX_DURATION)|FIELD(SIGNAL)|FIELD(SIGNAL_AVG)|FIELD(BSS_PARAM);
 a.inactive_time=100;b.inactive_time=10;a.txrate.marker=1;b.txrate.marker=2;
 a.rxrate.marker=3;b.rxrate.marker=4;a.tx_packets=5;b.tx_packets=7;
 a.tx_duration=8;b.tx_duration=9;
 a.signal=-115;b.signal=-105;a.signal_avg=-110;b.signal_avg=-100;
 a.bss_param=(struct sta_bss_parameters){3,100,11};b.bss_param=(struct sta_bss_parameters){1,200,22};
 a.filled|=FIELD(RX_BYTES64);a.rx_bytes=1ULL<<40;
 b.filled|=FIELD(TX_BYTES64);b.tx_bytes=(1ULL<<40)+1;
 a.pertid=at;b.pertid=bt;
 at[5].filled=BIT(NL80211_TID_STATS_RX_MSDU);at[5].rx_msdu=3;
 bt[5].filled=BIT(NL80211_TID_STATS_RX_MSDU);bt[5].rx_msdu=4;
 bt[16].filled=BIT(NL80211_TID_STATS_TX_MSDU_FAILED);bt[16].tx_msdu_failed=9;
 out[5].rx_msdu=999;
 cfg80211_sta_set_mld_sinfo(&s);
 assert(s.tx_packets==12&&s.rx_packets==123&&s.tx_duration==17);
 assert(s.inactive_time==10&&s.txrate.marker==2&&s.rxrate.marker==4);
 assert(s.signal==-105&&s.signal_avg==-100);
 assert(s.bss_param.dtim_period==1&&s.bss_param.beacon_interval==200&&s.bss_param.flags==22);
 assert((s.filled&(FIELD(INACTIVE_TIME)|FIELD(BSS_PARAM)|FIELD(RX_BYTES64)|FIELD(TX_BYTES64)))==
        (FIELD(INACTIVE_TIME)|FIELD(BSS_PARAM)|FIELD(RX_BYTES64)|FIELD(TX_BYTES64)));
 assert(s.rx_bytes==(1ULL<<40)&&s.tx_bytes==(1ULL<<40)+1);
 assert(out[5].rx_msdu==7&&out[16].tx_msdu_failed==9&&out[0].filled==0);
 /* Repeating aggregation must not double existing default-link values. */
 cfg80211_sta_set_mld_sinfo(&s);assert(s.tx_packets==12&&out[5].rx_msdu==7);
 s.links[0]=&b;s.links[1]=&a;cfg80211_sta_set_mld_sinfo(&s);
 assert(s.txrate.marker==2&&s.tx_duration==17);
 /* The newest link supplies no rate. TX/RX choose independent providers. */
 c.filled=FIELD(INACTIVE_TIME);c.inactive_time=1;
 b.filled&=~FIELD(RX_BITRATE);cfg80211_sta_set_mld_sinfo(&s);
 assert(s.inactive_time==1&&s.txrate.marker==2&&s.rxrate.marker==3);
 /* Known time beats an unknown-time fallback; no invalid time is read. */
 a.filled&=~FIELD(INACTIVE_TIME);a.inactive_time=0xdeadbeef;
 s.links[0]=&a;s.links[1]=&b;cfg80211_sta_set_mld_sinfo(&s);
 assert(s.txrate.marker==2&&s.rxrate.marker==3&&s.tx_duration==17);
 struct station_info rates={.valid_links=1,.links={&a}};
 cfg80211_sta_set_mld_sinfo(&rates);
 assert(!(rates.filled&FIELD(INACTIVE_TIME))&&rates.txrate.marker==1&&rates.rxrate.marker==3);
 /* NULL per-TID arrays and valid-link holes are safe. */
 b.pertid=NULL;s.links[0]=NULL;cfg80211_sta_set_mld_sinfo(&s);
 assert(out[5].rx_msdu==7);
 struct station_info empty={.valid_links=2,.rx_packets=77,.signal=-120};
 cfg80211_sta_set_mld_sinfo(&empty);assert(empty.rx_packets==77&&empty.signal==-120&&!empty.filled);
 /* Run the actual SLO call-site condition, which must skip aggregation. */
 struct station_info slo={.valid_links=0,.filled=FIELD(CHAIN_SIGNAL),.signal=-121};
 slo=query_dispatch(slo);assert((slo.filled&FIELD(CHAIN_SIGNAL))&&slo.signal==-121);
 puts("PASS actual link stats: sparse fields, independent rate/time selection, 64-bit totals, no double counts, all TIDs, NULL arrays and SLO dispatch");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    parser.add_argument('--uapi', type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source = (args.backports / 'net/wireless/nl80211.c').read_text()
    uapi = args.uapi or (args.backports / 'include/uapi/linux/nl80211.h')
    # The staging source subset intentionally keeps only changed/common headers.
    if not uapi.exists():
        parser.error('--backports must also contain include/uapi/linux/nl80211.h')
    header = uapi.read_text()
    enums = ''.join(re.search(r'enum ' + name + r'\s*\{.*?\};', header, re.S).group()
                    for name in ('nl80211_sta_info', 'nl80211_tid_stats'))
    dispatch = re.findall(r'if \(sinfo\.valid_links\)\s*\n\s*cfg80211_sta_set_mld_sinfo\(&sinfo\);', source)
    assert len(dispatch) == 2
    function = helper.function(source, 'cfg80211_sta_set_mld_sinfo')
    with tempfile.TemporaryDirectory(prefix='nss-link-stats-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(SHIM + enums + function + TEST.replace('DISPATCH', dispatch[0]))
        subprocess.run(['cc', '-std=gnu11', '-O2', '-g', '-Wall', '-Wextra',
                        '-Werror=maybe-uninitialized', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=15)


if __name__ == '__main__':
    main()
