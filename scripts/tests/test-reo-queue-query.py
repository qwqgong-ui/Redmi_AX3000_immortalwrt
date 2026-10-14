#!/usr/bin/env python3
"""Execute queue references, WMI instances and private REO queries under sanitizers."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

extract = load("queue_functions", "test-nss-control.py")
types = load("queue_types", "test-reo-command-lifetime.py")

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <stddef.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include <unistd.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
typedef uintptr_t dma_addr_t;
typedef pthread_mutex_t spinlock_t;
typedef struct {atomic_uint value;} refcount_t;
struct completion {pthread_mutex_t lock;pthread_cond_t cond;bool done;};
static void refcount_set(refcount_t *r,unsigned n){atomic_store(&r->value,n);}
static void refcount_inc(refcount_t *r){assert(atomic_fetch_add(&r->value,1)>0);}
static bool refcount_dec_and_test(refcount_t *r){unsigned old=atomic_fetch_sub(&r->value,1);assert(old);return old==1;}
static void init_completion(struct completion *c){pthread_mutex_init(&c->lock,NULL);pthread_cond_init(&c->cond,NULL);c->done=false;}
static void complete(struct completion *c){pthread_mutex_lock(&c->lock);c->done=true;pthread_cond_broadcast(&c->cond);pthread_mutex_unlock(&c->lock);}
static unsigned wait_for_completion_timeout(struct completion *c,unsigned ms){
 struct timespec end;clock_gettime(CLOCK_REALTIME,&end);end.tv_nsec+=(long)ms*1000000;
 end.tv_sec+=end.tv_nsec/1000000000;end.tv_nsec%=1000000000;
 pthread_mutex_lock(&c->lock);while(!c->done){int rc=pthread_cond_timedwait(&c->cond,&c->lock,&end);if(rc==ETIMEDOUT)break;assert(!rc);}
 bool done=c->done;pthread_mutex_unlock(&c->lock);return done;
}
#define msecs_to_jiffies(ms) ((ms)/20)
#define __packed __attribute__((packed))
#define BIT(n) (UINT32_C(1)<<(n))
#define GENMASK(h,l) ((UINT32_MAX>>(31-(h)))&~((UINT32_C(1)<<(l))-1))
#define FIELD_GET(mask,x) (((x)&(mask))>>__builtin_ctz(mask))
#define FIELD_PREP(mask,x) (((x)<<__builtin_ctz(mask))&(mask))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define GFP_ATOMIC 0
#define GFP_KERNEL 1
#define DMA_BIDIRECTIONAL 2
#define DMA_TO_DEVICE 1
#define ETH_ALEN 6
#define IEEE80211_NUM_TIDS 16
	#define ATH11K_FLAG_CRASH_FLUSH 0
	#define ATH11K_FLAG_QMI_FAIL 1
#define test_bit(n,p) (!!(*(p)&(1ul<<(n))))
#define spin_lock_bh(p) assert(!pthread_mutex_lock(p))
#define spin_unlock_bh(p) assert(!pthread_mutex_unlock(p))
#define lockdep_assert_held(p) do{int rc=pthread_mutex_trylock(p);assert(rc==EBUSY);}while(0)
#define U64_MAX UINT64_MAX
#define lower_32_bits(x) ((u32)(x))
#define upper_32_bits(x) ((u32)((u64)(x)>>32))
#define PTR_ALIGN(p,a) ((__typeof__(p))(((uintptr_t)(p)+(a)-1)&~((uintptr_t)(a)-1)))
#define memset_startat(p,x,m) memset(&(p)->m,x,sizeof(*(p))-offsetof(__typeof__(*(p)),m))
#define ffz(x) __builtin_ctz(~(unsigned)(x))
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
static unsigned warnings;
#define WARN_ON_ONCE(x) ((x)?(warnings++,true):false)
struct list_head {struct list_head *next,*prev;};
#define INIT_LIST_HEAD(h) (*(h)=(struct list_head){(h),(h)})
#define list_empty(h) ((h)->next==(h))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_for_each_entry(p,h,m) for(struct list_head *it=(h)->next;it!=(h)&&((p)=container_of(it,__typeof__(*(p)),m),true);it=it->next)
#define list_for_each_entry_safe(p,n,h,m) for(struct list_head *it=(h)->next,*next;it!=(h)&&((p)=container_of(it,__typeof__(*(p)),m),next=it->next,(n)=next==(h)?NULL:container_of(next,__typeof__(*(n)),m),true);it=next)
static void list_add_tail(struct list_head *n,struct list_head *h){n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n;}
static void list_del(struct list_head *n){n->prev->next=n->next;n->next->prev=n->prev;}
struct device {unsigned refs;};
static struct device *get_device(struct device *d){d->refs++;return d;}
static void put_device(struct device *d){assert(d->refs>1);d->refs--;}
struct sk_buff_head {unsigned marker;};
struct timer_list {unsigned marker;};
struct hal_reo_dest_ring {u32 queue_addr_lo,info0;};
struct work_struct {void (*fn)(struct work_struct *);};
struct ath11k_base;struct ath11k_peer;struct ath11k_dp;struct ath11k_reo_query;
struct hal_tlv_hdr {u32 tl;u8 value[];};
static bool fail_allocation,fail_dma;
static unsigned allocations,heap_frees,dma_allocations,dma_frees;
static void *kzalloc(size_t size,int flags){(void)flags;if(fail_allocation)return NULL;allocations++;return calloc(1,size);}
static void kfree(void *p){if(p){heap_frees++;free(p);}}
static void *dma_alloc_noncoherent(struct device *d,size_t size,dma_addr_t *addr,int direction,int flags){
 (void)d;(void)flags;assert(direction==DMA_BIDIRECTIONAL);if(fail_dma)return NULL;
 dma_allocations++;*addr=0x51000000+dma_allocations*4096;return aligned_alloc(128,(size+127)&~(size_t)127);
}
static void dma_free_noncoherent(struct device *d,size_t size,void *p,dma_addr_t addr,int direction){
 (void)d;(void)size;(void)addr;assert(p&&direction==DMA_BIDIRECTIONAL);dma_frees++;free(p);
}
static void dma_sync_single_for_device(struct device *d,dma_addr_t addr,size_t size,int direction){(void)d;(void)addr;(void)size;assert(direction==DMA_TO_DEVICE);}
static bool ether_addr_equal(const u8 *a,const u8 *b){return !memcmp(a,b,6);}
static void ether_addr_copy(u8 *a,const u8 *b){memcpy(a,b,6);}
'''

STRUCTURES = r'''
struct ath11k_hp_update_timer {unsigned unused;};
struct hal_srng {spinlock_t lock;bool initialized;unsigned num_entries,hp;u32 slot[16][16];unsigned count,read;u32 replies[64][32];};
struct hal_srng_params {u32 *ring_base_vaddr;unsigned num_entries;};
struct ath11k_hal {struct hal_srng srng_list[2];unsigned avail_blk_resource,current_blk_index;};
struct ath11k_dp {
 struct ath11k_base *ab;spinlock_t reo_cmd_lock,reo_cmd_update_queue_lock,reo_stats_lock;
 bool reo_cmd_accepting,reo_query_outstanding,reo_ownership_uncertain;u64 reo_cmd_epoch,reo_queue_generation;
	 u32 reo_retained_count,reo_wmi_inflight,reo_cmd_cache_flush_count,reo_pn_outstanding;
	 struct ath11k_reo_pn_stats reo_pn_stats;
 u16 reo_cmd_status_tag[257];struct ath11k_reo_cmd_stats reo_cmd_stats;struct ath11k_reo_update_stats reo_update_stats;
 struct list_head reo_cmd_list,reo_cmd_update_rx_queue_list,reo_cmd_cache_flush_list,reo_retained_queues;
 struct {unsigned ring_id;} reo_cmd_ring,reo_status_ring;struct ath11k_hp_update_timer reo_cmd_timer;
};
struct ath11k {struct ath11k_base *ab;struct list_head peers;spinlock_t conf_mutex,tbl_mtx_lock;unsigned num_peers,num_stations;};
#define mutex_lock(p) spin_lock_bh(p)
#define mutex_unlock(p) spin_unlock_bh(p)
#define list_first_entry(h,t,m) container_of((h)->next,t,m)
struct ieee80211_sta {u8 addr[6];};
struct ieee80211_ampdu_params {struct ieee80211_sta *sta;u8 tid;};
struct ath11k_vif {struct ath11k *ar;int vdev_id;};
struct ath11k_peer {struct list_head list;refcount_t refs;int vdev_id,peer_id;u8 addr[6];bool dp_setup_done;void *tfm_mmic;struct dp_rx_tid rx_tid[17];};
struct hw_regs {u32 hal_reo1_aging_thresh_ix_0,hal_reo1_aging_thresh_ix_1,hal_reo1_aging_thresh_ix_2,hal_reo1_aging_thresh_ix_3;};
static const struct hw_regs regs={.hal_reo1_aging_thresh_ix_0=0x564,.hal_reo1_aging_thresh_ix_1=0x568,.hal_reo1_aging_thresh_ix_2=0x56c,.hal_reo1_aging_thresh_ix_3=0x570};
struct ath11k_base {struct device *dev;spinlock_t base_lock;unsigned long dev_flags;struct ath11k_dp dp;struct ath11k_hal hal;struct {const struct hw_regs *regs;} hw_params;struct {bool ownership_uncertain;struct list_head retained_host_peers;} nss;unsigned num_radios;struct {struct ath11k *ar;} pdevs[1];struct {unsigned reo_cmd_update_rx_queue_error,hal_reo_cmd_drain,reo_cmd_cache_error;} soc_stats;};
static unsigned aging_reads;
static u32 ath11k_hif_read32(struct ath11k_base *ab,u32 address){
 assert(ab->hw_params.regs==&regs);lockdep_assert_held(&ab->dp.reo_cmd_lock);
 u32 offset=address-HAL_SEQ_WCSS_UMAC_REO_REG;assert(offset>=0x564&&offset<=0x570&&!((offset-0x564)%4));
 aging_reads++;return 40000+(offset-0x564)/4;
}
static struct ath11k_peer *replacement;
static int wmi_result;
static unsigned wmi_calls;
static bool close_in_wmi,delete_in_wmi,check_fragment_in_wmi;
static void ath11k_peer_get(struct ath11k_peer *p);
static void ath11k_peer_put(struct ath11k *ar,struct ath11k_peer *p);
static void ath11k_peer_put_locked(struct ath11k *ar,struct ath11k_peer *p);
static void ath11k_dp_reo_retry_queues(struct ath11k_base *ab);
static void ath11k_dp_rx_tid_del_func(struct ath11k_dp *,void *,enum hal_reo_cmd_status);
static void ath11k_peer_rx_tid_delete(struct ath11k *,struct ath11k_peer *,u8);
static void ath11k_dp_reo_query_quarantine(struct ath11k_base *);
static inline void ath11k_dp_reo_cmd_close(struct ath11k_dp *);
static bool ath11k_dp_reo_fragment_match(const struct dp_rx_tid *,const struct hal_reo_dest_ring *);
static bool unmap_during_cleanup;
static unsigned cleanup_rhash_deletes;
static void ath11k_peer_rhash_delete(struct ath11k *ar,struct ath11k_peer *p){(void)ar;(void)p;cleanup_rhash_deletes++;}
static void ath11k_peer_rx_tid_cleanup(struct ath11k *ar,struct ath11k_peer *p){
 lockdep_assert_held(&ar->ab->base_lock);
 if(!unmap_during_cleanup)return;
 unmap_during_cleanup=false;spin_unlock_bh(&ar->ab->base_lock);spin_lock_bh(&ar->ab->base_lock);
 list_del(&p->list);ath11k_peer_put_locked(ar,p);
 if(!list_empty(&ar->peers)){struct ath11k_peer *next=list_first_entry(&ar->peers,struct ath11k_peer,list);list_del(&next->list);ath11k_peer_put_locked(ar,next);}
}
static int ath11k_dp_tx_send_reo_cmd(struct ath11k_base *,struct dp_rx_tid *,enum hal_reo_cmd_type,struct ath11k_hal_reo_cmd *,void (*)(struct ath11k_dp *,void *,enum hal_reo_cmd_status));
static int ath11k_dp_tx_reo_query(struct ath11k_base *,struct ath11k_reo_query *);
static struct ath11k_peer *ath11k_peer_find(struct ath11k *ar,int vdev,const u8 *mac){
 lockdep_assert_held(&ar->ab->base_lock);struct ath11k_peer *p;
 list_for_each_entry(p,&ar->peers,list)if(p->vdev_id==vdev&&ether_addr_equal(p->addr,mac))return p;return NULL;
}
static int ath11k_wmi_peer_rx_reorder_queue_setup(struct ath11k *ar,int vdev,const u8 *mac,dma_addr_t addr,unsigned tid,unsigned enable,unsigned window){
 (void)addr;(void)tid;(void)enable;(void)window;wmi_calls++;
 if(close_in_wmi){assert(ar->ab->dp.reo_wmi_inflight==1);ath11k_dp_reo_cmd_close(&ar->ab->dp);ath11k_dp_reo_query_quarantine(ar->ab);}
 if(delete_in_wmi){spin_lock_bh(&ar->ab->base_lock);struct ath11k_peer *p=ath11k_peer_find(ar,vdev,mac);assert(p);ath11k_peer_rx_tid_delete(ar,p,tid);spin_unlock_bh(&ar->ab->base_lock);assert(!list_empty(&ar->ab->dp.reo_cmd_update_rx_queue_list));}
 if(check_fragment_in_wmi){spin_lock_bh(&ar->ab->base_lock);struct ath11k_peer *p=ath11k_peer_find(ar,vdev,mac);struct hal_reo_dest_ring desc={.queue_addr_lo=lower_32_bits(addr),.info0=FIELD_PREP(HAL_REO_DEST_RING_INFO0_QUEUE_ADDR_HI,upper_32_bits(addr))};assert(ath11k_dp_reo_fragment_match(&p->rx_tid[tid],&desc));spin_unlock_bh(&ar->ab->base_lock);}
 if(replacement){spin_lock_bh(&ar->ab->base_lock);struct ath11k_peer *p=ath11k_peer_find(ar,vdev,mac);assert(p);list_del(&p->list);list_add_tail(&replacement->list,&ar->peers);replacement=NULL;spin_unlock_bh(&ar->ab->base_lock);}
 return wmi_result;
}
static unsigned ath11k_hal_reo_qdesc_size(unsigned window,unsigned tid){(void)window;(void)tid;return 192;}
static void ath11k_hal_reo_qdesc_setup(void *p,unsigned tid,unsigned window,unsigned ssn,enum hal_pn_type pn){(void)tid;(void)window;(void)ssn;(void)pn;memset(p,0,192);}
static unsigned long jiffies=10000;
#define time_after(a,b) ((a)>(b))
static void ath11k_dp_shadow_start_timer(struct ath11k_base *ab,struct hal_srng *s,struct ath11k_hp_update_timer *t){(void)ab;(void)s;(void)t;}
static void ath11k_hal_srng_access_begin(struct ath11k_base *ab,struct hal_srng *s){(void)ab;(void)s;}
static void ath11k_hal_srng_access_end(struct ath11k_base *ab,struct hal_srng *s){(void)ab;(void)s;}
static u32 *ath11k_hal_srng_src_peek(struct ath11k_base *ab,struct hal_srng *s){(void)ab;return s->slot[s->hp];}
static u32 *ath11k_hal_srng_src_get_next_entry(struct ath11k_base *ab,struct hal_srng *s){u32 *p=ath11k_hal_srng_src_peek(ab,s);s->hp=(s->hp+1)%s->num_entries;return p;}
static u32 *ath11k_hal_srng_dst_get_next_entry(struct ath11k_base *ab,struct hal_srng *s){(void)ab;return s->read<s->count?s->replies[s->read++]:NULL;}
static int ath11k_hal_srng_get_entrysize(struct ath11k_base *ab,int type){(void)ab;(void)type;return 64;}
static void ath11k_hal_srng_get_params(struct ath11k_base *ab,struct hal_srng *s,struct hal_srng_params *p){(void)ab;p->num_entries=s->num_entries;p->ring_base_vaddr=&s->slot[0][0];}
'''

CASES = r'''
static const u8 mac[6]={2,3,4,5,6,7};
static void init(struct ath11k_base *ab,struct ath11k *ar,struct device *dev){
 memset(ab,0,sizeof(*ab));memset(ar,0,sizeof(*ar));*dev=(struct device){1};ab->dev=dev;ar->ab=ab;ab->num_radios=1;ab->pdevs[0].ar=ar;ab->hw_params.regs=&regs;
 pthread_mutex_init(&ab->base_lock,NULL);pthread_mutex_init(&ab->dp.reo_cmd_lock,NULL);pthread_mutex_init(&ab->dp.reo_cmd_update_queue_lock,NULL);pthread_mutex_init(&ab->dp.reo_stats_lock,NULL);
 pthread_mutex_init(&ar->conf_mutex,NULL);pthread_mutex_init(&ar->tbl_mtx_lock,NULL);
 INIT_LIST_HEAD(&ar->peers);INIT_LIST_HEAD(&ab->nss.retained_host_peers);INIT_LIST_HEAD(&ab->dp.reo_cmd_list);INIT_LIST_HEAD(&ab->dp.reo_cmd_update_rx_queue_list);INIT_LIST_HEAD(&ab->dp.reo_cmd_cache_flush_list);INIT_LIST_HEAD(&ab->dp.reo_retained_queues);
 ab->dp.ab=ab;ab->dp.reo_cmd_accepting=true;ab->dp.reo_cmd_epoch=1;ab->dp.reo_status_ring.ring_id=1;
 for(unsigned i=0;i<2;i++){pthread_mutex_init(&ab->hal.srng_list[i].lock,NULL);ab->hal.srng_list[i].initialized=true;ab->hal.srng_list[i].num_entries=16;}
 ath11k_hal_reo_init_cmd_ring(ab,&ab->hal.srng_list[0]);
}
static struct ath11k_peer *peer_new(struct ath11k *ar){
 struct ath11k_peer *p=calloc(1,sizeof(*p));p->vdev_id=1;p->peer_id=42;p->dp_setup_done=true;ether_addr_copy(p->addr,mac);refcount_set(&p->refs,1);list_add_tail(&p->list,&ar->peers);return p;
}
static struct hal_reo_get_queue_stats_status *reply(struct ath11k_base *ab,unsigned id,unsigned tag,unsigned code,unsigned len){
 struct hal_srng *s=&ab->hal.srng_list[1];assert(s->count<64);u32 *raw=s->replies[s->count++];memset(raw,0,128);
 struct hal_tlv_hdr *tlv=(void *)raw;tlv->tl=FIELD_PREP(HAL_TLV_HDR_TAG,tag)|FIELD_PREP(HAL_TLV_HDR_LEN,len);
 struct hal_reo_get_queue_stats_status *r=(void *)tlv->value;
 r->hdr.info0=FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_STATUS_NUM,id)|FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_EXEC_STATUS,code)|FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_EXEC_TIME,1023);r->hdr.timestamp=0xfedcba98;return r;
}
static unsigned pending_id(struct ath11k_base *ab){
 unsigned id=0;spin_lock_bh(&ab->dp.reo_cmd_lock);struct dp_reo_cmd *entry;
 list_for_each_entry(entry,&ab->dp.reo_cmd_list,list)if(entry->kind==ATH11K_REO_CMD_QUERY)id=entry->cmd_num;
 spin_unlock_bh(&ab->dp.reo_cmd_lock);return id;
}
struct query_call {struct ath11k_base *ab;struct ath11k_reo_query_result result;int ret;};
static void *query_thread(void *arg){struct query_call *c=arg;c->ret=ath11k_dp_reo_queue_query(c->ab,1,mac,0,&c->result);return NULL;}
static unsigned wait_pending(struct ath11k_base *ab){for(unsigned i=0;i<1000;i++){unsigned id=pending_id(ab);if(id)return id;usleep(100);}assert(!"query not published");return 0;}
static void retire_peer_fixture(struct ath11k *ar,struct ath11k_peer *p){
 for(unsigned i=0;i<17;i++){ath11k_dp_reo_queue_retired(p->rx_tid[i].reo_queue);ath11k_dp_reo_tid_drop(&p->rx_tid[i]);}
 list_del(&p->list);ath11k_peer_put(ar,p);
}
static void wmi_lifetime_cases(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);struct ath11k_peer *p=peer_new(&ar);
 delete_in_wmi=true;wmi_result=-ENOMEM;unsigned freed=dma_frees;
 assert(ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,64,0,HAL_PN_TYPE_NONE)==-ENOMEM);
 assert(!p->rx_tid[0].reo_queue&&list_empty(&ab.dp.reo_cmd_update_rx_queue_list)&&dma_frees==freed+1&&!ab.dp.reo_wmi_inflight);
 delete_in_wmi=false;wmi_result=0;
 assert(!ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,64,0,HAL_PN_TYPE_NONE));
 struct ath11k_reo_queue *q=p->rx_tid[0].reo_queue;
 check_fragment_in_wmi=true;
 assert(!ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,32,8,HAL_PN_TYPE_NONE));
 check_fragment_in_wmi=false;
 reply(&ab,1,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS,0,8);ath11k_dp_process_reo_status(&ab);
 assert(!ab.dp.reo_cmd_stats.pending&&q->phase==ATH11K_REO_QUEUE_PUBLISHED&&atomic_load(&q->refs.value)==1);
 struct hal_reo_dest_ring desc={.queue_addr_lo=lower_32_bits(q->paddr),.info0=FIELD_PREP(HAL_REO_DEST_RING_INFO0_QUEUE_ADDR_HI,upper_32_bits(q->paddr))};
 assert(ath11k_dp_reo_fragment_match(&p->rx_tid[0],&desc));desc.queue_addr_lo+=128;assert(!ath11k_dp_reo_fragment_match(&p->rx_tid[0],&desc));
 close_in_wmi=true;freed=dma_frees;
 assert(ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,1,64,0,HAL_PN_TYPE_NONE)==-ESTALE);
 close_in_wmi=false;
 assert(ab.nss.ownership_uncertain&&!ab.dp.reo_wmi_inflight&&ab.dp.reo_retained_count==1&&dma_frees==freed);
 struct ath11k_reo_queue *held=container_of(ab.dp.reo_retained_queues.next,struct ath11k_reo_queue,retained_list);
 list_del(&held->retained_list);ath11k_dp_reo_queue_retired(held);ath11k_dp_reo_queue_put(held);ab.nss.ownership_uncertain=false;
 retire_peer_fixture(&ar,p);assert(dev.refs==1);
}
static void retirement_callback_cases(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);struct ath11k_peer *p=peer_new(&ar);
 assert(!ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,64,0,HAL_PN_TYPE_NONE));unsigned freed=dma_frees;
 spin_lock_bh(&ab.base_lock);ath11k_peer_rx_tid_delete(&ar,p,0);spin_unlock_bh(&ab.base_lock);
 reply(&ab,1,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS,0,8);ath11k_dp_process_reo_status(&ab);
 assert(!p->rx_tid[0].reo_queue&&ab.dp.reo_cmd_cache_flush_count==1&&dma_frees==freed);
 jiffies+=100;
 struct ath11k_peer *second=peer_new(&ar);second->addr[5]=8;second->peer_id=43;
 assert(!ath11k_peer_rx_tid_setup_instance(&ar,second,second->addr,1,0,64,0,HAL_PN_TYPE_NONE));
 spin_lock_bh(&ab.base_lock);ath11k_peer_rx_tid_delete(&ar,second,0);spin_unlock_bh(&ab.base_lock);
 reply(&ab,2,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS,0,8);ath11k_dp_process_reo_status(&ab);
 assert(ab.dp.reo_cmd_stats.pending==1&&dma_frees==freed);
 reply(&ab,3,HAL_REO_FLUSH_CACHE_STATUS,0,8);ath11k_dp_process_reo_status(&ab);
 assert(!ab.dp.reo_cmd_stats.pending&&dma_frees==freed+1);
 ath11k_dp_reo_cmd_list_cleanup(&ab);assert(dma_frees==freed+2);
 retire_peer_fixture(&ar,p);retire_peer_fixture(&ar,second);assert(dev.refs==1);

 init(&ab,&ar,&dev);p=peer_new(&ar);
 assert(!ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,64,0,HAL_PN_TYPE_NONE));freed=dma_frees;
 spin_lock_bh(&ab.base_lock);ath11k_peer_rx_tid_delete(&ar,p,0);spin_unlock_bh(&ab.base_lock);
 reply(&ab,1,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS,HAL_REO_CMD_FAILED,8);ath11k_dp_process_reo_status(&ab);
 assert(ab.nss.ownership_uncertain&&ab.dp.reo_ownership_uncertain&&ab.dp.reo_retained_count==1&&dma_frees==freed);
 struct ath11k_reo_queue *held=container_of(ab.dp.reo_retained_queues.next,struct ath11k_reo_queue,retained_list);
 assert(held->dma_live);list_del(&held->retained_list);ath11k_dp_reo_queue_retired(held);ath11k_dp_reo_queue_put(held);
 ab.nss.ownership_uncertain=false;retire_peer_fixture(&ar,p);assert(dev.refs==1);
}
static void cleanup_iteration_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);
 peer_new(&ar);struct ath11k_peer *next=peer_new(&ar);next->addr[5]=8;
 unmap_during_cleanup=true;cleanup_rhash_deletes=0;
 spin_lock_bh(&ar.conf_mutex);ath11k_mac_peer_cleanup_all(&ar);spin_unlock_bh(&ar.conf_mutex);
 assert(list_empty(&ar.peers)&&cleanup_rhash_deletes==0);
}
int main(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;init(&ab,&ar,&dev);struct ath11k_peer *p=peer_new(&ar);
 fail_allocation=true;unsigned calls=wmi_calls,allocated=dma_allocations;
 assert(ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,64,5,HAL_PN_TYPE_NONE)==-ENOMEM);
 assert(!p->rx_tid[0].reo_queue&&wmi_calls==calls&&dma_allocations==allocated&&dev.refs==1);
 fail_allocation=false;fail_dma=true;
 assert(ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,64,5,HAL_PN_TYPE_NONE)==-ENOMEM);
 assert(!p->rx_tid[0].reo_queue&&wmi_calls==calls&&dev.refs==1);fail_dma=false;
 assert(!ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,0,64,5,HAL_PN_TYPE_NONE));
 struct ath11k_reo_queue *q=p->rx_tid[0].reo_queue;assert(q&&q->phase==ATH11K_REO_QUEUE_PUBLISHED&&q->dma_live&&p->rx_tid[0].active);
 assert(atomic_load(&q->refs.value)==1&&dev.refs==2&&!ab.dp.reo_wmi_inflight);
 /* clone/drop never aliases timer/fragment queues, and cannot retire a HW owner. */
 struct dp_rx_tid copy={0};p->rx_tid[0].frag_timer.marker=123;p->rx_tid[0].rx_frags.marker=456;
 ath11k_dp_reo_tid_clone(&copy,&p->rx_tid[0]);assert(copy.reo_queue==q&&!copy.frag_timer.marker&&!copy.rx_frags.marker&&atomic_load(&q->refs.value)==2);
 ath11k_dp_reo_tid_drop(&copy);assert(atomic_load(&q->refs.value)==1&&!dma_frees);
 /* Every GET field is copied, with its native width and unsigned representation. */
 struct hal_reo_get_queue_stats_status *raw=reply(&ab,1,HAL_REO_GET_QUEUE_STATS_STATUS,0,100);
 raw->info0=raw->info1=raw->info2=raw->info3=raw->info4=raw->info5=UINT32_MAX;
 for(unsigned i=0;i<4;i++)raw->pn[i]=0x80000000+i;
 for(unsigned i=0;i<8;i++)raw->rx_bitmap[i]=0xa0000000+i;
 raw->last_rx_enqueue_timestamp=11;raw->last_rx_dequeue_timestamp=22;raw->num_mpdu_frames=raw->num_msdu_frames=raw->total_bytes=UINT32_MAX;
 struct hal_reo_status out;memset(&out,0xcc,sizeof(out));ath11k_hal_reo_status_queue_stats(&ab,ab.hal.srng_list[1].replies[0],&out);
 assert(out.payload_valid&&out.tlv_payload_len==100&&out.uniform_hdr.cmd_exe_time==1023&&out.uniform_hdr.timestamp==0xfedcba98);
 assert(out.u.queue_stats.ssn==4095&&out.u.queue_stats.curr_idx==255&&out.u.queue_stats.curr_mpdu_cnt==127&&out.u.queue_stats.curr_msdu_cnt==0x1ffffff);
 assert(out.u.queue_stats.timeout_cnt==63&&out.u.queue_stats.fwd_due_to_bar_cnt==63&&out.u.queue_stats.dup_cnt==65535);
 assert(out.u.queue_stats.frames_in_order_cnt==0xffffff&&out.u.queue_stats.bar_rx_cnt==255&&out.u.queue_stats.late_rx_mpdu_cnt==4095&&out.u.queue_stats.num_window_2k_jump_cnt==15&&out.u.queue_stats.reorder_hole_cnt==65535);
 assert(out.u.queue_stats.num_mpdu_processed_cnt==UINT32_MAX&&out.u.queue_stats.pn[3]==0x80000003&&out.u.queue_stats.rx_bitmap[7]==0xa0000007&&out.loop_cnt==15);
 for(unsigned code=1;code<=3;code++){raw->hdr.info0=FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_EXEC_STATUS,code);memset(&out,0xcc,sizeof(out));ath11k_hal_reo_status_queue_stats(&ab,ab.hal.srng_list[1].replies[0],&out);assert(!out.payload_valid&&!out.u.queue_stats.ssn&&!out.u.queue_stats.pn[0]);}
 ab.hal.srng_list[1].count=ab.hal.srng_list[1].read=0;
 /* A real waiter and status thread share private request lifetime. */
 struct query_call call={.ab=&ab};pthread_t worker;assert(!pthread_create(&worker,NULL,query_thread,&call));unsigned id=wait_pending(&ab);
 struct hal_reo_get_queue_stats_status *r=reply(&ab,id,HAL_REO_GET_QUEUE_STATS_STATUS,0,100);r->info0=FIELD_PREP(HAL_REO_GET_QUEUE_STATS_STATUS_INFO0_SSN,777);r->num_mpdu_frames=123;
 ath11k_dp_process_reo_status(&ab);pthread_join(worker,NULL);
 assert(!call.ret&&call.result.payload_valid&&call.result.current_instance&&call.result.queue_generation==q->generation&&call.result.status.u.queue_stats.ssn==777);
#ifdef HAVE_REO_AGING_CAPTURE
 assert(call.result.aging_valid_at_submit);
 for(unsigned i=0;i<4;i++)assert(call.result.aging_threshold_raw_at_submit[i]==40000+i);
#endif
 assert(!ab.dp.reo_query_outstanding&&!ab.dp.reo_cmd_stats.pending&&atomic_load(&q->refs.value)==1);
 /* A timeout retains command/ID/DMA ownership; another query cannot hide it. */
 struct ath11k_reo_query_result timed;assert(ath11k_dp_reo_queue_query(&ab,1,mac,0,&timed)==-ETIMEDOUT);id=pending_id(&ab);
 assert(id&&ab.dp.reo_query_outstanding&&ab.dp.reo_cmd_stats.pending==1&&atomic_load(&q->refs.value)==2&&!timed.payload_valid&&!timed.header_valid);
 struct ath11k_reo_query_result blocked;assert(ath11k_dp_reo_queue_query(&ab,1,mac,0,&blocked)==-EBUSY);
 assert(atomic_load(&q->refs.value)==2&&ab.dp.reo_cmd_stats.pending==1);
 reply(&ab,id,HAL_REO_FLUSH_CACHE_STATUS,0,100);ath11k_dp_process_reo_status(&ab);assert(ab.dp.reo_query_outstanding&&ab.dp.reo_cmd_stats.tag_mismatch==1);
 reply(&ab,id,HAL_REO_GET_QUEUE_STATS_STATUS,0,4);ath11k_dp_process_reo_status(&ab);assert(ab.dp.reo_query_outstanding);
 reply(&ab,id,HAL_REO_GET_QUEUE_STATS_STATUS,0,100);ath11k_dp_process_reo_status(&ab);assert(!ab.dp.reo_query_outstanding&&atomic_load(&q->refs.value)==1);
 /* Header-valid, short queue payload is not published as hardware SSN. */
 call=(struct query_call){.ab=&ab};assert(!pthread_create(&worker,NULL,query_thread,&call));id=wait_pending(&ab);reply(&ab,id,HAL_REO_GET_QUEUE_STATS_STATUS,0,8);ath11k_dp_process_reo_status(&ab);pthread_join(worker,NULL);
 assert(call.ret==-EMSGSIZE&&call.result.header_valid&&!call.result.payload_valid);
 /* WMI failure does not free a replacement peer's queue. */
 struct ath11k_peer *new_peer=calloc(1,sizeof(*new_peer));new_peer->vdev_id=1;new_peer->peer_id=99;new_peer->dp_setup_done=true;ether_addr_copy(new_peer->addr,mac);refcount_set(&new_peer->refs,1);
 replacement=new_peer;wmi_result=-ENOMEM;
 assert(ath11k_peer_rx_tid_setup_instance(&ar,p,mac,1,1,64,0,HAL_PN_TYPE_NONE)==-ENOMEM);
 assert(!p->rx_tid[1].reo_queue&&new_peer->peer_id==99&&!new_peer->rx_tid[1].reo_queue);
 list_del(&new_peer->list);free(new_peer);list_add_tail(&p->list,&ar.peers);wmi_result=0;
 /* Closing with an unanswered query retains every command and allocation. */
 assert(ath11k_dp_reo_queue_query(&ab,1,mac,0,&timed)==-ETIMEDOUT);unsigned before_free=dma_frees;
#ifdef HAVE_REO_AGING_CAPTURE
 assert(!timed.aging_valid_at_submit);
#endif
 ath11k_dp_reo_cmd_close(&ab.dp);ath11k_dp_reo_query_quarantine(&ab);ath11k_dp_reo_cmd_list_cleanup(&ab);
 assert(ab.nss.ownership_uncertain&&pending_id(&ab)&&dma_frees==before_free&&atomic_load(&q->refs.value)==2);
 /* Test teardown represents a confirmed hardware halt, not driver timeout cleanup. */
 struct dp_reo_cmd *entry=container_of(ab.dp.reo_cmd_list.next,struct dp_reo_cmd,list);list_del(&entry->list);ath11k_dp_reo_query_put(entry->query);kfree(entry);
 ab.nss.ownership_uncertain=false;retire_peer_fixture(&ar,p);
 assert(dev.refs==1&&dma_allocations==dma_frees&&!warnings);
 wmi_lifetime_cases();assert(dma_allocations==dma_frees&&!warnings);
 retirement_callback_cases();assert(dma_allocations==dma_frees&&!warnings);
 cleanup_iteration_case();
 puts("REO queue/query: allocation failures, DMA retirement, WMI close/update/delete, cleanup/unmap iteration, field widths, private completion, timeout/late reply, malformed TLV and quarantine passed");return 0;
}
'''

def build_fixture(source, draft):
    def read(name):
        candidate = draft / name
        return (candidate if candidate.exists() else source / name).read_text()
    header = read("dp.h")
    hal = read("hal.h")
    desc = (source / "hal_desc.h").read_text()
    rx = read("dp_rx.c").replace("*\nath11k_dp_reo_cmd_take", "*ath11k_dp_reo_cmd_take")
    tx = read("dp_tx.c")
    macros = re.findall(r"(?m)^#define[ \t]+(?:HAL_(?:REO|SEQ_WCSS_UMAC_REO_REG|TLV_HDR|SRNG_TLV_HDR_TAG|RX_REO_QUEUE|MAX_AVAIL_BLK_RES|DESC_REO_NON_QOS_TID|LINK_DESC_ALIGN)\w*|DP_(?:REO_CMD_RING_SIZE|BA_WIN_SZ_MAX|REO_DESC_FREE_THRESHOLD|REO_DESC_FREE_TIMEOUT_MS))[ \t]+[^\n]*(?:\\\n[^\n]*)*", hal + "\n" + desc + "\n" + header)
    declarations = "\n".join(types.declaration(text, "enum", name) for text, name in (
        (hal, "hal_reo_cmd_type"), (hal, "hal_reo_cmd_status"), (hal, "hal_pn_type"),
        (desc, "hal_tlv_tag"), (desc, "hal_rx_reo_queue_pn_size"),
        (header, "ath11k_reo_queue_phase"), (header, "ath11k_reo_cmd_kind")))
    for name in ("hal_reo_cmd_hdr", "hal_reo_get_queue_stats", "hal_reo_flush_cache", "hal_reo_update_rx_queue",
                 "hal_reo_status_hdr", "hal_reo_get_queue_stats_status", "hal_reo_flush_queue_status",
                 "hal_reo_flush_cache_status", "hal_reo_unblock_cache_status", "hal_reo_flush_timeout_list_status",
                 "hal_reo_desc_thresh_reached_status"):
        declarations += types.declaration(desc, "struct", name)
    declarations += types.declaration(hal, "struct", "ath11k_hal_reo_cmd")
    if "aging_valid_at_submit" in header:
        declarations += "\n#define HAVE_REO_AGING_CAPTURE 1\n"
    declarations += hal[hal.index("struct hal_reo_status_header {"):hal.index("/* HAL context to be used")]
    for name in ("ath11k_reo_queue", "dp_rx_tid", "dp_reo_cmd", "dp_reo_update_rx_queue_elem", "dp_reo_cache_flush_elem",
                 "ath11k_reo_query_result", "ath11k_reo_query", "ath11k_reo_pn_update", "ath11k_reo_pn_stats",
                 "ath11k_reo_update_stats", "ath11k_reo_update_input", "ath11k_reo_cmd_stats"):
        declarations += types.declaration(header, "struct", name)
    helpers = header[header.index("static inline void ath11k_dp_reo_cmd_close"):header.index("/* HTT definitions */")]
    hal_source = read("hal_rx.c")
    hal_functions = ("ath11k_hal_reo_cmd_queue_stats", "ath11k_hal_reo_cmd_flush_cache", "ath11k_hal_reo_cmd_update_rx_queue",
                     "ath11k_hal_reo_cmd_send", "ath11k_hal_reo_init_cmd_ring", "ath11k_hal_reo_process_status",
                     "ath11k_hal_reo_status_queue_stats", "ath11k_hal_reo_flush_queue_status", "ath11k_hal_reo_flush_cache_status",
                     "ath11k_hal_reo_unblk_cache_status", "ath11k_hal_reo_flush_timeout_list_status",
                     "ath11k_hal_reo_desc_thresh_reached_status", "ath11k_hal_reo_update_rx_reo_queue_status")
    rx_functions = ("ath11k_dp_reo_queue_get", "ath11k_dp_reo_queue_put", "ath11k_dp_reo_tid_clone", "ath11k_dp_reo_tid_drop",
                    "ath11k_dp_reo_queue_retired", "ath11k_dp_reo_queue_retain", "ath11k_dp_reo_query_put",
                    "ath11k_dp_reo_pn_update_put", "ath11k_dp_reo_pn_update_complete",
                    "ath11k_dp_reo_query_quarantine", "ath11k_peer_rx_tid_delete_handler", "ath11k_dp_dma_quarantine",
                    "ath11k_dp_reo_cmd_list_cleanup", "ath11k_dp_reo_cmd_free", "ath11k_dp_reo_cache_flush",
                    "ath11k_dp_reo_retry_queues", "ath11k_dp_rx_tid_del_func", "ath11k_peer_rx_tid_delete",
                    "ath11k_peer_rx_tid_reo_update", "ath11k_dp_reo_wmi_finish", "ath11k_dp_reo_wmi_begin",
                    "ath11k_peer_rx_tid_setup_instance", "ath11k_dp_reo_fragment_match", "ath11k_dp_reo_query_peer", "ath11k_dp_reo_queue_query",
                    "ath11k_dp_reo_query_complete", "ath11k_dp_reo_cmd_take", "ath11k_dp_process_reo_status")
    peer = read("peer.c")
    hardware = types.declaration((source / "hw.h").read_text(), "struct", "ath11k_hw_regs")
    structures = re.sub(r"struct hw_regs \{[^}]+\};", lambda _: hardware + "\n#define hw_regs ath11k_hw_regs\n", STRUCTURES, count=1)
    code = (SHIM + declarations + "\n" + "\n".join(macros) + "\n#define HAL_REO_CMD 1\n" + structures + helpers +
            "\n".join(extract.function(peer, name) for name in ("ath11k_peer_get", "ath11k_peer_put_locked", "ath11k_peer_put", "ath11k_peer_release")) +
            extract.function(read("mac.c"), "ath11k_mac_peer_cleanup_all") +
            "\n".join(extract.function(hal_source, name) for name in hal_functions) +
            "\n".join(extract.function(rx, name) for name in rx_functions) +
            "\n".join(extract.function(tx, name) for name in ("ath11k_dp_tx_reo_submit_locked", "ath11k_dp_tx_send_reo_cmd", "ath11k_dp_tx_reo_query")) + CASES)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backports", type=Path, required=True)
    parser.add_argument("--draft", type=Path)
    args = parser.parse_args()
    source = args.backports / "drivers/net/wireless/ath/ath11k"
    code = build_fixture(source, args.draft or source)
    with tempfile.TemporaryDirectory(prefix="reo-queue-query-") as directory:
        root = Path(directory)
        c, binary = root / "test.c", root / "test"
        c.write_text(code)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-pthread", "-Wall", "-Werror",
                        "-Wno-unused-function", "-Wno-misleading-indentation", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", str(c), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=20, env=dict(os.environ,
                       ASAN_OPTIONS="detect_leaks=1", UBSAN_OPTIONS="halt_on_error=1"))

if __name__ == "__main__":
    main()
