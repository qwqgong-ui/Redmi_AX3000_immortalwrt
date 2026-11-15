#!/usr/bin/env python3
"""Test the actual 12.2 table/detach with real locks and a draining RCU shim."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#define GFP_KERNEL 0
#define NSS_QDISC_LIST_TABLE_INIT_SIZE 1024
#define nss_qdisc_warning(...) ((void)0)
#define nss_qdisc_info(...) ((void)0)
#define spin_lock_bh pthread_mutex_lock
#define spin_unlock_bh pthread_mutex_unlock
#define spin_lock_init(p) pthread_mutex_init(p,NULL)
struct hlist_node { struct hlist_node *next,**pprev; };
struct hlist_head { struct hlist_node *first; };
#define INIT_HLIST_NODE(n) ((n)->next=NULL,(n)->pprev=NULL)
#define INIT_HLIST_HEAD(h) ((h)->first=NULL)
#define hlist_unhashed(n) (!(n)->pprev)
static void hlist_del_init(struct hlist_node *n) {
 if(n->pprev) { *n->pprev=n->next;if(n->next)n->next->pprev=n->pprev; }
 INIT_HLIST_NODE(n);
}
static void hlist_add_head(struct hlist_node *n,struct hlist_head *h) {
 n->next=h->first;if(n->next)n->next->pprev=&n->next;
 h->first=n;n->pprev=&h->first;
}
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define hlist_for_each_entry(v,h,m) \
 for(struct hlist_node *_p=(h)->first;_p&&((v)=container_of(_p,__typeof__(*(v)),m),1);_p=_p->next)
#define hlist_for_each_entry_safe(v,tmp,h,m) \
 for(struct hlist_node *_p=(h)->first;_p&&((tmp)=_p->next,(v)=container_of(_p,__typeof__(*(v)),m),1);_p=(tmp))
struct Qdisc { int unused; };
struct nss_qdisc_htable { pthread_mutex_t lock;uint32_t count,htsize;struct hlist_head *htable; };
struct nss_qdisc { unsigned qos_tag;struct hlist_node hlist;struct nss_qdisc_htable *stats_table;bool is_class;struct Qdisc *qdisc; };
static bool fail_alloc;
static unsigned get_order(unsigned n) { unsigned o=0;while((4096U<<o)<n)o++;return o; }
static unsigned long __get_free_pages(int flags,unsigned order) { return fail_alloc?0:(unsigned long)calloc(1,4096UL<<order); }
static void free_pages(unsigned long p,unsigned o) { free((void*)p); }
static pthread_rwlock_t rcu=PTHREAD_RWLOCK_INITIALIZER;
static atomic_bool sync_started,writer_done,release_reader,reader_entered,lookup_stop;
static void synchronize_net(void) {
 atomic_store(&sync_started,true);
 pthread_rwlock_wrlock(&rcu);
 pthread_rwlock_unlock(&rcu);
}
'''
TEST = r'''
static struct Qdisc qdisc;
static struct nss_qdisc_htable table;
static struct nss_qdisc *victim;
static void *hold_reader(void *arg) {
 pthread_rwlock_rdlock(&rcu);
 struct nss_qdisc *n=nss_qdisc_htable_entry_lookup(&table,0xab0000);
 assert(n==victim);atomic_store(&reader_entered,true);
 while(!atomic_load(&release_reader))sched_yield();
 assert(n->qos_tag==0xab0000);
 pthread_rwlock_unlock(&rcu);return NULL;
}
static void *remove_writer(void *arg) {
 nss_qdisc_stats_qdisc_detach(victim);
 free(victim);atomic_store(&writer_done,true);return NULL;
}
static void *lookup_reader(void *arg) {
 while(!atomic_load(&lookup_stop)) {
  pthread_rwlock_rdlock(&rcu);
  assert(nss_qdisc_htable_entry_lookup(&table,0xab0000)==victim);
  pthread_rwlock_unlock(&rcu);
 }
 return NULL;
}
int main(void) {
 assert(nss_qdisc_htable_init(&table));
 struct nss_qdisc empty={.qdisc=&qdisc};
 nss_qdisc_stats_qdisc_detach(&empty);
 empty.is_class=true;nss_qdisc_stats_qdisc_detach(&empty);
 victim=calloc(1,sizeof(*victim));victim->qdisc=&qdisc;victim->qos_tag=0xab0000;
 nss_qdisc_htable_entry_add(&table,victim);
 nss_qdisc_htable_entry_add(&table,victim);
 assert(table.count==1&&victim->stats_table==&table);
 struct nss_qdisc_htable other={0};assert(nss_qdisc_htable_init(&other));
 nss_qdisc_htable_entry_del(&other,victim);assert(table.count==1&&victim->stats_table==&table);
 pthread_t reader,writer;
 pthread_create(&reader,NULL,hold_reader,NULL);
 while(!atomic_load(&reader_entered))sched_yield();
 pthread_create(&writer,NULL,remove_writer,NULL);
 while(!atomic_load(&sync_started))sched_yield();
 assert(!atomic_load(&writer_done));
 atomic_store(&release_reader,true);
 pthread_join(reader,NULL);pthread_join(writer,NULL);
 assert(!table.count&&!nss_qdisc_htable_entry_lookup(&table,0xab0000));
 victim=calloc(1,sizeof(*victim));victim->qdisc=&qdisc;victim->qos_tag=0xab0000;
 nss_qdisc_htable_entry_add(&table,victim);
 pthread_create(&reader,NULL,lookup_reader,NULL);
 struct nss_qdisc *nodes=calloc(5000,sizeof(*nodes));
 for(unsigned i=0;i<5000;i++) {
  nodes[i].qos_tag=(i+0x100)<<16;nodes[i].qdisc=&qdisc;
  nss_qdisc_htable_entry_add(&table,&nodes[i]);
  nss_qdisc_htable_resize(&qdisc,&table);
 }
 atomic_store(&lookup_stop,true);pthread_join(reader,NULL);
 assert(table.htsize==8192&&table.count==5001);
 /* Allocation failure must not publish a size for unallocated storage. */
 unsigned size=table.htsize;table.count=size;fail_alloc=true;
 nss_qdisc_htable_resize(&qdisc,&table);assert(table.htsize==size);
 fail_alloc=false;table.count=5001;
 /* Root storage may be withdrawn before a child's destructor runs. */
 nss_qdisc_htable_dealloc(&table);
 assert(!victim->stats_table&&!nodes[4999].stats_table);
 nss_qdisc_stats_qdisc_detach(victim);
 nss_qdisc_stats_qdisc_detach(victim);
 nss_qdisc_htable_dealloc(&table);
 nss_qdisc_htable_dealloc(&other);
 free(victim);free(nodes);
 puts("PASS actual 12.2 table owner: concurrent resize/lookup, draining detach, duplicate/unattached/class detach, allocation failure and root-before-child destruction");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clients', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source = (args.clients / 'nss_qdisc/nss_qdisc_htable.c').read_text()
    table = source[source.index('static inline uint32_t nss_qdisc_htable_entry_compute_hash'):]
    stats = (args.clients / 'nss_qdisc/nss_qdisc_stats.c').read_text()
    # Select the actual current firmware branch; the first definition is 11.4.
    stats = stats[stats.index('#else /* !NSS_FIRMWARE_VERSION_11_4 */'):]
    detach = helper.function(stats, 'nss_qdisc_stats_qdisc_detach')
    with tempfile.TemporaryDirectory(prefix='nss-stats-table-owner-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(SHIM + table + detach + TEST)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-pthread',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-fno-pie', '-no-pie', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=15)


if __name__ == '__main__':
    main()
