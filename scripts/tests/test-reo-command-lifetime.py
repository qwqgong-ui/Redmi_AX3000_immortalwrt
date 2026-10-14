#!/usr/bin/env python3
"""Execute REO publication, callback matching and cache-flush retry code."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "reo_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def declaration(source, kind, name):
    start = source.index(kind + " " + name + " {")
    end = re.search(r"(?m)^}[ \t]*(?:__packed)?;", source[start:])
    if not end:
        raise ValueError("Missing declaration end: " + name)
    return source[start:start + end.end()]


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
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef pthread_mutex_t spinlock_t;
#define __packed __attribute__((packed))
#define BIT(n) (UINT32_C(1) << (n))
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & ~((UINT32_C(1)<<(l))-1))
#define FIELD_GET(mask,value) (((value)&(mask)) >> __builtin_ctz(mask))
#define FIELD_PREP(mask,value) (((value)<<__builtin_ctz(mask)) & (mask))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define ath11k_dbg(...) ((void)0)
#define GFP_ATOMIC 0
#define GFP_KERNEL 1
#define DP_TCL_NUM_RING_MAX 3
#define DP_TX_COMP_RING_SIZE 64
#define HAL_WBM_IDLE_LINK 1
#define HAL_DSCP_TID_MAP_TBL_NUM_ENTRIES_MAX 1
#define spin_lock_init(p) assert(!pthread_mutex_init(p,NULL))
#define idr_init(p) ((void)(p))
#define ATH11K_FLAG_CRASH_FLUSH 0
#define test_bit(bit,p) (!!(*(p)&(1ul<<(bit))))
#define spin_lock_bh(p) assert(!pthread_mutex_lock(p))
#define spin_unlock_bh(p) assert(!pthread_mutex_unlock(p))
#define lockdep_assert_held(p) do {(void)(p);} while (0)
#define memset_startat(p,value,member) memset(&(p)->member,value,sizeof(*(p))-offsetof(__typeof__(*(p)),member))
#define lower_32_bits(x) ((u32)(x))
#define upper_32_bits(x) ((u32)((u64)(x)>>32))
#define ffz(x) __builtin_ctz(~(unsigned)(x))
struct list_head {struct list_head *next,*prev;};
#define INIT_LIST_HEAD(h) (*(h)=(struct list_head){(h),(h)})
static bool list_empty(const struct list_head *h){return h->next==h;}
static void list_add_tail(struct list_head *n,struct list_head *h){n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n;}
static void list_del(struct list_head *n){n->prev->next=n->next;n->next->prev=n->prev;}
#define list_for_each_entry(pos,h,member) for(struct list_head *it=(h)->next;it!=(h)&&((pos)=(void *)((char *)it - offsetof(__typeof__(*(pos)),member)),true);it=it->next)
struct ath11k_base; struct ath11k_dp;
struct ath11k_reo_queue;
struct dp_rx_tid {u64 paddr,paddr_unaligned;u32 size,pending_desc_size,ba_win_sz,unaligned_size;void *vaddr_unaligned;u8 tid;bool active;struct ath11k_reo_queue *reo_queue;};
static void ath11k_dp_reo_queue_get(struct ath11k_reo_queue *q){assert(!q);}
static void ath11k_dp_reo_queue_put(struct ath11k_reo_queue *q){assert(!q);}
struct hal_tlv_hdr {u32 tl;u8 value[];};
struct hal_reo_status_header {u16 cmd_num;enum hal_reo_cmd_status cmd_status;u16 cmd_exe_time;u32 timestamp;};
'''

STRUCTURES = r'''
struct ath11k_hp_update_timer {int unused;};
struct dp_srng {unsigned ring_id;};
struct dp_link_desc_bank {unsigned unused;};
struct hal_wbm_release_ring {u32 raw[8];};
struct hal_srng {
 spinlock_t lock;unsigned num_entries,hp,advances,published;bool full;
 unsigned status_count,status_read;u32 status_slot[16][32];
 u32 slot[DP_REO_CMD_RING_SIZE][16];
};
struct hal_srng_params {unsigned num_entries;u32 *ring_base_vaddr;};
struct ath11k_dp {
 struct ath11k_base *ab;
 spinlock_t reo_stats_lock,reo_cmd_lock,reo_cmd_update_queue_lock;
 struct ath11k_reo_update_stats reo_update_stats;
 bool reo_cmd_accepting;
 u64 reo_cmd_epoch;
 u16 reo_cmd_status_tag[DP_REO_CMD_RING_SIZE+1];
	 struct ath11k_reo_cmd_stats reo_cmd_stats;
	 struct ath11k_reo_pn_stats {unsigned submitted,completed,status[4],drained,status_unknown;} reo_pn_stats;
	 bool reo_query_outstanding,reo_ownership_uncertain;unsigned reo_retained_count,reo_wmi_inflight;
	 unsigned reo_pn_outstanding;
 struct {unsigned ring_id;} reo_cmd_ring,reo_status_ring;
 struct list_head reo_cmd_list;
 struct list_head reo_cmd_cache_flush_list,reo_cmd_update_rx_queue_list,dp_full_mon_mpdu_list;
 unsigned reo_cmd_cache_flush_count;
 struct dp_srng wbm_idle_ring;struct dp_link_desc_bank link_desc_banks[1];
 struct {int txbuf_idr;spinlock_t tx_idr_lock;unsigned tcl_data_ring_id,tx_status_head,tx_status_tail;void *tx_status;} tx_ring[3];
 struct ath11k_hp_update_timer reo_cmd_timer;
};
struct ath11k_hal {struct hal_srng srng_list[2];unsigned avail_blk_resource,current_blk_index;};
struct ath11k_base {unsigned long dev_flags;spinlock_t base_lock;struct ath11k_dp dp;struct ath11k_hal hal;struct {bool ownership_uncertain;} nss;};
struct ath11k_reo_query {unsigned refs;u16 cmd_num;};
struct ath11k_reo_pn_update {unsigned refs;u16 cmd_num;};
static void refcount_inc(unsigned *refs){(void)refs;assert(!"QUERY is covered by the queue/query fixture");}
static void ath11k_dp_reo_query_complete(struct ath11k_reo_query *q,const struct hal_reo_status *s){(void)q;(void)s;assert(!"Unexpected query fixture");}
static void ath11k_dp_reo_query_put(struct ath11k_reo_query *q){(void)q;assert(!"Unexpected query fixture");}
static void ath11k_dp_reo_pn_update_complete(struct ath11k_reo_pn_update *u,enum hal_reo_cmd_status s){(void)u;(void)s;assert(!"PN is covered by the PN execution fixture");}
static void ath11k_dp_reo_pn_update_put(struct ath11k_reo_pn_update *u){(void)u;assert(!"Unexpected PN fixture");}
static unsigned allocations,deallocations,callback_count;
static bool allocation_fail,replace_epoch_on_allocation,early_reply,reply_started,reply_lock_held;
static struct ath11k_dp *allocation_dp;
static pthread_t reply_thread;
static pthread_mutex_t reply_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t reply_condition=PTHREAD_COND_INITIALIZER;
static void *kzalloc(size_t size,int flags){
 (void)flags;allocations++;
 if(replace_epoch_on_allocation){
  spin_lock_bh(&allocation_dp->reo_cmd_lock);
  allocation_dp->reo_cmd_accepting=false;allocation_dp->reo_cmd_epoch++;
  allocation_dp->reo_cmd_accepting=true;allocation_dp->reo_cmd_epoch++;
  spin_unlock_bh(&allocation_dp->reo_cmd_lock);
 }
 return allocation_fail?NULL:calloc(1,size);
}
static void kfree(void *p){if(p){deallocations++;free(p);}}
static void *kmalloc(size_t size,int flags){return kzalloc(size,flags);}
static int ath11k_wbm_idle_ring_setup(struct ath11k_base *ab,u32 *count){(void)ab;(void)count;return -ENOMEM;}
static int ath11k_dp_link_desc_setup(struct ath11k_base *ab,struct dp_link_desc_bank *bank,int type,struct hal_srng *s,u32 count){(void)ab;(void)bank;(void)type;(void)s;(void)count;return 0;}
static int ath11k_dp_srng_common_setup(struct ath11k_base *ab){(void)ab;return 0;}
static void ath11k_dp_srng_common_cleanup(struct ath11k_base *ab){(void)ab;}
static void ath11k_dp_link_desc_cleanup(struct ath11k_base *ab,struct dp_link_desc_bank *bank,int type,struct dp_srng *s){(void)ab;(void)bank;(void)type;(void)s;}
static void ath11k_hal_tx_set_dscp_tid_map(struct ath11k_base *ab,unsigned id){(void)ab;(void)id;}
static void ath11k_warn(struct ath11k_base *ab,const char *format,...){(void)ab;(void)format;}
static void ath11k_dp_shadow_start_timer(struct ath11k_base *ab,struct hal_srng *s,struct ath11k_hp_update_timer *t){(void)ab;(void)s;(void)t;}
static void ath11k_hal_srng_access_begin(struct ath11k_base *ab,struct hal_srng *s){(void)ab;(void)s;}
static u32 *ath11k_hal_srng_src_peek(struct ath11k_base *ab,struct hal_srng *s){(void)ab;return s->full?NULL:s->slot[s->hp];}
static u32 *ath11k_hal_srng_src_get_next_entry(struct ath11k_base *ab,struct hal_srng *s){u32 *p=ath11k_hal_srng_src_peek(ab,s);if(p){s->hp=(s->hp+1)%s->num_entries;s->advances++;}return p;}
static int ath11k_hal_srng_get_entrysize(struct ath11k_base *ab,int type){(void)ab;(void)type;return 64;}
static void ath11k_hal_srng_get_params(struct ath11k_base *ab,struct hal_srng *s,struct hal_srng_params *p){(void)ab;p->num_entries=s->num_entries;p->ring_base_vaddr=&s->slot[0][0];}
static struct dp_reo_cmd *ath11k_dp_reo_cmd_take(struct ath11k_dp *,u16,u16,bool *);
static struct dp_reo_cmd *take(struct ath11k_dp *,u16,u16);
static int ath11k_dp_tx_send_reo_cmd(struct ath11k_base *,struct dp_rx_tid *,enum hal_reo_cmd_type,struct ath11k_hal_reo_cmd *,void (*)(struct ath11k_dp *,void *,enum hal_reo_cmd_status));
static void client_callback(struct ath11k_dp *dp,void *ctx,enum hal_reo_cmd_status status){
 struct dp_rx_tid *tid=ctx;assert(status==HAL_REO_CMD_SUCCESS&&tid->tid==42);
 /* A callback must execute without holding the publication lock. */
 assert(!pthread_mutex_trylock(&dp->reo_cmd_lock));pthread_mutex_unlock(&dp->reo_cmd_lock);
 callback_count++;
}
struct early_context {struct ath11k_dp *dp;u16 id,tag;};
static struct early_context early;
static void *early_status(void *unused){
 (void)unused;int rc=pthread_mutex_trylock(&early.dp->reo_cmd_lock);
 reply_lock_held=rc==EBUSY;assert(rc==0||rc==EBUSY);
 if(!rc)pthread_mutex_unlock(&early.dp->reo_cmd_lock);
 pthread_mutex_lock(&reply_lock);reply_started=true;pthread_cond_signal(&reply_condition);pthread_mutex_unlock(&reply_lock);
 struct dp_reo_cmd *entry=take(early.dp,early.id,early.tag);
 if(entry){entry->handler(early.dp,&entry->data,HAL_REO_CMD_SUCCESS);kfree(entry);}return NULL;
}
static void ath11k_hal_srng_access_end(struct ath11k_base *ab,struct hal_srng *s){
 if(s->published==s->advances)return;s->published=s->advances;
 if(!early_reply)return;
 struct hal_tlv_hdr *tlv=(void *)s->slot[(s->hp+s->num_entries-1)%s->num_entries];
 struct hal_reo_cmd_hdr *hdr=(void *)tlv->value;
 early=(struct early_context){&ab->dp,FIELD_GET(HAL_REO_CMD_HDR_INFO0_CMD_NUMBER,hdr->info0),HAL_REO_UPDATE_RX_REO_QUEUE_STATUS};
 pthread_mutex_lock(&reply_lock);reply_started=false;assert(!pthread_create(&reply_thread,NULL,early_status,NULL));
 while(!reply_started)pthread_cond_wait(&reply_condition,&reply_lock);pthread_mutex_unlock(&reply_lock);
}
static unsigned ath11k_hal_reo_qdesc_size(unsigned window,unsigned tid){(void)window;(void)tid;return 64;}
static void ath11k_dp_reo_cmd_free(struct ath11k_dp *dp,void *ctx,enum hal_reo_cmd_status status){(void)dp;(void)ctx;(void)status;}
static void initialize(struct ath11k_base *ab,unsigned entries){
 memset(ab,0,sizeof(*ab));ab->dp.ab=ab;ab->dp.reo_cmd_accepting=true;
 pthread_mutex_init(&ab->base_lock,NULL);
 pthread_mutex_init(&ab->dp.reo_cmd_lock,NULL);pthread_mutex_init(&ab->dp.reo_stats_lock,NULL);
 pthread_mutex_init(&ab->dp.reo_cmd_update_queue_lock,NULL);
 pthread_mutex_init(&ab->hal.srng_list[0].lock,NULL);ab->hal.srng_list[0].num_entries=entries;
 pthread_mutex_init(&ab->hal.srng_list[1].lock,NULL);ab->dp.reo_status_ring.ring_id=1;
 INIT_LIST_HEAD(&ab->dp.reo_cmd_list);
 INIT_LIST_HEAD(&ab->dp.reo_cmd_cache_flush_list);INIT_LIST_HEAD(&ab->dp.reo_cmd_update_rx_queue_list);INIT_LIST_HEAD(&ab->dp.dp_full_mon_mpdu_list);
}
static u32 *ath11k_hal_srng_dst_get_next_entry(struct ath11k_base *ab,struct hal_srng *s){
 (void)ab;return s->status_read<s->status_count?s->status_slot[s->status_read++]:NULL;
}
static void inject_status(struct ath11k_base *ab,u16 id,u16 tag){
 struct hal_srng *s=&ab->hal.srng_list[1];assert(s->status_count<16);
 struct hal_tlv_hdr *tlv=(void *)s->status_slot[s->status_count++];
 tlv->tl=FIELD_PREP(HAL_SRNG_TLV_HDR_TAG,tag)|FIELD_PREP(HAL_TLV_HDR_LEN,sizeof(struct hal_reo_status_hdr));
 struct hal_reo_status_hdr *hdr=(void *)tlv->value;
 hdr->info0=FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_STATUS_NUM,id);
}
'''

TAKE_WRAPPER = r'''
static struct dp_reo_cmd *take(struct ath11k_dp *dp,u16 id,u16 tag){
 bool accepted;spin_lock_bh(&dp->reo_cmd_lock);
 struct dp_reo_cmd *entry=ath11k_dp_reo_cmd_take(dp,id,tag,&accepted);
 spin_unlock_bh(&dp->reo_cmd_lock);return entry;
}
'''

CASES = r'''
static void take_callback(struct ath11k_dp *dp,u16 id,u16 tag){
 struct dp_reo_cmd *entry=take(dp,id,tag);assert(entry);
 entry->handler(dp,&entry->data,HAL_REO_CMD_SUCCESS);kfree(entry);
}
static void check_reopen_rejection(struct ath11k_base *ab){
 struct ath11k_dp *dp=&ab->dp;struct list_head monitor,owner;
 list_add_tail(&monitor,&dp->dp_full_mon_mpdu_list);dp->reo_update_stats.epoch=77;
 assert(ath11k_dp_alloc(ab)==-EBUSY);
 dp->reo_cmd_accepting=false;dp->reo_cmd_stats.pending=1;
 assert(ath11k_dp_alloc(ab)==-EBUSY);dp->reo_cmd_stats.pending=0;
 struct list_head *heads[]={&dp->reo_cmd_list,&dp->reo_cmd_cache_flush_list,&dp->reo_cmd_update_rx_queue_list};
 for(unsigned i=0;i<ARRAY_SIZE(heads);i++){
  list_add_tail(&owner,heads[i]);assert(ath11k_dp_alloc(ab)==-EBUSY);
  assert(heads[i]->next==&owner);list_del(&owner);
 }
 assert(dp->reo_update_stats.epoch==77&&dp->dp_full_mon_mpdu_list.next==&monitor);
 assert(!pthread_mutex_trylock(&dp->reo_cmd_lock));pthread_mutex_unlock(&dp->reo_cmd_lock);
 assert(!pthread_mutex_trylock(&dp->reo_cmd_update_queue_lock));pthread_mutex_unlock(&dp->reo_cmd_update_queue_lock);
 list_del(&monitor);dp->reo_cmd_accepting=true;
}
int main(void){
 struct ath11k_base ab;initialize(&ab,4);struct ath11k_dp *dp=&ab.dp;
 check_reopen_rejection(&ab);
 struct hal_srng *ring=&ab.hal.srng_list[0];ath11k_hal_reo_init_cmd_ring(&ab,ring);
 struct dp_rx_tid tid={.tid=42,.paddr=0x123000,.size=192};
 struct ath11k_hal_reo_cmd cmd={.flag=HAL_REO_CMD_FLG_NEED_STATUS,.ba_window_size=64};
 allocation_fail=true;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ENOMEM);
 assert(!ring->advances&&list_empty(&dp->reo_cmd_list)&&!dp->reo_cmd_stats.pending);
 assert(dp->reo_cmd_stats.allocation_failed==1&&dp->reo_update_stats.rejected==1);
 allocation_fail=false;
 replace_epoch_on_allocation=true;allocation_dp=dp;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ESHUTDOWN);
 replace_epoch_on_allocation=false;
 assert(dp->reo_cmd_accepting&&!ring->advances&&list_empty(&dp->reo_cmd_list));
 cmd.flag=0;unsigned attempts=allocations;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-EINVAL);
 assert(allocations==attempts&&!ring->advances);
 cmd.flag=HAL_REO_CMD_FLG_NEED_STATUS;
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,(void *)16,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL));
 assert(dp->reo_cmd_stats.pending==1&&allocations==attempts&&ring->advances==1);
 /* Model HW consumption and ring wrap while the original reply is not consumed. */
 ring->hp=0;cmd.flag=0;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,(void *)16,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL)==-EBUSY);
 assert(ring->hp==0&&ring->advances==1&&dp->reo_cmd_stats.pending==1);
 assert(!take(dp,1,HAL_REO_FLUSH_CACHE_STATUS));
 assert(dp->reo_cmd_stats.tag_mismatch==1&&dp->reo_cmd_stats.pending==1);
 assert(!take(dp,0,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS));
 assert(!take(dp,257,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS));
 assert(dp->reo_cmd_stats.unexpected_status==2);
 assert(!take(dp,1,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS));
 assert(!dp->reo_cmd_stats.pending);
 cmd.flag=HAL_REO_CMD_FLG_NEED_STATUS;early_reply=true;
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback));
 pthread_join(reply_thread,NULL);early_reply=false;
 assert(reply_lock_held&&callback_count==1&&list_empty(&dp->reo_cmd_list));
 assert(dp->reo_cmd_stats.callbacks_registered==1&&dp->reo_cmd_stats.callbacks_claimed==1&&!dp->reo_cmd_stats.pending);
 /* Encoding failure and invalid descriptors do not publish a stale ring slot. */
 unsigned advances=ring->advances,hp=ring->hp;
 ab.hal.avail_blk_resource=7;cmd.flag|=HAL_REO_CMD_FLG_FLUSH_BLOCK_LATER;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_FLUSH_CACHE,&cmd,client_callback)==-ENOSPC);
 assert(ring->advances==advances&&ring->hp==hp&&!dp->reo_cmd_stats.pending);
 spin_lock_bh(&dp->reo_cmd_lock);
 assert(ath11k_hal_reo_cmd_send(&ab,ring,HAL_REO_CMD_FLUSH_QUEUE,&cmd)==-EOPNOTSUPP);
 spin_unlock_bh(&dp->reo_cmd_lock);
 assert(ring->advances==advances&&ring->hp==hp);
 struct hal_reo_cmd_hdr *hdr=(void *)((struct hal_tlv_hdr *)ring->slot[hp])->value;
 u32 saved=hdr->info0;hdr->info0=FIELD_PREP(HAL_REO_CMD_HDR_INFO0_CMD_NUMBER,5);
 cmd.flag=HAL_REO_CMD_FLG_NEED_STATUS;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-EINVAL);
 assert(ring->advances==advances);hdr->info0=saved;
 ring->full=true;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ENOBUFS);
 ring->full=false;assert(ring->advances==advances);
 /* Closing does not cancel a published owner; its matching status can still retire it. */
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback));
 u16 pending_id=hp+1;
 assert(!take(dp,pending_id,HAL_REO_FLUSH_CACHE_STATUS));
 assert(dp->reo_cmd_stats.pending==1&&!list_empty(&dp->reo_cmd_list)&&callback_count==1);
 ath11k_dp_reo_cmd_close(dp);advances=ring->advances;
 assert(dp->reo_cmd_stats.pending==1&&!list_empty(&dp->reo_cmd_list));
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ESHUTDOWN);
 assert(ring->advances==advances&&dp->reo_cmd_stats.pending==1);
 take_callback(dp,pending_id,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS);
 assert(!dp->reo_cmd_stats.pending&&callback_count==2);
 dp->reo_cmd_accepting=true;ab.nss.ownership_uncertain=true;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ESHUTDOWN);
 ab.nss.ownership_uncertain=false;ab.dev_flags=1;
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ESHUTDOWN);
 ab.dev_flags=0;assert(ring->advances==advances);
 /* Any failed extension flush retains the entire unsubmitted range. */
 dp->reo_cmd_status_tag[ring->hp+1]=HAL_REO_UPDATE_RX_REO_QUEUE_STATUS;
 assert(ath11k_dp_reo_cache_flush(&ab,&tid)==-EBUSY);
 assert(tid.pending_desc_size==192&&ring->advances==advances);
 dp->reo_cmd_status_tag[ring->hp+1]=0;
 assert(!ath11k_dp_reo_cache_flush(&ab,&tid));
 assert(ring->advances==advances+3&&tid.pending_desc_size==64&&dp->reo_cmd_stats.pending==1);
 u16 base_id=((ring->hp+ring->num_entries-1)%ring->num_entries)+1;
 struct dp_reo_cmd *base=take(dp,base_id,HAL_REO_FLUSH_CACHE_STATUS);assert(base);kfree(base);
 /* A later extension failure must not be hidden by a successful base flush. */
 tid.pending_desc_size=0;tid.size=256;advances=ring->advances;
 u16 blocked_id=((ring->hp+1)%ring->num_entries)+1;
 dp->reo_cmd_status_tag[blocked_id]=HAL_REO_UPDATE_RX_REO_QUEUE_STATUS;dp->reo_cmd_stats.pending++;
 assert(ath11k_dp_reo_cache_flush(&ab,&tid)==-EBUSY);
 assert(tid.pending_desc_size==192&&ring->advances==advances+1);
 assert(!take(dp,blocked_id,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS));
 assert(!ath11k_dp_reo_cache_flush(&ab,&tid));
 assert(ring->advances==advances+4&&tid.pending_desc_size==64);
 base_id=((ring->hp+ring->num_entries-1)%ring->num_entries)+1;
 base=take(dp,base_id,HAL_REO_FLUSH_CACHE_STATUS);assert(base);kfree(base);
 /* Exercise more than 65535 submissions without arbitrary token exhaustion. */
 for(unsigned i=0;i<70000;i++){
  unsigned id=ring->hp+1;
  assert(!ath11k_dp_tx_send_reo_cmd(&ab,(void *)16,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL));
  assert(!take(dp,id,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS));
 }
 assert(!dp->reo_cmd_stats.pending&&list_empty(&dp->reo_cmd_list));
 /* Run the whole receive path: a rejected status must not modify HAL resources. */
 ab.hal.avail_blk_resource=0;ab.hal.current_blk_index=2;
 inject_status(&ab,42,HAL_REO_FLUSH_CACHE_STATUS);
 inject_status(&ab,0,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS);
 inject_status(&ab,0,HAL_REO_DESCRIPTOR_THRESHOLD_REACHED_STATUS);
 ath11k_dp_process_reo_status(&ab);assert(!ab.hal.avail_blk_resource);
 unsigned id=ring->hp+1;
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,(void *)16,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL));
 inject_status(&ab,id,HAL_REO_FLUSH_CACHE_STATUS);
 ath11k_dp_process_reo_status(&ab);
 assert(!ab.hal.avail_blk_resource&&dp->reo_cmd_stats.pending==1);
 inject_status(&ab,id,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS);
 ath11k_dp_process_reo_status(&ab);assert(!dp->reo_cmd_stats.pending);
 /* A valid NULL-callback reply must still run its parser. */
 id=ring->hp+1;cmd.flag=HAL_REO_CMD_FLG_NEED_STATUS|HAL_REO_CMD_FLG_FLUSH_BLOCK_LATER;
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,(void *)16,HAL_REO_CMD_FLUSH_CACHE,&cmd,NULL));
 inject_status(&ab,id,HAL_REO_FLUSH_CACHE_STATUS);
 ath11k_dp_process_reo_status(&ab);assert(ab.hal.avail_blk_resource==1&&!dp->reo_cmd_stats.pending);
 id=ring->hp+1;cmd.flag=HAL_REO_CMD_FLG_NEED_STATUS;
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback));
 inject_status(&ab,id,HAL_REO_FLUSH_CACHE_STATUS);
 inject_status(&ab,id,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS);
 ath11k_dp_process_reo_status(&ab);assert(callback_count==3&&!dp->reo_cmd_stats.pending);
 assert(deallocations+1==allocations); /* The one injected allocation failure has no object. */
 puts("REO lifetime: prepublication failures, early reply, full status/HAL effects, ID backpressure/type match, reopen guards/epoch, cache retry and 70000 wraps passed");return 0;
}
'''

BASELINE = r'''
int main(void){
 struct ath11k_base ab;initialize(&ab,4);struct hal_srng *ring=&ab.hal.srng_list[0];
 ath11k_hal_reo_init_cmd_ring(&ab,ring);allocation_fail=true;
 struct dp_rx_tid tid={.tid=42};struct ath11k_hal_reo_cmd cmd={.flag=HAL_REO_CMD_FLG_NEED_STATUS};
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ENOMEM);
 assert(ring->advances==1&&list_empty(&ab.dp.reo_cmd_list));
 puts("Original REO bug reproduced: ENOMEM returned after hardware publication without a callback owner");return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backports", type=Path, required=True)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    source = args.backports / "drivers/net/wireless/ath/ath11k"
    draft = args.draft or source
    header = (draft / "dp.h").read_text()
    hal = (source / "hal.h").read_text()
    desc = (source / "hal_desc.h").read_text()
    macros = re.findall(
        r"(?m)^#define[ \t]+(?:HAL_(?:REO|TLV_HDR|SRNG_TLV_HDR_TAG|RX_REO_QUEUE|MAX_AVAIL_BLK_RES|DESC_REO_NON_QOS_TID)\w*|DP_REO_CMD_RING_SIZE)[ \t]+[^\n]*(?:\\\n[^\n]*)*",
        hal + "\n" + desc + "\n" + header)
    enums = "\n".join(declaration(text, "enum", name) for text, name in (
        (hal, "hal_reo_cmd_type"), (hal, "hal_reo_cmd_status"),
        (desc, "hal_tlv_tag"), (desc, "hal_rx_reo_queue_pn_size"), (header, "ath11k_reo_cmd_kind")))
    structs = "\n".join(declaration(desc, "struct", name) for name in (
        "hal_reo_cmd_hdr", "hal_reo_get_queue_stats", "hal_reo_flush_cache", "hal_reo_update_rx_queue",
        "hal_reo_status_hdr", "hal_reo_get_queue_stats_status", "hal_reo_flush_queue_status",
        "hal_reo_flush_cache_status", "hal_reo_unblock_cache_status", "hal_reo_flush_timeout_list_status",
        "hal_reo_desc_thresh_reached_status"))
    structs += declaration(hal, "struct", "ath11k_hal_reo_cmd")
    diagnostic = header[header.index("struct ath11k_reo_update_stats {"):header.index("struct ath11k_dp {")]
    helpers = header[header.index("static inline void ath11k_dp_reo_cmd_close"):header.index("/* HTT definitions */")]
    selected = args.baseline or draft
    hal_source = (selected / "hal_rx.c").read_text()
    # The shim declares status enums before its uniform status header.
    status_types = hal[hal.index("struct hal_reo_status_header {"):hal.index("/* HAL context to be used")]
    shim = SHIM[:SHIM.index("struct hal_reo_status_header")] + enums + "\n"
    code = (shim + "\n" + "\n".join(macros) + "\n#define HAL_REO_CMD 1\n" + structs + status_types + diagnostic +
            declaration(header, "struct", "dp_reo_cmd") + STRUCTURES + helpers +
            extract.function((draft / "dp_rx.c").read_text(), "ath11k_dp_reo_tid_clone") +
            extract.function((draft / "dp_rx.c").read_text(), "ath11k_dp_reo_tid_drop") +
            extract.function((draft / "dp_rx.c").read_text().replace(
                "*\nath11k_dp_reo_cmd_take", "*ath11k_dp_reo_cmd_take"), "ath11k_dp_reo_cmd_take") + TAKE_WRAPPER +
            "\n".join(extract.function(hal_source, name) for name in (
                "ath11k_hal_reo_cmd_queue_stats", "ath11k_hal_reo_cmd_flush_cache",
                "ath11k_hal_reo_cmd_update_rx_queue", "ath11k_hal_reo_cmd_send", "ath11k_hal_reo_init_cmd_ring")) +
            "\n".join(extract.function((draft / "hal_rx.c").read_text(), name) for name in (
                "ath11k_hal_reo_process_status", "ath11k_hal_reo_status_queue_stats",
                "ath11k_hal_reo_flush_queue_status", "ath11k_hal_reo_flush_cache_status",
                "ath11k_hal_reo_unblk_cache_status", "ath11k_hal_reo_flush_timeout_list_status",
                "ath11k_hal_reo_desc_thresh_reached_status", "ath11k_hal_reo_update_rx_reo_queue_status")) +
            extract.function((draft / "dp_rx.c").read_text(), "ath11k_dp_process_reo_status") +
            ("" if args.baseline else extract.function((draft / "dp_tx.c").read_text(), "ath11k_dp_tx_reo_submit_locked")) +
            extract.function((selected / "dp_tx.c").read_text(), "ath11k_dp_tx_send_reo_cmd") +
            extract.function((draft / "dp_rx.c").read_text(), "ath11k_dp_reo_cache_flush") +
            extract.function((draft / "dp.c").read_text(), "ath11k_dp_alloc") +
            (BASELINE if args.baseline else CASES))
    with tempfile.TemporaryDirectory(prefix="reo-lifetime-test-") as directory:
        root = Path(directory)
        c, binary = root / "test.c", root / "test"
        c.write_text(code)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-pthread",
                        "-Wall", "-Werror", "-Wno-unused-function", "-Wno-misleading-indentation",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", str(c), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, env=dict(os.environ,
                       UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="detect_leaks=1"))


if __name__ == "__main__":
    main()
