#!/usr/bin/env python3
"""Run actual basic/many stats callbacks with exact public wire layouts and short buffers."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "stats_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uintptr_t nss_ptr_t;typedef int nss_tx_status_t,nss_if_num_t;
typedef uint64_t __u64;
#define ETH_ALEN 6
#define NSS_MAX_NUM_PRI 4
struct sk_buff;struct net_device;struct napi_struct;struct module;
struct nss_ctx_instance { unsigned id; };
'''

SHIM = r'''
#define PAGE_SIZE 4096
#define HZ 100
#define NSS_QDISC_STATS_SYNC_MANY_PERIOD 100
#define READ_ONCE(v) (v)
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
typedef struct {int value;} atomic_t;
typedef struct {unsigned value;} refcount_t;
static void atomic_set(atomic_t *p,int n) { p->value=n; }
static void atomic_sub(int n,atomic_t *p) { assert(p->value>=n);p->value-=n; }
static unsigned refcount_read(refcount_t *p) { return p->value; }
struct gnet_stats_basic_sync { uint64_t bytes,packets; };
struct gnet_stats_queue { unsigned backlog,drops,qlen,requeues,overlimits; };
struct timer_list { unsigned long expires; };
struct Qdisc { struct gnet_stats_basic_sync bstats;struct gnet_stats_queue qstats;refcount_t refcnt; };
struct nss_qdisc;
struct nss_qdisc_stats_wq {
 struct nss_if_msg stats_sync_req_msg;atomic_t pending_stat_resp;
 int stats_resp_waitqueue;bool stats_polling_stopped;
 unsigned stats_request_fail;unsigned long next_req_time;struct timer_list stats_get_timer;
};
struct nss_qdisc {
 struct Qdisc *qdisc;struct nss_ctx_instance *nss_shaping_ctx;
 struct nss_qdisc_stats_wq *stats_wq;unsigned type,qos_tag,lock;bool is_class,stats_stopping;
 struct gnet_stats_basic_sync bstats;struct gnet_stats_queue qstats;refcount_t refcnt;
 atomic_t pending_stat_requests;int wait_queue;struct timer_list stats_get_timer;
 void (*stats_cb)(struct nss_qdisc *,struct nss_shaper_node_stats_response *);
};
static struct nss_ctx_instance context;
static unsigned actual_length,wakes,queued,timers,warnings,processed;
static unsigned long jiffies=1000;
static unsigned char last_byte;
uint32_t nss_if_rx_msg_buf_len(struct nss_ctx_instance *ctx) { assert(ctx==&context);return actual_length; }
static void wake_up(int *p) { assert(p);wakes++; }
static void u64_stats_add(uint64_t *p,uint64_t n) { *p+=n; }
static void add_timer(struct timer_list *p) { assert(p);timers++; }
static void mod_timer(struct timer_list *p,unsigned long expires) { p->expires=expires;timers++; }
static bool time_after(unsigned long a,unsigned long b) { return (long)(b-a)<0; }
#define spin_lock_bh(p) do {assert(!*(p));*(p)=1;} while(0)
#define spin_unlock_bh(p) do {assert(*(p));*(p)=0;} while(0)
__attribute__((noinline,noipa)) static void warning(const char *format,...) { assert(format);warnings++; }
__attribute__((noinline,noipa)) static void info(const char *format,...) { assert(format); }
#define nss_qdisc_warning(...) warning(__VA_ARGS__)
#define nss_qdisc_info(...) info(__VA_ARGS__)
static void consume_stats(struct nss_qdisc *nq,struct nss_shaper_node_stats_response *response) {
 assert(nq&&response);
 last_byte=*((volatile unsigned char *)response+sizeof(*response)-1);processed++;
}
static void nss_qdisc_stats_process_node_stats(struct nss_qdisc *nq,struct nss_shaper_node_stats_response *r) { consume_stats(nq,r); }
static void nss_qdisc_stats_queue_delayed_work(struct nss_qdisc *nq) {
 assert(nq->stats_wq&&!nq->stats_wq->stats_polling_stopped);queued++;
}
static struct Qdisc qdisc;
static struct nss_qdisc nq;
static struct nss_qdisc_stats_wq work;
static void fresh(void) {
 memset(&qdisc,0,sizeof(qdisc));memset(&nq,0,sizeof(nq));memset(&work,0,sizeof(work));
 wakes=queued=timers=warnings=processed=0;actual_length=0;
 nq.qdisc=&qdisc;nq.nss_shaping_ctx=&context;nq.stats_wq=&work;nq.qos_tag=0x10001;
 nq.stats_cb=consume_stats;nq.refcnt.value=qdisc.refcnt.value=1;nq.pending_stat_requests.value=1;
 work.pending_stat_resp.value=1;work.next_req_time=jiffies;
 work.stats_sync_req_msg.msg.shaper_configure.config.msg.stats_get.size=PAGE_SIZE;
 work.stats_sync_req_msg.msg.shaper_configure.config.msg.stats_get.last_qos_tag=0x1234;
}
static struct nss_if_msg *frame(unsigned size,unsigned response) {
 assert(size>=sizeof(struct nss_cmn_msg));
 struct nss_if_msg *msg=calloc(1,size);assert(msg);actual_length=size;
 msg->cm.response=response;
 /* Deliberately leave cm.len at zero; it is not the received extent. */
 return msg;
}
'''

BASIC = r'''
int main(void) {
 size_t end=offsetof(struct nss_if_msg,msg.shaper_configure.config.msg.shaper_node_stats_get.response)+
  sizeof(((struct nss_shaper_node_basic_stats_get *)0)->response);
 for(unsigned response=0;response<2;response++)for(unsigned length=0;length<2;length++){
  fresh();unsigned size=length?end-1:sizeof(struct nss_cmn_msg);
  struct nss_if_msg *msg=frame(size,response?NSS_CMN_RESPONSE_EMSG:NSS_CMN_RESPONSE_ACK);
  nss_qdisc_stats_basic_stats_callback(&nq,msg);free(msg);
  assert(!processed&&!timers&&!nq.pending_stat_requests.value&&wakes==1&&warnings==1);
  assert(!qdisc.bstats.bytes&&!qdisc.qstats.drops);
 }
 for(unsigned class=0;class<2;class++){
  fresh();nq.is_class=class;struct nss_if_msg *msg=frame(end,NSS_CMN_RESPONSE_ACK);
  struct nss_shaper_node_stats *s=&msg->msg.shaper_configure.config.msg.shaper_node_stats_get.response.sn_stats;
  s->delta.dequeued_bytes=77;s->delta.dequeued_packets=2;s->delta.enqueued_packets_dropped=3;
  s->qlen_bytes=50;s->qlen_packets=1;
  nss_qdisc_stats_basic_stats_callback(&nq,msg);free(msg);
  struct gnet_stats_basic_sync *b=class?&nq.bstats:&qdisc.bstats;
  struct gnet_stats_queue *q=class?&nq.qstats:&qdisc.qstats;
  assert(b->bytes==77&&b->packets==2&&q->drops==3&&q->backlog==50);
  assert(processed==1&&timers==1&&!wakes&&!warnings&&nq.pending_stat_requests.value==1);
 }
 fresh();nq.stats_stopping=true;struct nss_if_msg *msg=frame(sizeof(struct nss_cmn_msg),NSS_CMN_RESPONSE_ACK);
 nss_qdisc_stats_basic_stats_callback(&nq,msg);free(msg);
 assert(!processed&&!timers&&!warnings&&!nq.pending_stat_requests.value&&wakes==1);
 puts("PASS actual basic-stats callback: exact complete union, short ACK/NACK, no body log overread, class/root counters and stopped retirement");
}
'''

MANY = r'''
static void one(unsigned actual,unsigned count,unsigned capacity,unsigned response,bool stopped,bool good) {
 fresh();work.stats_polling_stopped=stopped;
 struct nss_shaper_node_stats_sync_many *host=&work.stats_sync_req_msg.msg.shaper_configure.config.msg.stats_get;
 host->size=capacity;struct nss_if_msg *msg=frame(actual,response);
 size_t hdr=offsetof(struct nss_if_msg,msg.shaper_configure.config.msg.stats_get.stats_sync);
 if(actual>=hdr){
  struct nss_shaper_node_stats_sync_many *wire=&msg->msg.shaper_configure.config.msg.stats_get;
  wire->size=UINT16_MAX;wire->count=count;wire->last_qos_tag=0x55;
 }
 nss_qdisc_stats_sync_many_callback(&nq,msg);free(msg);
 assert(!work.pending_stat_resp.value&&wakes==1);
 if(stopped){assert(!processed&&!queued&&!timers&&!warnings&&!work.stats_request_fail);return;}
 if(good){
  assert(processed==count&&queued==1&&!timers&&!warnings&&!work.stats_request_fail&&host->last_qos_tag==0x55);
 } else{
  assert(!processed&&queued==1&&!timers&&warnings==1&&work.stats_request_fail==1&&!host->last_qos_tag);
 }
}
int main(void) {
 size_t hdr=offsetof(struct nss_if_msg,msg.shaper_configure.config.msg.stats_get.stats_sync);
 size_t record=sizeof(struct nss_shaper_node_stats_response);
 one(sizeof(struct nss_cmn_msg),0,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,false);
 one(sizeof(struct nss_cmn_msg),0,PAGE_SIZE,NSS_CMN_RESPONSE_EMSG,false,false);
 one(hdr-1,0,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,false);
 one(hdr,0,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,true);
 one(hdr+record,1,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,true);
 one(hdr,1,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,false);
 one(hdr+record-1,1,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,false);
 one(hdr+2*record-1,2,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,false);
 one(hdr+2*record,2,hdr+record,NSS_CMN_RESPONSE_ACK,false,false);
 one(hdr+2*record,2,hdr-1,NSS_CMN_RESPONSE_ACK,false,false);
 one(hdr+2*record,UINT16_MAX,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,false);
 one(hdr+2*record,2,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,false,true);
 one(sizeof(struct nss_cmn_msg),0,PAGE_SIZE,NSS_CMN_RESPONSE_ACK,true,false);
 /* A returned size of zero must not reduce a valid host/actual extent. */
 fresh();struct nss_if_msg *msg=frame(hdr+record,NSS_CMN_RESPONSE_ACK);
 struct nss_shaper_node_stats_sync_many *wire=&msg->msg.shaper_configure.config.msg.stats_get;
 wire->size=0;wire->count=1;wire->last_qos_tag=1;
 nss_qdisc_stats_sync_many_callback(&nq,msg);free(msg);
 assert(processed==1&&queued==1&&!warnings);
 puts("PASS actual sync-many callback: header/record truncation, u16 counts, host and actual bounds, unchanged cm.len, ignored wire size and no partial accounting");
}
'''


def run(clients, driver, selected="both"):
    source = (clients / "nss_qdisc/nss_qdisc_stats.c").read_text()
    common = (driver / "exports/nss_cmn.h").read_text()
    types = re.search(r"enum nss_cmn_response \{.*?\n\};", common, re.S).group()
    types += extract.structures.structure(common, "nss_cmn_msg")
    types += extract.structures.structure(common, "nss_cmn_node_stats")
    types += (driver / "exports/nss_shaper.h").read_text()
    types += (driver / "exports/nss_if.h").read_text()
    for name, macro, callback, cases in (
        ("basic", "#define NSS_FIRMWARE_VERSION_11_4\n", "nss_qdisc_stats_basic_stats_callback", BASIC),
        ("many", "", "nss_qdisc_stats_sync_many_callback", MANY)):
        if selected not in ("both", name):
            continue
        with tempfile.TemporaryDirectory(prefix="nss-stats-"+name+"-") as directory:
            cfile = Path(directory) / "stats.c"
            binary = cfile.with_suffix("")
            cfile.write_text(macro + PREFIX + types + SHIM + extract.function(source, callback) + cases)
            subprocess.run(["cc", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                            "-Werror=implicit-function-declaration", "-Wno-unused-function",
                            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                            "-fno-pie", "-no-pie", str(cfile), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30,
                           env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=Path, required=True)
    parser.add_argument("--drv", type=Path, required=True)
    parser.add_argument("--case", choices=("basic", "many", "both"), default="both")
    args = parser.parse_args()
    run(args.clients, args.drv, args.case)
