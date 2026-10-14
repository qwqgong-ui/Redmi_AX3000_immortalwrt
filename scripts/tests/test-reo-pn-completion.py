#!/usr/bin/env python3
"""Execute PN UPDATE publication, hardware completion and queue lifetime under ASan/UBSan."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


spec = importlib.util.spec_from_file_location(
    "pn_queue_fixture", Path(__file__).with_name("test-reo-queue-query.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

KEY_SHIM = r'''
#include <sys/types.h>
#define __user
#define scnprintf snprintf
struct file {void *private_data;};
static ssize_t simple_read_from_buffer(char *out,size_t count,loff_t *pos,const char *data,size_t len){
 if(*pos<0)return -EINVAL;if((size_t)*pos>=len)return 0;
 size_t available=len-(size_t)*pos;if(available>count)available=count;
 memcpy(out,data+*pos,available);*pos+=available;return available;
}
#define IEEE80211_KEY_FLAG_PAIRWISE BIT(0)
#define WLAN_CIPHER_SUITE_TKIP 1
#define WLAN_CIPHER_SUITE_CCMP 2
#define WLAN_CIPHER_SUITE_CCMP_256 3
#define WLAN_CIPHER_SUITE_GCMP 4
#define WLAN_CIPHER_SUITE_GCMP_256 5
#define ATH11K_FLAG_UNREGISTERING 2
#define ATH11K_STATE_ON 1
#define ATH11K_STATE_RESTARTED 3
enum set_key_cmd {SET_KEY, DISABLE_KEY};
struct ieee80211_key_conf {u32 flags,cipher;};
static unsigned long pn_clock_ms(void){
 struct timespec t;assert(!clock_gettime(CLOCK_MONOTONIC,&t));
 return t.tv_sec*1000ul+t.tv_nsec/1000000ul;
}
#define time_before(a,b) ((long)((a)-(b))<0)
#define jiffies_to_msecs(t) ((t)*10)
static int ath11k_dp_tx_reo_pn_update(struct ath11k_base *,struct ath11k_reo_pn_update *,struct ath11k_hal_reo_cmd *);
'''

CASES = r'''
struct pn_call {
 struct ath11k_vif vif;
 struct ath11k_peer *peer;
 struct ieee80211_key_conf key;
 enum set_key_cmd command;
 int ret;
 atomic_bool done;
};
static void call_init(struct pn_call *c,struct ath11k *ar,struct ath11k_peer *p){
 memset(c,0,sizeof(*c));c->vif=(struct ath11k_vif){.ar=ar,.vdev_id=1};c->peer=p;
 c->key=(struct ieee80211_key_conf){.flags=IEEE80211_KEY_FLAG_PAIRWISE,.cipher=WLAN_CIPHER_SUITE_CCMP};
}
static void *pn_thread(void *arg){
 struct pn_call *c=arg;mutex_lock(&c->vif.ar->conf_mutex);
 c->ret=ath11k_dp_peer_rx_pn_replay_config(&c->vif,mac,c->command,&c->key,c->peer);
 mutex_unlock(&c->vif.ar->conf_mutex);atomic_store(&c->done,true);return NULL;
}
static void make_tids(struct ath11k *ar,struct ath11k_peer *p,unsigned count){
 for(unsigned tid=0;tid<count;tid++)
  assert(!ath11k_peer_rx_tid_setup_instance(ar,p,p->addr,1,tid,64,0,HAL_PN_TYPE_NONE));
}
static unsigned pn_ids(struct ath11k_base *ab,unsigned ids[17]){
 unsigned n=0;memset(ids,0,17*sizeof(*ids));spin_lock_bh(&ab->dp.reo_cmd_lock);
 struct dp_reo_cmd *entry;list_for_each_entry(entry,&ab->dp.reo_cmd_list,list){
  if(entry->kind!=ATH11K_REO_CMD_PN_UPDATE)continue;
  assert(!entry->handler&&!entry->data.reo_queue&&!entry->data.paddr);
  assert(entry->pn_update->tid<17);ids[entry->pn_update->tid]=entry->cmd_num;n++;
 }
 spin_unlock_bh(&ab->dp.reo_cmd_lock);return n;
}
static void wait_pn(struct ath11k_base *ab,unsigned ids[17],unsigned count){
 for(unsigned i=0;i<1000;i++){if(pn_ids(ab,ids)==count)return;usleep(100);}
 assert(!"PN commands not published");
}
static void reply_pn(struct ath11k_base *ab,const unsigned ids[17],unsigned code){
 for(int tid=16;tid>=0;tid--)if(ids[tid])
  reply(ab,ids[tid],HAL_REO_UPDATE_RX_REO_QUEUE_STATUS,code,sizeof(struct hal_reo_status_hdr));
 ath11k_dp_process_reo_status(ab);
}
static void assert_live(struct ath11k_peer *p,unsigned n){
 for(unsigned i=0;i<n;i++){
  struct ath11k_reo_queue *q=p->rx_tid[i].reo_queue;
  assert(p->rx_tid[i].active&&q&&q->phase==ATH11K_REO_QUEUE_PUBLISHED&&q->dma_live&&!q->retiring);
  assert(atomic_load(&q->refs.value)==1);
 }
}
static void success_and_status_cases(void){
 for(unsigned status=0;status<4;status++){
  struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
  struct ath11k_peer *p=peer_new(&ar);unsigned n=status?3:17;make_tids(&ar,p,n);
  struct pn_call c;call_init(&c,&ar,p);pthread_t thread;unsigned ids[17];
  assert(!pthread_create(&thread,NULL,pn_thread,&c));wait_pn(&ab,ids,n);
  assert(!atomic_load(&c.done)&&ab.dp.reo_pn_outstanding==n);
  /* SUCCESS must be returned for every TID, not just the first one. */
  if(!status){reply(&ab,ids[0],HAL_REO_UPDATE_RX_REO_QUEUE_STATUS,0,8);ath11k_dp_process_reo_status(&ab);
   assert(!atomic_load(&c.done));ids[0]=0;}
  reply_pn(&ab,ids,status);assert(!pthread_join(thread,NULL));
  assert(c.ret==(status==0?0:-EIO));
  assert(ab.dp.reo_pn_stats.submitted==n&&ab.dp.reo_pn_stats.completed==n&&!ab.dp.reo_pn_outstanding);
  assert(ab.dp.reo_pn_stats.status[status]==n&&ab.dp.reo_pn_stats.succeeded==!status);
  assert_live(p,n);retire_peer_fixture(&ar,p);assert(dev.refs==1);
 }
}
static void malformed_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
 struct ath11k_peer *p=peer_new(&ar);make_tids(&ar,p,1);struct pn_call c;call_init(&c,&ar,p);
 pthread_t thread;unsigned ids[17];assert(!pthread_create(&thread,NULL,pn_thread,&c));wait_pn(&ab,ids,1);
 reply(&ab,ids[0],HAL_REO_UPDATE_RX_REO_QUEUE_STATUS,0,7);ath11k_dp_process_reo_status(&ab);
 reply(&ab,ids[0],HAL_REO_GET_QUEUE_STATS_STATUS,0,8);ath11k_dp_process_reo_status(&ab);
 assert(ab.dp.reo_pn_outstanding==1&&ab.dp.reo_cmd_stats.pending==1&&!ab.dp.reo_pn_stats.completed);
 assert(ab.dp.reo_cmd_stats.unexpected_status==1&&ab.dp.reo_cmd_stats.tag_mismatch==1&&!atomic_load(&c.done));
 reply_pn(&ab,ids,0);assert(!pthread_join(thread,NULL)&&!c.ret);assert_live(p,1);
 reply_pn(&ab,ids,0);assert(ab.dp.reo_cmd_stats.unexpected_status==2&&ab.dp.reo_pn_stats.completed==1);
 retire_peer_fixture(&ar,p);
}
static void timeout_and_late_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
 struct ath11k_peer *p=peer_new(&ar);make_tids(&ar,p,3);struct pn_call c;call_init(&c,&ar,p);
 pthread_t thread;unsigned ids[17];atomic_store(&requested_wait_ms,0);
 assert(!pthread_create(&thread,NULL,pn_thread,&c));wait_pn(&ab,ids,3);assert(!pthread_join(thread,NULL));
 assert(c.ret==-ETIMEDOUT&&ab.dp.reo_pn_stats.timed_out==3&&ab.dp.reo_pn_outstanding==3);
 assert(atomic_load(&requested_wait_ms)<=100); /* One budget for the whole batch. */
 for(unsigned i=0;i<3;i++)assert(atomic_load(&p->rx_tid[i].reo_queue->refs.value)==2);
 reply_pn(&ab,ids,0);assert(!ab.dp.reo_pn_outstanding&&!ab.dp.reo_pn_stats.succeeded);
 assert(ab.dp.reo_pn_stats.completed==3&&ab.dp.reo_pn_stats.last_errno==-ETIMEDOUT);
 assert_live(p,3);retire_peer_fixture(&ar,p);
}
static void stale_and_close_cases(void){
 for(unsigned kind=0;kind<6;kind++){
  struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
  struct ath11k_peer *p=peer_new(&ar);make_tids(&ar,p,1);struct pn_call c;call_init(&c,&ar,p);
  pthread_t thread;unsigned ids[17];assert(!pthread_create(&thread,NULL,pn_thread,&c));wait_pn(&ab,ids,1);
  spin_lock_bh(&ab.base_lock);
  if(kind==0){spin_unlock_bh(&ab.base_lock);retire_peer_fixture(&ar,p);p=peer_new(&ar);
   make_tids(&ar,p,1);spin_lock_bh(&ab.base_lock);}
  else if(kind==1)ath11k_dp_reo_cmd_close(&ab.dp);
  else if(kind==2)ab.wmi_key_admitting=false;
  else if(kind==3)ar.install_key.closed=true;
  else if(kind==4)ab.dev_flags|=BIT(ATH11K_FLAG_UNREGISTERING);
  else ab.wmi_key_poisoned=BIT(ar.pdev_idx);
  spin_unlock_bh(&ab.base_lock);
  reply_pn(&ab,ids,0);assert(!pthread_join(thread,NULL));
  assert(c.ret==(kind==0?-ESTALE:-ESHUTDOWN)&&!ab.dp.reo_pn_stats.succeeded&&!ab.dp.reo_pn_outstanding);
  assert_live(p,1);retire_peer_fixture(&ar,p);
 }
}
static void partial_and_allocation_cases(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
 struct ath11k_peer *p=peer_new(&ar);make_tids(&ar,p,3);struct pn_call c;call_init(&c,&ar,p);
 /* Slot 2 still belongs to a different requested status. */
 ab.dp.reo_cmd_status_tag[2]=HAL_REO_FLUSH_CACHE_STATUS;ab.dp.reo_cmd_stats.pending=1;
 pthread_t thread;unsigned ids[17];assert(!pthread_create(&thread,NULL,pn_thread,&c));wait_pn(&ab,ids,1);
 reply_pn(&ab,ids,0);assert(!pthread_join(thread,NULL)&&c.ret==-EBUSY);
 assert(ab.dp.reo_pn_stats.submitted==1&&ab.dp.reo_pn_stats.completed==1&&!ab.dp.reo_pn_outstanding);
 assert(ab.dp.reo_cmd_status_tag[2]==HAL_REO_FLUSH_CACHE_STATUS&&ab.dp.reo_cmd_stats.pending==1);
 assert_live(p,3);retire_peer_fixture(&ar,p);
 init(&ab,&ar,&dev);p=peer_new(&ar);make_tids(&ar,p,1);call_init(&c,&ar,p);
 /* Allocate all 17 waiters, then fail the command entry before HAL publication. */
 allocation_fail_after=allocations+17;pn_thread(&c);allocation_fail_after=0;
 assert(c.ret==-ENOMEM&&!ab.dp.reo_pn_stats.submitted&&!ab.dp.reo_cmd_stats.submitted);
 assert_live(p,1);retire_peer_fixture(&ar,p);
}
static void quarantine_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
 struct ath11k_peer *p=peer_new(&ar);make_tids(&ar,p,2);struct pn_call c;call_init(&c,&ar,p);
 unsigned freed=dma_frees;pthread_t thread;unsigned ids[17];
 assert(!pthread_create(&thread,NULL,pn_thread,&c));wait_pn(&ab,ids,2);
 ath11k_dp_reo_cmd_close(&ab.dp);ath11k_dp_reo_query_quarantine(&ab);ath11k_dp_reo_cmd_list_cleanup(&ab);
 assert(ab.nss.ownership_uncertain&&ab.dp.reo_ownership_uncertain&&ab.dp.reo_pn_outstanding==2);
 assert(dma_frees==freed);assert(!pthread_join(thread,NULL)&&c.ret==-ETIMEDOUT);
 reply_pn(&ab,ids,0);assert(ab.dp.reo_pn_outstanding==2&&dma_frees==freed);
 /* Test teardown explicitly represents confirmed HW halt. DRAIN completes an
  * observation without retiring either active descriptor or restoring PN.
  */
 struct dp_reo_cmd *entry,*pending_tmp;list_for_each_entry_safe(entry,pending_tmp,&ab.dp.reo_cmd_list,list){
  list_del(&entry->list);ath11k_dp_reo_pn_update_complete(entry->pn_update,HAL_REO_CMD_DRAIN);
  assert(entry->pn_update->status==HAL_REO_CMD_DRAIN&&entry->pn_update->error==-ESHUTDOWN);
  ath11k_dp_reo_pn_update_put(entry->pn_update);ab.dp.reo_pn_outstanding--;kfree(entry);
 }
 assert_live(p,2);ab.nss.ownership_uncertain=false;retire_peer_fixture(&ar,p);
}
static void numeric_debugfs_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
 struct file file={.private_data=&ab};char buf[1024]={0};loff_t pos=0;
 ab.dp.reo_pn_stats.status[HAL_REO_CMD_RESOURCE_BLOCKED]=3;ab.dp.reo_pn_stats.drained=7;
 assert(ath11k_debugfs_reo_pn_stats(&file,buf,sizeof(buf)-1,&pos)>0);
 assert(strstr(buf,"status_resource_blocked: 3\n")&&strstr(buf,"status_drain: 7\n"));
 assert(HAL_REO_CMD_DRAIN==255&&HAL_REO_CMD_RESOURCE_BLOCKED==3);
}
int main(void){
 success_and_status_cases();malformed_case();timeout_and_late_case();
 stale_and_close_cases();partial_and_allocation_cases();quarantine_case();numeric_debugfs_case();
 assert(dma_allocations==dma_frees&&!warnings);
 puts("REO PN: 17-TID completion barrier, BLOCKED/FAILED/RESOURCE_BLOCKED, short/wrong/duplicate TLV, one deadline, timeout/late status, unmap/reuse, key/REO close, partial publication and quarantine/DRAIN passed");
 return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backports", required=True, type=Path)
    parser.add_argument("--draft", type=Path)
    args = parser.parse_args()
    source = args.backports / "drivers/net/wireless/ath/ath11k"
    draft = args.draft or source
    code = base.build_fixture(source, draft).replace(base.CASES, "")
    # Kernel u64 is unsigned long long; libc uint64_t is unsigned long on x86-64.
    code = code.replace("typedef uint64_t u64;", "typedef unsigned long long u64;")
    code = code.replace("static unsigned long jiffies=10000;", "#define jiffies pn_clock_ms()")
    code = code.replace("#define msecs_to_jiffies(ms) ((ms)/20)", "#define msecs_to_jiffies(ms) ((ms)/10)")
    code = code.replace("struct completion {", "static atomic_uint requested_wait_ms;\nstruct completion {")
    code = code.replace("static bool fail_allocation,fail_dma;", "static bool fail_allocation,fail_dma;\nstatic unsigned allocation_fail_after;")
    code = code.replace("if(fail_allocation)return NULL;", "if(fail_allocation||(allocation_fail_after&&allocations==allocation_fail_after))return NULL;")
    code = code.replace(" struct timespec end;clock_gettime", " atomic_fetch_add(&requested_wait_ms,ms);\n struct timespec end;clock_gettime")
    code = code.replace("u32 slot[16][16]", "u32 slot[32][16]")
    # Insert key ABI and a real clock before the source bodies that use jiffies.
    code = code.replace("struct ath11k_hp_update_timer {unsigned unused;};", KEY_SHIM + "\nstruct ath11k_hp_update_timer {unsigned unused;};")
    code = code.replace("spinlock_t conf_mutex,tbl_mtx_lock;unsigned num_peers,num_stations;", "spinlock_t conf_mutex,tbl_mtx_lock;unsigned num_peers,num_stations,pdev_idx;int state;struct {bool closed;} install_key;")
    code = code.replace("unsigned long dev_flags;struct ath11k_dp dp;", "unsigned long dev_flags;bool wmi_key_admitting;unsigned long wmi_key_poisoned;struct ath11k_dp dp;")
    mac = (draft / "mac.c").read_text()
    available = base.extract.function(mac, "ath11k_mac_key_install_available_locked")
    bodies = base.extract.function((draft / "dp_tx.c").read_text(), "ath11k_dp_tx_reo_pn_update")
    bodies += base.extract.function((draft / "dp_rx.c").read_text(), "ath11k_dp_peer_rx_pn_replay_config")
    bodies += base.extract.function((draft / "debugfs.c").read_text(), "ath11k_debugfs_reo_pn_stats")
    helpers = base.CASES.split("static void wmi_lifetime_cases(void)")[0]
    helpers = helpers.replace("ab->dev=dev;ar->ab=ab;", "ab->dev=dev;ar->ab=ab;ab->wmi_key_admitting=true;ar->state=ATH11K_STATE_ON;")
    helpers = helpers.replace("num_entries=16", "num_entries=32")
    code += available + bodies + helpers + CASES
    with tempfile.TemporaryDirectory(prefix="reo-pn-completion-") as directory:
        root = Path(directory)
        c, binary = root / "test.c", root / "test"
        c.write_text(code)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-pthread", "-Wall", "-Werror",
                        "-Wno-unused-function", "-Wno-misleading-indentation", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", str(c), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=20,
                       env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1", UBSAN_OPTIONS="halt_on_error=1"))


if __name__ == "__main__":
    main()
