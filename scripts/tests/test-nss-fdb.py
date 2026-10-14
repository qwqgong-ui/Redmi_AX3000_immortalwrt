#!/usr/bin/env python3
"""Exercise the prepared bridge producers with the actual ECM consumers."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(text, name):
    match = re.search(r'(?m)^(?:static\s+)?(?:inline\s+)?[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*[ \t*]+\b' +
                      re.escape(name) + r'\s*\([^;]*?\)\s*\{', text)
    if not match:
        raise AssertionError('Missing prepared function: ' + name)
    depth, end = 1, match.end()
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end] + '\n'


HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint16_t __u16;
#define BIT(n) (1UL << (n))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define likely(x) (x)
#define unlikely(x) (x)
#define min(a,b) ((a)<(b)?(a):(b))
#define max_t(t,a,b) ((t)(a)>(t)(b)?(t)(a):(t)(b))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define DEBUG_TRACE(...) ((void)0)
#define DEBUG_WARN(...) ((void)0)
#define pr_info(...) ((void)0)
#define br_warn(...) ((void)0)
#define WARN_ON(x) ((void)(x))
#define RTM_NEWNEIGH 1
#define RTM_DELNEIGH 2
#define BR_FDB_EVENT_ADD 1
#define BR_FDB_EVENT_DEL 2
#define NOTIFY_DONE 0
#define ECM_DB_IP_VERSION_IGNORE 0
#define GFP_ATOMIC 0
#define RTNLGRP_NEIGH 0
#define BR_STATE_DISABLED 0
#define BR_STATE_LEARNING 2
#define BR_STATE_FORWARDING 3
#define BR_PORT_MAB 1
#define NTF_STICKY 1
#define NUD_PERMANENT 0x80
#define NUD_NOARP 0x40
#define NUD_REACHABLE 0x02
#define NLM_F_CREATE 1
#define NLM_F_EXCL 2
#define NFEA_DONT_REFRESH 0
#define NFEA_ACTIVITY_NOTIFY 1
#define BR_FDB_NOTIFY_SETTABLE_BITS 3
#define FDB_NOTIFY_INACTIVE_BIT 2
enum { BR_FDB_LOCAL, BR_FDB_STATIC, BR_FDB_ADDED_BY_EXT_LEARN,
       BR_FDB_NOTIFY, BR_FDB_NOTIFY_INACTIVE, BR_FDB_STICKY,
       BR_FDB_LOCKED, BR_FDB_ADDED_BY_USER, BR_FDB_DYNAMIC_LEARNED };
struct net_bridge_port;
struct net_device { char name[16]; struct net_bridge_port *port; bool bridge_port; };
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; };
struct net_bridge_fdb_entry {
 struct net_bridge_port *dst;
 unsigned long flags,updated,used;
 struct { struct { u8 addr[6]; } addr; } key;
 struct { bool unhashed; } fdb_node;
 int rhnode,rcu;
 struct net_bridge_fdb_entry *next;
};
struct net_bridge {
 struct net_device *dev;
 struct delayed_work gc_work;
 int hash_lock,fdb_hash_tbl,fdb_n_learned;
 struct net_bridge_fdb_entry *fdb_list;
 unsigned long delay;
};
struct net_bridge_port { struct net_device *dev; struct net_bridge *br; int state,flags; };
struct notifier_block { int unused; };
struct notifier_chain { int unused; };
struct sk_buff { int unused; };
struct net { int unused; };
struct ndmsg { u16 ndm_state; u8 ndm_flags; };
struct nlattr { u8 value; };
static struct net_bridge bridge;
static struct net_bridge_fdb_entry entry;
static struct notifier_chain br_fdb_notifier_list,br_fdb_update_notifier_list;
static struct net net;
static struct sk_buff skb;
static unsigned long jiffies=100;
static int rcu_depth,spin_depth,moves,deletes,adds,defuncts,port_lookups;
static bool exists;
static int system_long_wq,br_fdb_rht_params;
static u8 defunct_mac[6];
static bool test_bit(int n,const unsigned long *p) { return !!(*p & BIT(n)); }
static void set_bit(int n,unsigned long *p) { *p |= BIT(n); }
static void clear_bit(int n,unsigned long *p) { *p &= ~BIT(n); }
static bool test_and_clear_bit(int n,unsigned long *p) { bool old=test_bit(n,p); clear_bit(n,p); return old; }
static bool test_and_set_bit(int n,unsigned long *p) { bool old=test_bit(n,p); set_bit(n,p); return old; }
static void change_bit(int n,unsigned long *p) { *p ^= BIT(n); }
static void rcu_read_lock(void) { ++rcu_depth; }
static void rcu_read_unlock(void) { assert(rcu_depth>0); --rcu_depth; }
#define spin_lock(p) (++spin_depth)
#define spin_unlock(p) (--spin_depth)
#define spin_lock_bh spin_lock
#define spin_unlock_bh spin_unlock
#define atomic_dec(p) (--*(p))
#define time_after(a,b) ((long)((b)-(a))<0)
#define hlist_for_each_entry_rcu(f,head,node) for((f)=*(head);(f);(f)=(f)->next)
#define hlist_unhashed(n) ((n)->unhashed)
#define hlist_del_init_rcu(n) ((n)->unhashed=true)
#define trace_br_fdb_update(...) ((void)0)
#define trace_br_fdb_external_learn_add(...) ((void)0)
#define trace_fdb_delete(...) ((void)0)
static unsigned long hold_time(struct net_bridge *b) { return b->delay; }
static unsigned long msecs_to_jiffies(unsigned long n) { return n; }
static void mod_delayed_work(int q,struct delayed_work *w,unsigned long delay) { (void)q; (void)w; (void)delay; }
static void ether_addr_copy(void *dst,const void *src) { memcpy(dst,src,6); }
static bool is_valid_ether_addr(const void *addr) { const u8 *a=addr; return !(a[0]&1) && memcmp(a,"\0\0\0\0\0\0",6); }
static int net_ratelimit(void) { return 0; }
static void br_switchdev_fdb_notify(struct net_bridge *b,const struct net_bridge_fdb_entry *f,int type) { }
static struct net *dev_net(struct net_device *d) { return &net; }
static int fdb_nlmsg_size(void) { return 1; }
static struct sk_buff *nlmsg_new(int size,int flags) { return &skb; }
static int fdb_fill_info(struct sk_buff *s,struct net_bridge *b,const struct net_bridge_fdb_entry *f,int p,int seq,int type,int flags) { return 0; }
static void kfree_skb(struct sk_buff *s) { }
static void rtnl_notify(struct sk_buff *s,struct net *n,int p,int group,void *cb,int flags) { }
static void rtnl_set_sk_err(struct net *n,int group,int err) { assert(!"unexpected netlink error"); }
static void fdb_add_hw_addr(struct net_bridge *b,const u8 *mac) { }
static void fdb_del_hw_addr(struct net_bridge *b,const u8 *mac) { }
static void rhashtable_remove_fast(int *table,int *node,int params) { exists=false; }
static void fdb_rcu_free(int *rcu) { }
static void call_rcu(int *rcu,void (*cb)(int *)) { }
static struct net_bridge_fdb_entry *fdb_find_rcu(int *table,const void *mac,u16 vid) {
 assert(rcu_depth>0); return exists && !memcmp(entry.key.addr.addr,mac,6) ? &entry : NULL;
}
static struct net_bridge_fdb_entry *br_fdb_find(struct net_bridge *b,const void *mac,u16 vid) {
 assert(spin_depth>0); return exists && !memcmp(entry.key.addr.addr,mac,6) ? &entry : NULL;
}
static struct net_bridge_fdb_entry *fdb_create(struct net_bridge *b,struct net_bridge_port *p,const void *mac,u16 vid,unsigned long flags) {
 memset(&entry,0,sizeof(entry)); entry.dst=p; entry.flags=flags;
 ether_addr_copy(entry.key.addr.addr,mac); b->fdb_list=&entry; exists=true; return &entry;
}
static u16 fdb_to_nud(struct net_bridge *b,struct net_bridge_fdb_entry *f) {
 return test_bit(BR_FDB_LOCAL,&f->flags) ? NUD_PERMANENT : test_bit(BR_FDB_STATIC,&f->flags) ? NUD_NOARP : NUD_REACHABLE;
}
static bool fdb_handle_notify(struct net_bridge_fdb_entry *f,u8 flags) { return false; }
static u8 nla_get_u8(struct nlattr *attr) { return attr->value; }
static struct net_bridge_port *br_port_get_rcu(struct net_device *dev) {
 assert(rcu_depth>0); ++port_lookups; return dev->port;
}
static struct net_bridge_port *br_port_get_check_rcu(struct net_device *dev) {
 assert(rcu_depth>0); return dev->bridge_port ? br_port_get_rcu(dev) : NULL;
}
static void ecm_interface_node_connections_defunct(uint8_t *mac,int version) {
 ++defuncts; ether_addr_copy(defunct_mac,mac);
}
'''

NOTIFIERS = r'''
static struct br_fdb_event last,last_move;
static int atomic_notifier_call_chain(struct notifier_chain *chain,unsigned long event,void *data) {
 struct br_fdb_event *fe=data;
 int result=chain==&br_fdb_update_notifier_list ?
  ecm_interface_node_br_fdb_notify_event(NULL,event,data) :
  ecm_interface_node_br_fdb_delete_event(NULL,event,data);
 assert(fe->br==&bridge);
 assert(!memcmp(fe->addr,entry.key.addr.addr,6));
 last=*fe;
 if(chain==&br_fdb_update_notifier_list) {
  last_move=*fe;
  ++moves; assert(event==0 && fe->orig_dev && fe->dev && !fe->is_local);
  return result;
 }
 assert(fe->orig_dev==NULL);
 if(event==BR_FDB_EVENT_DEL) ++deletes; else ++adds;
 return result;
}
'''

MAIN = r'''
static void reset(struct net_bridge_port *port,const u8 *mac,unsigned long flags) {
 memset(&entry,0,sizeof(entry)); entry.dst=port; entry.flags=flags;
 ether_addr_copy(entry.key.addr.addr,mac); exists=true; bridge.fdb_list=&entry;
 moves=deletes=adds=defuncts=port_lookups=0; memset(&last,0xa5,sizeof(last));
}
int main(void) {
 struct net_device brdev={.name="br-lan"},a={.name="lan1"},b={.name="wlan"};
 struct net_bridge_port pa={.dev=&a,.br=&bridge,.state=BR_STATE_FORWARDING};
 struct net_bridge_port pb={.dev=&b,.br=&bridge,.state=BR_STATE_FORWARDING};
 a.port=&pa; b.port=&pb; a.bridge_port=b.bridge_port=true; bridge.dev=&brdev; bridge.delay=10;
 /* A six-byte allocation makes the old raw-MAC-as-struct ABI fail ASan. */
 u8 *mac=malloc(6); ether_addr_copy(mac,"\x02\x11\x22\x33\x44\x55");
 reset(&pa,mac,0);
 rcu_read_lock(); br_fdb_update(&bridge,&pb,mac,0,0); rcu_read_unlock();
 assert(moves==1 && defuncts==1 && last.orig_dev==NULL); /* ADD follows MOVE. */
 assert(last_move.orig_dev==&a && last_move.dev==&b && last_move.br==&bridge);
 assert(!memcmp(defunct_mac,mac,6) && entry.dst==&pb && adds==1);
 rcu_read_lock(); br_fdb_update(&bridge,&pb,mac,0,0); rcu_read_unlock();
 assert(moves==1 && defuncts==1);
 reset(&pa,mac,BIT(BR_FDB_STICKY));
 rcu_read_lock(); br_fdb_update(&bridge,&pb,mac,0,0); rcu_read_unlock();
 assert(entry.dst==&pa && moves==0 && defuncts==0);
 reset(&pa,mac,BIT(BR_FDB_LOCAL));
 rcu_read_lock(); br_fdb_update(&bridge,&pb,mac,0,0); rcu_read_unlock();
 assert(entry.dst==&pa && moves==0);
 reset(&pa,mac,BIT(BR_FDB_DYNAMIC_LEARNED));
 br_fdb_cleanup(&bridge.gc_work.work);
 assert(deletes==1 && moves==0 && defuncts==1 && !exists);
 reset(&pa,mac,0); fdb_delete(&bridge,&entry,true);
 assert(deletes==1 && moves==0 && defuncts==1);
 reset(&pa,mac,BIT(BR_FDB_LOCAL)); fdb_delete(&bridge,&entry,true);
 assert(deletes==1 && defuncts==0);
 reset(NULL,mac,BIT(BR_FDB_LOCAL)); fdb_delete(&bridge,&entry,true);
 assert(deletes==0 && moves==0 && defuncts==0);
 struct nlattr *attrs[2]={0}; struct ndmsg ndm={.ndm_state=NUD_REACHABLE};
 reset(&pa,mac,0); spin_lock_bh(&bridge.hash_lock);
 assert(fdb_add_entry(&bridge,&pb,mac,&ndm,0,0,attrs)==0); spin_unlock_bh(&bridge.hash_lock);
 assert(moves==1 && defuncts==1 && entry.dst==&pb);
 reset(&pa,mac,0); spin_lock_bh(&bridge.hash_lock);
 assert(fdb_add_entry(&bridge,&pa,mac,&ndm,0,0,attrs)==0); spin_unlock_bh(&bridge.hash_lock);
 assert(moves==0 && deletes==0 && defuncts==0);
 for(int null_port=0;null_port<2;++null_port) {
  reset(&pa,mac,0); ndm.ndm_state=NUD_PERMANENT; spin_lock_bh(&bridge.hash_lock);
  assert(fdb_add_entry(&bridge,null_port?NULL:&pa,mac,&ndm,0,0,attrs)==0); spin_unlock_bh(&bridge.hash_lock);
  assert(moves==0 && deletes==1 && defuncts==1 && test_bit(BR_FDB_LOCAL,&entry.flags));
 }
 reset(&pa,mac,0); assert(br_fdb_external_learn_add(&bridge,&pb,mac,0,false,true)==0);
 assert(moves==1 && defuncts==1 && entry.dst==&pb);
 moves=deletes=adds=defuncts=0;
 assert(br_fdb_external_learn_add(&bridge,&pb,mac,0,false,true)==0);
 assert(moves==0 && deletes==0 && adds==0 && defuncts==0);
 reset(&pa,mac,0); assert(br_fdb_external_learn_add(&bridge,NULL,mac,0,false,true)==0);
 assert(moves==0 && deletes==1 && defuncts==1 && last.dev==&a);
 for(int null_port=0;null_port<2;++null_port) {
  reset(null_port?NULL:&pa,mac,BIT(BR_FDB_LOCAL)); ndm.ndm_state=NUD_REACHABLE;
  spin_lock_bh(&bridge.hash_lock);
  assert(fdb_add_entry(&bridge,&pb,mac,&ndm,0,0,attrs)==0); spin_unlock_bh(&bridge.hash_lock);
  assert(moves==0 && deletes==0 && defuncts==0 && entry.dst==&pb);
  reset(null_port?NULL:&pa,mac,BIT(BR_FDB_LOCAL));
  assert(br_fdb_external_learn_add(&bridge,&pb,mac,0,false,true)==0);
  assert(moves==0 && deletes==0 && defuncts==0 && entry.dst==&pb);
 }
 reset(&pa,mac,0); exists=false; ndm.ndm_state=NUD_REACHABLE; spin_lock_bh(&bridge.hash_lock);
 assert(fdb_add_entry(&bridge,&pb,mac,&ndm,NLM_F_CREATE,0,attrs)==0); spin_unlock_bh(&bridge.hash_lock);
 assert(moves==0 && deletes==0 && defuncts==0 && adds==1);
 reset(&pa,mac,0); exists=false;
 assert(br_fdb_external_learn_add(&bridge,&pb,mac,0,false,true)==0);
 assert(moves==0 && deletes==0 && defuncts==0 && adds==1);
 reset(&pa,mac,0); br_fdb_entry_refresh(&a,(const char *)mac,0);
 assert(entry.updated==jiffies && port_lookups==1 && rcu_depth==0);
 assert(br_fdb_has_entry(&a,(const char *)mac,0)==&entry && rcu_depth==0);
 entry.updated=0; pa.state=BR_STATE_DISABLED; br_fdb_entry_refresh(&a,(const char *)mac,0);
 assert(entry.updated==0 && rcu_depth==0);
 assert(br_fdb_has_entry(&a,(const char *)mac,0)==NULL && rcu_depth==0);
 pa.state=BR_STATE_FORWARDING; br_refresh_fdb_entry(&a,(const char *)mac);
 assert(entry.updated==jiffies && rcu_depth==0 && moves==0 && deletes==0);
 a.port=NULL; br_refresh_fdb_entry(&a,(const char *)mac); br_fdb_entry_refresh(&a,(const char *)mac,0);
 assert(br_fdb_has_entry(&a,(const char *)mac,0)==NULL);
 a.port=&pa; a.bridge_port=false; entry.updated=0;
 br_refresh_fdb_entry(&a,(const char *)mac); br_fdb_entry_refresh(&a,(const char *)mac,0);
 assert(br_fdb_has_entry(&a,(const char *)mac,0)==NULL && entry.updated==0);
 assert(rcu_depth==0 && spin_depth==0);
 free(mac); return 0;
}
'''


def run(kernel, ecm, reference=None):
    bridge = (reference or kernel / 'net/bridge/br_fdb.c').read_text()
    header = (kernel / 'include/linux/if_bridge.h').read_text()
    start = header.index('struct br_fdb_event {')
    event = header[start:header.index('};', start) + 2] + '\n'
    consumer = (ecm / 'ecm_interface.c').read_text()
    code = HARNESS + event
    for name in ('ecm_interface_node_br_fdb_notify_event', 'ecm_interface_node_br_fdb_delete_event'):
        code += function(consumer, name)
    code += NOTIFIERS
    for name in ('fdb_notify', 'fdb_delete', '__fdb_mark_active', 'br_fdb_notify_move',
                 'br_fdb_update', 'br_fdb_cleanup', 'br_refresh_fdb_entry',
                 'br_fdb_entry_refresh', 'br_fdb_has_entry', 'fdb_add_entry', 'br_fdb_external_learn_add'):
        if name == 'br_fdb_notify_move' and name not in bridge:
            continue
        code += function(bridge, name)
    code += MAIN
    with tempfile.TemporaryDirectory(prefix='nss-fdb-test-') as tmp:
        src, exe = Path(tmp) / 'test.c', Path(tmp) / 'test'
        src.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-Wno-pointer-sign', '-fsanitize=address,undefined', '-g',
                        str(src), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=bool(reference), text=True)
        if reference:
            assert result.returncode != 0, 'The faulty reference unexpectedly passed'
            assert 'AddressSanitizer' in result.stderr, result.stderr
            assert 'ecm_interface_node_br_fdb_notify_event' in result.stderr, result.stderr
            print('PASS old raw-MAC notifier reproduced an AddressSanitizer failure')
        else:
            result.check_returncode()
            print('PASS prepared FDB learning, ageing, deletion, admin/external replacement and refresh lifetime')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--ecm', type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    run(args.kernel, args.ecm, args.reference)
