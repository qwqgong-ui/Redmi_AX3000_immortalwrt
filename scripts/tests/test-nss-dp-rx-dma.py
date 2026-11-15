#!/usr/bin/env python3
"""Run actual GMAC refill, receive unmap and teardown with a DMA ownership ledger."""
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

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint64_t dma_addr_t,atomic64_t;typedef uint32_t atomic_t;
#define likely(v) (v)
#define unlikely(v) (v)
#define GFP_ATOMIC 0
#define DMA_FROM_DEVICE 1
#define NET_IP_ALIGN 2
#define SYN_DP_SKB_HEADROOM 128
#define PAGE_SIZE 4096
#define SYN_DP_RX_DESC_SIZE RX_RING_SIZE
#define SYN_DP_RX_DESC_MAX_INDEX (SYN_DP_RX_DESC_SIZE-1)
#define SYN_DP_MAX_DESC_BUFF_LEN 8191
#define DESC_SIZE1_SHIFT 0
#define DESC_SIZE1_MASK 0x1fff
#define DESC_SIZE2_SHIFT 16
#define DESC_SIZE2_MASK 0x1fff0000
#define DESC_OWN_BY_DMA 0x80000000
#define dsb(v) ((void)0)
#define READ_ONCE(v) read_status(&(v))
#define WRITE_ONCE(v,x) write_status(&(v),(x))
#define netdev_dbg(...) ((void)0)
static unsigned atomic_read(atomic_t *p) { return *p; }
static void atomic_inc(atomic_t *p) { ++*p; }
static inline void atomic_set(atomic_t *p,unsigned n) { *p=n; }
static void atomic64_inc(atomic64_t *p) { ++*p; }
struct page { unsigned char bytes[PAGE_SIZE]; };
struct sk_buff { unsigned char *allocation,*data;size_t capacity;struct page *page;struct sk_buff *child; };
struct dma_desc_rx { uint32_t status,length,buffer1,buffer2,extstatus; };
struct syn_dp_rx_buf {
 struct sk_buff *skb;size_t map_addr_virt;dma_addr_t dma_addr;uint32_t dma_len;bool map_page;
};
struct syn_dp_info_rx {
 struct dma_desc_rx *rx_desc;uint32_t busy_rx_desc_cnt,rx_refill_idx,rx_idx;
 struct syn_dp_rx_buf rx_buf_pool[SYN_DP_RX_DESC_SIZE];
 struct { atomic64_t rx_skb_alloc_errors; } rx_stats;
 void *dev,*netdev,*mac_base;bool page_mode;unsigned alloc_buf_len,prev_len;
 struct sk_buff *head,*tail;
};
struct syn_dp_info { struct syn_dp_info_rx dp_info_rx;dma_addr_t rx_desc_dma_addr; };
struct mapping { dma_addr_t dma;size_t length;bool page,live; };
static struct mapping mappings[SYN_DP_RX_DESC_SIZE];
static unsigned maps,unmaps,allocations,fail_alloc,fail_map,fail_page,frees,coherent_frees,pages,resumes,live_skbs;
static void *active_dev;
static bool write_barrier,read_owned;
static unsigned read_barriers;
static struct dma_desc_rx *read_descriptor;
static inline void dma_wmb(void) { write_barrier=true; }
static inline void write_status(uint32_t *p,uint32_t value) {
 assert(value==DESC_OWN_BY_DMA&&write_barrier);
 write_barrier=false;*p=value;
}
static inline uint32_t read_status(uint32_t *p) {
 assert(read_descriptor&&p==&read_descriptor->status);
 read_owned=!(*p&DESC_OWN_BY_DMA);return *p;
}
static bool syn_dp_gmac_is_rx_desc_owned_by_dma(uint32_t status) { return status&DESC_OWN_BY_DMA; }
static inline void dma_rmb(void) {
 assert(read_owned&&read_descriptor);read_barriers++;
 read_descriptor->extstatus=0x1234;
}
static struct sk_buff *__netdev_alloc_skb(void *dev,size_t len,int flags) {
 (void)dev;assert(flags==GFP_ATOMIC);allocations++;
 if(allocations==fail_alloc)return NULL;
 struct sk_buff *skb=calloc(1,sizeof(*skb));assert(skb);
 skb->allocation=malloc(len);assert(skb->allocation);skb->data=skb->allocation;skb->capacity=len;live_skbs++;return skb;
}
static void dev_kfree_skb_any(struct sk_buff *skb) {
 if(!skb)return;
 dev_kfree_skb_any(skb->child);free(skb->page);free(skb->allocation);free(skb);
 assert(live_skbs);live_skbs--;frees++;
}
#define dev_kfree_skb dev_kfree_skb_any
static void skb_reserve(struct sk_buff *skb,unsigned n) { assert(n<=skb->capacity);skb->data+=n; }
static struct page *alloc_page(int flags) {
 assert(flags==GFP_ATOMIC);pages++;return pages==fail_page?NULL:calloc(1,sizeof(struct page));
}
static void skb_fill_page_desc(struct sk_buff *skb,unsigned index,struct page *page,unsigned offset,unsigned len) {
 assert(!index&&!offset&&len==PAGE_SIZE);skb->page=page;
}
static void *page_address(struct page *page) { return page->bytes; }
static dma_addr_t map_buffer(void *dev,size_t size,bool page) {
 assert(dev==active_dev&&size);unsigned index=maps++;
 if(maps==fail_map)return UINT32_MAX;
 assert(index<SYN_DP_RX_DESC_SIZE);
 /* A successful DMA address of zero is deliberately included. */
 mappings[index]=(struct mapping){.dma=(dma_addr_t)index*0x10000,.length=size,.page=page,.live=true};
 return mappings[index].dma;
}
static dma_addr_t dma_map_single(void *dev,void *data,size_t len,int direction) {
 assert(data&&direction==DMA_FROM_DEVICE);return map_buffer(dev,len,false);
}
static dma_addr_t dma_map_page(void *dev,struct page *page,unsigned offset,size_t len,int direction) {
 assert(page&&!offset&&len==PAGE_SIZE&&direction==DMA_FROM_DEVICE);return map_buffer(dev,len,true);
}
static bool dma_mapping_error(void *dev,dma_addr_t addr) { assert(dev==active_dev);return addr==UINT32_MAX; }
static void unmap(void *dev,dma_addr_t addr,size_t len,int direction,bool page) {
 assert(dev==active_dev&&direction==DMA_FROM_DEVICE);
 unsigned index=addr/0x10000;assert(!(addr%0x10000)&&index<maps);
 struct mapping *m=&mappings[index];
 assert(m->live&&m->dma==addr&&m->length==len&&m->page==page);
 m->live=false;unmaps++;
}
static void dma_unmap_single(void *dev,dma_addr_t addr,size_t len,int direction) { unmap(dev,addr,len,direction,false); }
static void dma_unmap_page(void *dev,dma_addr_t addr,size_t len,int direction) { unmap(dev,addr,len,direction,true); }
static void dma_free_coherent(void *dev,size_t size,void *pointer,dma_addr_t addr) {
 assert(dev==active_dev&&pointer&&size==sizeof(struct dma_desc_rx)*SYN_DP_RX_DESC_SIZE&&addr==0x5555);
 for(unsigned i=0;i<maps;i++)assert(!mappings[i].live);
 coherent_frees++;free(pointer);
}
static void syn_resume_dma_rx(void *base) { assert(base==active_dev);resumes++; }
'''

NORMAL = r'''
static void receive_unmap(struct syn_dp_info_rx *rx_info,unsigned rx_idx) {
 struct dma_desc_rx *rx_desc __attribute__((unused))=rx_info->rx_desc+rx_idx;
 CONSUMER
}
static bool receive_ready(struct dma_desc_rx *rx_desc) {
 uint32_t status;
 do {
  OWNERSHIP
  return true;
 } while(0);
 return false;
}
'''

TEST = r'''
static void fresh(struct syn_dp_info *info,unsigned start,bool page_mode) {
 memset(info,0,sizeof(*info));memset(mappings,0,sizeof(mappings));
 maps=unmaps=allocations=fail_alloc=fail_map=fail_page=frees=coherent_frees=pages=resumes=live_skbs=0;
 struct syn_dp_info_rx *rx=&info->dp_info_rx;active_dev=rx;rx->dev=rx->netdev=rx->mac_base=rx;
 rx->alloc_buf_len=2048;rx->page_mode=page_mode;rx->rx_idx=rx->rx_refill_idx=start;
 rx->rx_desc=calloc(SYN_DP_RX_DESC_SIZE,sizeof(*rx->rx_desc));assert(rx->rx_desc);
 rx->rx_desc[SYN_DP_RX_DESC_MAX_INDEX].length=0x8000;info->rx_desc_dma_addr=0x5555;
}
static void cleanup_matrix(void) {
 unsigned starts[]={0,1,SYN_DP_RX_DESC_SIZE/2,SYN_DP_RX_DESC_SIZE-2,SYN_DP_RX_DESC_SIZE-1};
 unsigned counts[]={0,1,2,3,SYN_DP_RX_DESC_SIZE-1,SYN_DP_RX_DESC_SIZE};
 for(unsigned page=0;page<2;page++)for(unsigned si=0;si<5;si++)for(unsigned ci=0;ci<6;ci++) {
  struct syn_dp_info info;unsigned count=counts[ci],start=starts[si];fresh(&info,start,page);
  struct syn_dp_info_rx *rx=&info.dp_info_rx;
  if(count<SYN_DP_RX_DESC_SIZE)fail_alloc=count+1;
  int pending=page?syn_dp_rx_refill_page_mode(rx):syn_dp_rx_refill(rx);
  assert(pending==(int)(SYN_DP_RX_DESC_SIZE-count)&&rx->busy_rx_desc_cnt==count&&maps==count);
  assert(rx->rx_refill_idx==((start+count)&SYN_DP_RX_DESC_MAX_INDEX));
  for(unsigned i=0;i<count;i++) {
   unsigned index=(start+i)&SYN_DP_RX_DESC_MAX_INDEX;
   assert(rx->rx_buf_pool[index].skb);
   /* The host ledger must survive changes to current settings/descriptors. */
   rx->rx_desc[index].length|=0x60000000;
   rx->rx_desc[index].buffer1^=0x1234;
  }
  rx->alloc_buf_len+=128;rx->page_mode=!page;
  if(count) {
   receive_unmap(rx,start);
   assert(unmaps==1&&!rx->rx_buf_pool[start].dma_len);
  }
  fail_alloc=0;rx->head=__netdev_alloc_skb(rx,64,0);rx->head->child=__netdev_alloc_skb(rx,64,0);
  rx->tail=rx->head->child;rx->prev_len=32;
  syn_dp_cfg_rx_cleanup_rings(&info);
  assert(unmaps==count&&frees==count+2&&!live_skbs&&coherent_frees==1);
  assert(!rx->rx_desc&&!info.rx_desc_dma_addr&&!rx->head&&!rx->tail&&!rx->prev_len&&!rx->busy_rx_desc_cnt);
  for(unsigned i=0;i<SYN_DP_RX_DESC_SIZE;i++)
   assert(!rx->rx_buf_pool[i].skb&&!rx->rx_buf_pool[i].dma_len);
  syn_dp_cfg_rx_cleanup_rings(&info);assert(coherent_frees==1&&frees==count+2);
 }
}
int main(void) {
 struct dma_desc_rx completion={.status=DESC_OWN_BY_DMA};
 read_descriptor=&completion;read_owned=false;
 assert(!receive_ready(&completion)&&!read_barriers);
 completion.status=0;
 assert(receive_ready(&completion)&&read_barriers==1&&completion.extstatus==0x1234);
 cleanup_matrix();
 for(unsigned page=0;page<2;page++)for(unsigned failed=1;failed<=4;failed++) {
  struct syn_dp_info info;fresh(&info,SYN_DP_RX_DESC_SIZE-2,page);fail_map=failed;
  struct syn_dp_info_rx *rx=&info.dp_info_rx;
  int pending=page?syn_dp_rx_refill_page_mode(rx):syn_dp_rx_refill(rx);
  assert(pending==(int)(SYN_DP_RX_DESC_SIZE-failed+1)&&rx->busy_rx_desc_cnt==failed-1);
  assert(maps==failed&&frees==1);
  syn_dp_cfg_rx_cleanup_rings(&info);assert(unmaps==failed-1&&!live_skbs&&coherent_frees==1);
 }
 puts("PASS real GMAC RX DMA: both refill APIs, circular partial/full teardown, exact original mapping length/type/address, zero DMA address, normal-unmap reuse, partial scatter owner and failures");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dp", type=Path, required=True)
    args = parser.parse_args()
    root = args.dp / "hal/dp_ops/syn_gmac_dp"
    rx, header = (root / "syn_dp_rx.c").read_text(), (root / "syn_dp_rx.h").read_text()
    ring_size = re.search(r"^#define SYN_DP_RX_DESC_SIZE\s+(\d+)", header, re.M).group(1)
    helpers = extractor.function(header, "syn_dp_rx_inc_index")
    if "void syn_dp_rx_unmap_buffer(" in rx:
        helpers += extractor.function(rx, "syn_dp_rx_unmap_buffer")
    helpers += "".join(extractor.function(rx, name) for name in
                       ("syn_dp_rx_refill_one_desc", "syn_dp_rx_inval_and_flush",
                        "syn_dp_rx_refill_page_mode", "syn_dp_rx_refill"))
    helpers += extractor.function((root / "syn_dp_cfg_rx.c").read_text(),
                                  "syn_dp_cfg_rx_cleanup_rings")
    receive = extractor.function(rx, "syn_dp_rx")
    anchor = "frame_length = syn_dp_gmac_get_rx_desc_frame_length(status);"
    consumer = receive[receive.index(anchor)+len(anchor):receive.index("prefetch((void *)rx_buf->map_addr_virt);")]
    ownership = receive[receive.index("status =", receive.index("do {")):receive.index("rx_idx = rx_info->rx_idx;", receive.index("do {"))]
    program = "#define RX_RING_SIZE "+ring_size+"\n"+SHIM+helpers
    program += NORMAL.replace("CONSUMER", consumer).replace("OWNERSHIP", ownership)+TEST
    with tempfile.TemporaryDirectory(prefix="nss-dp-rx-dma-") as directory:
        root = Path(directory)
        source, binary = root / "rx.c", root / "rx"
        source.write_text(program)
        # The real fence-only helper has intentionally unused arguments.
        subprocess.run(["cc", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", "-Wno-sign-compare",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30,
                       env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})


if __name__ == "__main__":
    main()
