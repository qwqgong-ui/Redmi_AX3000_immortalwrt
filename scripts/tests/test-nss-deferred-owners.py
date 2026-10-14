#!/usr/bin/env python3
"""Run actual REO callbacks and peer finalizers across quarantine publication."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('owner_extract', Path(__file__).with_name('test-nss-control.py'))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
typedef uint32_t u32;typedef uint16_t u16;typedef uint8_t u8;typedef uint64_t u64;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
typedef struct { unsigned value; } refcount_t;
static void refcount_set(refcount_t *r,unsigned value) { r->value=value; }
static bool refcount_dec_and_test(refcount_t *r) { assert(r->value);return --r->value==0; }
#define CPTCFG_ATH11K_NSS_SUPPORT 1
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,x) ((v)=(x))
#define GFP_ATOMIC 0
#define DMA_BIDIRECTIONAL 1
#define FIELD_GET(mask,v) ((v)&(mask))
#define HAL_SRNG_TLV_HDR_TAG 0xff
#define HAL_REO_GET_QUEUE_STATS_STATUS 1
#define HAL_REO_FLUSH_QUEUE_STATUS 2
#define HAL_REO_FLUSH_CACHE_STATUS 3
#define HAL_REO_UNBLOCK_CACHE_STATUS 4
#define HAL_REO_FLUSH_TIMEOUT_LIST_STATUS 5
#define HAL_REO_DESCRIPTOR_THRESHOLD_REACHED_STATUS 6
#define HAL_REO_UPDATE_RX_REO_QUEUE_STATUS 7
#define HAL_TLV_HDR_LEN 0xff00
struct hal_reo_status_hdr {u32 info0,timestamp;};
#define ath11k_warn(...) ((void)0)
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(h) ((h)->next=(h),(h)->prev=(h))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_empty(h) ((h)->next==(h))
#define list_for_each_entry_safe(p,n,h,m) \
 for(p=container_of((h)->next,__typeof__(*p),m),n=container_of((p)->m.next,__typeof__(*p),m); \
 &(p)->m!=(h);p=n,n=container_of((n)->m.next,__typeof__(*n),m))
#define list_for_each_entry(p,h,m) for(struct list_head *it=(h)->next;it!=(h)&&((p)=container_of(it,__typeof__(*p),m),true);it=it->next)
static void list_add_tail(struct list_head *p,struct list_head *h) { p->next=h;p->prev=h->prev;h->prev->next=p;h->prev=p; }
static void list_del(struct list_head *p) { p->prev->next=p->next;p->next->prev=p->prev;p->next=p->prev=NULL; }
enum ath11k_reo_queue_phase {ATH11K_REO_QUEUE_PREPARED,ATH11K_REO_QUEUE_SUBMITTING,ATH11K_REO_QUEUE_PUBLISHED,ATH11K_REO_QUEUE_RETIRED,ATH11K_REO_QUEUE_UNRESOLVED};
struct ath11k_reo_queue {bool retiring,dma_live;enum ath11k_reo_queue_phase phase;};
struct dp_rx_tid { bool active;void *vaddr_unaligned;uintptr_t paddr,paddr_unaligned;unsigned size,pending_desc_size,ba_win_sz,unaligned_size,tid;struct ath11k_reo_queue *reo_queue; };
struct ath11k_peer { struct list_head list;refcount_t refs;struct dp_rx_tid rx_tid[2];unsigned peer_id; };
struct dp_reo_update_rx_queue_elem { struct list_head list;struct dp_rx_tid data;unsigned peer_id,tid;bool reo_cmd_update_rx_queue_resend_flag; };
struct ath11k_dp;
enum ath11k_reo_cmd_kind {ATH11K_REO_CMD_RETIRE,ATH11K_REO_CMD_QUERY};
struct ath11k_reo_query;
struct dp_reo_cmd { struct list_head list;unsigned cmd_num;u16 status_tag;enum ath11k_reo_cmd_kind kind;struct ath11k_reo_query *query;struct dp_rx_tid data;void (*handler)(struct ath11k_dp *,void *,int); };
struct hal_srng { bool initialized;pthread_mutex_t lock; };
struct ath11k_dp { struct { unsigned ring_id; } reo_status_ring;pthread_mutex_t reo_cmd_lock,reo_cmd_update_queue_lock,reo_stats_lock;bool reo_query_outstanding,reo_ownership_uncertain;unsigned reo_retained_count;u16 reo_cmd_status_tag[257];struct ath11k_reo_cmd_stats reo_cmd_stats;struct ath11k_reo_update_stats reo_update_stats;struct list_head reo_cmd_list,reo_cmd_update_rx_queue_list; };
struct ath11k_base { pthread_mutex_t base_lock;struct ath11k_dp dp;struct { struct hal_srng srng_list[1]; } hal;struct { _Atomic bool ownership_uncertain;struct list_head retained_host_peers; } nss;struct { unsigned reo_cmd_update_rx_queue_error; } soc_stats;void *dev; };
struct ath11k { struct ath11k_base *ab;struct ath11k_peer *bss_peer; };
struct hal_reo_status_header {u16 cmd_num;int cmd_status;u16 cmd_exe_time;u32 timestamp;};
struct hal_reo_status { struct hal_reo_status_header uniform_hdr; };
static void ath11k_dp_reo_queue_get(struct ath11k_reo_queue *q){assert(!q);}
static void ath11k_dp_reo_queue_put(struct ath11k_reo_queue *q){assert(!q);}
static void ath11k_dp_reo_query_complete(struct ath11k_reo_query *q,const struct hal_reo_status *s){(void)q;(void)s;assert(!"Query is covered by queue/query fixture");}
static void ath11k_dp_reo_query_put(struct ath11k_reo_query *q){(void)q;assert(!"Unexpected query fixture");}
static struct ath11k_base *active;
static struct ath11k_peer *lookup_peer;
static unsigned heap_frees,dma_frees,allocs,detaches,ast_cleanups,ring_accesses;
static bool allocation_failure,descriptor_available;
static _Thread_local bool publishing;
static _Atomic bool publication_waiting;
static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static bool callback_entered,callback_release;
static void spin_lock_bh(pthread_mutex_t *lock) { if(publishing&&lock==&active->hal.srng_list[0].lock)publication_waiting=true;assert(!pthread_mutex_lock(lock)); }
static void spin_unlock_bh(pthread_mutex_t *lock) { assert(!pthread_mutex_unlock(lock)); }
static void lockdep_assert_held(pthread_mutex_t *lock) { assert(pthread_mutex_trylock(lock)!=0); }
static void *kzalloc(size_t size,unsigned flags) { (void)flags;allocs++;return allocation_failure?NULL:calloc(1,size); }
static void kfree(void *p) { assert(p&&!active->nss.ownership_uncertain);heap_frees++;free(p); }
static void dma_free_noncoherent(void *dev,size_t size,void *p,uintptr_t addr,int dir) { (void)dev;(void)size;(void)addr;assert(dir==DMA_BIDIRECTIONAL&&p&&!active->nss.ownership_uncertain);dma_frees++;free(p); }
static struct ath11k_peer *ath11k_peer_find(struct ath11k *ar,int vdev,const u8 *mac) { (void)ar;(void)vdev;(void)mac;return lookup_peer; }
static void ath11k_nss_peer_detach(struct ath11k *ar,struct ath11k_peer *p) { assert(ar&&p);detaches++; }
static void ath11k_peer_ast_cleanup(struct ath11k *ar,struct ath11k_peer *p,bool local,unsigned count) { assert(ar&&p&&local&&!count);ast_cleanups++; }
static int ath11k_peer_rx_tid_delete_handler(struct ath11k_base *ab,struct dp_rx_tid *tid,unsigned number) { assert(ab==active&&tid&&number<2);return -1; }
static void ath11k_hal_srng_access_begin(struct ath11k_base *ab,struct hal_srng *s) { assert(ab==active&&s->initialized&&!ab->nss.ownership_uncertain);ring_accesses++; }
static void ath11k_hal_srng_access_end(struct ath11k_base *ab,struct hal_srng *s) { assert(ab==active&&s->initialized&&!ab->nss.ownership_uncertain); }
static u32 *ath11k_hal_srng_dst_get_next_entry(struct ath11k_base *ab,struct hal_srng *s) { static u32 tag=HAL_REO_UPDATE_RX_REO_QUEUE_STATUS;(void)ab;(void)s;if(!descriptor_available)return NULL;descriptor_available=false;return &tag; }
static int ath11k_hal_reo_process_status(u8 *desc,u8 *status) {(void)desc;*status=0;return 42;}
static void decode(struct ath11k_base *ab,u32 *desc,struct hal_reo_status *status) { assert(ab==active&&desc);status->uniform_hdr.cmd_num=42; }
#define ath11k_hal_reo_status_queue_stats decode
#define ath11k_hal_reo_flush_queue_status decode
#define ath11k_hal_reo_flush_cache_status decode
#define ath11k_hal_reo_unblk_cache_status decode
#define ath11k_hal_reo_flush_timeout_list_status decode
#define ath11k_hal_reo_desc_thresh_reached_status decode
#define ath11k_hal_reo_update_rx_reo_queue_status decode
'''

CASES = r'''
static void callback(struct ath11k_dp *dp,void *data,int status) {
 (void)status;assert(dp==&active->dp);assert(!pthread_mutex_lock(&gate));callback_entered=true;pthread_cond_broadcast(&condition);
 while(!callback_release)assert(!pthread_cond_wait(&condition,&gate));assert(!pthread_mutex_unlock(&gate));
 struct dp_rx_tid *tid=data;dma_free_noncoherent(active->dev,tid->unaligned_size,tid->vaddr_unaligned,tid->paddr_unaligned,DMA_BIDIRECTIONAL);
}
static void *process(void *p) { ath11k_dp_process_reo_status(p);return NULL; }
static void *publish(void *p) { publishing=true;ath11k_dp_dma_quarantine(p);return NULL; }
static void init(struct ath11k_base *ab) {
 memset(ab,0,sizeof(*ab));active=ab;pthread_mutex_init(&ab->base_lock,NULL);pthread_mutex_init(&ab->hal.srng_list[0].lock,NULL);
 pthread_mutex_init(&ab->dp.reo_cmd_lock,NULL);pthread_mutex_init(&ab->dp.reo_cmd_update_queue_lock,NULL);
 pthread_mutex_init(&ab->dp.reo_stats_lock,NULL);
 INIT_LIST_HEAD(&ab->dp.reo_cmd_list);INIT_LIST_HEAD(&ab->dp.reo_cmd_update_rx_queue_list);INIT_LIST_HEAD(&ab->nss.retained_host_peers);
 ab->hal.srng_list[0].initialized=true;
}
int main(void) {
 struct ath11k_base ab;init(&ab);struct ath11k ar={.ab=&ab};pthread_t service,quarantine;
 struct dp_reo_cmd *cmd=calloc(1,sizeof(*cmd));cmd->cmd_num=42;cmd->handler=callback;cmd->data.vaddr_unaligned=malloc(64);cmd->data.unaligned_size=64;
 cmd->status_tag=HAL_REO_UPDATE_RX_REO_QUEUE_STATUS;ab.dp.reo_cmd_status_tag[42]=cmd->status_tag;ab.dp.reo_cmd_stats.pending=1;
 list_add_tail(&cmd->list,&ab.dp.reo_cmd_list);descriptor_available=true;
 assert(!pthread_create(&service,NULL,process,&ab));assert(!pthread_mutex_lock(&gate));while(!callback_entered)assert(!pthread_cond_wait(&condition,&gate));assert(!pthread_mutex_unlock(&gate));
 assert(!pthread_create(&quarantine,NULL,publish,&ab));while(!publication_waiting)sched_yield();assert(!ab.nss.ownership_uncertain&&heap_frees==0&&dma_frees==0);
 assert(!pthread_mutex_lock(&gate));callback_release=true;pthread_cond_broadcast(&condition);assert(!pthread_mutex_unlock(&gate));
 pthread_join(service,NULL);pthread_join(quarantine,NULL);assert(ab.nss.ownership_uncertain&&dma_frees==1&&heap_frees==1);
 assert(!ab.dp.reo_cmd_stats.pending&&ab.dp.reo_cmd_stats.callbacks_claimed==1);
 cmd=calloc(1,sizeof(*cmd));cmd->data.vaddr_unaligned=malloc(64);list_add_tail(&cmd->list,&ab.dp.reo_cmd_list);descriptor_available=true;
 unsigned accesses=ring_accesses;ath11k_dp_process_reo_status(&ab);assert(ring_accesses==accesses&&!list_empty(&ab.dp.reo_cmd_list)&&heap_frees==1);
 struct ath11k_peer *peer=calloc(1,sizeof(*peer));peer->refs.value=1;peer->rx_tid[0]=(struct dp_rx_tid){.active=true,.vaddr_unaligned=malloc(64),.unaligned_size=64};lookup_peer=peer;ar.bss_peer=peer;
 allocation_failure=true;spin_lock_bh(&ab.base_lock);ath11k_peer_rx_tid_delete(&ar,peer,0);ath11k_peer_release(&ar,peer);spin_unlock_bh(&ab.base_lock);
 assert(peer->rx_tid[0].active&&peer->rx_tid[0].vaddr_unaligned&&!ar.bss_peer&&allocs==0&&!list_empty(&ab.nss.retained_host_peers)&&detaches==1&&ast_cleanups==1);
 assert(dma_frees==1&&peer->rx_tid[0].active);
 /* Test process teardown frees retained fixtures, not driver cleanup. */
 list_del(&cmd->list);free(cmd->data.vaddr_unaligned);free(cmd);list_del(&peer->list);free(peer->rx_tid[0].vaddr_unaligned);free(peer);
 ab.nss.ownership_uncertain=false;allocation_failure=false;
 peer=calloc(1,sizeof(*peer));peer->refs.value=1;lookup_peer=peer;
 spin_lock_bh(&ab.base_lock);ath11k_peer_release(&ar,peer);spin_unlock_bh(&ab.base_lock);assert(heap_frees==2&&list_empty(&ab.nss.retained_host_peers));
 /* Before SRNG initialization the base lock still serializes host owners. */
 ab.hal.srng_list[0].initialized=false;ath11k_dp_dma_quarantine(&ab);assert(ab.nss.ownership_uncertain);
 puts("deferred owners: real in-flight REO callback drain, retained command/peer/TID metadata without allocation and ordinary release passed");return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', required=True, type=Path)
    args = parser.parse_args()
    root = args.backports / 'drivers/net/wireless/ath/ath11k'
    rx, peer, mac = [(root / name).read_text() for name in ('dp_rx.c', 'peer.c', 'mac.c')]
    header = (root / 'dp.h').read_text()
    statistics = ''
    for name in ('ath11k_reo_cmd_stats', 'ath11k_reo_update_stats'):
        start = header.index('struct ' + name + ' {')
        statistics += header[start:header.index('};', start) + 2] + '\n'
    shim = SHIM.replace('struct ath11k_dp;', statistics + 'struct ath11k_dp;', 1)
    bodies = extractor.function(header, 'ath11k_dp_reo_update_status')
    bodies += extractor.function(rx, 'ath11k_dp_reo_tid_drop')
    bodies += extractor.function(rx, 'ath11k_dp_reo_tid_clone')
    bodies += extractor.function(rx, 'ath11k_dp_reo_retry_queues')
    bodies += extractor.function(rx.replace('*\nath11k_dp_reo_cmd_take', '*ath11k_dp_reo_cmd_take'), 'ath11k_dp_reo_cmd_take')
    bodies += '\n'.join(extractor.function(rx, name) for name in
                       ('ath11k_dp_dma_quarantine', 'ath11k_peer_rx_tid_delete',
                        'ath11k_dp_process_reo_status'))
    bodies += extractor.function(peer, 'ath11k_peer_put_locked')
    bodies += extractor.function(peer, 'ath11k_peer_release')
    for name, text in [('ath11k_peer_unmap_event', peer), ('ath11k_peer_unmap_v2_event', peer),
                       ('ath11k_peer_cleanup', peer), ('ath11k_mac_peer_cleanup_all', mac),
                       ('ath11k_mac_op_sta_state', mac)]:
        body = extractor.function(text, name)
        assert 'ath11k_peer_release(ar, peer)' in body and 'kfree(peer)' not in body, name
    with tempfile.TemporaryDirectory(prefix='nss-deferred-owners-') as temp:
        source, binary = Path(temp) / 'test.c', Path(temp) / 'test'
        source.write_text(shim + bodies + CASES)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Werror',
                        '-Wno-unused-function', '-Wno-unused-parameter',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-g', '-pthread', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15)

if __name__ == '__main__':
    main()
