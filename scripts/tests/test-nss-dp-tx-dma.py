#!/usr/bin/env python3
"""Run real GMAC TX/complete/teardown with per-map failure and publication races."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "extract_nss", Path(__file__).with_name("test-nss-control.py"))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

DECLS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t atomic_t;typedef uint64_t atomic64_t,dma_addr_t;
typedef int netdev_tx_t;
typedef struct { unsigned held; } spinlock_t;
#define __iomem
#define likely(v) (v)
#define unlikely(v) (v)
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,x) write_status(&(v),(x))
#define NETDEV_TX_OK 0
#define NETDEV_TX_BUSY 16
#define NSS_DP_SUCCESS 0
#define NSS_DP_FAILURE 1
#define GFP_KERNEL 0
#define DMA_TO_DEVICE 1
#define CHECKSUM_PARTIAL 1
#define SYN_DP_MAX_DESC_BUFF_LEN 8191
#define SYN_DP_QUEUE_INDEX 0
#define MAX_SKB_FRAGS 16
#define U32_MAX UINT32_MAX
#define netdev_dbg(dev,...) ((void)(dev))
#define prefetch(p) ((void)(p))
struct napi_struct { unsigned dummy; };
struct device { unsigned dummy; };
struct netdev_queue { bool stopped; };
struct net_device { struct netdev_queue queue;bool carrier;void *priv; };
struct sk_buff;
typedef struct { unsigned char *address;unsigned length; } skb_frag_t;
struct skb_shared_info { unsigned nr_frags;skb_frag_t frags[MAX_SKB_FRAGS];struct sk_buff *frag_list; };
struct sk_buff {
 unsigned char *data;unsigned len,data_len,ip_summed;uintptr_t end;
 struct skb_shared_info shinfo;struct sk_buff *next;bool gso;
};
struct sk_buff_head { struct sk_buff *head,*tail; };
static struct { bool tx_requeue_stop; } dp_global_ctx;
'''

SUPPORT = r'''
struct syn_dp_info { struct syn_dp_info_tx dp_info_tx;void *mac_base;dma_addr_t tx_desc_dma_addr; };
struct nss_dp_dev { struct { struct syn_dp_info syn_info; } dp_info; };
struct nss_dp_data_plane_ctx { struct net_device *dev; };
static struct nss_dp_dev gmac;
static struct net_device netdev;
static struct device device;
static struct syn_dp_info_tx *active;
struct map_record { void *cpu;size_t length;dma_addr_t dma;bool live; };
static struct map_record ledger[SYN_DP_TX_DESC_SIZE+256];
static unsigned map_calls,map_count,unmaps,fail_map,frees,live_skbs,kicks,coherent_frees,barriers,wakes,stops;
static unsigned packet_maps,payload_offset,old_complete_on_map,ordered_kicks;
static unsigned char registers[0x1010];
static unsigned char expected[131072];
static unsigned expected_len,current_start;
static bool forced,instant,pending_napi,in_complete,quiesced,linearize_fail;
static dma_addr_t forced_address;
int syn_dp_tx_complete(struct syn_dp_info_tx *,int);
static inline unsigned atomic_read(atomic_t *p) { return *p; }
static inline void atomic_inc(atomic_t *p) { ++*p; }
static inline void atomic_dec(atomic_t *p) { assert(*p);--*p; }
static inline void atomic_set(atomic_t *p,unsigned n) { *p=n; }
static inline void atomic_add(unsigned n,atomic_t *p) { *p+=n; }
static inline void atomic64_inc(atomic64_t *p) { ++*p; }
static inline void atomic64_add(unsigned n,atomic64_t *p) { *p+=n; }
static inline void spin_lock_init(spinlock_t *p) { assert(!p->held);p->held=0; }
static inline void spin_lock(spinlock_t *p) { assert(!p->held);p->held=1; }
static inline void spin_unlock(spinlock_t *p) {
 assert(p->held);p->held=0;
 if(p==&active->ring_lock&&pending_napi&&!in_complete) {
  pending_napi=false;in_complete=true;
  assert(syn_dp_tx_complete(active,SYN_DP_TX_DESC_SIZE)>0);
  in_complete=false;
 }
}
#define spin_lock_bh spin_lock
#define spin_unlock_bh spin_unlock
static inline struct skb_shared_info *skb_shinfo(struct sk_buff *s) { return &s->shinfo; }
static inline unsigned skb_headlen(struct sk_buff *s) { return s->len-s->data_len; }
static inline bool skb_has_frag_list(struct sk_buff *s) { return s->shinfo.frag_list!=NULL; }
static inline bool skb_is_nonlinear(struct sk_buff *s) { return s->data_len!=0; }
static inline bool skb_is_gso(struct sk_buff *s) { return s->gso; }
static inline void *skb_frag_address(const skb_frag_t *f) { return f->address; }
static inline unsigned skb_frag_size(const skb_frag_t *f) { return f->length; }
#define skb_walk_frags(s,p) for((p)=(s)->shinfo.frag_list;(p);(p)=(p)->next)
static inline void *netdev_priv(struct net_device *n) { return n->priv; }
static inline struct netdev_queue *netdev_get_tx_queue(struct net_device *n,unsigned index) { assert(!index);return &n->queue; }
static inline bool netif_tx_queue_stopped(struct netdev_queue *q) { return q->stopped; }
static inline bool netif_carrier_ok(struct net_device *n) { return n->carrier; }
static inline void netif_stop_queue(struct net_device *n) {
 if(TRANSACTION)assert(active->ring_lock.held);n->queue.stopped=true;stops++;
}
static inline void netif_wake_queue(struct net_device *n) {
 n->queue.stopped=false;wakes++;
}
static inline void assert_not_mapped(void *pointer) {
 for(unsigned i=0;i<map_count;i++)assert(!ledger[i].live||ledger[i].cpu!=pointer);
}
static void dev_kfree_skb_any(struct sk_buff *s) {
 if(!s)return;assert(!active->ring_lock.held);
 struct sk_buff *part=s->shinfo.frag_list;
 while(part){struct sk_buff *next=part->next;dev_kfree_skb_any(part);part=next;}
 assert_not_mapped(s->data);
 for(unsigned i=0;i<s->shinfo.nr_frags;i++){assert_not_mapped(s->shinfo.frags[i].address);free(s->shinfo.frags[i].address);}
 free(s->data);free(s);assert(live_skbs);live_skbs--;frees++;
}
static inline void __skb_queue_head_init(struct sk_buff_head *q) { q->head=q->tail=NULL; }
static inline void __skb_queue_tail(struct sk_buff_head *q,struct sk_buff *s) {
 s->next=NULL;if(q->tail)q->tail->next=s;else q->head=s;q->tail=s;
}
static inline struct sk_buff *__skb_dequeue(struct sk_buff_head *q) {
 struct sk_buff *s=q->head;if(s){q->head=s->next;if(!q->head)q->tail=NULL;s->next=NULL;}return s;
}
static unsigned copy_payload(struct sk_buff *s,unsigned char *out) {
 unsigned count=skb_headlen(s);memcpy(out,s->data,count);
 for(unsigned i=0;i<s->shinfo.nr_frags;i++){
  memcpy(out+count,s->shinfo.frags[i].address,s->shinfo.frags[i].length);count+=s->shinfo.frags[i].length;
 }
 for(struct sk_buff *p=s->shinfo.frag_list;p;p=p->next)count+=copy_payload(p,out+count);
 return count;
}
static inline int skb_linearize(struct sk_buff *s) {
 if(linearize_fail)return -ENOMEM;
 unsigned char *data=malloc(s->len?s->len:1);assert(data);
 assert(copy_payload(s,data)==s->len);
 for(unsigned i=0;i<s->shinfo.nr_frags;i++)free(s->shinfo.frags[i].address);
 struct sk_buff *p=s->shinfo.frag_list;
 while(p){struct sk_buff *next=p->next;dev_kfree_skb_any(p);p=next;}
 free(s->data);s->data=data;s->data_len=0;memset(&s->shinfo,0,sizeof(s->shinfo));return 0;
}
static void hardware_done(unsigned count) {
 unsigned index=active->tx_comp_idx;
 if(count>active->busy_tx_desc_cnt)count=active->busy_tx_desc_cnt;
 for(unsigned i=0;i<count;i++){
  active->tx_desc[index].status&=~DESC_OWN_BY_DMA;
  index=(index+1)&SYN_DP_TX_DESC_MAX_INDEX;
 }
}
static inline dma_addr_t dma_map_single(struct device *d,void *data,size_t size,int direction) {
 assert(d==&device&&data&&size&&direction==DMA_TO_DEVICE);
 if(TRANSACTION)assert(active->producer_lock.held&&!active->ring_lock.held);
 map_calls++;packet_maps++;
 if(old_complete_on_map&&packet_maps==old_complete_on_map) {
  old_complete_on_map=0;in_complete=true;
  assert(syn_dp_tx_complete(active,1)==1);in_complete=false;
 }
 if(map_calls==fail_map)return UINT64_MAX;
 assert(payload_offset+size<=expected_len&&!memcmp(expected+payload_offset,data,size));
 payload_offset+=size;assert(map_count<sizeof(ledger)/sizeof(*ledger));
 dma_addr_t address=forced?forced_address:(dma_addr_t)map_count*0x10000;
 ledger[map_count++]=(struct map_record){data,size,address,true};return address;
}
static inline bool dma_mapping_error(struct device *d,dma_addr_t address) { assert(d==&device);return address==UINT64_MAX; }
static inline void dma_unmap_single(struct device *d,dma_addr_t address,size_t size,int direction) {
 assert(d==&device&&direction==DMA_TO_DEVICE);
 for(unsigned i=0;i<map_count;i++)if(ledger[i].live&&ledger[i].dma==address){
  assert(ledger[i].length==size);ledger[i].live=false;unmaps++;return;
 }
 assert(!"unknown or duplicate DMA unmap");
}
static inline void *dma_alloc_coherent(struct device *d,size_t size,dma_addr_t *address,int flags) {
 assert(d==&device&&flags==GFP_KERNEL&&size==sizeof(struct dma_desc_tx)*SYN_DP_TX_DESC_SIZE);
 *address=0x5555;return calloc(1,size);
}
static inline void dma_free_coherent(struct device *d,size_t size,void *pointer,dma_addr_t address) {
 assert(d==&device&&size==sizeof(struct dma_desc_tx)*SYN_DP_TX_DESC_SIZE&&address==0x5555&&pointer);
 assert(!active->ring_lock.held&&!active->producer_lock.held);
 for(unsigned i=0;i<map_count;i++)assert(!ledger[i].live);
 coherent_frees++;free(pointer);
}
static inline bool syn_dp_gmac_is_tx_desc_owned_by_dma(uint32_t status) { return status&DESC_OWN_BY_DMA; }
static inline void syn_dp_gmac_tx_desc_init_ring(struct dma_desc_tx *p,unsigned count) {
 memset(p,0,sizeof(*p)*count);p[count-1].status=DESC_TX_DESC_END_OF_RING;
}
static inline void syn_init_tx_desc_base(void *base,dma_addr_t address) { (void)base;(void)address; }
static inline void dma_wmb(void) { barriers++; }
#define wmb dma_wmb
static inline void write_status(uint32_t *p,uint32_t value) {
 *p=value;
 if((value&(DESC_OWN_BY_DMA|DESC_TX_FIRST))==(DESC_OWN_BY_DMA|DESC_TX_FIRST)){
  assert(active->ring_lock.held&&active->producer_lock.held&&barriers);
  assert(active->busy_tx_desc_cnt>=packet_maps&&payload_offset==expected_len);
 }
}
static inline void test_doorbell(void) {
 kicks++;
 if(TRANSACTION)assert(active->ring_lock.held&&active->producer_lock.held);
 if(instant){hardware_done(active->busy_tx_desc_cnt);pending_napi=true;}
}
static inline void writel(uint32_t value,void *address) {
 assert(!value&&address==registers+SYN_DMA_TX_POLL_DEMAND);
 ordered_kicks++;test_doorbell();
}
static inline void hal_write_relaxed_reg(void *base,unsigned offset,uint32_t value) {
 assert(!value&&base==registers&&offset==SYN_DMA_TX_POLL_DEMAND);
 if(TRANSACTION)assert(!"descriptor OWN requires an ordered MMIO doorbell");
 test_doorbell();
}
'''

TEST = r'''
static void fixture(unsigned start) {
 memset(&gmac,0,sizeof(gmac));memset(&netdev,0,sizeof(netdev));memset(ledger,0,sizeof(ledger));
 netdev.priv=&gmac;netdev.carrier=true;active=&gmac.dp_info.syn_info.dp_info_tx;
 active->netdev=&netdev;active->dev=&device;
 active->mac_base=gmac.dp_info.syn_info.mac_base=registers;
 map_calls=map_count=unmaps=fail_map=frees=live_skbs=kicks=coherent_frees=barriers=wakes=stops=0;
 packet_maps=payload_offset=old_complete_on_map=ordered_kicks=0;forced=instant=pending_napi=in_complete=quiesced=linearize_fail=false;
 dp_global_ctx.tx_requeue_stop=false;
 assert(!syn_dp_cfg_tx_setup_desc_queue(&gmac.dp_info.syn_info));
 active->tx_idx=active->tx_comp_idx=start;
}
static struct sk_buff *packet(unsigned head) {
 struct sk_buff *s=calloc(1,sizeof(*s));assert(s);s->data=malloc(head?head:1);assert(s->data);
 memset(s->data,0xa5,head);s->len=head;s->end=(uintptr_t)&s->shinfo;s->ip_summed=CHECKSUM_PARTIAL;live_skbs++;return s;
}
static void add_frag(struct sk_buff *s,unsigned length) {
 unsigned n=s->shinfo.nr_frags++;assert(n<MAX_SKB_FRAGS);
 s->shinfo.frags[n]=(skb_frag_t){.address=malloc(length?length:1),.length=length};assert(s->shinfo.frags[n].address);
 memset(s->shinfo.frags[n].address,0x60+n,length);s->data_len+=length;s->len+=length;
}
static void add_child(struct sk_buff *s,struct sk_buff *child) {
 struct sk_buff **p=&s->shinfo.frag_list;while(*p)p=&(*p)->next;*p=child;s->len+=child->len;s->data_len+=child->len;
}
static struct sk_buff *shape(unsigned type) {
 struct sk_buff *s=packet(type==2?0:64);
 if(type==0)return s;
 add_frag(s,129);add_frag(s,257);add_frag(s,33);
 if(type==3){
  struct sk_buff *a=packet(17),*b=packet(31);add_frag(a,45);add_frag(a,7);add_child(s,a);add_child(s,b);
 }
 return s;
}
static void begin(struct sk_buff *s) {
 expected_len=copy_payload(s,expected);assert(expected_len==s->len);
 payload_offset=packet_maps=0;current_start=active->tx_idx;
}
static void check_empty(unsigned start) {
 assert(!active->busy_tx_desc_cnt&&active->tx_idx==start);
 for(unsigned i=0;i<SYN_DP_TX_DESC_SIZE;i++) {
  assert(!active->tx_buf_pool[i].mapped&&!active->tx_buf_pool[i].skb);
  assert(active->tx_desc[i].status==(i==SYN_DP_TX_DESC_MAX_INDEX?DESC_TX_DESC_END_OF_RING:0));
 }
}
static void finish(void) {
 if(TRANSACTION)assert(ordered_kicks==kicks);
 quiesced=true;syn_dp_cfg_tx_cleanup_rings(&gmac.dp_info.syn_info);
 assert(!live_skbs&&coherent_frees==1&&!active->tx_desc&&!active->busy_tx_desc_cnt);
 syn_dp_cfg_tx_cleanup_rings(&gmac.dp_info.syn_info);assert(coherent_frees==1);
}
static void failures(void) {
 unsigned starts[]={0,SYN_DP_TX_DESC_SIZE-2,SYN_DP_TX_DESC_SIZE-1};
 for(unsigned type=0;type<4;type++)for(unsigned start=0;start<3;start++){
  unsigned segments=type==0?1:type==2?3:type==3?8:4;
  for(unsigned failed=1;failed<=segments;failed++){
   fixture(starts[start]);struct sk_buff *s=shape(type);begin(s);fail_map=failed;
   assert(syn_dp_tx(active,s)==-EIO);
   assert(map_calls==failed&&unmaps==failed-1&&!kicks&&!frees);
   check_empty(starts[start]);dev_kfree_skb_any(s);finish();
  }
 }
 /* The actual ndo wrapper frees a failed packet; it must not stop the queue. */
 fixture(0);struct sk_buff *s=shape(3);begin(s);fail_map=4;
 struct nss_dp_data_plane_ctx context={.dev=&netdev};
 assert(syn_dp_if_xmit(&context,s)==NETDEV_TX_OK);
 assert(!live_skbs&&!netdev.queue.stopped&&active->tx_stats.tx_dropped==1);
 finish();
}
static void success_and_partial(void) {
 for(unsigned type=0;type<4;type++){
  fixture(SYN_DP_TX_DESC_SIZE-1);struct sk_buff *s=shape(type);begin(s);
  assert(!syn_dp_tx(active,s));unsigned count=map_calls;
  assert(count==(type==0?1:type==2?3:type==3?8:4)&&active->busy_tx_desc_cnt==count&&kicks==1);
  for(unsigned i=0;i<count;i++){
   unsigned index=(current_start+i)&SYN_DP_TX_DESC_MAX_INDEX;
   uint32_t status=active->tx_desc[index].status;
   assert(status&DESC_OWN_BY_DMA);assert(!!(status&DESC_TX_FIRST)==(i==0));
   assert(!!(status&DESC_TX_LAST)==(i==count-1));
   assert((status&DESC_TX_CIS_MASK)==DESC_TX_CIS_TCP_PSEUDO_CS);
  }
  if(count>1){hardware_done(count-1);assert(syn_dp_tx_complete(active,count-1)==(int)count-1);assert(!frees);}
  finish();assert(unmaps==count);
 }
}
static void ranges(void) {
 unsigned lengths[]={8191,8192,16382};
 for(unsigned i=0;i<3;i++){
  fixture(0);struct sk_buff *s=packet(lengths[i]);begin(s);assert(!syn_dp_tx(active,s));
  uint32_t encoded=active->tx_desc[0].length;
  assert(((encoded&DESC_SIZE1_MASK)>>DESC_SIZE1_SHIFT)+((encoded&DESC_SIZE2_MASK)>>DESC_SIZE2_SHIFT)==lengths[i]);
  hardware_done(1);assert(syn_dp_tx_complete(active,1)==1&&unmaps==1&&!live_skbs);finish();
 }
 fixture(0);struct sk_buff *too_big=packet(16383);begin(too_big);
 assert(syn_dp_tx(active,too_big)==-EMSGSIZE&&!map_calls&&!kicks);dev_kfree_skb_any(too_big);finish();
 dma_addr_t addresses[]={0,UINT32_MAX-31,UINT32_MAX-30,UINT64_C(0x100000000)};
 for(unsigned i=0;i<4;i++){
  fixture(0);forced=true;forced_address=addresses[i];struct sk_buff *s=packet(32);begin(s);
  int result=syn_dp_tx(active,s);
  if(i<2){assert(!result);hardware_done(1);assert(syn_dp_tx_complete(active,1)==1);}
  else{assert(result==-EOVERFLOW&&!kicks&&!active->busy_tx_desc_cnt);dev_kfree_skb_any(s);}
  assert(unmaps==1&&!live_skbs);finish();
 }
}
static void completion_races(void) {
 fixture(SYN_DP_TX_DESC_SIZE-2);struct sk_buff *old=packet(64);begin(old);assert(!syn_dp_tx(active,old));hardware_done(1);
 unsigned old_unmaps=unmaps,old_frees=frees,start=active->tx_idx;
 struct sk_buff *next=shape(1);begin(next);old_complete_on_map=2;fail_map=map_calls+2;
 assert(syn_dp_tx(active,next)==-EIO);
 assert(unmaps==old_unmaps+2&&frees==old_frees+1&&!active->busy_tx_desc_cnt&&active->tx_comp_idx==start);
 check_empty(start);dev_kfree_skb_any(next);finish();
 fixture(SYN_DP_TX_DESC_SIZE-1);struct sk_buff *s=shape(3);begin(s);instant=true;
 assert(!syn_dp_tx(active,s));assert(!live_skbs&&!active->busy_tx_desc_cnt&&unmaps==8&&kicks==1);
 finish();
}
static void full_ring(void) {
 fixture(0);
 for(unsigned i=0;i<SYN_DP_TX_DESC_SIZE;i++){struct sk_buff *s=packet(32);begin(s);assert(!syn_dp_tx(active,s));}
 struct sk_buff *retry=packet(32);begin(retry);unsigned before=map_calls;
 struct nss_dp_data_plane_ctx context={.dev=&netdev};
 assert(syn_dp_if_xmit(&context,retry)==NETDEV_TX_BUSY&&netdev.queue.stopped&&map_calls==before);
 hardware_done(2);assert(syn_dp_tx_complete(active,2)==2&&!netdev.queue.stopped&&wakes==1);
 begin(retry);assert(syn_dp_if_xmit(&context,retry)==NETDEV_TX_OK);
 hardware_done(SYN_DP_TX_DESC_SIZE);
 assert(syn_dp_tx_complete(active,SYN_DP_TX_DESC_SIZE*2)==SYN_DP_TX_DESC_SIZE-1);
 assert(!live_skbs&&active->tx_stats.tx_packets==SYN_DP_TX_DESC_SIZE+1);finish();
 fixture(0);
 for(unsigned i=0;i<SYN_DP_TX_DESC_SIZE;i++){struct sk_buff *s=packet(32);begin(s);assert(!syn_dp_tx(active,s));}
 dp_global_ctx.tx_requeue_stop=true;retry=packet(32);begin(retry);before=map_calls;
 assert(syn_dp_if_xmit(&context,retry)==NETDEV_TX_OK&&!netdev.queue.stopped&&map_calls==before);
 assert(active->tx_stats.tx_dropped==1);finish();
}
static void nested_and_invalid(void) {
 for(unsigned failure=0;failure<2;failure++){
  fixture(0);struct sk_buff *s=packet(64),*child=packet(32),*grandchild=packet(16);
  add_child(child,grandchild);add_child(s,child);begin(s);linearize_fail=failure;
  int ret=syn_dp_tx(active,s);
  if(failure){assert(ret==-ENOMEM&&!map_calls&&!frees);dev_kfree_skb_any(s);}
  else{assert(!ret&&map_calls==1&&frees==2);hardware_done(1);assert(syn_dp_tx_complete(active,1)==1);}
  finish();
 }
 fixture(0);struct sk_buff *s=packet(64);s->gso=true;begin(s);
 assert(syn_dp_tx(active,s)==-EOPNOTSUPP&&!map_calls);dev_kfree_skb_any(s);finish();
}
int main(void) {
 failures();success_and_partial();ranges();completion_races();full_ring();nested_and_invalid();
 puts("PASS actual GMAC TX: every map failure, exact DMA pairing, SG/fraglist payloads, nested fallback, range limits, partial teardown, old/instant completion, full-ring stop/wake and NAPI batches");
}
'''


def structure(source, name):
    return re.search(r"struct "+name+r" \{.*?\n\};", source, re.S).group()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dp", type=Path, required=True)
    args = parser.parse_args()
    root = args.dp / "hal/dp_ops/syn_gmac_dp"
    source = (root / "syn_dp_tx.c").read_text()
    cfg, common = (root / "syn_dp_cfg_tx.c").read_text(), (root / "syn_dp.c").read_text()
    header, desc = (root / "syn_dp_tx.h").read_text(), (root / "syn_dma_desc.h").read_text()
    registers = (root / "syn_dma_reg.h").read_text()
    transaction = "struct syn_dp_tx_prepare" in source
    constants = "\n".join(re.findall(r"^#define SYN_DP_(?:NAPI_BUDGET_TX|TX_DESC_SIZE|TX_DESC_MAX_INDEX|TX_INVALID_DESC_INDEX)[^\n]*", header, re.M))
    constants += "\n"+re.search(r"^#define SYN_DMA_TX_POLL_DEMAND[^\n]*", registers, re.M).group()
    enumeration = re.search(r"enum syn_dma_desc_status \{.*?\n\};", desc, re.S).group()
    stats = set(re.findall(r"tx_stats\.(\w+)", source+extractor.function(common, "syn_dp_if_xmit")))
    stats_decl = "struct nss_dp_hal_gmac_stats_tx { "+" ".join("atomic64_t "+name+";" for name in sorted(stats))+" };\n"
    buffer, info = structure(header, "syn_dp_tx_buf"), structure(header, "syn_dp_info_tx")
    # Extra shim storage keeps the old producer compilable for behavioral ablation.
    if not transaction:
        buffer = buffer[:-2]+"dma_addr_t dma_addr;uint32_t dma_len;bool mapped;\n};"
        info = info[:-2]+"spinlock_t producer_lock,ring_lock;bool locks_initialized,stopping;\n};"
    helpers = "".join(extractor.function(header, name) for name in
                      ("syn_dp_tx_inc_index", "syn_dp_tx_comp_desc_get", "syn_dp_tx_comp_index_get"))
    program = "#define TRANSACTION "+str(int(transaction))+"\n"+DECLS+constants+"\n"+enumeration
    program += structure(desc, "dma_desc_tx")+stats_decl+buffer+info+SUPPORT+helpers
    program += extractor.function(registers, "syn_resume_dma_tx")
    program += re.sub(r"(?m)^#include[^\n]*", "", source)
    program += extractor.function(cfg, "syn_dp_cfg_tx_setup_desc_queue")
    program += extractor.function(cfg, "syn_dp_cfg_tx_cleanup_rings")
    program += extractor.function(common, "syn_dp_if_xmit")+TEST
    with tempfile.TemporaryDirectory(prefix="nss-dp-tx-dma-") as directory:
        folder = Path(directory)
        cfile, binary = folder / "tx.c", folder / "tx"
        cfile.write_text(program)
        subprocess.run(["cc", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", "-Wno-sign-compare", "-Wno-misleading-indentation",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie",
                        *([] if transaction else ["-Wno-unused-but-set-variable"]),
                        str(cfile), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30,
                       env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})


if __name__ == "__main__":
    main()
