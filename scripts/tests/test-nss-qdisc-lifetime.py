#!/usr/bin/env python3
"""Exercise actual qdisc cancellation, timer drain and failed-detach destruction."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

SHIM=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef int nss_tx_status_t;
enum { NSS_TX_SUCCESS=0,NSS_TX_FAILURE_NOT_READY=1,NSS_QDISC_STATE_IDLE=0,NSS_QDISC_STATE_READY=1 };
#define LINUX_VERSION_CODE 0x060c00
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define NSS_SHAPER_CONFIG_TYPE_SHAPER_NODE_DETACH 1
#define NSS_QDISC_COMMAND_TIMEOUT 10
#define nss_qdisc_info(...) ((void)0)
#define nss_qdisc_error(...) ((void)0)
#define nss_qdisc_warning(...) ((void)0)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define xchg(p,v) ({ __typeof__(*(p)) _old=*(p);*(p)=(v);_old; })
typedef struct { int value; } atomic_t;
static int atomic_read(atomic_t *a) { return a->value; }
static void atomic_set(atomic_t *a,int n) { a->value=n; }
static unsigned failed_waits;
#define wait_event_timeout(wq,condition,timeout) ({ int ok=(condition); if(!ok)failed_waits++; ok; })
struct timer_list { bool active; };
struct nss_qdisc;
struct Qdisc { void *priv;unsigned handle;int refs; };
static void *qdisc_priv(struct Qdisc *q) { return q->priv; }
struct nss_if_msg { struct { struct { struct { struct { struct { unsigned qos_tag; } shaper_node_config; } msg; } config; } shaper_configure; } msg; };
struct nss_qdisc {
 uint32_t command_cookie,stats_cookie;bool command_stopping,stats_timer_initialized,stats_stopping;
 struct timer_list stats_get_timer;atomic_t pending_stat_requests,state;
 bool is_root,is_bridge,is_virtual,destroy_virtual_interface;int nss_interface_number,pending_final_state;
 void *bounce_context;
 unsigned qos_tag,type;void *block,*nss_shaping_ctx,*virt_if_ctx,*stats_wq;struct Qdisc *qdisc;
};
struct nss_tbl_sched_data { struct nss_qdisc nq;struct Qdisc *qdisc; };
static struct Qdisc noop_qdisc;
static unsigned tokens=10,cancels,child_puts,stats_stops,cleanup_calls,timer_stops;
static struct nss_qdisc *during_cancel;
static bool inject_new_token;
static unsigned tracked_pending;
static nss_tx_status_t nss_qdisc_command_tx(struct nss_qdisc *,struct nss_if_msg *);
static void nss_if_cancel_msg(uint32_t cookie) {
 cancels++;
 if(cookie==tracked_pending)tracked_pending=0;
 if(during_cancel) {
  struct nss_if_msg message={0};
  assert(during_cancel->command_stopping);
  assert(nss_qdisc_command_tx(during_cancel,&message)==NSS_TX_FAILURE_NOT_READY);
  if(inject_new_token) { during_cancel->command_cookie=99;tracked_pending=99;inject_new_token=false; }
 }
}
static nss_tx_status_t nss_if_tx_msg_tracked(void *ctx,struct nss_if_msg *msg,uint32_t *cookie) {
 *cookie=++tokens;tracked_pending=*cookie;return NSS_TX_SUCCESS;
}
static void del_timer_sync(struct timer_list *timer) { timer->active=false;timer_stops++; }
static void tcf_block_put(void *block) {}
static void nss_qdisc_stats_stop_polling(struct nss_qdisc *nq) { stats_stops++; }
static int cleanup_state=NSS_QDISC_STATE_IDLE;
static unsigned bounce_unregisters;
static void nss_shaper_unregister_shaper_bounce_bridge(int n) { bounce_unregisters++; }
static void nss_shaper_unregister_shaper_bounce_interface(int n) { bounce_unregisters++; }
static void nss_shaper_unregister_shaping(void *ctx) {}
static void nss_qdisc_child_cleanup_free_node(struct nss_qdisc *nq) { cleanup_calls++;atomic_set(&nq->state,cleanup_state); }
static void nss_qdisc_root_cleanup_free_node(struct nss_qdisc *nq) { cleanup_calls++;atomic_set(&nq->state,cleanup_state); }
static void nss_qdisc_refresh_bshaper_assignment(struct Qdisc *q,int mode) {}
#define NSS_QDISC_SCAN_AND_UNASSIGN_BSHAPER 1
static bool nss_igs_verify_if_num(int n) { return false; }
static void nss_igs_module_put(void) {}
static int nss_virt_if_destroy_sync(void *ctx) { return NSS_TX_SUCCESS; }
static int nss_qdisc_node_detach(struct nss_qdisc *a,struct nss_qdisc *b,struct nss_if_msg *m,int kind) { return -1; }
static void nss_qdisc_destroy(struct nss_qdisc *nq);
static void nss_qdisc_put(struct Qdisc *q) {
 if(q==&noop_qdisc)return;
 assert(q->refs==1);q->refs--;child_puts++;nss_qdisc_destroy(q->priv);
}
'''
TEST=r'''
int main(void) {
 struct nss_qdisc active={0};struct nss_if_msg message={0};
 assert(nss_qdisc_command_tx(&active,&message)==NSS_TX_SUCCESS);
 during_cancel=&active;inject_new_token=true;
 nss_qdisc_command_cancel(&active);
 assert(cancels==2 && !active.command_cookie && !tracked_pending && !active.command_stopping);
 during_cancel=NULL;
 struct nss_qdisc stats={.stats_timer_initialized=true,.stats_cookie=55,.stats_get_timer={true}};
 atomic_set(&stats.pending_stat_requests,1);
 nss_qdisc_stats_qdisc_detach(&stats);
 assert(stats.stats_stopping && !stats.stats_timer_initialized && !stats.stats_cookie);
 assert(!atomic_read(&stats.pending_stat_requests) && timer_stops==2);
 nss_qdisc_stats_qdisc_detach(&stats);assert(timer_stops==2);
 struct nss_qdisc child={.state={NSS_QDISC_STATE_READY}};
 struct Qdisc leaf={.priv=&child,.handle=10,.refs=1};child.qdisc=&leaf;
 struct nss_tbl_sched_data tree={.nq={.state={NSS_QDISC_STATE_READY},.is_root=true},.qdisc=&leaf};
 struct Qdisc root={.priv=&tree,.handle=1,.refs=1};tree.nq.qdisc=&root;
 nss_tbl_destroy(&root);
 assert(!leaf.refs && child_puts==1 && cleanup_calls==2 && stats_stops==1);
 /* Even a non-ready destroy must revoke outstanding callbacks. */
 struct nss_qdisc failed={.state={-1},.is_root=true,.command_cookie=77};tracked_pending=77;
 nss_qdisc_destroy(&failed);assert(!failed.command_cookie&&!tracked_pending);
 /* Negative FREE must terminate promptly and still unregister host bounce. */
 cleanup_state=-16;
 struct nss_qdisc rejected={.state={NSS_QDISC_STATE_READY},.is_root=true,.is_virtual=true,.bounce_context=(void *)1};
 nss_qdisc_destroy(&rejected);
 assert(!failed_waits && bounce_unregisters==1 && !rejected.bounce_context);
 nss_qdisc_destroy(&rejected);assert(bounce_unregisters==1);
 puts("PASS actual qdisc lifetime: in-flight callback gate, token published during drain, stats timer/request cancellation, failed DETACH releases child and non-ready destroy revokes callbacks");
}
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--clients',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('extract_nss',Path(__file__).with_name('test-nss-control.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    core=(args.clients/'nss_qdisc/nss_qdisc.c').read_text()
    stats=(args.clients/'nss_qdisc/nss_qdisc_stats.c').read_text()
    tbl=(args.clients/'nss_qdisc/nss_tbl.c').read_text()
    functions=(helper.function(core,'nss_qdisc_command_tx')+helper.function(core,'nss_qdisc_command_cancel')+
               helper.function(stats,'nss_qdisc_stats_qdisc_detach')+
               helper.function(core,'nss_qdisc_root_cleanup_host')+helper.function(core,'nss_qdisc_destroy')+
               helper.function(tbl,'nss_tbl_destroy'))
    with tempfile.TemporaryDirectory(prefix='nss-qdisc-lifetime-') as directory:
        root=Path(directory);(root/'test.c').write_text(SHIM+functions+TEST)
        subprocess.run(['cc','-std=gnu11','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                        str(root/'test.c'),'-o',str(root/'test')],check=True)
        subprocess.run([str(root/'test')],check=True,timeout=15)


if __name__=='__main__':main()
