#!/usr/bin/env python3
"""Exercise actual NSS stats writes against actual Linux skb queue functions."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <limits.h>
typedef uint64_t __u64;
typedef int refcount_t;
typedef int spinlock_t;
#define LINUX_VERSION_CODE 0x060c00
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define READ_ONCE(x) (x)
#define likely(x) (x)
#define TCQ_F_CPUSTATS 1
#define QDISC_STATE_NON_EMPTY 1
#define TC_H_MAJ(x) ((x)&0xffff0000U)
#define TC_H_MIN(x) ((x)&0xffffU)
#define nss_qdisc_info(...) ((void)0)
#define spin_lock(p) ((void)(p))
#define spin_unlock(p) ((void)(p))
#define spin_lock_bh(p) ((void)(p))
#define spin_unlock_bh(p) ((void)(p))
struct sk_buff { struct sk_buff *next; };
struct qdisc_skb_head { struct sk_buff *head,*tail;unsigned qlen; };
struct gnet_stats_basic_sync { uint64_t bytes,packets; };
struct gnet_stats_queue { unsigned backlog,drops,qlen,requeues,overlimits; };
struct Qdisc { struct qdisc_skb_head q;unsigned flags,state;struct gnet_stats_basic_sync bstats;struct gnet_stats_queue qstats;refcount_t refcnt; };
struct nss_shaper_node_stats_response {
 unsigned qos_tag;
 struct { unsigned qlen_packets,qlen_bytes;struct {unsigned dequeued_bytes,dequeued_packets,enqueued_packets_dropped,dequeued_packets_dropped,queue_overrun;} delta; } sn_stats;
};
struct nss_qdisc;
struct nss_qdisc_stats_wq { struct nss_qdisc *nqt; };
struct nss_qdisc { struct Qdisc *qdisc;struct nss_qdisc_stats_wq *stats_wq;bool is_class;struct gnet_stats_basic_sync bstats;struct gnet_stats_queue qstats;refcount_t refcnt;spinlock_t lock;void (*stats_cb)(struct nss_qdisc *,struct nss_shaper_node_stats_response *); };
static struct nss_qdisc *nss_qdisc_htable_entry_lookup(struct nss_qdisc **table,unsigned tag) { return *table; }
static struct nss_qdisc *nss_qdisc_stats_find_class_nq(struct nss_qdisc *nq,unsigned tag) { return nq; }
static spinlock_t root_lock;
static spinlock_t *qdisc_lock(struct Qdisc *q) { return &root_lock; }
static void u64_stats_add(uint64_t *value,uint64_t add) { *value+=add; }
'''

TEST = r'''
int main(void) {
 struct Qdisc q={0};struct nss_qdisc nq={.qdisc=&q};
 struct nss_qdisc_stats_wq work={.nqt=&nq};nq.stats_wq=&work;
 struct sk_buff packet={0};struct nss_shaper_node_stats_response report={.qos_tag=0x10000};
 __qdisc_enqueue_tail(&packet,&q.q);
 assert(q.q.qlen==1&&q.q.head==&packet&&!qdisc_is_empty(&q));
 report.sn_stats.qlen_packets=0;
 nss_qdisc_stats_process_node_stats(&nq,&report);
 assert(q.qstats.qlen==0);
#ifdef EXPECT_LEGACY
 assert(q.q.head==&packet&&qdisc_is_empty(&q));
 assert(__qdisc_dequeue_head(&q.q)==&packet&&q.q.qlen==UINT_MAX);
 puts("REPRODUCED actual firmware stats mark a nonempty host queue empty, then Linux dequeue underflows qlen to UINT_MAX");
#else
 assert(q.q.qlen==1&&q.q.head==&packet&&!qdisc_is_empty(&q));
 assert(__qdisc_dequeue_head(&q.q)==&packet&&q.q.qlen==0&&qdisc_is_empty(&q));
 struct sk_buff first={0},second={0};
 __qdisc_enqueue_tail(&first,&q.q);__qdisc_enqueue_tail(&second,&q.q);
 report.sn_stats.qlen_packets=7;report.sn_stats.qlen_bytes=4096;
 report.sn_stats.delta.dequeued_packets=3;report.sn_stats.delta.dequeued_bytes=1000;
 nss_qdisc_stats_process_node_stats(&nq,&report);
 assert(q.q.qlen==2&&q.qstats.qlen==7&&q.qstats.backlog==4096);
 assert(q.bstats.packets==3&&q.bstats.bytes==1000);
 assert(__qdisc_dequeue_head(&q.q)==&first);assert(__qdisc_dequeue_head(&q.q)==&second);
 assert(!q.q.head&&!q.q.tail&&!q.q.qlen&&qdisc_is_empty(&q));
 nq.is_class=true;report.qos_tag=0x10001;
 nss_qdisc_stats_process_node_stats(&nq,&report);
 assert(!q.q.qlen&&nq.qstats.qlen==7&&nq.qstats.backlog==4096);
 puts("PASS actual NSS stats update and Linux queue functions: firmware queue length stays in reported statistics; queued host skb and scheduler emptiness remain intact");
#endif
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clients', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--expect-legacy-corruption', action='store_true')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source = (args.clients / 'nss_qdisc/nss_qdisc_stats.c').read_text()
    kernel = (args.kernel / 'include/net/sch_generic.h').read_text()
    functions = ''.join(helper.function(kernel, name) for name in (
        'nolock_qdisc_is_empty', 'qdisc_is_percpu_stats', 'qdisc_is_empty',
        '__qdisc_enqueue_tail', '__qdisc_dequeue_head'))
    functions += helper.function(source, 'nss_qdisc_stats_process_node_stats')
    with tempfile.TemporaryDirectory(prefix='nss-host-queue-stats-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(SHIM + functions + TEST)
        command = ['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        if args.expect_legacy_corruption:
            command.append('-DEXPECT_LEGACY')
        subprocess.run(command + [str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=15)

if __name__ == '__main__':
    main()
