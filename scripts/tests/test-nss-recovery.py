#!/usr/bin/env python3
"""Run prepared ath11k recovery bodies; reject DMA reuse after failed NSS RESET."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    'nss_function_extraction', Path(__file__).with_name('test-nss-multicast.py'))
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
#define ATH11K_CRYPT_MODE_HW 0
#define ATH11K_CRYPT_MODE_SW 1
#define ATH11K_FLAG_HW_CRYPTO_DISABLED 0
#define ATH11K_FLAG_RAW_MODE 1
#define ATH11K_FLAG_CRASH_FLUSH 2
#define ATH11K_FLAG_RECOVERY 3
#define ATH11K_HW_TXRX_RAW 1
#define ATH11K_WIFILI_TARGET_TYPE_UNKNOWN 255
#define ATH11K_DBG_NSS 0
#define NSS_ETH_RX_INTERFACE 16
#define NSS_TX_SUCCESS 0
#define ENOTSUPP EOPNOTSUPP
#define TARGET_NUM_VDEVS(ab) 16
#define ath11k_err(...) ((void)0)
#define ath11k_warn(...) ((void)0)
#define ath11k_info(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define INIT_LIST_HEAD(p) (*(p)=1)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
static int ath11k_crypto_mode=ATH11K_CRYPT_MODE_HW, ath11k_frame_mode;
static bool nss_offload=true;
struct ath11k { struct { void *ctx;int if_num; } nss; };
struct ath11k_dp {int reo_cmd_lock;bool reo_cmd_accepting,reo_query_outstanding,reo_ownership_uncertain;uint64_t reo_cmd_epoch;unsigned reo_retained_count,reo_wmi_inflight;struct {unsigned ring_id;} reo_status_ring;};
struct hal_srng {bool initialized;int lock;};
struct ath11k_base {
 int core_lock,base_lock,fw_mode,num_radios;unsigned long dev_flags;
 uint64_t free_vdev_map;
 struct ath11k_dp dp;
 struct {struct hal_srng srng_list[1];} hal;
 struct { bool enabled,ownership_uncertain,quiescing,init_submitted,peers_initialized;
          int peers,complete;void *ctx; } nss;
 struct { struct ath11k *ar; } pdevs[2];
};
static void set_bit(unsigned n,unsigned long *v) { *v|=1UL<<n; }
static void clear_bit(unsigned n,unsigned long *v) { *v&=~(1UL<<n); }
static void mutex_lock(int *v) { assert(!*v);*v=1; }
static void mutex_unlock(int *v) { assert(*v);*v=0; }
#define spin_lock_bh mutex_lock
#define spin_unlock_bh mutex_unlock
static void init_completion(int *v) { *v=0; }
static int reset_result,ready_result;static unsigned released,writes,started,resets;
static unsigned desc_releases,radio_unregistrations;
static unsigned irq_disables;
/* Worker admission/cancellation is executed by test-nss-reo-notify.py. */
static void ath11k_nss_reoq_stop(struct ath11k_base *ab) { (void)ab; }
static void ath11k_hif_irq_disable(struct ath11k_base *ab) { assert(!ab->dp.reo_cmd_accepting);irq_disables++; }
static int ath11k_nss_stop(struct ath11k_base *ab) { (void)ab;return 0; }
static int ath11k_nss_pdev_deinit(struct ath11k_base *ab,int i) { (void)ab;(void)i;return 0; }
static int ath11k_nss_reset(struct ath11k_base *ab) {
 resets++;if(reset_result)ab->nss.ownership_uncertain=true;return reset_result;
}
static void nss_unregister_wifili_radio_if(int ifnum) { (void)ifnum;radio_unregistrations++; }
static void ath11k_nss_tx_desc_mem_free(struct ath11k_base *ab) {
 assert(!ab->nss.ownership_uncertain);desc_releases++;
}
static u32 ath11k_nss_get_target_type(struct ath11k_base *ab) { (void)ab;return 29; }
static bool nss_cmn_get_nss_enabled(void) { return true; }
static int ath11k_nss_init(struct ath11k_base *ab) { (void)ab;started++;return 0; }
static int ath11k_nss_pdev_init(struct ath11k_base *ab,int i) { (void)ab;(void)i;return 0; }
static int ath11k_nss_start(struct ath11k_base *ab) { (void)ab;return 0; }
static int nss_wifi_vdev_base_set_next_hop(void *ctx,int ifnum) { (void)ctx;(void)ifnum;return 0; }
#define RELEASE(name) static void name(struct ath11k_base *ab) { assert(!ab->nss.ownership_uncertain);released++; }
RELEASE(ath11k_dp_pdev_free)
RELEASE(ath11k_dp_pdev_reo_cleanup)
RELEASE(ath11k_dp_free)
RELEASE(ath11k_hal_srng_deinit)
RELEASE(ath11k_mac_destroy)
static void ath11k_hal_srng_clear(struct ath11k_base *ab) { assert(!ab->nss.ownership_uncertain);writes++; }
#define NOOP(name) static void name(struct ath11k_base *ab) { (void)ab; }
NOOP(ath11k_thermal_unregister)
NOOP(ath11k_spectral_deinit)
NOOP(ath11k_ce_cleanup_pipes)
NOOP(ath11k_wmi_detach)
NOOP(ath11k_hif_irq_enable)
NOOP(ath11k_core_stop)
NOOP(ath11k_qmi_firmware_stop)
static int ath11k_core_start_firmware(struct ath11k_base *ab,int mode) { (void)ab;(void)mode;started++;return ready_result; }
static int ath11k_ce_init_pipes(struct ath11k_base *ab) { (void)ab;return 0; }
static int ath11k_dp_alloc(struct ath11k_base *ab) { assert(!ab->nss.ownership_uncertain);writes++;return 0; }
static int ath11k_core_start(struct ath11k_base *ab) { (void)ab;return 0; }
static int ath11k_core_pdev_create(struct ath11k_base *ab) { (void)ab;return 0; }
'''

CASES = r'''
static void fresh(struct ath11k_base *ab) {
 memset(ab,0,sizeof(*ab));ab->nss.enabled=true;ab->num_radios=2;ab->dp.reo_cmd_accepting=true;irq_disables=0;
 ab->dev_flags=(1UL<<ATH11K_FLAG_CRASH_FLUSH)|(1UL<<ATH11K_FLAG_RECOVERY);
 reset_result=ready_result=0;released=writes=started=resets=desc_releases=radio_unregistrations=0;
}
int main(void) {
 struct ath11k_base ab;int failures[]={-ETIMEDOUT,-EREMOTEIO,-ENOMEM,-EIO};
 for(unsigned i=0;i<sizeof(failures)/sizeof(*failures);i++) {
  fresh(&ab);reset_result=failures[i];
  assert(ath11k_core_reconfigure_on_crash(&ab)==failures[i]);
  assert(ab.nss.ownership_uncertain&&!ab.core_lock&&!ab.base_lock&&ab.nss.enabled);
  assert(resets==1&&released==0&&writes==0&&started==0&&desc_releases==0);
  assert(!ab.dp.reo_cmd_accepting&&ab.dp.reo_cmd_epoch==1&&irq_disables==1);
  assert(ab.dev_flags&(1UL<<ATH11K_FLAG_CRASH_FLUSH));
  assert(ab.dev_flags&(1UL<<ATH11K_FLAG_RECOVERY));
  reset_result=0;
  assert(ath11k_core_qmi_firmware_ready(&ab)==-EIO&&released==0&&writes==0&&started==0);
  ab.nss.enabled=false;nss_offload=false;
  assert(ath11k_nss_teardown(&ab)==-EIO);
  assert(ath11k_nss_setup(&ab)==-EBUSY&&started==0);
  assert(ath11k_core_reconfigure_on_crash(&ab)==-EIO&&!ab.core_lock);
  assert(released==0&&writes==0&&started==0&&resets==1);
 }
 fresh(&ab);nss_offload=true;
 assert(ath11k_core_reconfigure_on_crash(&ab)==0);
 assert(!ab.nss.ownership_uncertain&&!ab.core_lock&&resets==1&&desc_releases==1);
 assert(released==3&&writes==2&&started==1&&ab.nss.enabled);
 assert(!(ab.dev_flags&((1UL<<ATH11K_FLAG_CRASH_FLUSH)|(1UL<<ATH11K_FLAG_RECOVERY))));
 fresh(&ab);ab.dp.reo_query_outstanding=true;
 assert(ath11k_core_reconfigure_on_crash(&ab)==-EIO&&ab.nss.ownership_uncertain&&resets==0&&released==0&&ab.dp.reo_query_outstanding);
 fresh(&ab);ab.dp.reo_wmi_inflight=1;
 assert(ath11k_core_reconfigure_on_crash(&ab)==-EIO&&ab.nss.ownership_uncertain&&resets==0&&released==0&&ab.dp.reo_wmi_inflight==1);
 fresh(&ab);ready_result=-EIO;
 assert(ath11k_core_reconfigure_on_crash(&ab)==-EIO);
 assert(!ab.nss.ownership_uncertain&&!ab.core_lock&&resets==1&&released==4);
 fresh(&ab);ab.nss.enabled=false;
 assert(ath11k_nss_teardown(&ab)==0&&resets==0);
 assert(ath11k_nss_setup(&ab)==0&&started==0);
 fresh(&ab);assert(ath11k_nss_setup(&ab)==0&&started==1&&!ab.nss.quiescing);
 puts("ath11k recovery: failed RESET retains rings, refuses late FW-ready and parameter bypass; successful RESET recovers normally");
 return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', required=True, type=Path)
    parser.add_argument('--draft', type=Path)
    args = parser.parse_args()
    root = args.draft or args.backports / 'drivers/net/wireless/ath/ath11k'
    nss = re.sub(r'/\*.*?\*/', '', (root / 'nss.c').read_text(), flags=re.S)
    core = re.sub(r'/\*.*?\*/', '', (root / 'core.c').read_text(), flags=re.S)
    bodies = [extractor.function((root / 'dp.h').read_text(), 'ath11k_dp_reo_cmd_close')]
    bodies += [extractor.function((root / 'dp_rx.c').read_text(), 'ath11k_dp_reo_query_quarantine')]
    bodies += [extractor.function(nss, name) for name in
              ('ath11k_nss_teardown', 'ath11k_nss_setup')]
    bodies += [extractor.function(core, name) for name in
               ('ath11k_core_qmi_firmware_ready', 'ath11k_core_reconfigure_on_crash')]
    with tempfile.TemporaryDirectory(prefix='nss-recovery-') as directory:
        source = Path(directory) / 'recovery.c'
        source.write_text(SHIM + '\n'.join(bodies) + CASES)
        binary = source.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g',
                        '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-no-pie', str(source), '-o', str(binary)],
                       check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
