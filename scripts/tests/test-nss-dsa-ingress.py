#!/usr/bin/env python3
"""Exercise the real NSS DSA exception receive and VLAN transition handlers."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
helpers = runpy.run_path(str(ROOT / 'scripts/tests/test-nss-relay.py'))
source = (ROOT / 'package/kernel/qca-dsa-nss/src/qca_dsa_nss.c').read_text()
SHIM = helpers['LIST'] + r'''
typedef uint16_t u16;
#define ETH_HLEN 14
#define PACKET_HOST 0
#define DSA_NSS_MAX_NODES 2
#define NOTIFY_DONE 0
#define SWITCHDEV_PORT_ATTR_SET 1
#define SWITCHDEV_ATTR_ID_BRIDGE_VLAN_FILTERING 2
#define ASSERT_RTNL() ((void)0)
#define HZ 100
#define system_wq NULL
#define pr_warn_ratelimited(...) ((void)0)
struct net_device;
struct dsa_bridge { bool tx_fwd_offload;unsigned vbid; };
struct dsa_switch { unsigned index; };
struct dsa_port { struct dsa_port *cpu_dp;struct net_device *conduit;struct dsa_bridge *bridge;struct dsa_switch *ds;unsigned index; };
struct net_device { struct dsa_port *dp;unsigned ifnum,bytes,packets,drops;char *name; };
struct sk_buff { struct net_device *dev;unsigned len,pkt_type,protocol;bool offload_fwd_mark; };
struct napi_struct {};
struct { struct net_device *dev;bool handler;int phys_if;u16 vid; } nodes[DSA_NSS_MAX_NODES];
static int table_lock,owner_lock,rcu_depth,delivered,dropped,disable_result,disable_calls,requeues;
static bool initialised=true,stopping;
static int last_error,reconcile_work;
static struct net_device *bound,*received;
static bool received_mark;
static void rcu_read_lock(void) { rcu_depth++; }
static void rcu_read_unlock(void) { assert(rcu_depth==1);rcu_depth--; }
static void spin_lock_bh(int *p) { assert(!*p);*p=1; }
static void spin_unlock_bh(int *p) { assert(*p);*p=0; }
#define mutex_lock spin_lock_bh
#define mutex_unlock spin_unlock_bh
static struct dsa_port *port_of(struct net_device *dev) { return dev->dp; }
static int nss_cmn_get_interface_number_by_dev(struct net_device *dev) { return dev->ifnum; }
static unsigned dsa_port_bridge_num_get(struct dsa_port *dp) { return dp->bridge->vbid; }
static unsigned dsa_tag_8021q_bridge_vid(unsigned vbid) { return 1000+vbid; }
static unsigned dsa_tag_8021q_standalone_vid(struct dsa_port *dp) { return 3000+dp->index; }
static struct net_device *dsa_tag_8021q_find_user(struct net_device *d,int port,int sw,int vid,int vbid) { return bound; }
static bool pskb_may_pull(struct sk_buff *skb,unsigned n) { return skb->len>=n; }
static unsigned eth_type_trans(struct sk_buff *skb,struct net_device *dev) { assert(skb->len>=14);skb->len-=14;return 0x800; }
static void dev_sw_netstats_rx_add(struct net_device *dev,unsigned len) { dev->bytes+=len;dev->packets++; }
static void dev_core_stats_rx_dropped_inc(struct net_device *dev) { dev->drops++; }
static void netif_receive_skb(struct sk_buff *skb) { assert(rcu_depth&&skb->pkt_type==PACKET_HOST);received=skb->dev;received_mark=skb->offload_fwd_mark;delivered++; }
static void dev_kfree_skb_any(struct sk_buff *skb) { dropped++; }
struct notifier_block {};
struct switchdev_attr { unsigned id; };
struct switchdev_notifier_info { struct net_device *dev; };
struct switchdev_notifier_port_attr_info { struct switchdev_notifier_info info;const struct switchdev_attr *attr;bool handled; };
static struct net_device *switchdev_notifier_info_to_dev(struct switchdev_notifier_info *i) { return i->dev; }
static bool netif_is_bridge_master(struct net_device *d) { return false; }
static int disable_locked(void) { assert(owner_lock);disable_calls++;return disable_result; }
static int notifier_from_errno(int e) { return e; }
static void mod_delayed_work(void *w,int *work,int time) { requeues++; }
'''
TEST = r'''
static struct sk_buff packet(void) { return (struct sk_buff){.len=100,.pkt_type=3,.offload_fwd_mark=true}; }
int main(void) {
 struct net_device conduit={.ifnum=2,.name="eth1"},a={.name="lan1"},b={.name="lan2"};
 struct dsa_switch ds={0};
 struct dsa_bridge bridge={.tx_fwd_offload=true,.vbid=1},other={.tx_fwd_offload=true,.vbid=2};
 struct dsa_port cpu={.conduit=&conduit};
 struct dsa_port pa={.cpu_dp=&cpu,.ds=&ds,.index=1,.bridge=&bridge};
 struct dsa_port pb={.cpu_dp=&cpu,.ds=&ds,.index=2,.bridge=&bridge};
 a.dp=&pa;b.dp=&pb;nodes[0].dev=&a;nodes[0].handler=true;nodes[0].phys_if=2;nodes[0].vid=1001;bound=&a;
 struct sk_buff skb=packet();node_receive(&a,&skb,NULL);
 assert(delivered==1&&received==&a&&received_mark&&a.bytes==100&&!rcu_depth);
 nodes[0].vid=1002;skb=packet();node_receive(&a,&skb,NULL);
 assert(dropped==1&&a.drops==1&&delivered==1);
 nodes[0].vid=1001;bound=&b;skb=packet();node_receive(&a,&skb,NULL);
 assert(delivered==2&&received==&b&&received_mark&&b.bytes==100);
 pb.bridge=&other;skb=packet();node_receive(&a,&skb,NULL);
 assert(dropped==2&&delivered==2);
 pa.bridge=NULL;bound=&a;nodes[0].vid=3001;skb=packet();node_receive(&a,&skb,NULL);
 assert(delivered==3&&!received_mark&&a.bytes==200);
 nodes[0].handler=false;skb=packet();node_receive(&a,&skb,NULL);
 assert(dropped==3&&delivered==3);
 struct switchdev_attr attr={.id=SWITCHDEV_ATTR_ID_BRIDGE_VLAN_FILTERING};
 struct switchdev_notifier_port_attr_info info={.info.dev=&a,.attr=&attr};
 assert(!switchdev_event(NULL,SWITCHDEV_PORT_ATTR_SET,&info)&&disable_calls==1&&requeues==1&&!info.handled);
 disable_result=-EBUSY;
 assert(switchdev_event(NULL,SWITCHDEV_PORT_ATTR_SET,&info)==-EBUSY&&info.handled&&last_error==-EBUSY);
 assert(!owner_lock&&!table_lock&&!rcu_depth);
 return 0;
}
'''
helpers['c_test']('actual DSA ingress: bridge/standalone flags, VID/conduit ownership, STP designated port, L2 RX accounting and VLAN pre-revoke',
                  SHIM + helpers['function'](source, 'node_receive') +
                  helpers['function'](source, 'switchdev_event') + TEST)
