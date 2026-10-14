#!/usr/bin/env python3
"""Exercise actual WMI key install/event/recovery code, including concurrent aborts."""
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
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sched.h>
#include <time.h>
typedef uint32_t u32;typedef uint64_t u64;typedef uint8_t u8;
#define ETH_ALEN 6
#define BIT(n) (1UL<<(n))
#define HZ 100
#define WARN_ON(x) (x)
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define spin_lock_bh(p) assert(pthread_mutex_lock(p)==0)
#define spin_unlock_bh(p) assert(pthread_mutex_unlock(p)==0)
#define lockdep_assert_held(p) assert(pthread_mutex_trylock(p)==EBUSY)
#define test_bit(n,p) (!!(*(p)&BIT(n)))
#define clear_bit(n,p) (*(p)&=~BIT(n))
#define ether_addr_copy(d,s) memcpy(d,s,6)
#define ether_addr_equal(a,b) (!memcmp(a,b,6))
#define WLAN_CIPHER_SUITE_CCMP 1
#define WLAN_CIPHER_SUITE_CCMP_256 2
#define WLAN_CIPHER_SUITE_TKIP 3
#define WLAN_CIPHER_SUITE_GCMP 4
#define WLAN_CIPHER_SUITE_GCMP_256 5
#define WMI_CIPHER_NONE 0
#define WMI_CIPHER_AES_CCM 1
#define WMI_CIPHER_TKIP 2
#define WMI_CIPHER_AES_GCM 3
#define IEEE80211_KEY_FLAG_GENERATE_IV_MGMT 1
#define IEEE80211_KEY_FLAG_GENERATE_IV 2
#define IEEE80211_KEY_FLAG_RESERVE_TAILROOM 4
#define ATH11K_FLAG_HW_CRYPTO_DISABLED 0
#define ATH11K_FLAG_RAW_MODE 1
#define ATH11K_FLAG_CRASH_FLUSH 2
#define ATH11K_FLAG_QMI_FAIL 3
#define ATH11K_FLAG_UNREGISTERING 4
#define ATH11K_FLAG_MONITOR_STARTED 5
#define ATH11K_FLAG_MONITOR_VDEV_CREATED 6
#define ATH11K_11D_IDLE 0
#define WMI_VDEV_INSTALL_KEY_COMPL_STATUS_SUCCESS 0
enum set_key_cmd { SET_KEY,DISABLE_KEY };
enum { ATH11K_STATE_OFF,ATH11K_STATE_ON,ATH11K_STATE_RESTARTING,ATH11K_STATE_RESTARTED,ATH11K_STATE_FTM };
struct completion { atomic_bool done; };
static void init_completion(struct completion *c) { atomic_init(&c->done,false); }
static void reinit_completion(struct completion *c) { atomic_store(&c->done,false); }
static void complete(struct completion *c) { atomic_store(&c->done,true); }
#define complete_all complete
static double now(void) { struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9; }
static unsigned long wait_for_completion_timeout(struct completion *c,unsigned long ticks) {
 assert(ticks==HZ);double end=now()+0.3;
 while(!atomic_load(&c->done) && now()<end)sched_yield();return atomic_load(&c->done);
}
struct ath11k_key_install_tuple { u32 vdev_id,key_idx,key_flags;u8 addr[6]; };
struct ath11k_key_install_state {
 struct ath11k_key_install_tuple expected,last_rx;
 u64 started,sent,completed,mismatched,unexpected,timeouts,aborted,send_failed,poisoned;
 u32 last_fw_status;int result;bool active,terminal,closed,reply_seen;
};
struct ath11k;struct ath11k_pdev { struct ath11k *ar; };
struct ath11k_base {
 pthread_mutex_t base_lock;unsigned long dev_flags,wmi_key_poisoned;bool wmi_key_admitting;
 unsigned num_radios;struct ath11k_pdev pdevs[2];struct ath11k *pdevs_active[2];
 struct { bool ownership_uncertain; } nss;
 struct { unsigned fw_crash_counter; } stats;
 struct { int tx_credits_wq; } wmi_ab;
 struct completion driver_recovery;
};
struct ieee80211_hw { int unused; };
struct ath11k {
 struct ath11k_base *ab;unsigned pdev_idx;int state;
 pthread_mutex_t conf_mutex;struct completion install_key_done;int install_key_status;
 struct ath11k_key_install_state install_key;
 struct ieee80211_hw *hw;int state_11d;struct completion completed_11d_scan;
 struct { struct completion started,completed,on_channel; } scan;
 struct completion peer_assoc_done,peer_delete_done,vdev_setup_done,vdev_delete_done,bss_survey_done;
 struct { struct completion wmi_sync; } thermal;
 struct { int tx_empty_waitq; } dp;
 int txmgmt_idr,txmgmt_empty_waitq,monitor_vdev_id,peer_mapping_wq;
 unsigned long monitor_flags;
 int fw_stats;
};
struct ath11k_vif { struct ath11k *ar;u32 vdev_id; };
struct ieee80211_key_conf { unsigned keyidx,keylen,vlan_id,hw_key_idx,cipher,flags;u8 key[32]; };
struct wmi_vdev_install_key_arg {
 u32 vdev_id,key_idx,key_len,key_flags,group_key_idx,key_cipher,key_txmic_len,key_rxmic_len;
 const u8 *key_data,*macaddr;
};
struct wmi_vdev_install_key_complete_arg { u32 vdev_id;const u8 *macaddr;u32 key_idx,key_flags,status; };
struct sk_buff { struct wmi_vdev_install_key_complete_arg event;bool invalid; };
static struct ath11k *lookup_ar;
static atomic_uint rcu_depth;
static unsigned submissions,freed;
static int mode;
static atomic_bool submitted;
static atomic_bool hold_reader,reader_entered,destroy_waiting;
enum { GOOD,NACK,NO_REPLY,SEND_FAIL,CRASH,WRONG_THEN_GOOD,ASYNC,IMPOSSIBLE_REPLY,NACK_AND_SEND_FAIL,NACK_CLOSE_AND_SEND_FAIL,ACK_CRASH_FLAG,ACK_QMI_FLAG,ACK_UNREGISTER_FLAG };
static void rcu_read_lock(void) { atomic_fetch_add(&rcu_depth,1); }
static void rcu_read_unlock(void) { assert(atomic_load(&rcu_depth));atomic_fetch_sub(&rcu_depth,1); }
static void synchronize_rcu(void) { atomic_store(&destroy_waiting,true);while(atomic_load(&rcu_depth))sched_yield(); }
#define READ_ONCE(x) (x)
#define RCU_INIT_POINTER(p,v) ((p)=(v))
#define mutex_lock(p) assert(pthread_mutex_lock(p)==0)
#define mutex_unlock(p) assert(pthread_mutex_unlock(p)==0)
static void ath11k_nss_reoq_stop(struct ath11k_base *ab) { (void)ab; }
static void ath11k_fw_stats_free(int *stats) { (void)stats; }
static void ieee80211_free_hw(struct ieee80211_hw *hw) { (void)hw;assert(!lookup_ar->install_key.active && !atomic_load(&rcu_depth));freed++; }
static struct ath11k *ath11k_mac_get_ar_by_vdev_id(struct ath11k_base *ab,u32 vdev) {
 assert(atomic_load(&rcu_depth));struct ath11k *found=ab==lookup_ar->ab && vdev==7 && ab->pdevs_active[0]==lookup_ar ? lookup_ar : NULL;
 if(found && atomic_load(&hold_reader)) { atomic_store(&reader_entered,true);while(atomic_load(&hold_reader))sched_yield(); }
 return found;
}
static int ath11k_pull_vdev_install_key_compl_ev(struct ath11k_base *ab,struct sk_buff *skb,struct wmi_vdev_install_key_complete_arg *e) { (void)ab;*e=skb->event;return skb->invalid ? -EINVAL : 0; }
static void ieee80211_stop_queues(struct ieee80211_hw *hw) { (void)hw; }
static void ath11k_mac_drain_tx(struct ath11k *ar) { (void)ar; }
static void wake_up(int *q) { (void)q; }
static int ath11k_mac_tx_mgmt_pending_free(int id,void *p,void *ar) { (void)id;(void)p;(void)ar;return 0; }
static void idr_for_each(int *p,int (*cb)(int,void *,void *),void *ar) { (void)p;(void)cb;(void)ar; }
static void idr_destroy(int *p) { (void)p; }
static int ath11k_wmi_vdev_install_key(struct ath11k *ar,const struct wmi_vdev_install_key_arg *arg);
void ath11k_core_pre_reconfigure_recovery(struct ath11k_base *ab);
static void ath11k_vdev_install_key_compl_event(struct ath11k_base *ab,struct sk_buff *skb);
void ath11k_mac_key_install_close(struct ath11k *ar);
'''

SUPPORT = r'''
static void event(struct ath11k *ar,u32 vdev,u32 idx,u32 flags,const u8 *addr,u32 status) {
 struct sk_buff skb={.event={.vdev_id=vdev,.key_idx=idx,.key_flags=flags,.macaddr=addr,.status=status}};
 ath11k_vdev_install_key_compl_event(ar->ab,&skb);
}
static int ath11k_wmi_vdev_install_key(struct ath11k *ar,const struct wmi_vdev_install_key_arg *arg) {
 submissions++;atomic_store(&submitted,true);
 assert(arg->vdev_id==7 && arg->key_idx==1);
 if(mode==SEND_FAIL)return -ENOBUFS;
 if(mode==CRASH) { ar->ab->dev_flags|=BIT(ATH11K_FLAG_CRASH_FLUSH);ath11k_core_pre_reconfigure_recovery(ar->ab);return 0; }
 if(mode==NO_REPLY || mode==ASYNC)return 0;
 if(mode==WRONG_THEN_GOOD)event(ar,7,2,arg->key_flags,arg->macaddr,0);
 event(ar,arg->vdev_id,arg->key_idx,arg->key_flags,arg->macaddr,(mode==NACK || mode==NACK_AND_SEND_FAIL || mode==NACK_CLOSE_AND_SEND_FAIL) ? 17 : 0);
 if(mode==NACK_CLOSE_AND_SEND_FAIL)ath11k_mac_key_install_close(ar);
 if(mode>=ACK_CRASH_FLAG)ar->ab->dev_flags|=BIT(ATH11K_FLAG_CRASH_FLUSH+(mode-ACK_CRASH_FLAG));
 return (mode==IMPOSSIBLE_REPLY || mode==NACK_AND_SEND_FAIL || mode==NACK_CLOSE_AND_SEND_FAIL) ? -ENOBUFS : 0;
}
static struct ath11k_base ab;
static struct ath11k ar;
static struct ath11k_vif vif;
static struct ieee80211_key_conf key;
static const u8 addr[6]={2,3,4,5,6,7};
static void fixture(void) {
 memset(&ab,0,sizeof(ab));memset(&ar,0,sizeof(ar));memset(&key,0,sizeof(key));
 pthread_mutex_init(&ab.base_lock,NULL);pthread_mutex_init(&ar.conf_mutex,NULL);
 ar.ab=&ab;ar.state=ATH11K_STATE_ON;ar.pdev_idx=0;ab.num_radios=1;ab.pdevs[0].ar=&ar;ab.pdevs_active[0]=&ar;ab.wmi_key_admitting=true;
 init_completion(&ar.install_key_done);vif.ar=&ar;vif.vdev_id=7;
 key.keyidx=1;key.keylen=16;key.cipher=WLAN_CIPHER_SUITE_CCMP;
 lookup_ar=&ar;submissions=freed=0;atomic_store(&rcu_depth,0);atomic_store(&submitted,false);
 atomic_store(&hold_reader,false);atomic_store(&reader_entered,false);atomic_store(&destroy_waiting,false);
}
static void finish_fixture(void) { assert(!atomic_load(&rcu_depth));pthread_mutex_destroy(&ar.conf_mutex);pthread_mutex_destroy(&ab.base_lock); }
static int install(enum set_key_cmd cmd) {
 pthread_mutex_lock(&ar.conf_mutex);int result=ath11k_install_key(&vif,&key,cmd,addr,4);pthread_mutex_unlock(&ar.conf_mutex);return result;
}
'''

MAIN = r'''
static void *install_thread(void *unused) { (void)unused;return (void *)(intptr_t)install(SET_KEY); }
static void *reader_thread(void *unused) { (void)unused;event(&ar,7,1,4,addr,0);return NULL; }
static void *destroy_thread(void *unused) { (void)unused;ath11k_mac_destroy(&ab);return NULL; }
int main(void) {
 for(int which=GOOD;which<=ACK_UNREGISTER_FLAG;which++) {
  if(which==ASYNC)continue;
  fixture();mode=which;int ret=install(SET_KEY);
  int expected=which==NACK ? -EINVAL : which==NO_REPLY ? -ETIMEDOUT : which==SEND_FAIL ? -ENOBUFS : (which==CRASH || which>=ACK_CRASH_FLAG) ? -ESHUTDOWN : (which==IMPOSSIBLE_REPLY || which==NACK_AND_SEND_FAIL || which==NACK_CLOSE_AND_SEND_FAIL) ? -EIO : 0;
  assert(ret==expected && !ar.install_key.active);
  assert(ar.install_key.completed==(which==GOOD || which==NACK || which==WRONG_THEN_GOOD || which>=IMPOSSIBLE_REPLY));
  assert(ar.install_key.mismatched==(which==WRONG_THEN_GOOD));
  bool poison=which==NO_REPLY || which==CRASH || (which>=IMPOSSIBLE_REPLY && which<=NACK_CLOSE_AND_SEND_FAIL);
  assert(!!ab.wmi_key_poisoned==poison);
  if(poison) {
   event(&ar,7,1,4,addr,0);assert(ar.install_key.unexpected==1);
   ab.dev_flags=0;ab.wmi_key_admitting=true;mode=GOOD;assert(install(SET_KEY)==-ESHUTDOWN && submissions==1);
   pthread_mutex_lock(&ar.conf_mutex);assert(ath11k_mac_key_install_open(&ar)==-ESHUTDOWN);pthread_mutex_unlock(&ar.conf_mutex);
   memset(&ar.install_key,0,sizeof(ar.install_key)); /* Fresh ar does not clear the base poison. */
   assert(install(SET_KEY)==-ESHUTDOWN && submissions==1);
  } else {
   mode=GOOD;ab.dev_flags=0;assert(install(DISABLE_KEY)==0);
  }
  finish_fixture();
 }
 fixture();mode=ASYNC;pthread_t t;pthread_create(&t,NULL,install_thread,NULL);
 while(!atomic_load(&submitted))sched_yield();
 u8 other[6]={2,3,4,5,6,8};
 event(&ar,7,1,4,other,0);event(&ar,7,1,5,addr,0);
 struct sk_buff bad={.invalid=true};ath11k_vdev_install_key_compl_event(&ab,&bad);
 event(&ar,99,1,4,addr,0);
 assert(!atomic_load(&ar.install_key_done.done) && ar.install_key.mismatched==2);
 event(&ar,7,1,4,addr,0);void *ret;pthread_join(t,&ret);assert((intptr_t)ret==0);
 event(&ar,7,1,4,addr,0);assert(ar.install_key.unexpected==1 && !ab.wmi_key_poisoned);
 finish_fixture();
 fixture();mode=ASYNC;pthread_t reader,destroyer;pthread_create(&t,NULL,install_thread,NULL);
 while(!atomic_load(&submitted))sched_yield();
 atomic_store(&hold_reader,true);pthread_create(&reader,NULL,reader_thread,NULL);
 while(!atomic_load(&reader_entered))sched_yield();
 pthread_create(&destroyer,NULL,destroy_thread,NULL);
 while(!atomic_load(&destroy_waiting))sched_yield();
 assert(!freed);atomic_store(&hold_reader,false);
 pthread_join(reader,NULL);pthread_join(t,&ret);pthread_join(destroyer,NULL);
 assert((intptr_t)ret==-ESHUTDOWN && freed==1 && !ab.pdevs[0].ar && !ab.pdevs_active[0]);
 finish_fixture();
 fixture();mode=ASYNC;pthread_create(&t,NULL,install_thread,NULL);
 while(!atomic_load(&submitted))sched_yield();
 ath11k_mac_key_install_close(&ar);pthread_join(t,&ret);assert((intptr_t)ret==-ESHUTDOWN && ab.wmi_key_poisoned==1);
 finish_fixture();
 fixture();
 for(unsigned bit=ATH11K_FLAG_CRASH_FLUSH;bit<=ATH11K_FLAG_UNREGISTERING;bit++) {
  ab.dev_flags=BIT(bit);mode=GOOD;assert(install(SET_KEY)==-ESHUTDOWN && !submissions);
 }
 ab.dev_flags=0;ar.install_key.closed=true;assert(install(SET_KEY)==-ESHUTDOWN);
 ab.wmi_key_admitting=false;pthread_mutex_lock(&ar.conf_mutex);assert(ath11k_mac_key_install_open(&ar)==-ESHUTDOWN);pthread_mutex_unlock(&ar.conf_mutex);
 ab.wmi_key_admitting=true;
 pthread_mutex_lock(&ar.conf_mutex);assert(!ath11k_mac_key_install_open(&ar));pthread_mutex_unlock(&ar.conf_mutex);
 assert(!install(SET_KEY));
 ar.state=ATH11K_STATE_OFF;assert(install(SET_KEY)==-ESHUTDOWN);
 ar.state=ATH11K_STATE_RESTARTED;assert(!install(SET_KEY));
 key.cipher=123;assert(install(SET_KEY)==-EOPNOTSUPP);
 ab.dev_flags=BIT(ATH11K_FLAG_HW_CRYPTO_DISABLED);assert(!install(SET_KEY));
 finish_fixture();
 /* The completion wins the shared lock at the timeout boundary. */
 fixture();struct wmi_vdev_install_key_arg arg={.vdev_id=7,.key_idx=1,.key_flags=4,.macaddr=addr};
 pthread_mutex_lock(&ar.conf_mutex);assert(!ath11k_mac_key_install_begin(&ar,&arg));
 assert(ath11k_mac_key_install_begin(&ar,&arg)==-EBUSY);
 event(&ar,7,1,4,addr,0);assert(!ath11k_mac_key_install_finish(&ar,0,false));
 pthread_mutex_unlock(&ar.conf_mutex);assert(!ab.wmi_key_poisoned);finish_fixture();
 /* Spurious completion without a matched terminal event must fail. */
 fixture();pthread_mutex_lock(&ar.conf_mutex);assert(!ath11k_mac_key_install_begin(&ar,&arg));
 complete(&ar.install_key_done);assert(ath11k_mac_key_install_finish(&ar,0,true)==-EIO && ab.wmi_key_poisoned);
 pthread_mutex_unlock(&ar.conf_mutex);finish_fixture();
 puts("actual WMI key identity/timeout/crash/channel lifetime: PASS");return 0;
}
'''

BASELINE_MAIN = r'''
int main(void) {
 fixture();mode=CRASH;
 int result=install(SET_KEY);
 assert(result==-ESHUTDOWN); /* Old code incorrectly returns 0 after recovery wake. */
 finish_fixture();return 0;
}
'''

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ath11k", type=Path)
    p.add_argument("--backports", type=Path)
    p.add_argument("--baseline", action="store_true")
    a = p.parse_args()
    root = a.ath11k or a.backports / "drivers/net/wireless/ath/ath11k"
    mac = (root / "mac.c").read_text()
    helpers = () if a.baseline else ("ath11k_mac_key_install_poison_locked", "ath11k_mac_key_install_open",
        "ath11k_mac_key_install_close", "ath11k_mac_key_install_begin", "ath11k_mac_key_install_event", "ath11k_mac_key_install_finish")
    source = SHIM + "".join(extractor.function(mac, n) for n in helpers)
    if a.baseline:
        # Only the crash case runs against baseline; other support modes are unused.
        source += "void ath11k_mac_key_install_close(struct ath11k *ar) { (void)ar; }\n"
    source += extractor.function(mac, "ath11k_install_key")
    source += extractor.function((root / "wmi.c").read_text(), "ath11k_vdev_install_key_compl_event")
    source += extractor.function((root / "core.c").read_text(), "ath11k_core_pre_reconfigure_recovery")
    if not a.baseline:
        source += extractor.function(mac, "ath11k_mac_destroy")
    source += SUPPORT + (BASELINE_MAIN if a.baseline else MAIN)
    with tempfile.TemporaryDirectory(prefix="wmi-key-lifetime-") as tmp:
        path = Path(tmp)
        (path / "test.c").write_text(source)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1", "-pthread",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                        str(path / "test.c"), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True,
                       env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1"))
