#!/usr/bin/env python3
"""Exercise actual RX head relocation and coalescing under ASan/UBSan."""
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
typedef uint32_t u32;typedef uint16_t u16;typedef uint8_t u8;
#define GFP_ATOMIC 0
#define DP_RX_BUFFER_SIZE 2048
static bool warn_once(bool value){return value;}
#define WARN_ON_ONCE(x) warn_once(x)
#define likely(x) (x)
#define unlikely(x) (x)
#define ath11k_warn(...) ((void)0)
struct hal_rx_desc { bool first,last;u8 decap_type;unsigned char marker[61]; };
struct ath11k_skb_rxcb { struct hal_rx_desc *rx_desc;bool is_first_msdu,is_last_msdu,is_continuation; };
struct sk_buff { u8 *head,*data,*tail,*end;unsigned len;struct ath11k_skb_rxcb cb;struct sk_buff *next; };
struct sk_buff_head { struct sk_buff *first; };
struct ath11k_base { struct { u32 hal_desc_sz; } hw_params;struct {unsigned invalid_rbm;} soc_stats; };
struct ath11k { struct ath11k_base *ab; };
struct ieee80211_hdr {u16 frame_control;} __attribute__((packed));
struct ieee80211_rx_status {unsigned unused;};
static unsigned ieee80211_hdrlen(u16 fc){return fc==0x88?26:24;}
static u8 ath11k_dp_rx_h_msdu_start_decap_type(struct ath11k_base *ab,struct hal_rx_desc *d){(void)ab;return d->decap_type;}
#define ATH11K_SKB_RXCB(s) (&(s)->cb)
static unsigned expansions,frees;
static bool fail_expand;
static u8 *skb_tail_pointer(struct sk_buff *s) { return s->tail; }
static unsigned skb_tailroom(struct sk_buff *s) { return s->end-s->tail; }
static void *skb_put(struct sk_buff *s,unsigned n) {
 assert(n<=skb_tailroom(s));void *p=s->tail;s->tail+=n;s->len+=n;return p;
}
static void *skb_pull(struct sk_buff *s,unsigned n) {
 assert(n<=s->len);s->data+=n;s->len-=n;return s->data;
}
static int pskb_expand_head(struct sk_buff *s,int nh,int nt,int gfp) {
 expansions++;if(fail_expand)return -ENOMEM;
 assert(nh>=0&&nt>=0);
 unsigned n=s->end-s->head;
 u8 *head=malloc(n+nh+nt);
 memcpy(head+nh,s->head,s->tail-s->head);
 s->data=head+nh+(s->data-s->head);s->tail=head+nh+(s->tail-s->head);
 free(s->head);s->head=head;s->end=head+n+nh+nt;return 0;
}
static struct sk_buff *alloc_skb(void) {
 struct sk_buff *s=calloc(1,sizeof(*s));
 s->head=calloc(1,DP_RX_BUFFER_SIZE);s->data=s->tail=s->head;s->end=s->head+DP_RX_BUFFER_SIZE;
 s->cb.rx_desc=(void*)s->head;return s;
}
static void dev_kfree_skb_any(struct sk_buff *s) { frees++;free(s->head);free(s); }
static struct sk_buff *__skb_dequeue(struct sk_buff_head *q) {
 struct sk_buff *s=q->first;if(s)q->first=s->next;return s;
}
static void skb_copy_from_linear_data(struct sk_buff *s,void *to,unsigned n) { assert(n<=s->len);memcpy(to,s->data,n); }
static bool ath11k_dp_rx_h_msdu_end_first_msdu(struct ath11k_base *a,struct hal_rx_desc *d) { return d->first; }
static bool ath11k_dp_rx_h_msdu_end_last_msdu(struct ath11k_base *a,struct hal_rx_desc *d) { return d->last; }
static void ath11k_dp_rx_desc_end_tlv_copy(struct ath11k_base *a,struct hal_rx_desc *to,struct hal_rx_desc *from) {
 memcpy(to,from,a->hw_params.hal_desc_sz);
}
static unsigned mpdu_calls;
static int ath11k_dp_rx_h_mpdu(struct ath11k *ar,struct sk_buff *s,struct hal_rx_desc *d,struct ieee80211_rx_status *status,bool *fast,bool nss){
 (void)ar;(void)status;(void)fast;(void)nss;assert(d==s->cb.rx_desc&&d==(void*)s->head);mpdu_calls++;return 0;
}
'''
TEST = r'''
int main(void) {
 struct sk_buff *s=alloc_skb();memset(s->head+8,0x5a,64);
 skb_put(s,256);skb_pull(s,128);
 struct hal_rx_desc *desc=(void*)(s->head+8);
 assert(!ath11k_dp_rx_expand_head(s,72,24,&desc,64));
 assert((u8*)desc==s->head+80&&desc->marker[10]==0x5a);
 unsigned before=expansions;
 desc=(void*)(s->tail-8);
 assert(ath11k_dp_rx_expand_head(s,1,0,&desc,64)==-EINVAL&&expansions==before);
 desc=(void*)(s->head+80);void *old=desc;fail_expand=true;
 assert(ath11k_dp_rx_expand_head(s,1,0,&desc,64)==-ENOMEM&&desc==old);
 fail_expand=false;
 /* ONLY_MONITOR has no RX descriptor/control-block ownership. */
 assert(!ath11k_dp_rx_expand_head(s,1,0,NULL,0));
 dev_kfree_skb_any(s);
 struct ath11k_base ab={.hw_params={64}};struct ath11k ar={&ab};
 struct sk_buff *first=alloc_skb(),*last=alloc_skb();
 last->cb.rx_desc->first=true;last->cb.rx_desc->last=true;
 memset(last->head+64,0xa7,69);
 struct sk_buff_head q={last};
 assert(!ath11k_dp_rx_msdu_coalesce(&ar,&q,first,last,3,2050));
 assert(first->len==2050&&!q.first&&first->cb.rx_desc==(void*)first->head);
 assert(first->cb.rx_desc->last&&first->cb.is_last_msdu&&first->data[2049]==0xa7);
 dev_kfree_skb_any(first);
 #ifdef HAVE_NATIVE_WIFI_GUARD
 first=alloc_skb();last=alloc_skb();q.first=last;before=expansions;
 last->cb.rx_desc->first=last->cb.rx_desc->last=true;
 last->cb.rx_desc->decap_type=DP_RX_DECAP_TYPE_NATIVE_WIFI;
 assert(!continuation_guard(&ar,&q,first,last));
 assert(expansions==before+1&&mpdu_calls==1&&!q.first);
 dev_kfree_skb_any(first);
 #endif
 first=alloc_skb();last=alloc_skb();q.first=last;fail_expand=true;before=frees;
 assert(ath11k_dp_rx_msdu_coalesce(&ar,&q,first,last,3,2050)==-ENOMEM);
 assert(!q.first&&frees==before+1);
 dev_kfree_skb_any(first);
 puts("PASS actual RX relocation/coalesce: moved head/tail descriptors, short geometry, allocation failure, monitor CB and unique buffer ownership");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    parser.add_argument('--draft', type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source_path = (args.draft or args.backports) / 'drivers/net/wireless/ath/ath11k/dp_rx.c'
    source = source_path.read_text()
    functions = ''.join(helper.function(source, name) for name in
                        ('ath11k_dp_rx_expand_head', 'ath11k_dp_rx_msdu_coalesce'))
    if 'ath11k_dp_rx_check_nwifi_hdr_len_valid(' in source:
        header = (args.backports / 'drivers/net/wireless/ath/ath11k/dp_rx.h').read_text()
        functions += '\n#define HAVE_NATIVE_WIFI_GUARD 1\n'
        functions += re.search(r'enum dp_rx_decap_type\s*\{.*?\};', header, re.S)[0] + '\n'
        functions += re.search(r'(?m)^#define DP_MAX_NWIFI_HDR_LEN[^\n]*', header)[0] + '\n'
        functions += helper.function(source, 'ath11k_dp_rx_check_nwifi_hdr_len_valid')
        process = helper.function(source, 'ath11k_dp_rx_process_msdu')
        guard = process.index('if (unlikely(!ath11k_dp_rx_check_nwifi_hdr_len_valid')
        start = process.rfind('\n\t}', 0, guard) + len('\n\t}')
        end = process.index('\n\tif (ret)\n\t\treturn ret;', guard)
        functions += '''
static int continuation_guard(struct ath11k *ar,struct sk_buff_head *msdu_list,struct sk_buff *msdu,struct sk_buff *last_buf){
 struct ath11k_base *ab=ar->ab;struct hal_rx_desc *rx_desc=msdu->cb.rx_desc;
 struct ieee80211_rx_status status={0},*rx_status=&status;bool fast=false,*fast_rx=&fast;
 int ret=ath11k_dp_rx_msdu_coalesce(ar,msdu_list,msdu,last_buf,3,2050);if(ret)return ret;
''' + process[start:end] + '\nfree_out:return ret;\n}\n'
    with tempfile.TemporaryDirectory(prefix='nss-rx-relocation-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(SHIM + functions + TEST)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=15)


if __name__ == '__main__':
    main()
