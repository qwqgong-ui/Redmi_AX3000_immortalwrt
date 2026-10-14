#!/usr/bin/env python3
"""Execute actual radio start/filter code through every failure after EAP ADD."""
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
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
enum ath11k_state { ATH11K_STATE_OFF, ATH11K_STATE_ON, ATH11K_STATE_RESTARTING,
 ATH11K_STATE_RESTARTED, ATH11K_STATE_WEDGED, ATH11K_STATE_FTM };
enum ath11k_routing_pkt_type { ATH11K_PKT_TYPE_EAP=2 };
#define ATH11K_WMI_PKTROUTE_ADD 1
#define ATH11K_WMI_PKTROUTE_DEL 2
#define ATH11K_WMI_PKTROUTE_USE_CCE 1
#define ATH11K_ROUTE_WBM_RELEASE 5
#define ATH11K_ROUTE_EAP_METADATA 146
#define WMI_PDEV_PARAM_PMF_QOS 1
#define WMI_PDEV_PARAM_DYNAMIC_BW 2
#define WMI_PDEV_PARAM_ARP_AC_OVERRIDE 3
#define WMI_PDEV_PARAM_MESH_MCAST_ENABLE 4
#define WMI_PDEV_PARAM_IDLE_PS_CONFIG 5
#define WMI_TLV_SERVICE_SPOOF_MAC_SUPPORT 0
#define HTT_PPDU_STATS_TAG_DEFAULT 0x1234
#define ath11k_warn(...) ((void)0)
#define ath11k_err(...) ((void)0)
#define WARN_ON(x) ((void)(x))
#define test_bit(n,p) (!!(*(p)&(1UL<<(n))))
#define rcu_assign_pointer(p,v) ((p)=(v))
struct ath11k_pdev { unsigned pdev_id; };
struct ath11k_base {
 struct { bool enabled; } nss;
 struct { bool idle_ps; } hw_params;
 struct ath11k_pdev *pdevs_active[2],pdevs[2];
};
struct wmi_ab { unsigned long svc_map[1]; };
struct ath11k_wmi { struct wmi_ab *wmi_ab; };
struct ath11k {
 struct ath11k_base *ab;
 struct ath11k_pdev *pdev;
 struct ath11k_wmi *wmi;
 int conf_mutex;
 enum ath11k_state state;
 unsigned pdev_idx,cfg_tx_chainmask,cfg_rx_chainmask;
 unsigned num_started_vdevs,num_created_vdevs,num_peers,allocated_vdev_map;
 unsigned char mac_addr[6];
};
struct ieee80211_hw { struct ath11k *priv; };
struct ath11k_wmi_pkt_route_param { u32 opcode,meta_data,dst_ring,dst_ring_handler,route_type_bmap; };
static bool ath11k_ftm_mode;
static unsigned fail_stage,add_attempts,del_attempts,antenna_calls,drains,waits;
static bool del_fails;
static int stage(unsigned n) { return fail_stage==n ? -EIO : 0; }
static void mutex_lock(int *lock) { assert(!*lock);*lock=1; }
static void mutex_unlock(int *lock) { assert(*lock);*lock=0; }
static void ath11k_mac_drain_tx(struct ath11k *ar) { assert(!ar->conf_mutex);drains++; }
static void ath11k_mac_wait_reconfigure(struct ath11k_base *ab) { (void)ab;waits++; }
static int ath11k_wmi_pdev_set_param(struct ath11k *ar,unsigned param,unsigned value,unsigned pdev) {
 assert(ar->conf_mutex && pdev==ar->pdev->pdev_id);(void)value;return stage(param);
}
static int ath11k_wmi_scan_prob_req_oui(struct ath11k *ar,const unsigned char *addr) { (void)addr;assert(ar->conf_mutex);return stage(6); }
static int ath11k_wmi_send_dfs_phyerr_offload_enable_cmd(struct ath11k *ar,unsigned pdev) { assert(ar->conf_mutex && pdev==ar->pdev->pdev_id);return stage(7); }
static int ath11k_dp_tx_htt_h2t_ppdu_stats_req(struct ath11k *ar,unsigned mask) { assert(ar->conf_mutex && mask==HTT_PPDU_STATS_TAG_DEFAULT);return stage(8); }
static void __ath11k_set_antenna(struct ath11k *ar,unsigned tx,unsigned rx) { assert(ar->conf_mutex);(void)tx;(void)rx;antenna_calls++; }
static void ath11k_reg_update_chan_list(struct ath11k *ar,bool scan) { assert(ar->conf_mutex && !scan); }
static int ath11k_mac_config_mon_status_default(struct ath11k *ar,bool enabled) { assert(ar->conf_mutex && enabled);return stage(9); }
static void ath11k_wmi_pdev_lro_cfg(struct ath11k *ar,unsigned pdev) { assert(ar->conf_mutex && pdev==ar->pdev->pdev_id); }
static void ath11k_thermal_set_throttling(struct ath11k *ar,unsigned level) { assert(ar->conf_mutex && level==1); }
static int __attribute__((unused)) ath11k_mac_key_install_open(struct ath11k *ar) { assert(ar->conf_mutex);return stage(11); }
static void __attribute__((unused)) ath11k_mac_key_install_close(struct ath11k *ar) { assert(ar->conf_mutex); }
static int ath11k_wmi_send_pdev_pkt_route(struct ath11k *ar,const struct ath11k_wmi_pkt_route_param *p) {
 assert(ar->conf_mutex);
 assert(p->meta_data==ATH11K_ROUTE_EAP_METADATA && p->dst_ring==ATH11K_ROUTE_WBM_RELEASE);
 assert(p->dst_ring_handler==ATH11K_WMI_PKTROUTE_USE_CCE && p->route_type_bmap==(1U<<ATH11K_PKT_TYPE_EAP));
 if(p->opcode==ATH11K_WMI_PKTROUTE_ADD) { assert(!add_attempts && !del_attempts);add_attempts++;return stage(10); }
 assert(p->opcode==ATH11K_WMI_PKTROUTE_DEL && add_attempts==1 && del_attempts==0);
 del_attempts++;return del_fails ? -ENOBUFS : 0;
}
'''

MAIN = r'''
int main(void) {
 struct ath11k_base ab={.nss.enabled=true,.hw_params.idle_ps=true};
 struct wmi_ab wa={.svc_map={1}};struct ath11k_wmi wmi={.wmi_ab=&wa};
 struct ath11k_pdev pdev={.pdev_id=7};
 struct ath11k ar={.ab=&ab,.pdev=&pdev,.wmi=&wmi,.pdev_idx=1};
 struct ieee80211_hw hw={.priv=&ar};
 for(unsigned fail=0;fail<=11;fail++)for(unsigned bad_del=0;bad_del<2;bad_del++) {
  memset(ab.pdevs_active,0,sizeof(ab.pdevs_active));
  ar.state=ATH11K_STATE_OFF;ar.conf_mutex=0;fail_stage=fail;del_fails=bad_del;
  add_attempts=del_attempts=antenna_calls=drains=waits=0;
  int ret=ath11k_mac_op_start(&hw);
  assert(ret==(fail ? -EIO : 0) && !ar.conf_mutex && drains==1);
  assert(ar.state==(fail ? ATH11K_STATE_OFF : ATH11K_STATE_ON));
  bool post_add=fail==5 || fail==9 || fail==11;
  assert(add_attempts==(fail==0 || post_add || fail==10));
  assert(del_attempts==post_add);
  assert((ab.pdevs_active[1]!=NULL)==(fail==0));
 }
 /* Native mode never owns this route, including failures after the ADD point. */
 ab.nss.enabled=false;
 for(unsigned fail=0;fail<=9;fail++) {
  ar.state=ATH11K_STATE_OFF;fail_stage=fail;add_attempts=del_attempts=0;
  assert(ath11k_mac_op_start(&hw)==(fail ? -EIO : 0));
  assert(!add_attempts && !del_attempts && !ar.conf_mutex);
 }
 ab.nss.enabled=true;fail_stage=0;del_fails=false;
 ar.state=ATH11K_STATE_RESTARTING;add_attempts=del_attempts=waits=0;
 assert(ath11k_mac_op_start(&hw)==0 && waits==1 && add_attempts==1 && !del_attempts);
 ar.state=ATH11K_STATE_ON;add_attempts=del_attempts=0;
 assert(ath11k_mac_op_start(&hw)==-EINVAL && !add_attempts && !del_attempts && !ar.conf_mutex);
 ath11k_ftm_mode=true;add_attempts=del_attempts=drains=0;
 assert(ath11k_mac_op_start(&hw)==-EOPNOTSUPP && !drains && !add_attempts && !del_attempts);
 assert(ath11k_dp_rx_pkt_type_filter(&ar,(enum ath11k_routing_pkt_type)9,146,true)==-EINVAL);
 puts("actual NSS EAP route start/filter failure rollback: PASS");
 return 0;
}
'''

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--backports", type=Path, required=True)
    p.add_argument("--mac-source", type=Path)
    a = p.parse_args()
    ath = a.backports / "drivers/net/wireless/ath/ath11k"
    mac = (a.mac_source or ath / "mac.c").read_text()
    dp = (ath / "dp_rx.c").read_text()
    source = SHIM + extractor.function(dp, "ath11k_dp_rx_pkt_type_filter") + extractor.function(mac, "ath11k_mac_op_start") + MAIN
    with tempfile.TemporaryDirectory(prefix="nss-eap-route-") as tmp:
        path = Path(tmp)
        (path / "test.c").write_text(source)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                        str(path / "test.c"), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True,
                       env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1"))
