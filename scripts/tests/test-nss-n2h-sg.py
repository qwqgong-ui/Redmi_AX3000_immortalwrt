#!/usr/bin/env python3
"""Exercise the actual linear N2H handler's chain replacement and ownership."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
extract = module('test-nss-control.py')
layout = module('test-nss-wifili.py')

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uintptr_t nss_ptr_t;
#define likely(x) (x)
#define unlikely(x) (x)
#define CONFIG_NET_CLS_ACT 1
#define DMA_FROM_DEVICE 2
#define NET_SKB_PAD 64
#define nss_warning(...) do { } while (0)
#define prefetch(x) ((void)(x))
#define NSS_PKT_STATS_INC(p) (++*(p))
#define NSS_PKT_STATS_DEC(p) (--*(p))
struct sk_buff;
struct skb_shared_info { struct sk_buff *frag_list; };
struct sk_buff {
 unsigned char *head, *data;
 unsigned int len, data_len, truesize, priority, end, tail;
 bool classified;
 struct sk_buff *next;
 struct skb_shared_info sh;
};
static unsigned live, unmapped;
static struct skb_shared_info *skb_shinfo(struct sk_buff *s) { return &s->sh; }
static bool skb_has_frag_list(struct sk_buff *s) { return s->sh.frag_list != NULL; }
static void skb_frag_list_init(struct sk_buff *s) { s->sh.frag_list = NULL; }
static unsigned skb_end_offset(struct sk_buff *s) { return s->end; }
static void skb_set_tail_pointer(struct sk_buff *s, unsigned len) { s->tail = (s->data-s->head)+len; }
static void nss_core_set_skb_classify(struct sk_buff *s) { s->classified = true; }
static void dma_unmap_single(void *dev, uintptr_t addr, unsigned len, int dir) {
 (void)dev; (void)addr; assert(len <= 512 && dir == DMA_FROM_DEVICE); unmapped++;
}
static void dev_kfree_skb_any(struct sk_buff *s) {
 assert(s && live);
 struct sk_buff *frag = s->sh.frag_list;
 while (frag) { struct sk_buff *next = frag->next; dev_kfree_skb_any(frag); frag = next; }
 free(s->head); free(s); live--;
}
'''

PLATFORM = r'''
struct nss_top_instance { long stats_drv[NSS_DRV_STATS_MAX]; };
struct nss_ctx_instance { struct nss_top_instance *nss_top; void *dev; unsigned max_buf_size; };
static struct nss_top_instance top;
static struct nss_ctx_instance ctx = { .nss_top = &top, .max_buf_size = 448 };
static struct sk_buff *head, *tail;
static struct sk_buff *packet(bool counted) {
 struct sk_buff *s = calloc(1, sizeof(*s)); assert(s);
 s->head = calloc(1,512); assert(s->head); s->data=s->head; s->end=512; s->truesize=640; live++;
 if (counted) top.stats_drv[NSS_DRV_STATS_NSS_SKB_COUNT]++;
 return s;
}
static void fresh(void) { assert(!live); memset(&top,0,sizeof(top)); head=tail=NULL; unmapped=0; }
static bool receive(struct sk_buff **s, unsigned flags) {
 struct n2h_descriptor d = { .buffer=0x1000, .payload_offs=32, .payload_len=64, .bit_flags=flags, .pri=7 };
 return nss_core_handle_linear_skb(&ctx,s,&head,&tail,&d);
}
static void deliver(struct sk_buff *s) {
 assert(top.stats_drv[NSS_DRV_STATS_NSS_SKB_COUNT] == 1);
 /* The real completed-buffer dispatcher consumes the retained head count. */
 top.stats_drv[NSS_DRV_STATS_NSS_SKB_COUNT]--; dev_kfree_skb_any(s);
 assert(!live && !head && !tail && !top.stats_drv[NSS_DRV_STATS_NSS_SKB_COUNT]);
}
'''

CASES = r'''
static void rejected_replacement(void) {
 fresh(); struct sk_buff *s=packet(true); assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT));
 s=packet(true); assert(!receive(&s,0)); assert(head && tail && head->sh.frag_list==tail);
 s=packet(true); s->sh.frag_list=packet(false);
 assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT));
 /* Baseline must reach the real next-segment dereference, not a model assertion. */
 s=packet(true); assert(!receive(&s,0));
 assert(!head && !tail && !live && top.stats_drv[NSS_DRV_STATS_NSS_SKB_COUNT]==0);
 s=packet(true); assert(!receive(&s,N2H_BIT_FLAG_LAST_SEGMENT)); assert(!live && !head && !tail);
}
static void healthy_chain(void) {
 fresh(); struct sk_buff *first=packet(true), *s=first;
 assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT)); assert(head==first && !tail);
 s=packet(true); assert(!receive(&s,0)); struct sk_buff *middle=s;
 s=packet(true); assert(receive(&s,N2H_BIT_FLAG_LAST_SEGMENT));
 assert(s==first && !head && !tail && s->sh.frag_list==middle && middle->next && !middle->next->next);
 assert(s->len==192 && s->data_len==128 && s->truesize==1920 && s->priority==7);
 assert(unmapped==3 && top.stats_drv[NSS_DRV_STATS_RX_SKB_FRAGLIST]==1); deliver(s);
}
static void accepted_replacement(void) {
 fresh(); struct sk_buff *s=packet(true); assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT));
 s=packet(true); assert(!receive(&s,0));
 struct sk_buff *next=packet(true); s=next;
 assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT)); assert(head==next && !tail && live==1);
 assert(top.stats_drv[NSS_DRV_STATS_NSS_SKB_COUNT]==1);
 s=packet(true); assert(receive(&s,N2H_BIT_FLAG_LAST_SEGMENT)); assert(s==next && s->len==128); deliver(s);
}
static void simple_replacement(void) {
 fresh(); struct sk_buff *s=packet(true); assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT));
 s=packet(true); assert(!receive(&s,0));
 s=packet(true); assert(receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT|N2H_BIT_FLAG_LAST_SEGMENT|N2H_BIT_FLAG_INGRESS_SHAPED));
 assert(!head && !tail && live==1 && s->classified && s->len==64);
 assert(top.stats_drv[NSS_DRV_STATS_RX_SIMPLE]==1); deliver(s);
}
static void rejects_and_recovers(void) {
 fresh(); struct sk_buff *s=packet(true); s->sh.frag_list=packet(false);
 assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT)); assert(!head && !tail && !live);
 s=packet(true); assert(!receive(&s,0)); assert(!live);
 struct sk_buff *first=packet(true); s=first; assert(!receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT));
 s=packet(true); struct n2h_descriptor bad={.payload_offs=500,.payload_len=64};
 assert(!nss_core_handle_linear_skb(&ctx,&s,&head,&tail,&bad)); assert(head==first && !tail && live==1);
 s=packet(true); assert(receive(&s,N2H_BIT_FLAG_LAST_SEGMENT)); deliver(s);
 fresh(); s=packet(true); assert(receive(&s,N2H_BIT_FLAG_FIRST_SEGMENT|N2H_BIT_FLAG_LAST_SEGMENT)); deliver(s);
}
int main(void) {
 rejected_replacement(); healthy_chain(); accepted_replacement(); simple_replacement(); rejects_and_recovers();
 puts("PASS actual N2H linear RX: rejected/accepted FIRST replacements, subsequent middle/last, full-frame replacement, owner clearing, retained head count, DMA and normal chain delivery");
 return 0;
}
'''

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--drv', type=Path, required=True)
    p.add_argument('--expect-vulnerable', action='store_true')
    a = p.parse_args()
    core = (a.drv / 'nss_core.c').read_text()
    hlos = (a.drv / 'nss_hlos_if.h').read_text()
    stats = (a.drv / 'nss_drv_stats.h').read_text()
    definitions = '\n'.join(line for line in hlos.splitlines() if re.match(r'#define N2H_BIT_FLAG_(FIRST_SEGMENT|LAST_SEGMENT|INGRESS_SHAPED)\s', line)) + '\n'
    definitions += re.search(r'enum NSS_DRV_STATS\s*\{.*?\n\};', stats, re.S)[0] + '\n'
    definitions += layout.structure(hlos, 'n2h_descriptor')
    handler = extract.function(core, 'nss_core_handle_linear_skb')
    with tempfile.TemporaryDirectory(prefix='nss-n2h-sg-') as tmp:
        source = Path(tmp) / 'test.c'
        binary = Path(tmp) / 'test'
        source.write_text(SHIM + definitions + PLATFORM.split('static bool receive',1)[0] + handler + '\nstatic bool receive' + PLATFORM.split('static bool receive',1)[1] + CASES)
        subprocess.run([os.environ.get('CC','cc'), '-std=gnu11','-Wall','-Werror','-O1','-g','-fsanitize=address,undefined','-fno-pie','-no-pie',str(source),'-o',str(binary)], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        if a.expect_vulnerable:
            assert result.returncode != 0 and 'AddressSanitizer: heap-use-after-free' in result.stderr, result.stdout + result.stderr
            print('PASS baseline reproduces actual N2H heap-use-after-free on middle segment after rejected replacement')
            print(result.stderr)
        else:
            print(result.stdout, end='')
            if result.returncode:
                print(result.stderr, end='')
            result.check_returncode()
if __name__ == '__main__':
    main()
