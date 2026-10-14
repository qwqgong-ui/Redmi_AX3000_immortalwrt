#!/usr/bin/env python3
"""Test the prepared bridge's real MDB snapshots, keys and forwarding bodies."""
import argparse
import importlib.util
import os
import re
from pathlib import Path
import subprocess
import tempfile

helper = importlib.util.spec_from_file_location('nss_mcast_test',
                    Path(__file__).with_name('test-nss-multicast.py'))
module = importlib.util.module_from_spec(helper)
helper.loader.exec_module(module)
function = module.function

SHIM = r'''
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint16_t u16, __be16;
typedef uint8_t u8;
typedef uint32_t __be32;
typedef uint64_t atomic64_t;
#undef htons
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#define htons(v) __builtin_bswap16((u16)(v))
#else
#define htons(v) ((u16)(v))
#endif
#define __rcu
#define IS_ENABLED(x) 1
#define CONFIG_BRIDGE_VLAN_FILTERING 1
#define ETH_ALEN 6
#define ETH_P_IP 0x0800
#define ETH_P_IPV6 0x86dd
#define BIT(i) (1U << (i))
#define BR_MULTICAST_TO_UNICAST BIT(12)
#define BR_STATE_FORWARDING 3
#define BROPT_MULTICAST_ENABLED 0
#define BROPT_MCAST_VLAN_SNOOPING_ENABLED 1
#define BROPT_HAS_IPV6_ADDR 2
#define IFF_ALLMULTI 0x200
#define GFP_ATOMIC 0
#define kmalloc_array(n,s,f) calloc((n),(s))
#define kfree(p) free(p)
#define MDB_PG_FLAGS_PERMANENT BIT(0)
#define MDB_PG_FLAGS_STAR_EXCL BIT(3)
#define MDB_PG_FLAGS_BLOCKED BIT(4)
#define RTPROT_KERNEL 2
#define RTPROT_STATIC 4
#define BR_MCAST_OFFLOAD_HOST_SPECIFIC BIT(0)
#define BR_MCAST_OFFLOAD_PERMANENT BIT(1)
#define BR_MCAST_OFFLOAD_STAR_EXCL BIT(2)
#define BR_MCAST_OFFLOAD_BLOCKED BIT(3)
#define RTM_NEWMDB 84
#define EXPORT_SYMBOL_GPL(x)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define rcu_dereference(x) (x)
#define mlock_dereference(x,b) (x)
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct hlist_node { struct hlist_node *next; bool hashed; };
struct hlist_head { struct hlist_node *first; };
#define hlist_entry(p,t,m) container_of(p,t,m)
#define hlist_first_rcu(h) ((h)->first)
#define hlist_next_rcu(n) ((n)->next)
#define hlist_unhashed(n) (!(n)->hashed)
#define hlist_for_each_entry(p,h,m) \
    for ((p)=(h)->first ? container_of((h)->first,__typeof__(*(p)),m):NULL; \
         (p); (p)=(p)->m.next ? container_of((p)->m.next,__typeof__(*(p)),m):NULL)
struct net_bridge_port;
struct list_head { struct net_bridge_port *first, *next; };
#define list_for_each_entry_rcu(p,h,m) \
    for ((p)=(h)->first; (p); (p)=(p)->m.next)
struct br_ip {
    union { __be32 ip4; struct in6_addr ip6; } src;
    union { __be32 ip4; struct in6_addr ip6; u8 mac_addr[6]; } dst;
    __be16 proto; u16 vid;
};
struct net_bridge;
struct net_device { int ifindex; unsigned int flags; bool master; void *priv; struct net_bridge_port *port; };
struct net_bridge_mcast_port {
    struct net_bridge_port *port;
    struct hlist_node ip4_rlist, ip6_rlist;
};
struct net_bridge_port {
    struct net_bridge *br; struct net_device *dev;
    unsigned long flags; u8 state; bool mcast_hw_to_unicast;
    struct hlist_head mglist; struct net_bridge_mcast_port multicast_ctx;
    struct list_head list;
};
struct net_bridge_port_group_sg_key {
    struct net_bridge_port *port; struct br_ip addr; u8 host_mac[6];
};
struct timer_list { bool pending; };
#define timer_pending(t) ((t)->pending)
struct net_bridge_group_src { struct br_ip addr; struct timer_list timer; struct hlist_node node; };
struct net_bridge_port_group {
    struct net_bridge_port_group_sg_key key;
    struct net_bridge_port_group *next;
    u8 eth_addr[6], flags, filter_mode, rt_protocol; bool host_specific;
    struct hlist_head src_list; struct hlist_node mglist;
};
struct net_bridge_mdb_entry {
    struct net_bridge *br; struct br_ip addr;
    struct net_bridge_port_group *ports; bool host_joined;
    struct hlist_node mdb_node;
};
struct bridge_mcast_other_query { struct timer_list timer,delay_timer; };
struct net_bridge_mcast {
    struct net_bridge *br; bool multicast_querier,local_router;
    u8 multicast_igmp_version,multicast_mld_version;
    struct bridge_mcast_other_query ip4_other_query,ip6_other_query;
    struct hlist_head ip4_mc_router_list, ip6_mc_router_list;
};
struct net_bridge {
    struct net_device *dev; struct list_head port_list;
    struct net_bridge_mcast multicast_ctx;
    atomic64_t mcast_offload_seq; int multicast_lock; bool enabled,vlan_snooping,has_ipv6_addr;
    struct hlist_head mdb_list;
    void *vlgrp;
    struct net_bridge_mdb_entry *entry;
};
struct br_mdb_event {
    struct net_device *dev; __be16 proto;
    union { __be32 ip; struct in6_addr in6; } group;
    struct br_ip addr; u64 seq; int port_ifindex; u8 host_mac[6]; bool host_specific;
};
struct br_mcast_offload_source { struct br_ip addr; bool blocked; };
struct br_mcast_offload_member {
    struct br_ip addr; u8 host_mac[6],filter_mode,flags;
    u32 source_offset,source_count;
};
struct br_mcast_offload_snapshot {
    u64 seq; u32 member_count,source_count; int bridge_ifindex;
    bool snooping,router_ipv4,router_ipv6,vlan_snooping;
};
struct br_mdb_entry { u16 vid; };
struct notifier_block { int (*notifier_call)(struct notifier_block *,unsigned long,void *); };
struct notifier_chain { struct notifier_block *nb; };
#define ATOMIC_NOTIFIER_HEAD(n) struct notifier_chain n
static int atomic_notifier_chain_register(struct notifier_chain *c,struct notifier_block *n) { c->nb=n; return 0; }
static int atomic_notifier_chain_unregister(struct notifier_chain *c,struct notifier_block *n) { assert(c->nb==n);c->nb=NULL;return 0; }
static int atomic_notifier_call_chain(struct notifier_chain *c,unsigned long e,void *d) { return c->nb ? c->nb->notifier_call(c->nb,e,d):0; }
static int rcu_depth,lock_depth;
static void rcu_read_lock(void) { rcu_depth++; }
static void rcu_read_unlock(void) { assert(rcu_depth>0);rcu_depth--; }
static void spin_lock_bh(int *p) { (void)p; assert(!lock_depth);lock_depth++; }
static void spin_unlock_bh(int *p) { (void)p;assert(lock_depth==1);lock_depth--; }
#define spin_lock spin_lock_bh
#define spin_unlock spin_unlock_bh
#define from_timer(v,t,m) container_of(t,__typeof__(*(v)),m)
static u64 atomic64_inc_return(atomic64_t *p) { return ++*p; }
static u64 atomic64_read(atomic64_t *p) { return *p; }
static bool br_opt_get(struct net_bridge *b,int opt) { return opt==BROPT_MULTICAST_ENABLED?b->enabled:opt==BROPT_HAS_IPV6_ADDR?b->has_ipv6_addr:b->vlan_snooping; }
static struct net_bridge_port *br_port_get_rcu(struct net_device *d) { assert(rcu_depth);return d->port; }
static void *netdev_priv(struct net_device *d) { return d->priv; }
static bool netif_is_bridge_master(struct net_device *d) { return d->master; }
static void ether_addr_copy(u8 *d,const u8 *s) { memcpy(d,s,6); }
static bool ether_addr_equal(const u8 *a,const u8 *b) { return !memcmp(a,b,6); }
static bool is_valid_ether_addr(const u8 *a) { return !(a[0]&1) && memcmp(a,(u8[6]){0},6); }
static bool br_multicast_is_star_g(const struct br_ip *a) { return !memcmp(&a->src,(u8[16]){0},16); }
struct net_bridge_vlan { struct net_bridge_mcast br_mcast_ctx; };
static struct net_bridge_vlan *br_vlan_find(void *vg,u16 vid) { (void)vg;(void)vid;assert(rcu_depth&&lock_depth);return NULL; }
static bool br_multicast_ctx_vlan_global_disabled(struct net_bridge_mcast *c) { (void)c;return false; }
struct ethhdr { __be16 h_proto; };
static bool br_group_is_l2(const struct br_ip *a) { return !a->proto; }
#define lockdep_assert_held(p) assert(lock_depth==1)
static struct net_bridge_mdb_entry *br_mdb_ip_get(struct net_bridge *b,struct br_ip *a) { assert(lock_depth);return b->entry&&!memcmp(&b->entry->addr,a,sizeof(*a))?b->entry:NULL; }
struct sk_buff { __be16 protocol; };
static bool br_multicast_is_router(struct net_bridge_mcast *c,struct sk_buff *s) { (void)s;return c->local_router; }
static struct hlist_node *br_multicast_get_first_rport_node(struct net_bridge_mcast *b,struct sk_buff *s) { return s->protocol==htons(ETH_P_IPV6)?b->ip6_mc_router_list.first:b->ip4_mc_router_list.first; }
static struct net_bridge_port *br_multicast_rport_from_node_skb(struct hlist_node *n,struct sk_buff *s) { if(!n)return NULL;return s->protocol==htons(ETH_P_IPV6)?hlist_entry(n,struct net_bridge_mcast_port,ip6_rlist)->port:hlist_entry(n,struct net_bridge_mcast_port,ip4_rlist)->port; }
static int ordinary_count,unicast_count,free_count;
static u8 delivered_mac[6];
static void br_tc_skb_miss_set(struct sk_buff *s,bool v) { (void)s;(void)v; }
/* These fixtures have no committed MCU owner. Exercise the native path;
 * packet storage/output-owner validation is tested separately.
 */
static bool br_mcast_packet_hosts(struct net_bridge_port *p,
 struct net_bridge_mdb_entry *m,struct sk_buff *s,bool o,bool include) {
 (void)p;(void)m;(void)s;(void)o;(void)include;return false;
}
static void maybe_deliver_addr(struct net_bridge_port *p,struct sk_buff *s,const u8 *a,bool o) { (void)p;(void)s;(void)o;unicast_count++;ether_addr_copy(delivered_mac,a); }
static struct net_bridge_port *maybe_deliver(struct net_bridge_port *prev,struct net_bridge_port *p,struct sk_buff *s,bool o) { (void)s;(void)o;if(prev==p)return prev;if(prev)ordinary_count++;return p; }
static void deliver_clone(struct net_bridge_port *p,struct sk_buff *s,bool o) { (void)p;(void)s;(void)o;ordinary_count++; }
static void __br_forward(struct net_bridge_port *p,struct sk_buff *s,bool o) { deliver_clone(p,s,o); }
static void kfree_skb(struct sk_buff *s) { (void)s;free_count++; }
'''

