#!/usr/bin/env python3
"""Exercise actual ECM multicast ownership and request-generation functions."""
import argparse
import importlib.util
import os
import re
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('nss_mcast_test',
                         Path(__file__).with_name('test-nss-multicast.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def function(source, name):
    # A kernel-doc name followed by () is not a function definition.
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    return module.function(source, name)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t u64, atomic64_t;
typedef uintptr_t ecm_ptr_t;
typedef uint32_t ip_addr_t[4];
#define ECM_NSS_IPV6_ADDR_TO_IP_ADDR(a, b) memcpy(a, b, sizeof(ip_addr_t))
typedef int ecm_front_end_acceleration_mode_t;
#define ECM_FRONT_END_ACCELERATION_FAILED(m) ((m) >= ECM_FRONT_END_ACCELERATION_MODE_FAIL_RULE)
#define ECM_FRONT_END_ACCEL_LIMIT_MODE_FIXED 1
enum { ECM_FRONT_END_ACCELERATION_MODE_DECEL,
 ECM_FRONT_END_ACCELERATION_MODE_ACCEL_PENDING,
 ECM_FRONT_END_ACCELERATION_MODE_ACCEL,
 ECM_FRONT_END_ACCELERATION_MODE_DECEL_PENDING,
 ECM_FRONT_END_ACCELERATION_MODE_FAIL_RULE,
 ECM_FRONT_END_ACCELERATION_MODE_FAIL_DEFUNCT,
 ECM_FRONT_END_ACCELERATION_MODE_FAIL_DEFUNCT_SHORT,
 ECM_FRONT_END_ACCELERATION_MODE_FAIL_ACCEL_ENGINE,
 ECM_FRONT_END_ACCELERATION_MODE_FAIL_DECEL };
#define ECM_FRONT_END_ENGINE_NSS 1
#define ECM_MULTICAST_ENABLE 1
#define DEBUG_TRACE(...) ((void)0)
#define DEBUG_INFO(...) ((void)0)
#define DEBUG_ERROR(...) ((void)0)
#define DEBUG_CHECK_MAGIC(...) ((void)0)
#define DEBUG_ASSERT(cond, ...) assert(cond)
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_EMSG 4
#define NSS_IPV@V@_DR_NO_CONNECTION_ENTRY_ERROR 5
#define NSS_IPV@V@_TX_CREATE_MC_RULE_MSG 1
#define NSS_IPV@V@_TX_DESTROY_RULE_MSG 2
#define NSS_IPV@V@_RULE_SYNC_REASON_FLUSH 2
#define NSS_IPV@V@_RULE_SYNC_REASON_EVICT 3
struct nss_ipv@V@_conn_sync { int reason; };
struct work_struct { int unused; };
struct ecm_db_connection_instance;
struct mode_stats {
 bool flush_happened, decelerate_pending;
 uint64_t slow_path_packets;
 int ae_nack, ae_nack_total, ae_nack_limit, no_action_seen;
};
struct ecm_front_end_connection_instance {
 struct ecm_db_connection_instance *ci;
 struct mode_stats stats;
 int lock, refs, accel_mode, accel_engine;
 bool is_defunct;
 u64 multicast_generation, multicast_route_cookie, multicast_rule_generation;
 unsigned long multicast_stats_request;
 u64 multicast_stats_rule_generation, multicast_stats_route_cookie;
 void (*decelerate)(struct ecm_front_end_connection_instance *);
};
struct ecm_db_connection_instance {
 struct ecm_front_end_connection_instance *feci;
 struct ecm_db_connection_instance *next;
 int refs, serial, ip_version;
 bool multicast;
};
struct mock_tuple { uint32_t flow_ip[4], return_ip[4]; };
struct nss_ipv@V@_mc_rule_create_msg { struct mock_tuple tuple; };
struct nss_ipv@V@_rule_destroy_msg { struct mock_tuple tuple; };
struct nss_ipv@V@_msg {
 struct { int type, response, error; } cm;
 struct { struct nss_ipv@V@_mc_rule_create_msg mc_rule_create;
          struct nss_ipv@V@_rule_destroy_msg rule_destroy; } msg;
};
static int ecm_nss_ipv@V@_lock, ecm_interface_lock;
static int ecm_nss_ipv@V@_accelerated_count;
static int ecm_nss_multicast_ipv@V@_accelerated_count;
static int ecm_nss_ipv@V@_pending_accel_count, ecm_nss_ipv@V@_pending_decel_count;
static int ecm_nss_ipv@V@_decel_unknown_count;
static int ecm_front_end_ipv@V@_stopped_temp, ecm_nss_ipv@V@_accel_limit_mode;
static int atomic_read(int *value) { return *value; }
static int nss_ipv@V@_max_conn_count(void) { return 4096; }
static bool ecm_db_connection_regeneration_required_peek(struct ecm_db_connection_instance *c) { (void)c; return false; }
static atomic64_t ecm_interface_multicast_generation = 1;
static bool ecm_interface_terminate_pending;
static int ecm_interface_multicast_work, system_unbound_wq;
static int queued, cancelled, defuncts, decels;
static struct ecm_db_connection_instance ci[3];
static struct ecm_front_end_connection_instance fe[3];
static void spin_lock_bh(int *lock) { assert(!*lock); *lock=1; }
static void spin_unlock_bh(int *lock) { assert(*lock); *lock=0; }
static u64 atomic64_read(atomic64_t *a) { return *a; }
static void atomic64_inc(atomic64_t *a) { ++*a; }
#define READ_ONCE(v) (v)
static void cond_resched(void) {}
static void queue_work(int wq, int *work) { (void)wq; (void)work; queued++; }
static void cancel_work_sync(int *work) { (void)work; cancelled++; }
static void decelerate(struct ecm_front_end_connection_instance *f) {
 assert(!f->lock); decels++;
 f->accel_mode=ECM_FRONT_END_ACCELERATION_MODE_DECEL_PENDING;
}
static void ecm_db_connection_make_defunct(struct ecm_db_connection_instance *c) {
 assert(!c->feci->lock && !ecm_nss_ipv@V@_lock); defuncts++;
 c->feci->is_defunct=true;
 if(c->feci->accel_mode==ECM_FRONT_END_ACCELERATION_MODE_ACCEL)
  decelerate(c->feci);
}
static void ecm_db_connection_deref(struct ecm_db_connection_instance *c) {
 assert(c->refs>1); c->refs--;
}
static struct ecm_db_connection_instance *ecm_db_connections_get_and_ref_first(void) {
 ci[0].refs++; return &ci[0];
}
static struct ecm_db_connection_instance *ecm_db_connection_get_and_ref_next(struct ecm_db_connection_instance *c) {
 if(c->next) c->next->refs++;
 return c->next;
}
static struct ecm_db_connection_instance *ecm_db_connection_serial_find_and_ref(uint32_t serial) {
 for(int i=0;i<3;i++) if(ci[i].serial==(int)serial) { ci[i].refs++; return &ci[i]; }
 return NULL;
}
static int ecm_db_connection_ip_version_get(struct ecm_db_connection_instance *c) { return c->ip_version; }
static bool ecm_db_multicast_connection_to_interfaces_set_check(struct ecm_db_connection_instance *c) { return c->multicast; }
static struct ecm_front_end_connection_instance *ecm_db_connection_front_end_get_and_ref(struct ecm_db_connection_instance *c) {
 c->feci->refs++; return c->feci;
}
static uint64_t ecm_front_end_get_slow_packet_count(struct ecm_front_end_connection_instance *f) { return f->stats.slow_path_packets; }
typedef int ecm_tracker_sender_type_t;
#define ECM_TRACKER_SENDER_TYPE_SRC 0
#define ECM_CONN_DIR_FLOW 0
#define ECM_CONN_DIR_RETURN 1
#define IPPROTO_TCP 6
#define IPPROTO_UDP 17
struct ecm_classifier_default_internal_instance {
 int protocol;uint32_t ci_serial;bool packet_seen[2];
};
static int ecm_classifier_accel_delay_pkts=1;
static void ecm_front_end_connection_deref(struct ecm_front_end_connection_instance *f) {
 assert(f->refs>1); f->refs--;
}
static bool _ecm_nss_ipv@V@_accel_pending_clear(struct ecm_front_end_connection_instance *f, int mode) {
 assert(f->lock && ecm_nss_ipv@V@_lock);
 assert(f->accel_mode==ECM_FRONT_END_ACCELERATION_MODE_ACCEL_PENDING);
 assert(ecm_nss_ipv@V@_pending_accel_count==1);
 bool pending=f->stats.decelerate_pending;
 ecm_nss_ipv@V@_pending_accel_count--;
 f->stats.decelerate_pending=false; f->accel_mode=mode; return pending;
}
static void ecm_nss_ipv@V@_decel_done_time_update(struct ecm_front_end_connection_instance *f) { (void)f; }
static void ecm_nss_ipv@V@_accel_done_time_update(struct ecm_front_end_connection_instance *f) { (void)f; }
'''

TESTS = r'''
static void reset(void) {
 memset(ci,0,sizeof(ci)); memset(fe,0,sizeof(fe));
 ecm_interface_multicast_generation=1; ecm_interface_terminate_pending=false;
 ecm_nss_ipv@V@_lock=ecm_interface_lock=0;
 ecm_nss_ipv@V@_pending_accel_count=ecm_nss_ipv@V@_pending_decel_count=0;
 ecm_nss_ipv@V@_accelerated_count=ecm_nss_multicast_ipv@V@_accelerated_count=0;
 ecm_nss_ipv@V@_decel_unknown_count=queued=cancelled=defuncts=decels=0;
 ecm_front_end_ipv@V@_stopped_temp=ecm_nss_ipv@V@_accel_limit_mode=0;
 for(int i=0;i<3;i++) {
  ci[i].feci=&fe[i]; ci[i].refs=1; ci[i].serial=10+i;
  ci[i].ip_version=i==1?6:4; ci[i].multicast=i<2;
  ci[i].next=i<2?&ci[i+1]:NULL;
  fe[i].ci=&ci[i]; fe[i].refs=1; fe[i].accel_engine=ECM_FRONT_END_ENGINE_NSS;
  fe[i].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_ACCEL;
  fe[i].multicast_generation=1; fe[i].multicast_rule_generation=1;
  fe[i].multicast_route_cookie=100+i; fe[i].stats.ae_nack_limit=3;
  fe[i].decelerate=decelerate;
 }
 ci[0].ip_version=@V@;
}
static void balanced(void) {
 for(int i=0;i<3;i++) { assert(ci[i].refs==1 && fe[i].refs==1); assert(!fe[i].lock); }
 assert(!ecm_nss_ipv@V@_lock && !ecm_interface_lock);
}
int main(void) {
 u64 cookie;
 reset(); ecm_interface_multicast_stats_snapshot(@V@,77);
 cookie=999; assert(ecm_interface_multicast_stats_valid(&fe[0],77,&cookie) && cookie==100);
 cookie=999; assert(!ecm_interface_multicast_stats_valid(&fe[0],0,&cookie) && cookie==999);
 assert(!ecm_interface_multicast_stats_valid(&fe[0],76,&cookie));
 fe[0].multicast_rule_generation++;
 assert(!ecm_interface_multicast_stats_valid(&fe[0],77,&cookie));
 fe[0].multicast_rule_generation--;
 fe[0].is_defunct=true; assert(!ecm_interface_multicast_stats_valid(&fe[0],77,&cookie));
 fe[0].is_defunct=false;
 fe[0].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_ACCEL_PENDING;
 assert(!ecm_interface_multicast_stats_valid(&fe[0],77,&cookie));
 fe[0].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_ACCEL;
 fe[0].multicast_route_cookie++;
 assert(!ecm_interface_multicast_stats_valid(&fe[0],77,&cookie));
 fe[0].multicast_route_cookie--;
 struct nss_ipv@V@_conn_sync sync={.reason=NSS_IPV@V@_RULE_SYNC_REASON_FLUSH};
 assert(!ecm_nss_ipv@V@_multicast_sync_valid(&ci[0],&sync,0,false,&cookie));
 assert(defuncts==0);
 assert(!ecm_nss_ipv@V@_multicast_sync_valid(&ci[0],&sync,76,false,&cookie));
 assert(defuncts==0);
 ecm_interface_multicast_invalidate();
 assert(queued==1 && ecm_interface_multicast_generation==2);
 assert(!ecm_interface_multicast_stats_valid(&fe[0],77,&cookie));
 ecm_interface_multicast_invalidate_work(NULL);
 assert(defuncts==2 && !fe[2].is_defunct); balanced();
 reset(); ecm_interface_multicast_invalidate(); fe[0].multicast_generation=2;
 ecm_interface_multicast_invalidate_work(NULL);
 assert(defuncts==1 && !fe[0].is_defunct && fe[1].is_defunct); balanced();
 ecm_interface_multicast_quiesce(); ecm_interface_multicast_invalidate();
 assert(cancelled==1 && queued==1);
 reset(); fe[0].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_DECEL;
 ecm_nss_ipv@V@_decel_unknown_count=1;
 assert(!ecm_nss_ipv@V@_accel_pending_set(&fe[0]));
 assert(!ecm_nss_ipv@V@_pending_accel_count); balanced();
 fe[0].multicast_generation=0;
 assert(ecm_nss_ipv@V@_accel_pending_set(&fe[0]));
 assert(ecm_nss_ipv@V@_pending_accel_count==1);
 ecm_nss_multicast_ipv@V@_accel_abort(&fe[0],ECM_FRONT_END_ACCELERATION_MODE_DECEL); balanced();

 for(int defunct=0;defunct<2;defunct++) {
  reset(); fe[0].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_ACCEL_PENDING;
  fe[0].is_defunct=defunct; ecm_nss_ipv@V@_pending_accel_count=1;
  ecm_nss_multicast_ipv@V@_accel_abort(&fe[0],ECM_FRONT_END_ACCELERATION_MODE_FAIL_RULE);
  assert(!ecm_nss_ipv@V@_pending_accel_count);
  assert(fe[0].accel_mode==(defunct?ECM_FRONT_END_ACCELERATION_MODE_FAIL_DEFUNCT:ECM_FRONT_END_ACCELERATION_MODE_FAIL_RULE));
  assert(defuncts==defunct); balanced();
 }
 for(int kind=0;kind<5;kind++) {
  reset(); struct nss_ipv@V@_msg msg={};
  msg.cm.type=NSS_IPV@V@_TX_CREATE_MC_RULE_MSG; msg.cm.response=NSS_CMN_RESPONSE_ACK;
  fe[0].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_ACCEL_PENDING;
  ecm_nss_ipv@V@_pending_accel_count=1; ci[0].refs++;
  if(kind==1) msg.cm.response=1;
  if(kind==2) fe[0].stats.flush_happened=true;
  if(kind==3) ecm_interface_multicast_generation=2;
  if(kind==4) { msg.cm.response=1; fe[0].is_defunct=true; }
  ecm_nss_multicast_ipv@V@_connection_create_callback((void *)(uintptr_t)10,&msg);
  assert(!ecm_nss_ipv@V@_pending_accel_count); balanced();
  assert(ecm_nss_ipv@V@_accelerated_count==((kind==0||kind==3)?1:0));
  if(kind==3) { assert(decels==1 && defuncts==1); assert(fe[0].accel_mode==ECM_FRONT_END_ACCELERATION_MODE_DECEL_PENDING); }
  if(kind==4) { assert(fe[0].accel_mode==ECM_FRONT_END_ACCELERATION_MODE_FAIL_DEFUNCT); assert(defuncts==1); }
 }
 reset(); struct nss_ipv@V@_conn_sync notification={.reason=NSS_IPV@V@_RULE_SYNC_REASON_EVICT};
 assert(!ecm_nss_ipv@V@_multicast_sync_valid(&ci[0],&notification,0,true,&cookie));
 assert(defuncts==1 && decels==1); balanced();
 for(int nack=0;nack<3;nack++) {
  reset(); struct nss_ipv@V@_msg msg={};
  msg.cm.type=NSS_IPV@V@_TX_DESTROY_RULE_MSG; msg.cm.response=nack;
  if(nack==2) { msg.cm.response=NSS_CMN_RESPONSE_EMSG; msg.cm.error=NSS_IPV@V@_DR_NO_CONNECTION_ENTRY_ERROR; }
  fe[0].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_DECEL_PENDING;
  ecm_nss_ipv@V@_pending_decel_count=1;
  ecm_nss_ipv@V@_accelerated_count=ecm_nss_multicast_ipv@V@_accelerated_count=1;
  ci[0].refs++;
  ecm_nss_multicast_ipv@V@_connection_destroy_callback((void *)(uintptr_t)10,&msg);
  assert(!ecm_nss_ipv@V@_pending_decel_count && !ecm_nss_ipv@V@_accelerated_count);
  assert(ecm_nss_ipv@V@_decel_unknown_count==(nack==1)); balanced();
 }
 reset(); struct nss_ipv@V@_msg late={};
 late.cm.type=NSS_IPV@V@_TX_DESTROY_RULE_MSG; late.cm.response=1;
 fe[0].accel_mode=ECM_FRONT_END_ACCELERATION_MODE_DECEL;
 ecm_nss_ipv@V@_pending_decel_count=1; ci[0].refs++;
 ecm_nss_multicast_ipv@V@_connection_destroy_callback((void *)(uintptr_t)10,&late);
 assert(!ecm_nss_ipv@V@_pending_decel_count && !ecm_nss_ipv@V@_decel_unknown_count); balanced();
 reset();struct ecm_classifier_default_internal_instance classifier={.protocol=IPPROTO_UDP,.ci_serial=10};
 ecm_classifier_accel_delay_pkts=1;fe[0].stats.slow_path_packets=1;
 assert(!ecm_classifier_default_ready_for_accel(&classifier,ECM_TRACKER_SENDER_TYPE_SRC));
 fe[0].stats.slow_path_packets=2;
 assert(ecm_classifier_default_ready_for_accel(&classifier,ECM_TRACKER_SENDER_TYPE_SRC));
 assert(!classifier.packet_seen[0]&&!classifier.packet_seen[1]);balanced();
 ci[0].multicast=false;
 assert(!ecm_classifier_default_ready_for_accel(&classifier,ECM_TRACKER_SENDER_TYPE_SRC));
 assert(ecm_classifier_default_ready_for_accel(&classifier,1));balanced();
 memset(classifier.packet_seen,0,sizeof(classifier.packet_seen));classifier.protocol=IPPROTO_TCP;ci[0].multicast=true;
 assert(!ecm_classifier_default_ready_for_accel(&classifier,ECM_TRACKER_SENDER_TYPE_SRC));
 assert(ecm_classifier_default_ready_for_accel(&classifier,1));balanced();
 classifier.protocol=IPPROTO_UDP;classifier.ci_serial=999;
 assert(!ecm_classifier_default_ready_for_accel(&classifier,ECM_TRACKER_SENDER_TYPE_SRC));
 classifier.ci_serial=10;ecm_classifier_accel_delay_pkts=3;
 assert(!ecm_classifier_default_ready_for_accel(&classifier,ECM_TRACKER_SENDER_TYPE_SRC));
 fe[0].stats.slow_path_packets=3;
 assert(ecm_classifier_default_ready_for_accel(&classifier,ECM_TRACKER_SENDER_TYPE_SRC));balanced();
 puts("IPv@V@ ECM: stale stats, CI/rule epochs, invalidation, quiesce, CREATE/DESTROY ownership and one-way multicast admission passed");
 return 0;
}
'''


ROUTED_SHIM = r'''
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t u64;
typedef uint32_t ip_addr_t[4];
#define ECM_DB_MULTICAST_IF_MAX 16
#define ECM_IPV6_ENABLE 1
#define ETH_P_IP 0x0800
#define ETH_P_IPV6 0x86dd
#define ECM_IP_ADDR_TO_NIN6_ADDR(out,in) memcpy(&(out),(in),sizeof(out))
struct net_device { int ifindex; };
struct ecm_front_end_connection_instance { u64 multicast_route_cookie; };
struct br_ip {
 uint16_t proto;
 union { uint32_t ip4; struct in6_addr ip6; } src,dst;
};
static int init_net, mfc_count=1, l2_calls, egress_calls;
static u64 mfc_cookie=7;
static uint32_t mfc_outputs[16]={9};
static int ipmr_find_mfc_entry(int *net,uint32_t source,uint32_t group,
 uint32_t capacity,uint32_t *indices,u64 *cookie) {
 assert(net==&init_net&&capacity==16);
 assert(source==htonl(1)&&group==htonl(2));
 *cookie=mfc_cookie;
 if(mfc_count>0&&mfc_count<=16)memcpy(indices,mfc_outputs,mfc_count*sizeof(*indices));
 return mfc_count;
}
static int ip6mr_find_mfc_entry(int *net,const struct in6_addr *source,
 const struct in6_addr *group,uint32_t capacity,uint32_t *indices,u64 *cookie) {
 assert(net==&init_net&&source&&group&&capacity==16);*cookie=mfc_cookie;
 if(mfc_count>0&&mfc_count<=16)memcpy(indices,mfc_outputs,mfc_count*sizeof(*indices));
 return mfc_count;
}
static int ecm_interface_linux_mcs_bridge_get_if(struct net_device *dev,
 ip_addr_t source,ip_addr_t group,uint32_t capacity,uint32_t *indices,bool v4) {
 (void)source;(void)group;(void)v4;assert(dev->ifindex==9&&capacity==2);
 l2_calls++;indices[0]=31;return 1;
}
static int br_mcast_offload_get_routed_egress_ifindexes(struct net_device *dev,
 const struct br_ip *ip,uint32_t *indices,uint32_t capacity,u64 *seq) {
 assert(dev->ifindex==9&&capacity==2);
 assert(ip->proto==htons(ETH_P_IP)||ip->proto==htons(ETH_P_IPV6));
 egress_calls++;indices[0]=41;*seq=3;return 1;
}
'''
ROUTED_TESTS = r'''
int main(void) {
 struct net_device bridge={.ifindex=9};
 struct ecm_front_end_connection_instance feci={.multicast_route_cookie=7};
 ip_addr_t source={1},group={2};
 for(int v4=0;v4<2;v4++) {
  uint32_t dst[2]={0xfeedbeef,0xfeedbeef};
  l2_calls=egress_calls=0;mfc_count=1;mfc_cookie=7;mfc_outputs[0]=9;
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,false,source,group,2,dst,v4)==1);
  assert(egress_calls==1&&!l2_calls&&dst[0]==41);
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,true,source,group,2,dst,v4)==1);
  assert(l2_calls==1&&egress_calls==1&&dst[0]==31);
  mfc_outputs[0]=8;
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,false,source,group,2,dst,v4)==1);
  assert(l2_calls==2&&egress_calls==1&&dst[0]==31);
  dst[0]=0xfeedbeef;mfc_cookie=8;mfc_outputs[0]=9;
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,false,source,group,2,dst,v4)==-ESTALE);
  mfc_cookie=0;
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,false,source,group,2,dst,v4)==-ESTALE);
  mfc_cookie=7;mfc_count=-EOPNOTSUPP;
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,false,source,group,2,dst,v4)==-EOPNOTSUPP);
  mfc_count=0;
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,false,source,group,2,dst,v4)==-ENOENT);
  mfc_count=17;
  assert(ecm_interface_multicast_routed_bridge_get_if(&feci,&bridge,false,source,group,2,dst,v4)==-E2BIG);
  assert(dst[0]==0xfeedbeef&&l2_calls==2&&egress_calls==1);
 }
 puts("IPv4/IPv6 ECM bridge expansion: genuine MFC outputs, input copies, cookie replacement and errors passed");
 return 0;
}
'''

INGRESS_SHIM = r'''
#include <arpa/inet.h>
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define ECM_IPV6_ENABLE 1
#define ETH_ALEN 6
#define ETH_HLEN 14
#define ETH_P_IP 0x0800
#define ETH_P_IPV6 0x86dd
#define ARPHRD_ETHER 1
struct ethhdr { uint8_t h_dest[6],h_source[6];uint16_t h_proto; };
struct net_device { int ifindex,type;int *net; };
struct sk_buff {
 unsigned char *head,*tail,*mac,*network;
 int skb_iif;bool mac_set,eligible4,eligible6;
};
static int init_net,other_net;
static int *dev_net(struct net_device *dev) { return dev->net; }
static bool net_eq(int *a,int *b) { return a==b; }
static bool skb_mac_header_was_set(struct sk_buff *s) { return s->mac_set; }
static unsigned char *skb_mac_header(struct sk_buff *s) { return s->mac; }
static unsigned char *skb_network_header(struct sk_buff *s) { return s->network; }
static unsigned char *skb_tail_pointer(struct sk_buff *s) { return s->tail; }
static bool ipmr_mfc_offload_eligible(int *net,struct sk_buff *s) { assert(net==&init_net);return s->eligible4; }
static bool ip6mr_mfc_offload_eligible(int *net,struct sk_buff *s) { assert(net==&init_net);return s->eligible6; }
static bool is_valid_ether_addr(const uint8_t *addr) { uint8_t zero[6]={0};return !(addr[0]&1)&&memcmp(addr,zero,6); }
static void ether_addr_copy(uint8_t *to,const uint8_t *from) { memcpy(to,from,6); }
'''
INGRESS_TESTS = r'''
int main(void) {
 for(int v4=0;v4<2;v4++) {
  uint8_t frame[64]={0},out[6];struct ethhdr *eth=(struct ethhdr *)frame;
  struct net_device dev={.ifindex=10,.type=ARPHRD_ETHER,.net=&init_net};
  struct sk_buff skb={.head=frame,.mac=frame,.tail=frame+64,.network=frame+14,
   .skb_iif=10,.mac_set=true,.eligible4=true,.eligible6=true};
  eth->h_proto=htons(v4?ETH_P_IP:ETH_P_IPV6);eth->h_source[0]=2;eth->h_source[5]=7;
  memset(out,0xa5,6);
  assert(ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));
  assert(!memcmp(out,eth->h_source,6));memset(out,0xa5,6);
  skb.skb_iif=0;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));skb.skb_iif=10;
  assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,11,v4,out));
  dev.net=&other_net;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));dev.net=&init_net;
  dev.type=0;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));dev.type=ARPHRD_ETHER;
  skb.mac_set=false;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));skb.mac_set=true;
  skb.eligible4=skb.eligible6=false;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));skb.eligible4=skb.eligible6=true;
  skb.tail=frame+12;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));skb.tail=frame+64;
  skb.mac=frame+62;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));skb.mac=frame;
  skb.network=frame+18;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));skb.network=frame+14;
  eth->h_proto=htons(0x8100);assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));eth->h_proto=htons(v4?ETH_P_IP:ETH_P_IPV6);
  eth->h_source[0]=1;assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));
  memset(eth->h_source,0,6);assert(!ecm_interface_multicast_ingress_mac_get(&dev,&skb,10,v4,out));
  for(int i=0;i<6;i++)assert(out[i]==0xa5);
 }
 puts("IPv4/IPv6 MFC ingress MAC: original Ethernet node, native predicate, interface, header bounds and invalid MAC rejection passed");
 return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ecm', type=Path, required=True)
    args = parser.parse_args()
    interface = (args.ecm / 'ecm_interface.c').read_text()
    classifier = (args.ecm / 'ecm_classifier_default.c').read_text()
    names = ['ecm_interface_multicast_generation_get',
             'ecm_interface_multicast_invalidate',
             'ecm_interface_multicast_quiesce',
             'ecm_interface_multicast_stats_snapshot',
             'ecm_interface_multicast_stats_valid',
             'ecm_interface_multicast_invalidate_work']
    with tempfile.TemporaryDirectory(prefix='nss-ecm-mcast-') as temporary:
        for version in (4, 6):
            source = (args.ecm / f'frontends/nss/ecm_nss_multicast_ipv{version}.c').read_text()
            body = '\n\n'.join(function(interface, name) for name in names)
            body += '\n\n' + function(classifier, 'ecm_classifier_default_ready_for_accel')
            header = (args.ecm / f'frontends/nss/ecm_nss_ipv{version}.h').read_text()
            body += '\n\n' + function(header, f'ecm_nss_ipv{version}_accel_pending_set')
            body += '\n\n' + '\n\n'.join(function(source,
                f'ecm_nss_multicast_ipv{version}_' + suffix) for suffix in
                ['accel_abort', 'connection_create_callback', 'connection_destroy_callback'])
            stats = (args.ecm / f'frontends/nss/ecm_nss_ipv{version}.c').read_text()
            body += '\n\n' + function(stats, f'ecm_nss_ipv{version}_multicast_sync_valid')
            text = (SHIM + body + TESTS).replace('@V@', str(version))
            path = Path(temporary) / f'ipv{version}.c'
            binary = path.with_suffix('')
            path.write_text(text)
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
                str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
        path = Path(temporary) / 'routed-bridge.c'
        path.write_text(ROUTED_SHIM + function(interface,
            'ecm_interface_multicast_routed_bridge_get_if') + ROUTED_TESTS)
        binary = path.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
            '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        path = Path(temporary) / 'ingress-node.c'
        path.write_text(INGRESS_SHIM + function(interface,
            'ecm_interface_multicast_ingress_mac_get') + INGRESS_TESTS)
        binary = path.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
            '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
