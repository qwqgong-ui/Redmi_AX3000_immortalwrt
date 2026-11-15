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
#include <stdlib.h>
#include <stddef.h>
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
#define NSS_WIFILI_SOC_RESET_MSG 9
#define GFP_ATOMIC 0
#define ENOTSUPP EOPNOTSUPP
#define TARGET_NUM_VDEVS(ab) 16
#define ath11k_err(...) ((void)0)
#define ath11k_warn(...) ((void)0)
#define ath11k_info(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(p) ((p)->next=(p),(p)->prev=(p))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_for_each_entry(p,h,m) for(struct list_head *it=(h)->next;it!=(h)&&((p)=container_of(it,__typeof__(*p),m),true);it=it->next)
static void list_add_tail(struct list_head *p,struct list_head *h) { p->next=h;p->prev=h->prev;h->prev->next=p;h->prev=p; }
static void list_del(struct list_head *p) { p->prev->next=p->next;p->next->prev=p->prev; }
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
static int ath11k_crypto_mode=ATH11K_CRYPT_MODE_HW, ath11k_frame_mode;
static bool nss_offload=true;
struct ath11k_base;
struct ath11k { struct ath11k_base *ab;int conf_mutex;struct list_head arvifs;struct { void *ctx;int if_num; } nss; };
struct ath11k_dp {int reo_cmd_lock;bool reo_cmd_accepting,reo_query_outstanding,reo_ownership_uncertain;uint64_t reo_cmd_epoch;unsigned reo_retained_count,reo_wmi_inflight,reo_pn_outstanding;struct {unsigned ring_id;} reo_status_ring;};
struct br_mcast_flight { unsigned refs;int pending,drained; };
struct ath11k_nss_me_policy { int unused; };
struct wireless_dev { void *netdev; };
struct ieee80211_vif { struct wireless_dev wdev; };
struct ath11k_nss_me_auto { bool initialized,registered,running,closing,active,retained;unsigned generation;int mdb,work;struct br_mcast_flight *flight;struct ath11k_nss_me_policy *policy; };
struct ath11k_vif { struct list_head list;struct ath11k *ar;struct ieee80211_vif *vif;struct { unsigned if_num;struct ath11k_nss_me_auto me_auto;struct { bool uncertain,mdb_staged; } me; } nss; };
struct hal_srng {bool initialized;int lock;};
struct ath11k_base {
 int core_lock,base_lock,fw_mode,num_radios;unsigned long dev_flags;
 uint64_t free_vdev_map;
 struct ath11k_dp dp;
 struct {struct hal_srng srng_list[1];} hal;
 struct { bool enabled,ownership_uncertain,quiescing,init_submitted,peers_initialized,registered,me_reader_uncertain;
          struct list_head peers;int complete;unsigned if_num;void *ctx; } nss;
 struct { int mem_lock; } qmi;
 struct { struct ath11k *ar; } pdevs[2];
};
static void set_bit(unsigned n,unsigned long *v) { *v|=1UL<<n; }
static void clear_bit(unsigned n,unsigned long *v) { *v&=~(1UL<<n); }
static void mutex_lock(int *v) { assert(!*v);*v=1; }
static void mutex_unlock(int *v) { assert(*v);*v=0; }
#define spin_lock_bh mutex_lock
#define spin_unlock_bh mutex_unlock
static void init_completion(int *v) { *v=0; }
static int reset_result,ready_result;static bool fail_reset_alloc;
static unsigned released,writes,started,reset_commands,stops,pdev_deinits;
static unsigned desc_releases,radio_unregistrations;
static unsigned quarantines,interface_quarantines,soc_quarantines,soc_unregistrations,purges,notify_removes,cancels,withdrawals,waits,flight_puts;
static bool purge_quarantined;
static struct ath11k_base *active;
static struct ath11k radios[2];static struct ath11k_vif vifs[2];static struct ieee80211_vif mac_vifs[2];static struct br_mcast_flight flights[2];
#define lockdep_assert_held(p) assert(*(p))
static unsigned msecs_to_jiffies(unsigned n) { return n; }
static int atomic_read(int *p) { return *p; }
static struct wireless_dev *ieee80211_vif_to_wdev(struct ieee80211_vif *v) { return &v->wdev; }
static void br_mcast_offload_mdb_unregister_notify(int *nb) { assert(nb==&vifs[0].nss.me_auto.mdb||nb==&vifs[1].nss.me_auto.mdb);notify_removes++; }
static void cancel_delayed_work_sync(int *work) { assert(work==&vifs[0].nss.me_auto.work||work==&vifs[1].nss.me_auto.work);cancels++; }
static void br_mcast_offload_set_mcu(void *dev,int bridge,int seq,bool enabled) { assert(dev&&!bridge&&!seq&&!enabled);withdrawals++; }
static unsigned wait_flight(bool done,unsigned ticks) { assert(!active->base_lock&&(radios[0].conf_mutex||radios[1].conf_mutex)&&ticks==3000);waits++;return done; }
#define wait_event_timeout(q,condition,ticks) ((void)(q),wait_flight((condition),(ticks)))
static void br_mcast_flight_put(struct br_mcast_flight *f) { assert(f&&f->refs);f->refs--;flight_puts++; }
static void ath11k_nss_me_policy_free(struct ath11k_vif *v,struct ath11k_nss_me_policy *p) { assert(v->ar->conf_mutex&&!active->base_lock&&!p); }
static void *kzalloc(size_t size,int flags) { assert(flags==GFP_ATOMIC&&active->qmi.mem_lock);return fail_reset_alloc?NULL:calloc(1,size); }
static void kfree(void *p) { free(p); }
struct nss_wifili_msg { struct { unsigned interface,type,len; } cm; };
static void nss_cmn_msg_init(void *ptr,unsigned ifnum,unsigned type,unsigned len,void *cb,void *data) { assert(!cb&&!data);struct nss_wifili_msg *m=ptr;m->cm.interface=ifnum;m->cm.type=type;m->cm.len=len; }
static int ath11k_nss_command_send(void *ctx,struct nss_wifili_msg *m,void *unused) { assert(ctx==active&&m->cm.interface==3&&m->cm.type==NSS_WIFILI_SOC_RESET_MSG&&!m->cm.len&&!unused&&waits==2);reset_commands++;return reset_result; }
static void ath11k_dp_dma_quarantine(struct ath11k_base *ab) { assert(ab==active&&ab->qmi.mem_lock&&!ab->base_lock);quarantines++;ab->nss.ownership_uncertain=true; }
static void nss_wifili_interface_quarantine(void *ctx,unsigned ifnum) { assert(ctx==active&&ifnum==3&&quarantines==soc_quarantines+1);interface_quarantines++; }
static void nss_wifili_soc_quarantine(void *ctx,unsigned ifnum,unsigned target,struct ath11k_base *ab) { assert(ctx==active&&ab==active&&ifnum==3&&target==29&&interface_quarantines==soc_quarantines+1);soc_quarantines++; }
static void nss_unregister_wifili_if(unsigned ifnum) { assert(ifnum==3&&active->nss.registered);soc_unregistrations++; }
/* Independent peer lease purge/late-response ownership runs in peer-lifetime. */
static void ath11k_nss_peer_states_purge(struct ath11k_base *ab,bool quarantine) { assert(ab==active&&!ab->nss.registered&&soc_unregistrations==purges+1);purges++;purge_quarantined=quarantine; }
static unsigned irq_disables;
/* Worker admission/cancellation is executed by test-nss-reo-notify.py. */
static void ath11k_nss_reoq_stop(struct ath11k_base *ab) { (void)ab; }
static void ath11k_hif_irq_disable(struct ath11k_base *ab) { assert(!ab->dp.reo_cmd_accepting);irq_disables++; }
static int ath11k_nss_stop(struct ath11k_base *ab) { assert(ab==active&&waits==2&&!ab->nss.me_reader_uncertain&&!ab->dp.reo_ownership_uncertain);stops++;return 0; }
static int ath11k_nss_pdev_deinit(struct ath11k_base *ab,int i) { assert(ab==active&&i<2&&waits==2&&!ab->nss.me_reader_uncertain&&!ab->dp.reo_ownership_uncertain);pdev_deinits++;return 0; }
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
 memset(ab,0,sizeof(*ab));ab->nss.enabled=ab->nss.registered=true;ab->nss.ctx=ab;ab->nss.if_num=3;ab->num_radios=2;ab->dp.reo_cmd_accepting=true;irq_disables=0;active=ab;
 memset(radios,0,sizeof(radios));memset(vifs,0,sizeof(vifs));
 for(unsigned i=0;i<2;i++) {
  radios[i].ab=ab;radios[i].nss.ctx=&radios[i];radios[i].nss.if_num=40+i;INIT_LIST_HEAD(&radios[i].arvifs);ab->pdevs[i].ar=&radios[i];
  mac_vifs[i].wdev.netdev=&mac_vifs[i];vifs[i].ar=&radios[i];vifs[i].vif=&mac_vifs[i];
  flights[i]=(struct br_mcast_flight){.refs=1};
  vifs[i].nss.me_auto=(struct ath11k_nss_me_auto){.initialized=true,.registered=true,.running=true,.active=true,.flight=&flights[i]};
  list_add_tail(&vifs[i].list,&radios[i].arvifs);
 }
 ab->dev_flags=(1UL<<ATH11K_FLAG_CRASH_FLUSH)|(1UL<<ATH11K_FLAG_RECOVERY);
 reset_result=ready_result=0;released=writes=started=reset_commands=desc_releases=radio_unregistrations=0;
 fail_reset_alloc=false;stops=pdev_deinits=quarantines=interface_quarantines=soc_quarantines=soc_unregistrations=purges=notify_removes=cancels=withdrawals=waits=flight_puts=0;purge_quarantined=false;
}
int main(void) {
 struct ath11k_base ab;int failures[]={-ETIMEDOUT,-EREMOTEIO,-ENOMEM,-EIO};
 for(unsigned i=0;i<sizeof(failures)/sizeof(*failures);i++) {
  fresh(&ab);reset_result=failures[i];if(failures[i]==-ENOMEM)fail_reset_alloc=true;
  assert(ath11k_core_reconfigure_on_crash(&ab)==failures[i]);
  assert(ab.nss.ownership_uncertain&&!ab.core_lock&&!ab.base_lock&&ab.nss.enabled);
  unsigned expected_commands=fail_reset_alloc?0:1;
  assert(reset_commands==expected_commands&&released==0&&writes==0&&started==0&&desc_releases==0);
  assert(quarantines==1&&interface_quarantines==1&&soc_quarantines==1&&soc_unregistrations==1&&purges==1&&purge_quarantined&&!ab.nss.registered&&!ab.qmi.mem_lock);
  assert(waits==2&&notify_removes==2&&cancels==2&&withdrawals==2&&flight_puts==2);
  assert(!ab.dp.reo_cmd_accepting&&ab.dp.reo_cmd_epoch==1&&irq_disables==1);
  assert(ab.dev_flags&(1UL<<ATH11K_FLAG_CRASH_FLUSH));
  assert(ab.dev_flags&(1UL<<ATH11K_FLAG_RECOVERY));
  reset_result=0;
  assert(ath11k_core_qmi_firmware_ready(&ab)==-EIO&&released==0&&writes==0&&started==0);
  ab.nss.enabled=false;nss_offload=false;
  assert(ath11k_nss_teardown(&ab)==-EIO);
  assert(ath11k_nss_setup(&ab)==-EBUSY&&started==0);
  assert(ath11k_core_reconfigure_on_crash(&ab)==-EIO&&!ab.core_lock);
  assert(released==0&&writes==0&&started==0&&reset_commands==expected_commands);
 }
 fresh(&ab);nss_offload=true;
 assert(ath11k_core_reconfigure_on_crash(&ab)==0);
 assert(!ab.nss.ownership_uncertain&&!ab.core_lock&&reset_commands==1&&desc_releases==1);
 assert(purges==1&&!purge_quarantined&&stops==1&&pdev_deinits==2&&waits==2&&!ab.qmi.mem_lock);
 assert(released==3&&writes==2&&started==1&&ab.nss.enabled);
 assert(!(ab.dev_flags&((1UL<<ATH11K_FLAG_CRASH_FLUSH)|(1UL<<ATH11K_FLAG_RECOVERY))));
 for(unsigned kind=0;kind<4;kind++) {
  fresh(&ab);
  if(kind==0)ab.dp.reo_query_outstanding=true;
  if(kind==1)ab.dp.reo_wmi_inflight=1;
  if(kind==2)ab.dp.reo_pn_outstanding=1;
  if(kind==3)ab.nss.me_reader_uncertain=true;
  assert(ath11k_core_reconfigure_on_crash(&ab)==-EUCLEAN&&ab.nss.ownership_uncertain&&!reset_commands&&!released);
  assert(!stops&&!pdev_deinits&&quarantines==1&&soc_quarantines==1&&interface_quarantines==1&&purges==1&&purge_quarantined&&!ab.qmi.mem_lock);
 }
 for(unsigned timeout_radio=0;timeout_radio<2;timeout_radio++) {
  fresh(&ab);flights[timeout_radio].pending=1;flights[timeout_radio].refs=2;
  assert(ath11k_core_reconfigure_on_crash(&ab)==-EUCLEAN);
  assert(vifs[timeout_radio].nss.me_auto.retained&&vifs[timeout_radio].nss.me.uncertain&&ab.nss.me_reader_uncertain);
  assert(waits==2&&notify_removes==2&&cancels==2&&withdrawals==2&&!vifs[0].nss.me_auto.initialized&&!vifs[1].nss.me_auto.initialized);
  assert(!radios[0].conf_mutex&&!radios[1].conf_mutex&&!ab.qmi.mem_lock);
  assert(!reset_commands&&!stops&&!pdev_deinits&&!desc_releases&&!released&&quarantines==1&&purge_quarantined);
  list_del(&vifs[0].list);list_del(&vifs[1].list);memset(vifs,0,sizeof(vifs));
  assert(ath11k_nss_teardown(&ab)==-EIO&&ab.nss.me_reader_uncertain&&!reset_commands);
  assert(ath11k_nss_setup(&ab)==-EBUSY);
  assert(flights[timeout_radio].refs==1);flights[timeout_radio].pending=0;br_mcast_flight_put(&flights[timeout_radio]);assert(!flights[timeout_radio].refs);
 }
 fresh(&ab);ready_result=-EIO;
 assert(ath11k_core_reconfigure_on_crash(&ab)==-EIO);
 assert(!ab.nss.ownership_uncertain&&!ab.core_lock&&reset_commands==1&&released==4);
 fresh(&ab);ab.nss.enabled=false;
 assert(ath11k_nss_teardown(&ab)==0&&reset_commands==0);
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
    me = (root / 'nss_me.c').read_text()
    bodies += [extractor.function(me, 'ath11k_nss_me_stop')]
    bodies += [extractor.function(nss, name) for name in
              ('ath11k_nss_reset', 'ath11k_nss_teardown', 'ath11k_nss_setup')]
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