TEST = r'''
static struct net_device master,dev[2];
static struct net_bridge br;
static struct net_bridge_port ports[2];
static struct net_bridge_port_group pg[3];
static struct net_bridge_group_src src[2];
static struct net_bridge_mdb_entry mp,foreign;
static const u8 mac0[6]={2,0,0,0,0,1},mac1[6]={2,0,0,0,0,2};
static int event_count;
static struct br_mdb_event last_event;
static void fixture(bool ipv6) {
    memset(&br,0,sizeof(br));memset(ports,0,sizeof(ports));memset(pg,0,sizeof(pg));memset(src,0,sizeof(src));memset(&mp,0,sizeof(mp));
    master=(struct net_device){.ifindex=1,.master=true,.priv=&br};br.dev=&master;br.enabled=true;br.has_ipv6_addr=true;br.mcast_offload_seq=7;br.entry=&mp;br.multicast_ctx.br=&br;br.multicast_ctx.multicast_querier=true;br.multicast_ctx.multicast_igmp_version=2;br.multicast_ctx.multicast_mld_version=1;
    for(int i=0;i<2;i++) { dev[i]=(struct net_device){.ifindex=10+i,.port=&ports[i]};ports[i].br=&br;ports[i].dev=&dev[i];ports[i].state=3;ports[i].multicast_ctx.port=&ports[i]; }
    br.port_list.first=&ports[1];ports[1].list.next=&ports[0];ports[1].flags=BR_MULTICAST_TO_UNICAST;
    mp.br=&br;mp.addr.proto=htons(ipv6?ETH_P_IPV6:ETH_P_IP);if(ipv6)mp.addr.dst.ip6.s6_addr[0]=0xff;else mp.addr.dst.ip4=htonl(0xefff0001);
    memset(&foreign,0,sizeof(foreign));foreign.br=&br;foreign.addr=mp.addr;foreign.addr.src.ip4=htonl(0x0a000009);
    br.mdb_list.first=&mp.mdb_node;mp.mdb_node.next=&foreign.mdb_node;
    for(int i=0;i<2;i++) { pg[i].key.port=&ports[1];pg[i].key.addr=mp.addr;pg[i].filter_mode=MCAST_EXCLUDE;pg[i].rt_protocol=RTPROT_KERNEL;pg[i].host_specific=true;ether_addr_copy(pg[i].eth_addr,i?mac1:mac0); }
    pg[0].next=&pg[1];mp.ports=&pg[0];ports[1].mglist.first=&pg[0].mglist;pg[0].mglist.next=&pg[1].mglist;
    pg[0].src_list.first=&src[0].node;src[0].node.next=&src[1].node;src[0].timer.pending=true;
    src[0].addr=mp.addr;src[0].addr.src.ip4=htonl(0x0a000001);src[1].addr=mp.addr;src[1].addr.src.ip4=htonl(0x0a000002);
    ordinary_count=unicast_count=free_count=0;event_count=0;
}
static int notify_cb(struct notifier_block *n,unsigned long type,void *data) {
    (void)n;(void)type;struct br_mdb_event *e=data;assert(rcu_depth);assert(e->dev==&master);assert(!ports[1].mcast_hw_to_unicast);last_event=*e;event_count++;return 0;
}
static struct notifier_block nb={.notifier_call=notify_cb};
static void flood(void) { struct sk_buff skb={.protocol=mp.addr.proto};rcu_read_lock();br_multicast_flood(&mp,&skb,&br.multicast_ctx,false,false);rcu_read_unlock(); }
int main(void) {
    for(int ipv6=0;ipv6<2;ipv6++) {
        struct br_mcast_offload_member members[2];struct br_mcast_offload_source sources[2];struct br_mcast_offload_snapshot info;
        struct net_bridge_port_group_sg_key k0,k1,k2;u32 dst[2]={0xfeedbeef,0xfeedbeef};u64 seq=999;
        fixture(ipv6);memset(members,0xa5,sizeof(members));memset(sources,0xa5,sizeof(sources));
        assert(br_mcast_offload_snapshot_port(&dev[1],members,1,sources,2,&info)==-E2BIG);
        assert(info.member_count==2&&info.source_count==2&&((u8 *)members)[0]==0xa5&&((u8 *)sources)[0]==0xa5);
        assert(br_mcast_offload_snapshot_port(&dev[1],members,2,sources,1,&info)==-E2BIG&&((u8 *)members)[0]==0xa5);
        assert(br_mcast_offload_snapshot_port(&dev[1],members,2,sources,2,&info)==0);
        assert(info.seq==7&&info.bridge_ifindex==1&&info.snooping);
        assert(members[0].source_count==2&&members[1].source_count==0);
        assert(!sources[0].blocked&&sources[1].blocked);
        struct br_mcast_offload_host hosts[2];struct br_ip keys[2];struct br_mcast_offload_lookup_snapshot lookup;
        memset(hosts,0xa5,sizeof(hosts));memset(keys,0xa5,sizeof(keys));
        assert(br_mcast_offload_snapshot_lookups(&dev[1],hosts,1,keys,2,&lookup)==-E2BIG);
        assert(lookup.host_count==2&&lookup.key_count==2&&((u8 *)hosts)[0]==0xa5&&((u8 *)keys)[0]==0xa5);
        assert(br_mcast_offload_snapshot_lookups(&dev[1],hosts,2,keys,1,&lookup)==-E2BIG&&((u8 *)hosts)[0]==0xa5);
        br.multicast_ctx.multicast_igmp_version=3;br.has_ipv6_addr=false;
        assert(br_mcast_offload_snapshot_lookups(&dev[1],hosts,2,keys,2,&lookup)==0);
        assert(lookup.seq==7&&lookup.bridge_ifindex==1&&lookup.snooping&&lookup.forwarding&&lookup.multicast_to_unicast);
        assert(lookup.source_filter_ipv4&&!lookup.source_filter_ipv6&&lookup.querier_ipv4&&!lookup.querier_ipv6);
        assert(!memcmp(&keys[1],&foreign.addr,sizeof(foreign.addr)));
        assert(hosts[0].flags&BR_MCAST_OFFLOAD_HOST_SPECIFIC);
        br.multicast_ctx.multicast_igmp_version=2;br.has_ipv6_addr=true;
        pg[0].filter_mode=MCAST_INCLUDE;
        assert(br_mcast_offload_snapshot_port(&dev[1],members,2,sources,2,&info)==0&&!sources[1].blocked);
        pg[0].filter_mode=MCAST_EXCLUDE;
        assert(br_mcast_offload_get_ifindexes(&master,&mp.addr,dst,2,&seq)==-EAGAIN&&dst[0]==0xfeedbeef&&seq==999);
        assert(br_mcast_offload_set_mcu(&dev[1],1,6,true)==-ESTALE);
        assert(br_mcast_offload_set_mcu(&dev[1],1,7,true)==0);
        assert(br_mcast_offload_get_ifindexes(&master,&mp.addr,dst,0,&seq)==-E2BIG&&dst[0]==0xfeedbeef);
        assert(br_mcast_offload_get_ifindexes(&master,&mp.addr,dst,2,&seq)==1&&dst[0]==11&&seq==7);
        for (int host_flags=1;host_flags<8;host_flags++) {
            mp.host_joined=host_flags&1;master.flags=(host_flags&2)?IFF_ALLMULTI:0;
            br.multicast_ctx.local_router=host_flags&4;
            dst[0]=0xfeedbeef;seq=999;
            assert(br_mcast_offload_get_ifindexes(&master,&mp.addr,dst,2,&seq)==-EOPNOTSUPP);
            assert(dst[0]==0xfeedbeef&&seq==999);
            assert(br_mcast_offload_get_routed_egress_ifindexes(&master,&mp.addr,dst,2,&seq)==1);
            assert(dst[0]==11&&seq==7);
        }
        mp.host_joined=false;master.flags=0;br.multicast_ctx.local_router=false;
        dst[0]=0xfeedbeef;seq=999;
        assert(br_mcast_offload_get_routed_egress_ifindexes(&master,&mp.addr,dst,0,&seq)==-E2BIG);
        assert(dst[0]==0xfeedbeef&&seq==999);
        br.multicast_ctx.multicast_querier=false;
        assert(br_mcast_offload_get_ifindexes(&master,&mp.addr,dst,2,&seq)==-EAGAIN);
        assert(br_mcast_offload_get_routed_egress_ifindexes(&master,&mp.addr,dst,2,&seq)==-EAGAIN);
        br.multicast_ctx.multicast_querier=true;br.entry=NULL;
        assert(br_mcast_offload_get_routed_egress_ifindexes(&master,&mp.addr,dst,2,&seq)==-ENOENT);
        br.entry=&mp;ports[1].mcast_hw_to_unicast=false;
        assert(br_mcast_offload_get_routed_egress_ifindexes(&master,&mp.addr,dst,2,&seq)==-EAGAIN);
        assert(dst[0]==0xfeedbeef&&seq==999);ports[1].mcast_hw_to_unicast=true;
        br.vlan_snooping=true;assert(br_mcast_offload_snapshot_port(&dev[1],members,2,sources,2,&info)==-EOPNOTSUPP&&info.vlan_snooping);br.vlan_snooping=false;
        assert(br_mcast_offload_mdb_register_notify(&nb)==0);
        spin_lock_bh(&br.multicast_lock);br_mcast_offload_notify(&master,&mp.addr,&pg[0],11,RTM_NEWMDB);spin_unlock_bh(&br.multicast_lock);
        assert(event_count==1&&last_event.seq==8&&last_event.proto==mp.addr.proto&&last_event.host_specific);
        assert(!memcmp(&last_event.addr,&mp.addr,sizeof(mp.addr))&&ether_addr_equal(last_event.host_mac,mac0));
        assert(br_mcast_offload_set_mcu(&dev[1],1,7,true)==-ESTALE);
        spin_lock_bh(&br.multicast_lock);br_mcast_offload_config_notify(&br);spin_unlock_bh(&br.multicast_lock);assert(last_event.proto==0&&last_event.seq==9);
        assert(br_mcast_offload_mdb_unregister_notify(&nb)==0);
        ports[1].mcast_hw_to_unicast=true;u64 previous=br.mcast_offload_seq;
        br_ip4_multicast_query_delay_expired(&br.multicast_ctx.ip4_other_query.delay_timer);
        assert(br.mcast_offload_seq==previous+1&&!ports[1].mcast_hw_to_unicast);
        ports[1].mcast_hw_to_unicast=true;
        br_ip6_multicast_query_delay_expired(&br.multicast_ctx.ip6_other_query.delay_timer);
        assert(br.mcast_offload_seq==previous+2&&!ports[1].mcast_hw_to_unicast);
        br_multicast_sg_key_init(&k0,&ports[1],&mp.addr,mac0,true);
        br_multicast_sg_key_init(&k1,&ports[1],&mp.addr,mac1,true);
        assert(memcmp(&k0,&k1,sizeof(k0))&&ether_addr_equal(k0.host_mac,mac0));
        ports[1].flags=0;br_multicast_sg_key_init(&k2,&ports[1],&mp.addr,mac0,true);
        assert(!memcmp(&k0,&k2,sizeof(k0)));
        br_multicast_sg_key_init(&k1,&ports[1],&mp.addr,mac0,false);
        br_multicast_sg_key_init(&k2,&ports[1],&mp.addr,mac1,false);
        assert(!memcmp(&k1,&k2,sizeof(k1)));
        assert(br_port_group_equal(&pg[0],&ports[1],mac0,true));
        assert(!br_port_group_equal(&pg[0],&ports[1],mac1,true));
        assert(!br_port_group_equal(&pg[0],&ports[1],mac0,false));
        fixture(ipv6);pg[1].flags=MDB_PG_FLAGS_BLOCKED;flood();
        assert(unicast_count==1&&ordinary_count==0&&ether_addr_equal(delivered_mac,mac0));
        ordinary_count=unicast_count=free_count=0;pg[0].flags=MDB_PG_FLAGS_BLOCKED;flood();assert(!unicast_count&&!ordinary_count&&free_count==1);
        fixture(ipv6);ports[1].mcast_hw_to_unicast=true;flood();assert(!ordinary_count&&unicast_count==2);
        fixture(ipv6);pg[0].filter_mode=pg[1].filter_mode=MCAST_INCLUDE;br.multicast_ctx.multicast_igmp_version=3;br.multicast_ctx.multicast_mld_version=2;flood();assert(!ordinary_count&&!unicast_count&&free_count==1);
        fixture(ipv6);pg[2]=pg[0];pg[2].host_specific=false;pg[2].rt_protocol=RTPROT_STATIC;pg[0].next=&pg[2];pg[2].next=&pg[1];flood();assert(ordinary_count==1&&!unicast_count);
        ordinary_count=unicast_count=free_count=0;pg[2].flags=MDB_PG_FLAGS_BLOCKED;flood();assert(!ordinary_count&&!unicast_count&&free_count==1);
        fixture(ipv6);pg[2]=pg[0];pg[2].host_specific=false;pg[0].next=&pg[2];pg[2].next=&pg[1];flood();assert(ordinary_count==1&&!unicast_count);
        fixture(ipv6);struct hlist_node *rnode=ipv6?&ports[1].multicast_ctx.ip6_rlist:&ports[1].multicast_ctx.ip4_rlist;rnode->hashed=true;
        if(ipv6)br.multicast_ctx.ip6_mc_router_list.first=rnode;else br.multicast_ctx.ip4_mc_router_list.first=rnode;
        flood();assert(ordinary_count==1&&!unicast_count);
        assert(rcu_depth==0&&lock_depth==0);
        printf("IPv%d MDB: capacities, sources, sequence, keys, blocked/include, aggregate/admin and router forwarding passed\n",ipv6?6:4);
    }
    return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--offload-source', type=Path)
    parser.add_argument('--multicast-source', type=Path)
    parser.add_argument('--bridge-header', type=Path)
    args = parser.parse_args()
    sources = {name: (args.kernel / 'net/bridge' / name).read_text()
               for name in ('br_private.h', 'br_mdb.c', 'br_multicast.c', 'br_forward.c')}
    if args.offload_source:
        sources['br_mdb.c'] = args.offload_source.read_text()
    if args.multicast_source:
        sources['br_multicast.c'] = args.multicast_source.read_text()
    bodies = []
    header = (args.bridge_header or args.kernel/'include/linux/if_bridge.h').read_text()
    for name in ('br_mcast_offload_host','br_mcast_offload_lookup_snapshot'):
        match = re.search(r'struct '+name+r'\s*\{[^}]*\};',header)
        if not match:
            raise ValueError('Missing complete lookup declaration: '+name)
        bodies.append(match.group())
    for name in ('__br_multicast_querier_exists','br_multicast_querier_exists',
                 'br_multicast_should_handle_mode'):
        body = function(sources['br_private.h'],name)
        if body.lstrip().startswith(name+'('):
            body = 'static inline bool '+body
        bodies.append(body)
    for name in ('br_multicast_port_static_override', 'br_multicast_pg_allowed',
                 'br_multicast_port_has_aggregate', 'br_multicast_port_allowed'):
        body = function(sources['br_private.h'], name)
        if name != 'br_multicast_pg_allowed':
            body = ('static inline struct net_bridge_port_group *' if
                    name == 'br_multicast_port_static_override' else 'static inline bool ') + body
        bodies.append(body)
    for name in ('br_port_group_equal', 'br_multicast_sg_key_init'):
        bodies.append(function(sources['br_multicast.c'], name))
    bodies.append('static ATOMIC_NOTIFIER_HEAD(br_mcast_offload_chain);')
    for name in ('br_mcast_offload_mdb_register_notify', 'br_mcast_offload_mdb_unregister_notify',
                 'br_mcast_offload_notify', 'br_mcast_offload_config_notify',
                 'br_mcast_offload_snapshot_port', 'br_mcast_offload_set_mcu',
                 'br_mcast_offload_conditions',
                 'br_mcast_offload_snapshot_lookups',
                 'br_mcast_offload_ports', 'br_mcast_offload_ifindexes',
                 'br_mcast_offload_get_ifindexes',
                 'br_mcast_offload_get_routed_egress_ifindexes'):
        bodies.append(function(sources['br_mdb.c'], name))
    for name in ('br_multicast_query_delay_expired','br_ip4_multicast_query_delay_expired',
                 'br_ip6_multicast_query_delay_expired'):
        bodies.append(function(sources['br_multicast.c'],name))
    bodies.append(function(sources['br_forward.c'], 'br_multicast_flood'))
    with tempfile.TemporaryDirectory(prefix='nss-mdb-') as directory:
        path = Path(directory) / 'mdb.c'
        path.write_text(SHIM + '\n' + '\n\n'.join(bodies) + '\n' + TEST)
        binary = path.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

if __name__ == '__main__':
    main()
