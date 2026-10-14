#!/usr/bin/env python3
"""Exercise real skb extension storage ownership, including inactive-slot COW."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

def helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

extract = helper('test-nss-control.py')
layout = helper('test-nss-wifili.py')

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint16_t __be16;
typedef int gfp_t;
typedef struct { unsigned count; } refcount_t;
typedef struct { unsigned count; } atomic_t;
typedef struct { unsigned unused; } wait_queue_head_t;
#define CONFIG_BRIDGE_IGMP_SNOOPING 1
#define CONFIG_NF_CONNTRACK 1
#define IS_ENABLED(x) (x)
#define IPS_CONFIRMED_BIT 3
#define IPS_SEQ_ADJUST_BIT 6
#define ETH_ALEN 6
#define BR_MCAST_PACKET_VERSION 1
#define BR_MCAST_PACKET_MAC_MAX 64
#define BR_MCAST_PACKET_INGRESS_PORT 1
#define BR_MCAST_PACKET_LOCAL_ORIG 2
#define BR_MCAST_PACKET_ORDINARY 1
#define BR_MCAST_PACKET_HOSTS 2
#define READ_ONCE(x) (x)
#define GFP_ATOMIC 0
#define SKB_EXT_ALIGN_VALUE 8
#define SKB_EXT_CHUNKSIZEOF(x) ((sizeof(x)+7)/8)
#define EXPORT_SYMBOL(x)
#define WARN_ON_ONCE(x) assert(!(x))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
enum skb_ext_id { OTHER_EXT, SKB_EXT_BR_MCAST_PACKET, SKB_EXT_NUM };
struct skb_ext { refcount_t refcnt; u8 offset[SKB_EXT_NUM],chunks;
 char data[] __attribute__((aligned(8))); };
struct nf_conn { unsigned long status;void *help; };
enum ip_conntrack_info { CTINFO_TEST };
struct sk_buff { u8 active_extensions; struct skb_ext *extensions;
 bool slow_gro,br_mcast_contract,gso;struct nf_conn *ct; };
static struct nf_conn *nf_ct_get(const struct sk_buff *s,enum ip_conntrack_info *info) { *info=CTINFO_TEST;return s->ct; }
static bool test_bit(unsigned bit,const unsigned long *value) { return !!(*value&(1UL<<bit)); }
static bool nf_ct_is_confirmed(struct nf_conn *ct) { return test_bit(IPS_CONFIRMED_BIT,&ct->status); }
static void *nfct_help(struct nf_conn *ct) { return ct->help; }
static bool skb_is_gso(const struct sk_buff *s) { return s->gso; }
struct nf_hook_ops { int hook_ops_type; };
struct nf_hook_entries { unsigned num_hook_entries;struct nf_hook_ops *ops[4]; };
static struct nf_hook_ops **nf_hook_entries_get_hook_ops(const struct nf_hook_entries *e) { return (struct nf_hook_ops **)e->ops; }
static int skbuff_ext_cache;
static unsigned stores,packets,frees;
static unsigned flights,flight_frees,wakes;
static void *flight_alloc;
static bool fail_alloc;
static void refcount_set(refcount_t *r,unsigned n) { r->count=n; }
static unsigned refcount_read(const refcount_t *r) { return r->count; }
static void refcount_inc(refcount_t *r) { assert(r->count); r->count++; }
static bool refcount_dec_and_test(refcount_t *r) { assert(r->count); return !--r->count; }
static void atomic_inc(atomic_t *r) { r->count++; }
static bool atomic_dec_and_test(atomic_t *r) { assert(r->count); return !--r->count; }
static void wake_up_all(wait_queue_head_t *q) { (void)q;wakes++; }
static void *kmem_cache_alloc(int cache,int flags) {
 (void)cache;(void)flags;if(fail_alloc)return NULL;
 void *p=malloc(2048);assert(p);memset(p,0xa5,2048);stores++;return p;
}
static void kmem_cache_free(int cache,void *p) {
 (void)cache;assert(stores);stores--;free(p);
}
static void kfree(void *p) {
 if(p==flight_alloc){assert(flights);flights--;flight_frees++;flight_alloc=NULL;}
 else {assert(p && packets);packets--;frees++;}
 free(p);
}
void __skb_ext_put(struct skb_ext *ext);
static inline void skb_ext_put(struct sk_buff *skb);
static inline bool __skb_ext_exist(const struct skb_ext *e,enum skb_ext_id id) { return !!e->offset[id]; }
static inline bool skb_ext_exist(const struct sk_buff *s,enum skb_ext_id id) { return s->active_extensions & (1<<id); }
struct net_bridge_port;
struct net_device { int ifindex; struct net_bridge_port *port; };
struct net_bridge { struct net_device *dev; };
struct net_bridge_port { struct net_bridge *br; u64 mcast_packet_cookie; };
static int rcu_depth;
static void rcu_read_lock(void) { rcu_depth++; }
static void rcu_read_unlock(void) { assert(rcu_depth);rcu_depth--; }
static struct net_bridge_port *br_port_get_rcu(struct net_device *dev) { assert(rcu_depth);return dev->port; }
'''

CASES = r'''
static struct br_mcast_packet *packet(void) {
 struct br_mcast_packet *p=calloc(1,sizeof(*p)+ETH_ALEN);assert(p);
 packets++;refcount_set(&p->refs,1);p->count=1;return p;
}
static void release(struct sk_buff *s) {
 skb_ext_put(s);s->active_extensions=0;s->extensions=NULL;
}
static void clone(struct sk_buff *dst,const struct sk_buff *src) {
 memset(dst,0,sizeof(*dst));__skb_ext_copy(dst,src);
}
static void inactive_cow(void) {
 struct sk_buff a={0},b={0};struct br_mcast_packet *p=packet();
 assert(skb_ext_add(&a,OTHER_EXT));
 assert(br_mcast_packet_install(&a,p));assert(p->refs.count==1);
 clone(&b,&a);assert(a.extensions==b.extensions && b.br_mcast_contract);
 __skb_ext_del(&b,SKB_EXT_BR_MCAST_PACKET);
 assert(b.active_extensions==(1<<OTHER_EXT) && p->refs.count==1);
 assert(skb_ext_add(&b,OTHER_EXT));
 assert(b.extensions!=a.extensions && p->refs.count==2);
 release(&a);assert(p->refs.count==1);
 struct br_mcast_packet *q=packet();
 assert(br_mcast_packet_install(&b,q));assert(packets==1 && q->refs.count==1);
 release(&b);assert(!stores && !packets);
}
static void cow_failure(void) {
 struct sk_buff a={0},b={0};struct br_mcast_packet *p=packet(),*q=packet();
 assert(br_mcast_packet_install(&a,p));clone(&b,&a);
 fail_alloc=true;assert(!br_mcast_packet_install(&b,q));fail_alloc=false;
 assert(a.extensions==b.extensions && p->refs.count==1 && q->refs.count==1);
 br_mcast_packet_put(q);release(&a);release(&b);assert(!stores && !packets);
}
static void initial_failure(void) {
 struct sk_buff s={0};struct br_mcast_packet *p=packet();
 fail_alloc=true;assert(!br_mcast_packet_install(&s,p));fail_alloc=false;
 assert(!s.active_extensions && !s.br_mcast_contract && p->refs.count==1);
 br_mcast_packet_put(p);assert(!stores && !packets);
}
static void scrub_and_fragment(void) {
 struct sk_buff a={0},fragment={0},scrubbed={0};
 assert(br_mcast_packet_install(&a,packet()));
 clone(&fragment,&a);release(&a);assert(fragment.br_mcast_contract && packets==1);
 release(&fragment);assert(fragment.br_mcast_contract && !packets);
 clone(&scrubbed,&fragment);
 assert(scrubbed.br_mcast_contract && !scrubbed.active_extensions);
}
static void empty_set(void) {
 struct sk_buff s={0};struct skb_ext *e=__skb_ext_alloc(0);assert(e);
 struct br_mcast_packet_ext *slot=__skb_ext_set(&s,SKB_EXT_BR_MCAST_PACKET,e);
 assert(!slot->packet && !slot->flight);release(&s);assert(!stores && !packets);
}
static void flight_lifetime(void) {
 struct sk_buff a={0},b={0};
 struct br_mcast_flight *f=calloc(1,sizeof(*f));assert(f);
 flight_alloc=f;flights++;refcount_set(&f->refs,1);
 assert(skb_ext_add(&a,OTHER_EXT));
 struct br_mcast_packet_ext *slot=skb_ext_add(&a,SKB_EXT_BR_MCAST_PACKET);
 assert(slot && !slot->flight);br_mcast_flight_hold(f);slot->flight=f;
 assert(f->pending.count==1 && f->refs.count==2);
 clone(&b,&a);assert(f->pending.count==1);
 __skb_ext_del(&b,SKB_EXT_BR_MCAST_PACKET);
 fail_alloc=true;assert(!skb_ext_add(&b,OTHER_EXT));fail_alloc=false;
 assert(f->pending.count==1 && a.extensions==b.extensions);
 assert(skb_ext_add(&b,OTHER_EXT));assert(f->pending.count==2);
 release(&a);assert(f->pending.count==1 && !wakes);
 br_mcast_flight_put(f);assert(flights && f->refs.count==1);
 release(&b);assert(!flights && flight_frees==1 && wakes==1 && !stores);
}
static void packet_identity(void) {
 struct net_device bridge={.ifindex=7},dev={.ifindex=3};
 struct net_bridge br={.dev=&bridge};
 struct net_bridge_port port={.br=&br,.mcast_packet_cookie=11};dev.port=&port;
 struct sk_buff s={0},lost={.br_mcast_contract=true};
 const struct br_mcast_packet *found=(void *)1;
 assert(!br_mcast_offload_packet_get(&dev,&s,&found) && !found);
 assert(br_mcast_offload_packet_get(&dev,&lost,&found)==-ENODATA && !found);
 struct br_mcast_packet *p=packet();p->version=1;p->action=BR_MCAST_PACKET_HOSTS;
 p->port_cookie=11;p->bridge_ifindex=7;p->port_ifindex=3;
 assert(br_mcast_packet_install(&s,p));
 assert(br_mcast_offload_packet_get(&dev,&s,&found)==1 && found==p);
 port.mcast_packet_cookie=12;
 assert(br_mcast_offload_packet_get(&dev,&s,&found)==-ESTALE && !found);
 port.mcast_packet_cookie=11;p->count=65;
 assert(br_mcast_offload_packet_get(&dev,&s,&found)==-EPROTO);
 p->count=0;p->action=BR_MCAST_PACKET_ORDINARY;
 assert(br_mcast_offload_packet_get(&dev,&s,&found)==1);
 s.br_mcast_contract=false;
 assert(br_mcast_offload_packet_get(&dev,&s,&found)==-EPROTO);
 release(&s);assert(!rcu_depth && !stores && !packets);
}
static void conntrack_guards(void) {
 struct sk_buff s={0};struct nf_conn ct={0};
 assert(br_mcast_packet_nf_safe(&s));s.gso=true;assert(!br_mcast_packet_nf_safe(&s));s.gso=false;
 s.ct=&ct;assert(!br_mcast_packet_nf_safe(&s));ct.status=1UL<<IPS_CONFIRMED_BIT;
 assert(br_mcast_packet_nf_safe(&s));ct.help=&ct;assert(!br_mcast_packet_nf_safe(&s));ct.help=NULL;
 ct.status|=1UL<<IPS_SEQ_ADJUST_BIT;assert(!br_mcast_packet_nf_safe(&s));
 struct nf_hook_ops a={.hook_ops_type=NF_HOOK_OP_BRIDGE_CT_GUARDED},b={.hook_ops_type=NF_HOOK_OP_NF_TABLES};
 struct nf_hook_entries e={.num_hook_entries=1,.ops={&a,&b}};
 assert(br_mcast_offload_ct_only_hooks(NULL)&&br_mcast_offload_ct_only_hooks(&e));
 e.num_hook_entries=2;assert(!br_mcast_offload_ct_only_hooks(&e));b.hook_ops_type=NF_HOOK_OP_BPF;assert(!br_mcast_offload_ct_only_hooks(&e));
 b.hook_ops_type=NF_HOOK_OP_UNDEFINED;assert(!br_mcast_offload_ct_only_hooks(&e));
 b.hook_ops_type=NF_HOOK_OP_BRIDGE_CT_GUARDED;assert(br_mcast_offload_ct_only_hooks(&e));
 b.hook_ops_type=NF_HOOK_OP_BRIDGE_AP_MCAST_CONTRACT;assert(br_mcast_offload_ct_only_hooks(&e));
 e.ops[1]=NULL;assert(!br_mcast_offload_ct_only_hooks(&e));
}
int main(void) {
 conntrack_guards();flight_lifetime();inactive_cow();cow_failure();initial_failure();scrub_and_fragment();empty_set();packet_identity();
 assert(frees==7);
 puts("PASS actual skb storage/COW, ownership/flight lifetime and guarded conntrack hooks; reject helpers, seq adjustment, unconfirmed CT, GSO and nft/BPF hooks");
 return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    args = parser.parse_args()
    core = (args.kernel/'net/core/skbuff.c').read_text()
    skb = (args.kernel/'include/linux/skbuff.h').read_text()
    packet = (args.kernel/'include/linux/br_mcast_packet.h').read_text()
    netfilter = (args.kernel/'include/linux/netfilter.h').read_text()
    forward = (args.kernel/'net/bridge/br_forward.c').read_text()
    mdb = (args.kernel/'net/bridge/br_mdb.c').read_text()
    structures = (layout.structure(packet, 'br_mcast_packet') + layout.structure(packet, 'br_mcast_flight') +
                  layout.structure(packet, 'br_mcast_packet_ext') +
                  '\nstatic const u8 skb_ext_type_len[]={1,SKB_EXT_CHUNKSIZEOF(struct br_mcast_packet_ext)};\n')
    import re
    structures += re.search(r'enum nf_hook_ops_type\s*\{[^}]*\};',netfilter).group()
    functions = ''.join(extract.function(packet, name) for name in
                        ('br_mcast_packet_get', 'br_mcast_packet_put',
                         'br_mcast_flight_put', 'br_mcast_flight_hold', 'br_mcast_flight_drop'))
    functions += extract.function(core, 'skb_ext_get_ptr')
    functions += extract.function(core, '__skb_ext_put')
    functions += ''.join(extract.function(core, name) for name in
                        ('__skb_ext_alloc','skb_ext_maybe_cow','__skb_ext_set',
                         'skb_ext_add','__skb_ext_del'))
    functions += extract.function(skb, 'skb_ext_put')
    functions += extract.function(skb, '__skb_ext_copy')
    functions += extract.function(skb, 'skb_ext_find')
    functions += extract.function(forward, 'br_mcast_packet_install')
    functions += extract.function(mdb, 'br_mcast_offload_packet_get')
    functions += extract.function(forward, 'br_mcast_packet_nf_safe')
    functions += extract.function(mdb, 'br_mcast_offload_ct_only_hooks')
    with tempfile.TemporaryDirectory(prefix='nss-mcast-packet-') as directory:
        cfile = Path(directory)/'test.c'
        binary = Path(directory)/'test'
        cfile.write_text(SHIM+structures+functions+CASES)
        subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Werror',
                        '-O1','-g','-fsanitize=address,undefined','-fno-pie','-no-pie',
                        str(cfile),'-o',str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

if __name__ == '__main__':
    main()
