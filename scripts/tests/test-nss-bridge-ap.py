#!/usr/bin/env python3
"""Execute the prepared AP exclusion and recorded-owner LEAVE helpers."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    'nss_control_test', Path(__file__).with_name('test-nss-control.py'))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
enum nl80211_iftype { NL80211_IFTYPE_STATION=2, NL80211_IFTYPE_AP=3,
                     NL80211_IFTYPE_AP_VLAN=4, NL80211_IFTYPE_MESH_POINT=7 };
struct wireless_dev { enum nl80211_iftype iftype; };
struct net_device { struct wireless_dev *ieee80211_ptr; int refs; };
struct list_head { struct list_head *next, *prev; };
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_for_each_entry(p,h,m) \
 for(p=container_of((h)->next,__typeof__(*p),m); &(p)->m!=(h); \
     p=container_of((p)->m.next,__typeof__(*p),m))
#define READ_ONCE(x) (x)
#define ASSERT_RTNL() assert(rtnl_held)
static bool rtnl_held=true;
struct nss_bridge_member { struct list_head list; struct net_device *dev;
 int32_t ifnum; bool leaving,uncertain; };
struct nss_bridge_pvt { struct list_head list,members; int ifnum; };
static struct { struct list_head list; } br_mgr_ctx;
struct nss_bridge_leave_msg { int if_num; };
struct nss_bridge_msg { int iface,type,len;
 struct { struct nss_bridge_leave_msg br_leave; } msg; };
#define NSS_BRIDGE_MSG_LEAVE 1
#define NSS_TX_SUCCESS 0
static unsigned submissions,retries,frees;
static int reply_status,recorded_ifnum,recorded_bridge;
static void nss_bridge_mgr_schedule_reconcile(void) { ++retries; }
static void nss_bridge_msg_init(struct nss_bridge_msg *m,int iface,int type,
 int len,void *cb,void *data) {
 (void)cb;(void)data;m->iface=iface;m->type=type;m->len=len;
}
static void *nss_bridge_get_context(void) { return NULL; }
static int nss_bridge_tx_msg_sync(void *ctx,struct nss_bridge_msg *m) {
 (void)ctx;submissions++;assert(m->type==NSS_BRIDGE_MSG_LEAVE);
 assert(m->len==sizeof(struct nss_bridge_leave_msg));
 recorded_ifnum=m->msg.br_leave.if_num;recorded_bridge=m->iface;return reply_status;
}
static void list_del(struct list_head *n) { n->prev->next=n->next;n->next->prev=n->prev; }
static void dev_put(struct net_device *d) { assert(d->refs>0); --d->refs; }
static void kfree(void *p) { frees++;free(p); }
static void init_list(struct list_head *h) { h->next=h->prev=h; }
static void add_tail(struct list_head *h,struct list_head *n) {
 n->next=h;n->prev=h->prev;h->prev->next=n;h->prev=n;
}
#define GFP_KERNEL 0
#define nss_bridge_mgr_warn(...) ((void)0)
static unsigned lookups,joins;
static int current_ifnum;
static void *kzalloc(size_t size,int flags) { (void)flags;return calloc(1,size); }
static int nss_cmn_get_interface_number_by_dev(struct net_device *d) {
 (void)d;lookups++;return current_ifnum;
}
static int nss_bridge_tx_join_msg(int iface,struct net_device *d) {
 (void)iface;(void)d;joins++;return NSS_TX_SUCCESS;
}
static void dev_hold(struct net_device *d) { d->refs++; }
#define list_add_tail(n,h) add_tail(h,n)
'''

CASES = r'''
static struct nss_bridge_pvt bridge,other;
static struct wireless_dev wdev;
static struct net_device dev;
static void fresh(enum nl80211_iftype type) {
 memset(&bridge,0,sizeof(bridge));memset(&other,0,sizeof(other));memset(&dev,0,sizeof(dev));
 init_list(&br_mgr_ctx.list);init_list(&bridge.members);init_list(&other.members);
 bridge.ifnum=100;other.ifnum=101;add_tail(&br_mgr_ctx.list,&bridge.list);add_tail(&br_mgr_ctx.list,&other.list);
 wdev.iftype=type;dev.ieee80211_ptr=&wdev;submissions=retries=frees=lookups=joins=0;reply_status=0;current_ifnum=-1;
}
static struct nss_bridge_member *member(struct nss_bridge_pvt *b,int ifnum) {
 struct nss_bridge_member *m=calloc(1,sizeof(*m));assert(m);
 m->dev=&dev;m->ifnum=ifnum;dev.refs++;add_tail(&b->members,&m->list);return m;
}
int main(void) {
 fresh(NL80211_IFTYPE_AP);assert(nss_bridge_mgr_keep_ap_on_host(&dev)==1);
 assert(!submissions && !dev.refs);
 assert(!nss_bridge_mgr_join_bridge(&dev,&bridge) && !lookups && !joins);
 fresh(NL80211_IFTYPE_AP_VLAN);assert(nss_bridge_mgr_keep_ap_on_host(&dev)==1);
 assert(!nss_bridge_mgr_join_bridge(&dev,&bridge) && !lookups && !joins);
 fresh(NL80211_IFTYPE_STATION);assert(!nss_bridge_mgr_keep_ap_on_host(&dev));
 fresh(NL80211_IFTYPE_MESH_POINT);assert(!nss_bridge_mgr_keep_ap_on_host(&dev));
 dev.ieee80211_ptr=NULL;assert(!nss_bridge_mgr_keep_ap_on_host(&dev));
 fresh(NL80211_IFTYPE_AP);member(&bridge,37);member(&other,38);
 assert(nss_bridge_mgr_keep_ap_on_host(&dev)==-EAGAIN);
 assert(!submissions && !frees && dev.refs==2 && retries==1);
 assert(nss_bridge_mgr_offload_port_revoke(&dev,37)==-EBUSY);
 assert(nss_bridge_mgr_offload_port_revoke(&dev,37)==-EBUSY);
 assert(!nss_bridge_mgr_offload_port_revoke(&dev,38));
 assert(nss_bridge_mgr_keep_ap_on_host(&dev)==1 && !dev.refs && frees==2);
 assert(recorded_ifnum==38 && recorded_bridge==101);
 fresh(NL80211_IFTYPE_AP);struct nss_bridge_member *m=member(&bridge,42);
 reply_status=1;assert(nss_bridge_mgr_offload_port_revoke(&dev,42)==-EIO);
 assert(m->leaving && m->uncertain && dev.refs==1 && !frees && retries==1);
 assert(recorded_ifnum==42 && recorded_bridge==100);
 reply_status=0;assert(!nss_bridge_mgr_offload_port_revoke(&dev,42));
 assert(nss_bridge_mgr_keep_ap_on_host(&dev)==1);
 assert(!dev.refs && frees==1 && submissions==2);
 fresh(NL80211_IFTYPE_AP);m=member(&other,99);reply_status=1;
 assert(nss_bridge_mgr_join_bridge(&dev,&bridge)==-EAGAIN && !joins && !lookups && !submissions);
 assert(m->uncertain && dev.refs==1);reply_status=0;
 assert(!nss_bridge_mgr_offload_port_revoke(&dev,99));
 assert(!nss_bridge_mgr_join_bridge(&dev,&bridge) && !joins && !dev.refs);
 fresh(NL80211_IFTYPE_STATION);current_ifnum=44;
 assert(!nss_bridge_mgr_join_bridge(&dev,&bridge) && joins==1 && dev.refs==1);
 assert(!nss_bridge_mgr_join_bridge(&dev,&bridge) && joins==1 && dev.refs==1);
 assert(!nss_bridge_mgr_revoke_member(&bridge,nss_bridge_mgr_find_member(&bridge,&dev)) && !dev.refs);
 puts("PASS actual AP/AP_VLAN public JOIN exclusion, ordinary wired/STA/mesh, unproven old-owner retention and explicit owned LEAVE ACK/failure handling");
 return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clients-source', type=Path, required=True)
    args = parser.parse_args()
    source = (args.clients_source/'bridge/nss_bridge_mgr.c').read_text()
    functions = '\n'.join(extract.function(source, name) for name in (
        'nss_bridge_mgr_find_member', 'nss_bridge_mgr_delete_member',
        'nss_bridge_mgr_ap_host_port', 'nss_bridge_mgr_revoke_member',
        'nss_bridge_mgr_keep_ap_on_host', 'nss_bridge_mgr_join_bridge',
        'nss_bridge_mgr_offload_port_revoke'))
    join = extract.function(source, 'nss_bridge_mgr_join_bridge')
    assert join.index('nss_bridge_mgr_keep_ap_on_host(dev)') < join.index(
        'nss_cmn_get_interface_number_by_dev(dev)')
    with tempfile.TemporaryDirectory(prefix='nss-bridge-ap-') as directory:
        cfile = Path(directory)/'test.c'
        binary = Path(directory)/'test'
        cfile.write_text(SHIM+functions+CASES)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall',
                        '-Wextra', '-Werror', '-O1', '-g',
                        '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                        str(cfile), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

if __name__ == '__main__':
    main()
