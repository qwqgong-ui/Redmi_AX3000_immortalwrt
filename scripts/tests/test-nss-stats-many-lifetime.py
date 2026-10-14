#!/usr/bin/env python3
"""Test the actual 12.2 stats-many bounded retries and local stop/drain path."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

SHIM=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
typedef uint32_t u32;
typedef int nss_tx_status_t;
#define NSS_TX_SUCCESS 0
#define PAGE_SIZE 4096
#define NSS_QDISC_COMMAND_TIMEOUT 10
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,n) ((v)=(n))
#define xchg(p,v) ({__typeof__(*(p)) old=*(p);*(p)=(v);old;})
typedef struct {int value;} atomic_t;
static int atomic_read(atomic_t *v) {return v->value;}
static void atomic_set(atomic_t *v,int n) {v->value=n;}
struct list_head {bool linked;};
static bool list_empty(struct list_head *v) {return !v->linked;}
static void list_del_init(struct list_head *v) {v->linked=false;}
static pthread_mutex_t nss_qdisc_stats_list_lock=PTHREAD_MUTEX_INITIALIZER;
#define spin_lock_bh(p) assert(!pthread_mutex_lock(p))
#define spin_unlock_bh(p) assert(!pthread_mutex_unlock(p))
struct nss_shaper_node_stats_sync_many {unsigned count,last_qos_tag,size;};
struct nss_if_msg {struct {struct {struct {struct {struct nss_shaper_node_stats_sync_many stats_get;} msg;} config;} shaper_configure;} msg;};
struct timer_list {bool active;};
struct nss_qdisc;
struct nss_qdisc_stats_wq {
 struct nss_qdisc *nq;struct nss_if_msg stats_sync_req_msg;
 struct list_head stats_list;struct timer_list stats_get_timer;
 atomic_t pending_stat_resp,pending_stat_work;bool stats_polling_stopped;
 unsigned stats_cookie,stats_request_fail,stats_request_success;
 int stats_resp_waitqueue,stats_work_waitqueue,nqt;
};
struct nss_qdisc {void *nss_shaping_ctx;unsigned qos_tag;struct nss_qdisc_stats_wq *stats_wq;};
static struct nss_qdisc_stats_wq *active;
static unsigned mode,submits,cancels,queued,pending,timer_stops,htable_frees,context_frees;
static int wait_response(void) {
 if(mode==1){atomic_set(&active->pending_stat_resp,0);return 1;}
 if(mode==2){active->stats_polling_stopped=true;atomic_set(&active->pending_stat_resp,0);return 1;}
 return 0;
}
#define wait_event_timeout(queue,condition,timeout) ((condition)?1:wait_response())
#define wait_event(queue,condition) do {if(!(condition))atomic_set(&active->pending_stat_work,0);assert(condition);}while(0)
static nss_tx_status_t nss_if_tx_msg_with_size_tracked(void *ctx,struct nss_if_msg *msg,u32 size,u32 *cookie) {
 assert(size==PAGE_SIZE && !active->stats_polling_stopped && !pending);
 *cookie=++submits;pending=*cookie;return mode==3?1:NSS_TX_SUCCESS;
}
static void nss_if_cancel_msg(u32 cookie) {
 cancels++;
 if(cookie==pending)pending=0;
 assert(active->nq->stats_wq==active);
}
static void usleep_range(int a,int b) {}
static void nss_qdisc_stats_queue_delayed_work(struct nss_qdisc *nq) {
 assert(!nq->stats_wq->stats_polling_stopped);queued++;
}
static void del_timer_sync(struct timer_list *timer) {timer->active=false;timer_stops++;}
static void wake_up(int *queue) {}
static void nss_qdisc_htable_dealloc(int *table) {assert(!pending && !atomic_read(&active->pending_stat_work));htable_frees++;}
static void kfree(void *p) {assert(p==active && !pending && !active->stats_get_timer.active);context_frees++;free(p);}
'''

TEST=r'''
int main(void) {
 for(mode=0;mode<3;mode++) {
  struct nss_qdisc nq={0};active=calloc(1,sizeof(*active));active->nq=&nq;nq.stats_wq=active;
  submits=cancels=queued=pending=0;
  nss_qdisc_stats_sync_msg_tx(active);
  if(mode==0)assert(submits==3 && cancels==3 && queued==1);
  else assert(submits==1 && cancels==1 && !queued);
  assert(!pending);free(active);
 }
 struct nss_qdisc nq={0};active=calloc(1,sizeof(*active));nq.stats_wq=active;active->nq=&nq;
 active->stats_list.linked=true;active->stats_get_timer.active=true;
 active->stats_cookie=77;pending=77;atomic_set(&active->pending_stat_work,1);atomic_set(&active->pending_stat_resp,1);
 nss_qdisc_stats_sync_many_exit(&nq);
 assert(!nq.stats_wq && context_frees==1 && htable_frees==1 && timer_stops==2 && !pending);
 nss_qdisc_stats_sync_many_exit(&nq);assert(context_frees==1);
 puts("PASS actual 12.2 stats-many lifetime: exactly three no-ACK attempts, ACK drain, stop-aware exit, pending worker/context protection, timer drain and repeated stop");
}
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--clients',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('extract_nss',Path(__file__).with_name('test-nss-control.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    source=(args.clients/'nss_qdisc/nss_qdisc_stats.c').read_text()
    # Select the target stats-many branch, not the 11.4 no-op compatibility functions.
    source=source.split('#else /* !NSS_FIRMWARE_VERSION_11_4 */',1)[1]
    functions=helper.function(source,'nss_qdisc_stats_sync_msg_tx')+helper.function(source,'nss_qdisc_stats_sync_many_exit')
    with tempfile.TemporaryDirectory(prefix='nss-stats-many-') as directory:
        root=Path(directory);(root/'test.c').write_text(SHIM+functions+TEST)
        subprocess.run(['cc','-std=gnu11','-O1','-g','-pthread','-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer',str(root/'test.c'),'-o',str(root/'test')],check=True)
        subprocess.run([str(root/'test')],check=True,timeout=15)


if __name__=='__main__':main()
