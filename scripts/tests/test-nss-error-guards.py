#!/usr/bin/env python3
"""Exercise real AQL input, EEE translation and late-kickout error paths."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

COMMON = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/types.h>
'''
AQL = r'''
#define __user
struct file {};
static bool aql_disable,copy_failure;
static int copy_from_user(void *to,const void *from,size_t n) { if(copy_failure)return 1;memcpy(to,from,n);return 0; }
static void static_branch_enable(bool *p) { *p=true; }
static void static_branch_disable(bool *p) { *p=false; }
'''
AQL_TEST = r'''
int main(void) {
 loff_t pos=0;struct file file;
 assert(aql_enable_write(&file,"",0,&pos)==-EINVAL);
 assert(aql_enable_write(&file,"0",1,&pos)==1&&aql_disable);
 assert(aql_enable_write(&file,"1",1,&pos)==1&&!aql_disable);
 assert(aql_enable_write(&file,"0\n",2,&pos)==2&&aql_disable);
 assert(aql_enable_write(&file,"1x",2,&pos)==-EINVAL&&aql_disable);
 assert(aql_enable_write(&file,"1xx",3,&pos)==-EINVAL&&aql_disable);
 copy_failure=true;
 assert(aql_enable_write(&file,"1",1,&pos)==-EFAULT&&aql_disable);
 puts("PASS actual AQL parser: empty/single-byte/newline/capacity/failed-copy");
}
'''
EEE = r'''
#define LINUX_VERSION_CODE 0x060c00
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define SW_OK 0
#define NSS_DP_ACL_DEV_ID 0
#define netdev_dbg(...) ((void)0)
enum { FAL_PHY_EEE_10BASE_T=1,FAL_PHY_EEE_100BASE_T=2,FAL_PHY_EEE_1000BASE_T=4,
 FAL_PHY_EEE_2500BASE_T=8,FAL_PHY_EEE_5000BASE_T=16,FAL_PHY_EEE_10000BASE_T=32 };
enum { SUPPORTED_10baseT_Full=2,SUPPORTED_100baseT_Full=8,SUPPORTED_1000baseT_Full=32,
 SUPPORTED_2500baseX_Full=128,SUPPORTED_10000baseT_Full=512 };
typedef int sw_error_t;
typedef struct { uint32_t capability,advertisement,link_partner_advertisement;
 unsigned enable,eee_status,lpi_tx_enable,lpi_sleep_timer; } fal_port_eee_cfg_t;
struct nss_dp_dev { unsigned macid; };
struct net_device { struct nss_dp_dev priv; };
struct ethtool_keee { unsigned long supported[1],advertised[1],lp_advertised[1];
 unsigned eee_enabled,eee_active,tx_lpi_enabled,tx_lpi_timer; };
static fal_port_eee_cfg_t input;
static int fal_result;
static void *netdev_priv(struct net_device *dev) { return &dev->priv; }
static int fal_port_interface_eee_cfg_get(unsigned dev,unsigned port,fal_port_eee_cfg_t *out) { *out=input;return fal_result; }
static void ethtool_convert_legacy_u32_to_link_mode(unsigned long *to,uint32_t from) { *to=from; }
'''
EEE_TEST = r'''
int main(void) {
 struct net_device dev={.priv.macid=1};struct ethtool_keee out;
 memset(&out,0xa5,sizeof(out));
 assert(!nss_dp_get_eee(&dev,&out));
 assert(!out.supported[0]&&!out.advertised[0]&&!out.lp_advertised[0]);
 input.capability=FAL_PHY_EEE_1000BASE_T;
 input.advertisement=FAL_PHY_EEE_100BASE_T;
 input.link_partner_advertisement=FAL_PHY_EEE_10BASE_T;
 assert(!nss_dp_get_eee(&dev,&out));
 assert(out.supported[0]==SUPPORTED_1000baseT_Full);
 assert(out.advertised[0]==SUPPORTED_100baseT_Full&&out.lp_advertised[0]==SUPPORTED_10baseT_Full);
 fal_result=1;assert(nss_dp_get_eee(&dev,&out)==-EIO);
 puts("PASS actual EEE: empty masks, distinct bitsets and failed FAL query");
}
'''
WMI = r'''
struct ieee80211_sta { unsigned reports; };
struct hw { struct ieee80211_sta *sta; };
struct ath11k { struct hw *hw; };
struct ath11k_pdev { struct ath11k *ar; };
struct ath11k_base { unsigned num_radios;struct ath11k_pdev *pdevs_active[3]; };
struct sk_buff {};
struct wmi_peer_sta_kickout_arg { unsigned char mac_addr[6]; };
static int rcu_depth;static bool malformed;
#define rcu_dereference(x) (x)
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define ATH11K_DBG_WMI 1
static void rcu_read_lock(void) { rcu_depth++; }
static void rcu_read_unlock(void) { assert(rcu_depth==1);rcu_depth--; }
static int ath11k_pull_peer_sta_kickout_ev(struct ath11k_base *ab,struct sk_buff *skb,struct wmi_peer_sta_kickout_arg *arg) { return malformed; }
static struct ieee80211_sta *ieee80211_find_sta_by_ifaddr(struct hw *hw,const unsigned char *a,void *b) { assert(rcu_depth);return hw->sta; }
static void ieee80211_report_low_ack(struct ieee80211_sta *sta,unsigned count) { assert(rcu_depth&&count==10);sta->reports++; }
'''
WMI_TEST = r'''
int main(void) {
 struct ieee80211_sta sta={0};struct hw hw={.sta=&sta};struct ath11k ar={&hw};
 struct ath11k_pdev pdev={&ar},empty={0};struct ath11k_base ab={.num_radios=3,.pdevs_active={&pdev,NULL,&empty}};
 struct sk_buff skb;
 ath11k_peer_sta_kickout_event(&ab,&skb);assert(sta.reports==1&&!rcu_depth);
 hw.sta=NULL;ath11k_peer_sta_kickout_event(&ab,&skb);assert(sta.reports==1&&!rcu_depth);
 ab.num_radios=0;ath11k_peer_sta_kickout_event(&ab,&skb);assert(!rcu_depth);
 malformed=true;ath11k_peer_sta_kickout_event(&ab,&skb);assert(!rcu_depth);
 puts("PASS actual kickout: active radio, missing STA, inactive/empty radio and malformed event without DP cleanup");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--backports', type=Path)
    parser.add_argument('--dp', type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    backports = args.backports or (args.stage / 'backports' if args.stage else None)
    dp = args.dp or (args.stage / 'dp' if args.stage else None)
    if backports is None or dp is None:
        parser.error('provide --stage or both --backports and --dp')
    debug = (backports / 'net/mac80211/debugfs.c').read_text()
    eee = (dp / 'nss_dp_ethtools.c').read_text()
    wmi = (backports / 'drivers/net/wireless/ath/ath11k/wmi.c').read_text()
    eee_body = helper.function(eee, 'nss_dp_get_eee')
    eee_body = 'static int32_t nss_dp_get_eee(struct net_device *netdev, struct ethtool_keee *eee)\n' + eee_body[eee_body.index('{'):]
    cases = (
        ('aql', AQL, helper.function(debug, 'aql_enable_write'), AQL_TEST),
        ('eee', EEE, helper.function(eee, 'nss_dp_fal_to_ethtool_linkmode_xlate') + eee_body, EEE_TEST),
        ('kickout', WMI, helper.function(wmi, 'ath11k_peer_sta_kickout_event'), WMI_TEST),
    )
    with tempfile.TemporaryDirectory(prefix='nss-error-guards-') as directory:
        root = Path(directory)
        for name, shim, code, test in cases:
            source = root / (name + '.c')
            source.write_text(COMMON + shim + code + test)
            executable = root / name
            subprocess.run(['cc', '-std=gnu11', '-O2', '-g', '-ftrivial-auto-var-init=pattern',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-fno-pie', '-no-pie', str(source), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True, timeout=15)


if __name__ == '__main__':
    main()
