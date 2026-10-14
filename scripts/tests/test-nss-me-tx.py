#!/usr/bin/env python3
"""Run the production packet identity and software fallback functions in C."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('control', Path(__file__).with_name('test-nss-control.py'))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <arpa/inet.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint16_t __be16;
typedef unsigned refcount_t;
typedef struct { unsigned count; } atomic64_t;
typedef int nss_tx_status_t;
#define ETH_ALEN 6
#define ETH_HLEN 14
#define ETH_P_IP 0x800
#define ETH_P_IPV6 0x86dd
#define GFP_ATOMIC 0
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define IEEE80211_TX_CTL_REQ_TX_STATUS 1
#define ATH11K_SKB_TX_STATUS 1
#define IEEE80211_SKB_CB(s) (&(s)->info)
#define ATH11K_SKB_CB(s) (&(s)->cb)
#define max_t(t,a,b) ((t)((a)>(b)?(a):(b)))
#define IS_ERR_OR_NULL(p) (!(p))
#define WARN_ON_ONCE(x) (assert(!(x)),false)
#define list_for_each_entry(p,h,m) for((p)=(h)->first;(p);(p)=(p)->next)
struct ethhdr { u8 h_dest[6],h_source[6];__be16 h_proto; } __attribute__((packed));
struct iphdr { u8 ihl:4,version:4;u8 tos;u16 tot_len,id,frag_off;u8 ttl,protocol;u16 check;u32 saddr,daddr; } __attribute__((packed));
struct ipv6hdr { u8 priority:4,version:4;u8 flow_lbl[3];u16 payload_len;u8 nexthdr,hop_limit;u8 saddr[16],daddr[16]; } __attribute__((packed));
struct sk_buff { u8 data[128];unsigned len;bool br_mcast_contract;struct {unsigned flags;} info,cb; };
struct ath11k_nss_peer_state { unsigned refs;bool retired; };
struct ath11k_peer {struct ath11k_peer *next;void *vif,*sta;bool is_authorized;u8 addr[6];unsigned refs;struct ath11k_nss_peer_state *state;};
struct list_head { struct ath11k_peer *first; };
struct ath11k_base { int base_lock; };
struct ath11k { struct ath11k_base *ab;struct list_head peers;struct {void *ctx;} nss;void *hw; };
struct ath11k_vif { struct ath11k *ar;void *vif;bool is_up;struct {int if_num;struct {bool running;} me_auto;struct {atomic64_t tx_copies,tx_copy_drop;} me;} nss; };
static unsigned lock_depth,live_skbs,copy_calls,copy_fail_at,enqueue_calls,enqueue_fail_at;
static unsigned sent;
static u8 recipients[16][6],expected_payload[122];
static bool fail_targets;
static struct ath11k_peer *deauth_on_copy;
static void spin_lock_bh(int *p) {(void)p;assert(!lock_depth);lock_depth++;}
static void spin_unlock_bh(int *p) {(void)p;assert(lock_depth==1);lock_depth--;}
static bool ether_addr_equal(const u8 *a,const u8 *b) {return !memcmp(a,b,6);}
static void ether_addr_copy(u8 *a,const u8 *b) {memcpy(a,b,6);}
static int skb_copy_bits(const struct sk_buff *s,int offset,void *out,unsigned len) {
 if(offset<0||(unsigned)offset+len>s->len)return -EFAULT;memcpy(out,s->data+offset,len);return 0;
}
static struct sk_buff *skb_copy(struct sk_buff *s,int flags) {
 (void)flags;copy_calls++;
 if(deauth_on_copy){deauth_on_copy->is_authorized=false;deauth_on_copy=NULL;}
 if(copy_fail_at==copy_calls)return NULL;
 struct sk_buff *copy=malloc(sizeof(*copy));assert(copy);*copy=*s;live_skbs++;return copy;
}
static void br_mcast_offload_packet_clear(struct sk_buff *s) {s->br_mcast_contract=false;}
static void ieee80211_free_txskb(void *hw,struct sk_buff *s) {(void)hw;assert(live_skbs);live_skbs--;free(s);}
static void *kcalloc(unsigned n,unsigned size,int flags) {(void)flags;return fail_targets?NULL:calloc(n,size);}
static void kfree(void *p) {free(p);}
static void atomic64_inc(atomic64_t *p) {p->count++;}
static int ath11k_nss_me_admit(struct ath11k_vif *v) {(void)v;assert(lock_depth);return 0;}
static struct ath11k_nss_peer_state *ath11k_nss_key_get(struct ath11k *ar,struct ath11k_peer *p) {
 (void)ar;assert(lock_depth);if(!p->state||p->state->retired)return NULL;p->state->refs++;return p->state;
}
static void ath11k_nss_key_put(struct ath11k_nss_peer_state *p) {assert(p->refs>1);p->refs--;}
static int ath11k_nss_key_check(struct ath11k *ar,struct ath11k_peer *p,struct ath11k_nss_peer_state *s) {
 (void)ar;assert(lock_depth);return p->state==s&&!s->retired?0:-ENOENT;
}
static void ath11k_peer_get(struct ath11k_peer *p) {assert(lock_depth);p->refs++;}
static void ath11k_peer_put(struct ath11k *ar,struct ath11k_peer *p) {(void)ar;assert(p->refs>1);p->refs--;}
static int nss_wifi_vdev_tx_buf(void *ctx,struct sk_buff *s,int if_num) {
 (void)ctx;assert(lock_depth&&if_num==31&&!s->br_mcast_contract);
 assert(!(s->info.flags&1)&&!(s->cb.flags&1));
 assert(!memcmp(s->data+6,expected_payload,s->len-6));
 enqueue_calls++;if(enqueue_calls==enqueue_fail_at)return NSS_TX_FAILURE;
 assert(sent<16);memcpy(recipients[sent++],s->data,6);ieee80211_free_txskb(NULL,s);return NSS_TX_SUCCESS;
}
'''

TEST = r'''
static struct ath11k_base ab;
static struct ath11k ar;
static struct ath11k_vif vif;
static struct ath11k_peer peers[4];
static struct ath11k_nss_peer_state states[4];
static const u8 mac[4][6]={{2,0,0,0,0,1},{2,0,0,0,0,2},{2,0,0,0,0,3},{2,0,0,0,0,4}};
static struct sk_buff *fixture(void) {
 assert(!live_skbs&&!lock_depth);memset(&ar,0,sizeof(ar));memset(&vif,0,sizeof(vif));
 memset(peers,0,sizeof(peers));memset(states,0,sizeof(states));
 ar.ab=&ab;ar.peers.first=peers;vif.ar=&ar;vif.vif=&vif;vif.is_up=true;vif.nss.if_num=31;vif.nss.me_auto.running=true;
 for(unsigned i=0;i<4;i++){peers[i].next=i<3?&peers[i+1]:NULL;peers[i].vif=vif.vif;peers[i].sta=&peers[i];peers[i].is_authorized=i!=2;peers[i].refs=1;states[i].refs=1;peers[i].state=&states[i];memcpy(peers[i].addr,mac[i],6);}
 peers[3].vif=&ar;
 copy_calls=enqueue_calls=sent=copy_fail_at=enqueue_fail_at=0;fail_targets=false;deauth_on_copy=NULL;
 struct sk_buff *s=calloc(1,sizeof(*s));assert(s);live_skbs++;s->len=64;s->br_mcast_contract=true;s->info.flags=s->cb.flags=1;
 struct ethhdr *eth=(void *)s->data;memcpy(eth->h_dest,(u8[6]){1,0,94,39,0,1},6);memcpy(eth->h_source,mac[0],6);eth->h_proto=htons(ETH_P_IP);
 struct iphdr *ip=(void *)(s->data+ETH_HLEN);ip->version=4;ip->ihl=5;ip->saddr=htonl(0xc0000201);ip->daddr=htonl(0xef270001);
 memcpy(expected_payload,s->data+6,s->len-6);return s;
}
static struct br_mcast_packet *context(struct sk_buff *s) {
 struct br_mcast_packet *p=calloc(1,sizeof(*p)+2*6);assert(p);p->action=BR_MCAST_PACKET_ORDINARY;
 struct ethhdr *eth=(void *)s->data;struct iphdr *ip=(void *)(s->data+14);
 p->proto=eth->h_proto;memcpy(p->group_da,eth->h_dest,6);memcpy(p->source_mac,eth->h_source,6);
 memcpy(p->source_ip,&ip->saddr,4);memcpy(p->group_ip,&ip->daddr,4);return p;
}
static void refs_balanced(void) {for(unsigned i=0;i<4;i++)assert(peers[i].refs==1&&states[i].refs==1);assert(!live_skbs&&!lock_depth);}
int main(void) {
 struct sk_buff *s=fixture();struct br_mcast_packet *p=context(s);
 assert(ath11k_nss_me_packet_same(s,p));s->data[0]^=1;assert(!ath11k_nss_me_packet_same(s,p));s->data[0]^=1;
 s->data[6]^=1;assert(!ath11k_nss_me_packet_same(s,p));s->data[6]^=1;
 s->data[26]^=1;assert(!ath11k_nss_me_packet_same(s,p));s->data[26]^=1;
 s->data[30]^=1;assert(!ath11k_nss_me_packet_same(s,p));s->data[30]^=1;
 s->len=15;assert(!ath11k_nss_me_packet_same(s,p));s->len=64;
 /* Native ORDINARY hairpin output includes the source STA. */
 p->flags=BR_MCAST_PACKET_INGRESS_PORT;
 assert(!ath11k_nss_me_fallback(&vif,s,p));assert(sent==2&&!memcmp(recipients[0],mac[0],6)&&!memcmp(recipients[1],mac[1],6));free(p);refs_balanced();
 s=fixture();p=context(s);p->action=BR_MCAST_PACKET_HOSTS;p->count=1;memcpy(p->mac[0],mac[1],6);
 assert(!ath11k_nss_me_fallback(&vif,s,p));assert(sent==1&&!memcmp(recipients[0],mac[1],6));free(p);refs_balanced();
 s=fixture();deauth_on_copy=&peers[1];assert(!ath11k_nss_me_fallback(&vif,s,NULL));assert(sent==1&&vif.nss.me.tx_copy_drop.count==1);refs_balanced();
 s=fixture();copy_fail_at=1;assert(!ath11k_nss_me_fallback(&vif,s,NULL));assert(sent==1&&vif.nss.me.tx_copy_drop.count==1);refs_balanced();
 s=fixture();enqueue_fail_at=1;assert(!ath11k_nss_me_fallback(&vif,s,NULL));assert(sent==1&&vif.nss.me.tx_copy_drop.count==1);refs_balanced();
 s=fixture();peers[0].sta=NULL;states[1].retired=true;assert(!ath11k_nss_me_fallback(&vif,s,NULL));assert(!sent);refs_balanced();
 s=fixture();fail_targets=true;assert(ath11k_nss_me_fallback(&vif,s,NULL)==-ENOMEM&&live_skbs==1);ieee80211_free_txskb(NULL,s);refs_balanced();
 s=fixture();vif.nss.me_auto.running=false;assert(ath11k_nss_me_fallback(&vif,s,NULL)==-ESHUTDOWN);ieee80211_free_txskb(NULL,s);refs_balanced();
 s=fixture();p=context(s);struct ethhdr *eth=(void *)s->data;eth->h_proto=htons(ETH_P_IPV6);p->proto=eth->h_proto;
 struct ipv6hdr *ip6=(void *)(s->data+14);memset(ip6,0,sizeof(*ip6));ip6->version=6;ip6->saddr[0]=0x20;ip6->saddr[15]=1;ip6->daddr[0]=0xff;ip6->daddr[1]=0x3e;ip6->daddr[15]=39;
 memcpy(p->source_ip,ip6->saddr,16);memcpy(p->group_ip,ip6->daddr,16);assert(ath11k_nss_me_packet_same(s,p));
 s->data[22]^=1;assert(!ath11k_nss_me_packet_same(s,p));s->data[22]^=1;
 s->data[38]^=1;assert(!ath11k_nss_me_packet_same(s,p));s->data[38]^=1;
 ieee80211_free_txskb(NULL,s);free(p);refs_balanced();
 puts("PASS production packet identity and NSS unicast fallback: exact/native ordinary recipients, authorization race, allocation/enqueue failures, ownership and stop gate");
 return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ath11k-source', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    args = parser.parse_args()
    me = (args.ath11k_source/'nss_me.c').read_text()
    packet = (args.kernel/'include/linux/br_mcast_packet.h').read_text()
    declarations = re.search(r'struct br_mcast_packet\s*\{[^}]*\};', packet).group()
    declarations += re.search(r'enum br_mcast_packet_action\s*\{[^}]*\};', packet).group()
    declarations += re.search(r'struct ath11k_nss_me_target\s*\{[^}]*\};', me).group()
    declarations += '\n' + '\n'.join(line for line in packet.splitlines() if line.startswith('#define BR_MCAST_PACKET_')) + '\n'
    functions = ''.join(extract.function(me, name) for name in
                        ('ath11k_nss_me_packet_same', 'ath11k_nss_me_fallback'))
    with tempfile.TemporaryDirectory(prefix='nss-me-tx-') as directory:
        source = Path(directory)/'test.c'
        binary = Path(directory)/'test'
        source.write_text(SHIM+declarations+functions+TEST)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-pie', '-no-pie', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

if __name__ == '__main__':
    main()
