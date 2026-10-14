#!/usr/bin/env python3
"""Exercise real FQ DMA change/free and node FREE callbacks under ASan/UBSan."""
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
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uintptr_t dma_addr_t;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define LINUX_VERSION_CODE 0x060c00
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define GFP_KERNEL 0
#define __GFP_RETRY_MAYFAIL 0
#define __GFP_NOWARN 0
#define __GFP_ZERO 0
#define DMA_TO_DEVICE 1
#define unlikely(x) (x)
#define NSS_CODEL_MIN_FQ_COUNT 64
#define NSS_QDISC_STATE_IDLE 0
#define NSS_QDISC_STATE_READY 1
#define NSS_QDISC_STATE_NODE_FREE_FAIL -16
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_SHAPER_RESPONSE_TYPE_SUCCESS 0
#define NSS_SHAPER_CONFIG_TYPE_SHAPER_NODE_CHANGE_PARAM 1
#define TCA_NSSCODEL_MAX 0
#define TCA_NSSCODEL_PARMS 0
#define nss_qdisc_trace(...) ((void)0)
#define nss_qdisc_info(...) ((void)0)
#define nss_qdisc_warning(...) ((void)0)
#define nss_qdisc_error(...) ((void)0)
typedef struct { int value; } atomic_t;
typedef struct { long value; } atomic_long_t;
#define ATOMIC_LONG_INIT(v) {v}
static void atomic_set(atomic_t *a,int value) { a->value=value; }
static void atomic_long_add(long value,atomic_long_t *a) { a->value+=value; }
static long atomic_long_read(atomic_long_t *a) { return a->value; }
static void wake_up(int *q) {}
struct list_head { struct list_head *next,*prev; };
#define LIST_HEAD(n) struct list_head n={&n,&n}
#define DEFINE_SPINLOCK(n) int n
#define spin_lock_bh(p) ((void)(p))
#define spin_unlock_bh(p) ((void)(p))
static void list_add_tail(struct list_head *n,struct list_head *h) { n->next=h;n->prev=h->prev;h->prev->next=n;h->prev=n; }
static unsigned pins, page_frees, unmaps, records, allocations;
static bool fail_record, fail_map, fail_config, fail_default, fail_unassign;
#define THIS_MODULE ((void *)1)
static void __module_get(void *module) { assert(module==THIS_MODULE);pins++; }
struct device { unsigned refs; };
static struct device dma_device;
static struct device *nss_shaper_get_dev(void) { return &dma_device; }
static struct device *get_device(struct device *d) { if(d)d->refs++;return d; }
static void put_device(struct device *d) { assert(d&&d->refs);d->refs--; }
static unsigned get_order(unsigned size) { unsigned order=0;while((4096U<<order)<size)order++;return order; }
static unsigned long __get_free_pages(int flags,unsigned order) { allocations++;return (unsigned long)calloc(1,4096U<<order); }
static void free_pages(unsigned long pages,unsigned order) { assert(pages);page_frees++;free((void *)pages); }
static void *kzalloc(size_t n,int flags) { if(fail_record)return NULL;records++;return calloc(1,n); }
static void kfree(void *memory) { assert(memory&&records);records--;free(memory); }
static dma_addr_t dma_map_single(struct device *dev,void *pages,unsigned bytes,int direction) {
 assert(dev==&dma_device&&dev->refs&&pages&&bytes==9216&&direction==DMA_TO_DEVICE);
 return fail_map?UINTPTR_MAX:(dma_addr_t)pages;
}
static bool dma_mapping_error(struct device *dev,dma_addr_t dma) { return dma==UINTPTR_MAX; }
static void dma_unmap_single(struct device *dev,dma_addr_t dma,unsigned bytes,int direction) {
 assert(dev==&dma_device&&dev->refs&&dma&&bytes==9216&&direction==DMA_TO_DEVICE);unmaps++;
}
struct nss_qdisc {
 bool fw_node_free_confirmed; unsigned qos_tag,type;
 atomic_t state; int wait_queue; void *qdisc;
};
struct nss_shaper_node_config {
 unsigned qos_tag;
 struct { struct { struct { unsigned interval,target,mtu; } cap;unsigned qlen_max,quantum,flows,flows_mem,flows_mem_sz,ecn; } codel_param; } snc;
};
struct nss_if_shaper_configure {
 struct { unsigned request_type,response_type;struct { struct nss_shaper_node_config shaper_node_config; } msg; } config;
};
struct nss_if_msg { struct { unsigned response,len; } cm;struct { struct nss_if_shaper_configure shaper_configure; } msg; };
struct net_device { char *name;unsigned tx_queue_len; };
static struct net_device device={"native",1000};
struct Qdisc { void *priv,*ops;unsigned limit; };
static int nss_fq_codel_qdisc_ops;
static int nss_codel_policy[1];
static void *qdisc_priv(struct Qdisc *sch) { return sch->priv; }
static struct net_device *qdisc_dev(struct Qdisc *sch) { return &device; }
static unsigned psched_mtu(struct net_device *dev) { return 1500; }
struct nlattr { int unused; };
struct netlink_ext_ack { int unused; };
struct tc_nsscodel_qopt { unsigned target,limit,interval,quantum,ecn,set_default,flows; };
static struct tc_nsscodel_qopt options={5000,128,100000,1514,0,1,128};
static struct tc_nsscodel_qopt *nss_qdisc_qopt_get(struct nlattr *opt,void *policy,struct nlattr **tb,int max,int parms,struct netlink_ext_ack *ack) { return &options; }
static unsigned nss_codel_flow_count(struct Qdisc *sch,struct tc_nsscodel_qopt *opt) { return opt->flows; }
static unsigned configured_bytes;
static int nss_qdisc_configure(struct nss_qdisc *nq,struct nss_if_msg *msg,int kind) {
 configured_bytes=msg->msg.shaper_configure.config.msg.shaper_node_config.snc.codel_param.flows_mem_sz;
 assert(configured_bytes==9216);return fail_config?-1:0;
}
static int nss_qdisc_set_default(struct nss_qdisc *nq) { return fail_default?-1:0; }
static void nss_qdisc_root_cleanup_shaper_unassign(struct nss_qdisc *nq) { atomic_set(&nq->state,fail_unassign?-17:0); }
static void nss_qdisc_child_cleanup_final(struct nss_qdisc *nq) { atomic_set(&nq->state,0); }
'''

SCHED = r'''
struct nss_codel_sched_data {
 struct nss_qdisc nq;
 unsigned target,limit,interval,flows,flows_req,quantum;
 unsigned long flow_queue_mem;dma_addr_t dma_mapped_mem;unsigned flow_queue_sz;
 struct nss_codel_flow_memory *flow_memory;unsigned ecn,set_default;
};
'''

TEST = r'''
static void setup(struct nss_codel_sched_data *q,struct Qdisc *sch) {
 memset(q,0,sizeof(*q));q->flow_queue_sz=72;q->nq.qos_tag=0x10000;
 sch->priv=q;sch->ops=&nss_fq_codel_qdisc_ops;
}
static struct nss_if_msg ack(void) {
 struct nss_if_msg m={0};m.cm.response=NSS_CMN_RESPONSE_ACK;
 m.cm.len=offsetof(struct nss_if_shaper_configure,config.response_type)+sizeof(m.msg.shaper_configure.config.response_type);
 return m;
}
int main(void) {
 struct nss_codel_sched_data q;struct Qdisc sch;struct nlattr opt={0};
 unsigned base;
 setup(&q,&sch);fail_record=true;base=page_frees;
 assert(nss_codel_change(&sch,&opt,NULL)<0&&!q.flow_memory&&!q.flow_queue_mem);
 assert(page_frees==base+1&&!dma_device.refs);fail_record=false;
 setup(&q,&sch);fail_map=true;base=page_frees;
 assert(nss_codel_change(&sch,&opt,NULL)<0&&!q.flow_memory&&!q.flow_queue_mem);
 assert(page_frees==base+1&&!dma_device.refs&&!unmaps);fail_map=false;

 setup(&q,&sch);assert(!nss_codel_change(&sch,&opt,NULL));
 assert(q.flow_memory->published&&q.flow_memory->mapped&&dma_device.refs==1);
 assert(!nss_codel_change(&sch,&opt,NULL)&&configured_bytes==9216);
 struct nss_if_msg m=ack();fail_unassign=true;
 nss_qdisc_root_cleanup_free_node_callback(&q.nq,&m);
 assert(q.nq.fw_node_free_confirmed&&q.nq.state.value==-17);
 nss_codel_flow_queues_free(&q);assert(!q.flow_memory&&!dma_device.refs&&unmaps==1);
 nss_codel_flow_queues_free(&q);assert(unmaps==1);fail_unassign=false;

 setup(&q,&sch);assert(!nss_codel_change(&sch,&opt,NULL));m=ack();
 nss_qdisc_child_cleanup_free_node_callback(&q.nq,&m);
 assert(q.nq.fw_node_free_confirmed);nss_codel_flow_queues_free(&q);assert(unmaps==2);

 /* Published configure failure must survive until a real node FREE. */
 setup(&q,&sch);fail_config=true;base=page_frees;
 assert(nss_codel_change(&sch,&opt,NULL)<0&&q.flow_memory&&q.flow_memory->published);
 assert(page_frees==base);fail_config=false;m=ack();
 nss_qdisc_root_cleanup_free_node_callback(&q.nq,&m);nss_codel_flow_queues_free(&q);
 assert(page_frees==base+1);

 /* Short ACK and NACK cannot transfer DMA ownership back to the host. */
 setup(&q,&sch);assert(!nss_codel_change(&sch,&opt,NULL));m=ack();m.cm.len=0;
 struct nss_if_msg *header_only=calloc(1,offsetof(struct nss_if_msg,msg));
 nss_qdisc_root_cleanup_free_node_callback(&q.nq,header_only);
 assert(!q.nq.fw_node_free_confirmed);free(header_only);
 nss_qdisc_root_cleanup_free_node_callback(&q.nq,&m);assert(!q.nq.fw_node_free_confirmed);
 m=ack();m.cm.response=1;nss_qdisc_child_cleanup_free_node_callback(&q.nq,&m);
 assert(!q.nq.fw_node_free_confirmed);base=page_frees;unsigned before_unmaps=unmaps;
 nss_codel_flow_queues_free(&q);assert(page_frees==base&&unmaps==before_unmaps&&pins==1&&dma_device.refs==1);
 assert(!q.flow_memory&&!q.flow_queue_mem&&!q.dma_mapped_mem);
 nss_codel_flow_queues_free(&q);assert(pins==1);

 /* SET_DEFAULT failure and no FREE response also retain the published map. */
 setup(&q,&sch);fail_default=true;assert(nss_codel_change(&sch,&opt,NULL)<0&&q.flow_memory);
 fail_default=false;nss_codel_flow_queues_free(&q);assert(pins==2&&unmaps==before_unmaps&&dma_device.refs==2);
 setup(&q,&sch);assert(!nss_codel_change(&sch,&opt,NULL));m=ack();m.msg.shaper_configure.config.response_type=1;
 nss_qdisc_child_cleanup_free_node_callback(&q.nq,&m);assert(!q.nq.fw_node_free_confirmed);
 nss_codel_flow_queues_free(&q);assert(pins==3&&unmaps==before_unmaps&&dma_device.refs==3);
 puts("PASS real FQ change/free and root/child FREE callbacks: allocation/map failures, preserved reconfigure length, configure/default failure, short ACK/NACK/timeout retention, successful FREE with failed UNASSIGN, matched DMA device/direction, repeated destroy");
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clients', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    core = (args.clients / 'nss_qdisc/nss_qdisc.c').read_text()
    codel = (args.clients / 'nss_qdisc/nss_codel.c').read_text()
    record = re.search(r'struct nss_codel_flow_memory \{.*?\n\};', codel, re.S).group(0)
    globals_ = ('static LIST_HEAD(nss_codel_retained_flow_memory);\n'
                'static DEFINE_SPINLOCK(nss_codel_retained_lock);\n'
                'static atomic_long_t nss_codel_retained_bytes = ATOMIC_LONG_INIT(0);\n')
    callbacks = ''.join(helper.function(core, name) for name in
                        ('nss_qdisc_node_free_succeeded', 'nss_qdisc_root_cleanup_free_node_callback',
                         'nss_qdisc_child_cleanup_free_node_callback'))
    change = helper.function(codel, 'nss_codel_change')
    # The 6.12 declaration precedes a common body behind an old-kernel #if.
    change = ('static int nss_codel_change(struct Qdisc *sch, struct nlattr *opt, '
              'struct netlink_ext_ack *extack)\n' + change[change.index('{'):])
    functions = helper.function(codel, 'nss_codel_flow_queues_free') + change
    with tempfile.TemporaryDirectory(prefix='nss-qdisc-dma-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(SHIM + record + globals_ + SCHED + callbacks + functions + TEST)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=15)

if __name__ == '__main__':
    main()
