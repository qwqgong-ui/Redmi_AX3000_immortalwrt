#!/usr/bin/env python3
"""Exercise relay control/error paths using the actual prepared C functions.

No target access. Optional arguments: --clients DIR --backports DIR --kernel DIR.
"""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(text, name):
    import re
    match = re.search(r"(?m)^(?:static[ \t]+)?(?:inline[ \t]+)?[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*[ \t*]+\b" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", text)
    if not match:
        raise AssertionError("Missing function: " + name)
    depth = 1
    i = match.end()
    while depth:
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    return text[match.start():i] + "\n"


def structure(text, name):
    start = text.index("struct " + name + " {")
    return text[start:text.index("};", start) + 2] + "\n"


def c_test(name, source):
    with tempfile.TemporaryDirectory(prefix="nss-relay-test-") as tmp:
        src, exe = Path(tmp) / "test.c", Path(tmp) / "test"
        src.write_text(source)
        subprocess.run(["cc", "-std=gnu11", "-Wall", "-Werror", "-Wno-unused-function",
                        "-Wno-unused-parameter", "-fsanitize=address,undefined", "-g",
                        str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS " + name)


LIST = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
struct list_head { struct list_head *next, *prev; };
#define INIT_LIST_HEAD(h) ((h)->next=(h), (h)->prev=(h))
#define list_empty(h) ((h)->next==(h))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_for_each_entry(p,h,m) \
 for(struct list_head *_n=(h)->next; _n!=(h) && ((p)=container_of(_n,__typeof__(*(p)),m),1); _n=_n->next)
#define list_for_each_entry_rcu list_for_each_entry
#define list_for_each_entry_safe(p,q,h,m) \
 for(struct list_head *_n=(h)->next,*_next; _n!=(h) && \
 ((p)=container_of(_n,__typeof__(*(p)),m),_next=_n->next, \
 (q)=(_next==(h)?NULL:container_of(_next,__typeof__(*(q)),m)),1); _n=_next)
static void list_add_tail(struct list_head *n, struct list_head *h) {
 n->prev=h->prev; n->next=h; h->prev->next=n; h->prev=n;
}
static void list_del(struct list_head *n) { n->prev->next=n->next; n->next->prev=n->prev; }
#define list_add_tail_rcu list_add_tail
#define list_del_rcu list_del
#define READ_ONCE(x) (x)
#define GFP_KERNEL 0
static int fail_alloc;
static void *test_alloc(size_t n) { return fail_alloc ? NULL : calloc(1,n); }
#define kzalloc(n,f) test_alloc(n)
#define kmalloc(n,f) test_alloc(n)
#define kfree free
'''


def test_ecm_service():
    script = (ROOT / "package/kernel/qca-nss-ecm/files/qca-nss-ecm.init").read_text()
    cases = ["enabled", "disabled", "not-ready", "host-wifi", "no-bridge", "firewall-offload",
             "load-failure", "parameter-failure", "stop-failure", "external-events-change"]
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="ecm-boot-test-") as tmp:
            base = Path(tmp)
            sys = base / "sys"
            proc = base / "proc/sys/net/netfilter"
            proc.mkdir(parents=True)
            events = proc / "nf_conntrack_events"
            events.write_text("2\n")
            for mod, value in (("qca_nss_drv", "0" if case == "not-ready" else "1"),
                               ("ath11k", "0" if case == "host-wifi" else "1")):
                p = sys / "module" / mod / "parameters"
                p.mkdir(parents=True)
                (p / ("core0_ready" if mod == "qca_nss_drv" else "nss_offload")).write_text(value)
            if case != "no-bridge":
                (sys / "module/qca_nss_bridge_mgr").mkdir()
            debug = sys / "kernel/debug/ecm"
            (debug / "ecm_classifier_default").mkdir(parents=True)
            (debug / "ecm_db").mkdir()
            for f in ("front_end_ipv4_stop", "front_end_ipv6_stop", "ecm_db/defunct_all",
                      "ecm_classifier_default/accel_delay_pkts"):
                (debug / f).write_text("1\n")
            if case == "parameter-failure":
                (debug / "ecm_classifier_default/accel_delay_pkts").unlink()
                (debug / "ecm_classifier_default/accel_delay_pkts").mkdir()
            text = script.replace(". /lib/functions.sh", ":").replace("/proc/sys/", "@PROC_SYS@/")
            text = text.replace("/sys/", str(sys) + "/").replace("@PROC_SYS@/", str(base / "proc/sys") + "/")
            text = text.replace("/var/run/ecm", str(base / "state"))
            prelude = r'''
config_load() { :; }
config_get_bool() { enabled="$ENABLED"; }
config_get() { delay=1; }
logger() { :; }
uci() { [ "$1" = -q ] && [ "$2" = get ] || exit 90; echo "$FLOW"; }
modprobe() { echo "modprobe $*" >> "$CALLS"; }
insmod() {
 echo "insmod $*" >> "$CALLS"
 [ "$CASE" != load-failure ] || return 1
 mkdir -p "$SYS/module/ecm"
}
rmmod() {
 echo "rmmod $*" >> "$CALLS"
 [ "$CASE" != stop-failure ] || return 1
 rm -rf "$SYS/module/ecm"
}
'''
            env = dict(os.environ, CASE=case, ENABLED="0" if case == "disabled" else "1",
                       FLOW="1" if case == "firewall-offload" else "0", SYS=str(sys), CALLS=str(base / "calls"))
            tail = "\nstart_service; result=$?; echo $result > \"$START_RESULT\"\n"
            if case == "external-events-change":
                tail += f'echo 0 > "{events}"\n'
            tail += "stop_service\n"
            env["START_RESULT"] = str(base / "start-result")
            result = subprocess.run(["sh"], input=prelude + text + tail, text=True, env=env, capture_output=True)
            start = int((base / "start-result").read_text())
            calls = (base / "calls").read_text() if (base / "calls").exists() else ""
            if case in ("disabled", "not-ready", "host-wifi", "no-bridge", "firewall-offload"):
                assert "insmod" not in calls and start == 0, (case, result.stderr)
            elif case in ("load-failure", "parameter-failure"):
                assert start != 0 and not (sys / "module/ecm").exists(), (case, result.stderr)
            else:
                assert start == 0 and "insmod ecm front_end_selection=1" in calls, (case, result.stderr)
                assert "register_br_post_routing=0 ecm_front_end_ipv4_stopped=1 ecm_front_end_ipv6_stopped=1" in calls, case
            if case == "stop-failure":
                assert result.returncode != 0 and events.read_text().strip() == "1"
                assert (debug / "front_end_ipv4_stop").read_text().strip() == "1"
            else:
                assert events.read_text().strip() == ("0" if case == "external-events-change" else "2"), case
                assert not (base / "state/conntrack_events").exists(), case
            print("PASS ECM service: " + case)


def test_observers(kernel):
    text = (kernel / "net/netfilter/nf_conntrack_ecache.c").read_text()
    header = (kernel / "include/net/netfilter/nf_conntrack_ecache.h").read_text()
    harness = LIST + r'''
#define EXPORT_SYMBOL_GPL(x)
#define likely(x) (x)
static int mutex_depth, rcu_depth, sync_calls;
static int nf_ct_ecache_mutex;
static void mutex_lock(int *p) { assert(!*p); *p=1; ++mutex_depth; }
static void mutex_unlock(int *p) { assert(*p); *p=0; --mutex_depth; }
#define rcu_read_lock() (++rcu_depth)
#define rcu_read_unlock() (--rcu_depth)
#define rcu_dereference(p) (p)
static void synchronize_rcu(void) { assert(!mutex_depth && !rcu_depth); ++sync_calls; }
#define cmpxchg(p,o,n) ({ unsigned int _old=*(p); if(_old==(o)) *(p)=(n); _old; })
struct nf_exp_event;
struct nf_ct_event;
struct nf_ct_event_notifier { int (*ct_event)(unsigned int,const struct nf_ct_event *); int (*exp_event)(unsigned int,const struct nf_exp_event *); };
struct net { struct { struct nf_ct_event_notifier *nf_conntrack_event_cb; struct list_head event_observers; } ct; };
struct nf_conn { struct net *net; };
struct nf_ct_event { struct nf_conn *ct; unsigned int portid; int report; };
struct nf_conntrack_ecache { unsigned int ctmask,missed; };
static struct net *nf_ct_net(struct nf_conn *ct) { return ct->net; }
'''
    code = structure(text, "nf_ct_event_observer")
    for name in ("nf_conntrack_notify_observers", "nf_conntrack_register_event_observer",
                 "nf_conntrack_unregister_event_observer", "__nf_conntrack_eventmask_report"):
        code += function(text, name)
    code = function(header, "nf_conntrack_has_event_observers") + code
    main = r'''
static int primary_calls, observer_calls;
static int primary(unsigned int e,const struct nf_ct_event *i) { assert(rcu_depth); ++primary_calls; return -ENOBUFS; }
static int observe(unsigned int e,const struct nf_ct_event *i) { assert(rcu_depth); ++observer_calls; return -EPERM; }
int main(void) {
 struct net net={0}; struct nf_conn ct={.net=&net}; struct nf_ct_event item={.ct=&ct};
 struct nf_conntrack_ecache ec={.ctmask=~0u};
 struct nf_ct_event_notifier p={.ct_event=primary}, o={.ct_event=observe}, invalid={0};
 INIT_LIST_HEAD(&net.ct.event_observers); net.ct.nf_conntrack_event_cb=&p;
 assert(nf_conntrack_register_event_observer(&net,&invalid)==-EINVAL);
 fail_alloc=1; assert(nf_conntrack_register_event_observer(&net,&o)==-ENOMEM); fail_alloc=0;
 assert(!nf_conntrack_register_event_observer(&net,&o));
 assert(nf_conntrack_register_event_observer(&net,&o)==-EEXIST);
 assert(net.ct.nf_conntrack_event_cb==&p);
 assert(__nf_conntrack_eventmask_report(&ec,1,0,&item)==-ENOBUFS);
 assert(primary_calls==1 && observer_calls==1 && ec.missed==1);
 nf_conntrack_unregister_event_observer(&net,&o);
 assert(sync_calls==1 && list_empty(&net.ct.event_observers) && net.ct.nf_conntrack_event_cb==&p);
 __nf_conntrack_eventmask_report(&ec,1,0,&item); assert(primary_calls==2 && observer_calls==1);
 net.ct.nf_conntrack_event_cb=NULL;
 assert(!nf_conntrack_register_event_observer(&net,&o)); ec.missed=0;
 assert(!__nf_conntrack_eventmask_report(&ec,1,0,&item)); assert(observer_calls==2);
 nf_conntrack_unregister_event_observer(&net,&o);
 assert(!mutex_depth && !rcu_depth && sync_calls==2);
 return 0;
}
'''
    c_test("conntrack observers preserve primary delivery and unregister lifetime", harness + code + main)


def test_rx(backports):
    import re
    ath = backports / "drivers/net/wireless/ath/ath11k"
    text = (ath / "dp_rx.c").read_text()
    body = function(text, "ath11k_dp_rxdma_ring_sel_config")
    size = re.search(r"(?m)^#define ATH11K_DP_RXDMA_NSS_REFILL_RING_SIZE\s+(\d+)",
                     (ath / "hw.h").read_text())
    assert size, "review the small-memory NSS buffer definition"
    harness = LIST + f"\n#define DP_RXDMA_NSS_REFILL_RING_SIZE {size.group(1)}\n" + r'''
#define DP_RX_BUFFER_SIZE 2048
#define DP_RXDMA_REFILL_RING_SIZE 512
#define HAL_RXDMA_BUF 1
#define HTT_RX_RXDMA_FILTER_TLV_FLAGS_BUF_RING 1
#define HTT_RX_FP_CTRL_PKT_FILTER_TLV_FLAGS2_BAR 2
#define HTT_RX_FP_DATA_PKT_FILTER_TLV_FLASG3_MCAST 4
#define HTT_RX_FP_DATA_PKT_FILTER_TLV_FLASG3_UCAST 8
struct htt_rx_ring_tlv_filter { unsigned int rx_filter,pkt_filter_flags2,pkt_filter_flags3; bool offset_valid; unsigned int rx_packet_offset,rx_header_offset; };
struct ath11k_base { struct { unsigned int hal_desc_sz; } hw_params; struct { bool enabled; } nss; };
struct ath11k_pdev_dp { struct { struct { int ring_id; } refill_buf_ring; } rx_refill_buf_ring; int mac_id; };
struct ath11k { struct ath11k_base *ab; struct ath11k_pdev_dp dp; };
static unsigned int bytes; static int setup_result;
static void ath11k_dp_get_rx_header_offset(struct ath11k_base *a,struct htt_rx_ring_tlv_filter *f) {}
static int ath11k_dp_tx_htt_rx_filter_setup(struct ath11k_base *a,int r,int m,int type,unsigned int n,struct htt_rx_ring_tlv_filter *f) {
 assert(f->offset_valid && f->rx_packet_offset==a->hw_params.hal_desc_sz); bytes=n; return setup_result;
}
'''
    main = r'''
int main(void) {
 struct ath11k_base ab={0}; struct ath11k ar={.ab=&ab};
 for(unsigned int tlv=256;tlv<=384;tlv+=128) {
 ab.hw_params.hal_desc_sz=tlv; ab.nss.enabled=false;
 assert(!ath11k_dp_rxdma_ring_sel_config(&ar) && bytes==2048 && bytes!=DP_RXDMA_REFILL_RING_SIZE);
 ab.nss.enabled=true; assert(!ath11k_dp_rxdma_ring_sel_config(&ar));
 assert(bytes==DP_RXDMA_NSS_REFILL_RING_SIZE && bytes<=2048);
 /* Real TLVs plus rounded pad, native Wi-Fi, mesh, SNAP and 1500 payload. */
 assert(bytes>=tlv+4+30+18+8+1500);
 }
 ab.nss.enabled=false; setup_result=-ETIMEDOUT;
 assert(ath11k_dp_rxdma_ring_sel_config(&ar)==-ETIMEDOUT && bytes==2048);
 return 0;
}
'''
    c_test("host RX bytes, 256/384-byte NSS TLVs, full MTU capacity and error propagation", harness + body + main)


def test_bridge(clients):
    text = (clients / "bridge/nss_bridge_mgr.c").read_text()
    harness = LIST + r'''
#define NSS_TX_SUCCESS 0
#define nss_bridge_mgr_warn(...) ((void)0)
#define ASSERT_RTNL() assert(rtnl_held)
#define HZ 100
#define system_wq NULL
static int rtnl_held, joins, leaves, fail_join, fail_leave, queued;
enum nl80211_iftype { NL80211_IFTYPE_STATION=2, NL80211_IFTYPE_AP=3, NL80211_IFTYPE_AP_VLAN=4 };
struct wireless_dev { enum nl80211_iftype iftype; };
struct net_device { char name[16]; int ifnum,refs; bool bridge,running; struct wireless_dev *ieee80211_ptr; struct net_device *master; struct list_head node,lowers; };
struct lower_link { struct list_head list; struct net_device *dev; };
struct nss_bridge_pvt { struct list_head list,members; struct net_device *dev; uint32_t ifnum; };
static struct { struct list_head list; } br_mgr_ctx;
struct work_struct { int dummy; }; struct delayed_work { int dummy; };
static struct delayed_work nss_bridge_reconcile_work;
static unsigned int nss_bridge_reconcile_retries;
static bool nss_bridge_stopping;
struct net { struct list_head devices; }; static struct net init_net;
#define for_each_netdev(n,d) list_for_each_entry(d,&(n)->devices,node)
#define netdev_for_each_lower_dev(d,l,i) \
 for(i=(d)->lowers.next; i!=&(d)->lowers && ((l)=container_of(i,struct lower_link,list)->dev,1); i=i->next)
static bool netif_is_bridge_master(struct net_device *d) { return d->bridge; }
static bool netif_running(struct net_device *d) { return d->running; }
static struct net_device *netdev_master_upper_dev_get(struct net_device *d) { return d->master; }
static void rtnl_lock(void) { assert(!rtnl_held); rtnl_held=1; }
static void rtnl_unlock(void) { assert(rtnl_held); rtnl_held=0; }
static int mod_delayed_work(void *w,struct delayed_work *d,int delay) { ++queued; return 0; }
static void nss_bridge_mgr_schedule_reconcile(void) { ++queued; }
static void dev_hold(struct net_device *d) { ++d->refs; }
static void dev_put(struct net_device *d) { assert(d->refs>1); --d->refs; }
static int nss_cmn_get_interface_number_by_dev(struct net_device *d) { return d->ifnum; }
static int nss_bridge_tx_join_msg(int n,struct net_device *d) { ++joins; return fail_join; }
static int nss_bridge_tx_leave_msg(int n,struct net_device *d) { assert(d->refs>1); ++leaves; return fail_leave; }
static struct nss_bridge_pvt *nss_bridge_mgr_find_instance(struct net_device *d) {
 struct nss_bridge_pvt *b; list_for_each_entry(b,&br_mgr_ctx.list,list) if(b->dev==d) return b; return NULL;
}
static int nss_bridge_mgr_register_br(struct net_device *d) { return -EIO; }
'''
    code = structure(text, "nss_bridge_member")
    for name in ("nss_bridge_mgr_find_member", "nss_bridge_mgr_delete_member",
                 "nss_bridge_mgr_ap_host_port", "nss_bridge_mgr_keep_ap_on_host",
                 "nss_bridge_mgr_join_bridge", "nss_bridge_mgr_leave_bridge", "nss_bridge_mgr_reconcile"):
        code += function(text, name)
    main = r'''
int main(void) {
 struct net_device a={.bridge=true,.running=true,.refs=1}, b={.bridge=true,.running=true,.refs=1};
 struct wireless_dev station={.iftype=NL80211_IFTYPE_STATION};
 struct net_device ap={.ifnum=-1,.refs=1,.running=true,.ieee80211_ptr=&station,.master=&a};
 struct net_device lan={.ifnum=-1,.refs=1,.running=true,.master=&a};
 struct nss_bridge_pvt ba={.dev=&a,.ifnum=40},bb={.dev=&b,.ifnum=41};
 struct lower_link la={.dev=&ap}, ll={.dev=&lan}; struct work_struct work={0};
 INIT_LIST_HEAD(&init_net.devices); INIT_LIST_HEAD(&br_mgr_ctx.list);
 INIT_LIST_HEAD(&a.lowers); INIT_LIST_HEAD(&b.lowers); INIT_LIST_HEAD(&ba.members); INIT_LIST_HEAD(&bb.members);
 list_add_tail(&a.node,&init_net.devices); list_add_tail(&b.node,&init_net.devices);
 list_add_tail(&ba.list,&br_mgr_ctx.list); list_add_tail(&bb.list,&br_mgr_ctx.list);
 list_add_tail(&la.list,&a.lowers); list_add_tail(&ll.list,&a.lowers);
 nss_bridge_reconcile_retries=10; nss_bridge_mgr_reconcile(&work);
 assert(queued==1 && joins==0); ap.ifnum=32; nss_bridge_mgr_reconcile(&work);
 assert(joins==1 && ap.refs==2); nss_bridge_mgr_reconcile(&work); assert(joins==1);
 rtnl_held=1; assert(nss_bridge_mgr_join_bridge(&lan,&ba)==-EINVAL && lan.refs==1);
 fail_leave=1; assert(nss_bridge_mgr_leave_bridge(&ap,&ba)!=0 && ap.refs==2);
 assert(nss_bridge_mgr_join_bridge(&ap,&bb)==-EAGAIN && joins==1);
 list_del(&la.list); list_add_tail(&la.list,&b.lowers); ap.master=&b; rtnl_held=0;
 fail_leave=0; nss_bridge_mgr_reconcile(&work); assert(joins==2 && ap.refs==2);
 rtnl_held=1; assert(!nss_bridge_mgr_find_member(&ba,&ap)); assert(nss_bridge_mgr_find_member(&bb,&ap));
 ap.ifnum=-1; int previous=leaves; assert(!nss_bridge_mgr_leave_bridge(&ap,&bb));
 assert(leaves==previous && ap.refs==1 && list_empty(&bb.members));
 ap.ifnum=33; fail_join=1; assert(nss_bridge_mgr_join_bridge(&ap,&bb)==-EIO && ap.refs==2);
 assert(nss_bridge_mgr_find_member(&bb,&ap)->uncertain);
 assert(nss_bridge_mgr_join_bridge(&ap,&bb)==-EAGAIN && ap.refs==2);
 fail_join=0; assert(!nss_bridge_mgr_leave_bridge(&ap,&bb) && ap.refs==1);
 fail_alloc=1; assert(nss_bridge_mgr_join_bridge(&ap,&bb)==-ENOMEM && ap.refs==1);
 fail_alloc=0; rtnl_held=0; nss_bridge_stopping=true; previous=joins;
 nss_bridge_mgr_reconcile(&work); assert(joins==previous); return 0;
}
'''
    c_test("bridge STA late registration, duplicate joins, leave NACK retries and references", harness + code + main)


def test_mec(backports):
    ath = backports / "drivers/net/wireless/ath/ath11k"
    peer = (ath / "peer.c").read_text()
    nss = (ath / "nss.c").read_text()
    start = peer.index("#ifdef CPTCFG_ATH11K_NSS_SUPPORT", peer.index("peer->vif = arvif->vif;"))
    binding = peer[start:peer.index("#endif", start) + len("#endif")]
    harness = LIST + r'''
#define CPTCFG_ATH11K_NSS_SUPPORT 1
#define NL80211_IFTYPE_STATION 1
#define ATH11K_AST_TYPE_MEC 1
#define ETH_ALEN 6
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define lockdep_assert_held(p) ((void)0)
#define swab32 __builtin_bswap32
#define swab16 __builtin_bswap16
typedef struct { unsigned value; } refcount_t;
static void refcount_set(refcount_t *r,unsigned value) { r->value=value; }
static bool refcount_dec_and_test(refcount_t *r) { assert(r->value);return --r->value==0; }
struct ath11k_ast_entry { struct list_head ase_list; };
struct ath11k_peer { struct list_head list,ast_entry_list; refcount_t refs; u8 addr[6]; u32 vdev_id; int peer_id; struct ath11k_ast_entry *self_ast_entry; };
struct ath11k_base { int base_lock,base_ast_lock; struct { bool enabled,ownership_uncertain; struct list_head retained_host_peers; } nss; };
struct ieee80211_vif { int type; u8 addr[6]; };
struct ath11k { struct ath11k_base *ab; struct ath11k_peer *bss_peer; struct list_head peers; int num_peers,conf_mutex,tbl_mtx_lock,peer_mapping_wq; };
struct ath11k_vif { struct ath11k *ar; struct ieee80211_vif *vif; u32 vdev_id; };
static struct ath11k *shared_ar; static int delete_on_lock,ast_calls;
static void spin_lock_bh(int *p) {
 assert(!*p);
 if(delete_on_lock) { free(shared_ar->bss_peer); shared_ar->bss_peer=NULL; delete_on_lock=0; }
 *p=1;
}
static void spin_unlock_bh(int *p) { assert(*p); *p=0; }
static void mutex_lock(int *p) { ++*p; }
static void mutex_unlock(int *p) { --*p; }
static void wake_up(int *p) {}
static bool ether_addr_equal(const u8 *a,const u8 *b) { return !memcmp(a,b,6); }
static struct ath11k_peer *ath11k_peer_find_list_by_id(struct ath11k *a,int id) {
 struct ath11k_peer *p; list_for_each_entry(p,&a->peers,list) if(p->peer_id==id) return p; return NULL;
}
static struct ath11k_ast_entry *ath11k_peer_ast_find_by_peer(struct ath11k *a,struct ath11k_peer *p,u8 *m) { return NULL; }
static void ath11k_peer_del_ast(struct ath11k *a,struct ath11k_ast_entry *p) {}
static void ath11k_peer_ast_cleanup(struct ath11k *a,struct ath11k_peer *p,bool w,u32 n) {}
/* This fixture covers BSS/MEC peer references; the independent NSS state and
 * its DMA retirement are exercised by test-nss-peer-lifetime.py.
 */
static void ath11k_nss_peer_detach(struct ath11k *a,struct ath11k_peer *p) { assert(a->ab->base_lock && p); }
static void ath11k_peer_rhash_delete(struct ath11k *a,struct ath11k_peer *p) {}
static void ath11k_peer_add_ast(struct ath11k *a,struct ath11k_peer *p,u8 *m,int type) {
 assert(a->ab->base_lock && p==a->bss_peer && p->vdev_id==42); ++ast_calls;
}
static struct ath11k_peer *new_peer(struct ath11k *a,int id,u32 vdev) {
 struct ath11k_peer *p=calloc(1,sizeof(*p)); assert(p); p->refs.value=1; p->peer_id=id; p->vdev_id=vdev;
 INIT_LIST_HEAD(&p->ast_entry_list); list_add_tail(&p->list,&a->peers); ++a->num_peers; return p;
}
'''
    code = "static void bind_peer(struct ath11k *ar, struct ieee80211_vif *vif, struct ath11k_peer *peer) {\nstruct ath11k_base *ab=ar->ab;\n" + binding + "\n}\n"
    for name in ("ath11k_peer_put_locked", "ath11k_peer_release", "ath11k_peer_unmap_event", "ath11k_peer_unmap_v2_event", "ath11k_peer_cleanup"):
        code += function(peer, name)
    code += function(nss, "ath11k_nss_mec_handler")
    main = r'''
int main(void) {
 struct ath11k_base ab={.nss.enabled=true}; struct ath11k ar={.ab=&ab};
 struct ieee80211_vif sta={.type=1},ap={.type=2}; struct ath11k_vif vif={.ar=&ar,.vif=&sta,.vdev_id=42};
 u8 mac[6]={0}; u8 payload[12] __attribute__((aligned(4)))={0,0,0,0,0x44,0x33,0x22,0x11,0x66,0x02};
 INIT_LIST_HEAD(&ar.peers); INIT_LIST_HEAD(&ab.nss.retained_host_peers); shared_ar=&ar;
 struct ath11k_peer *s=new_peer(&ar,1,42),*p=new_peer(&ar,2,43);
 bind_peer(&ar,&sta,s); bind_peer(&ar,&ap,p); assert(ar.bss_peer==s);
 ath11k_peer_unmap_v2_event(&ar,2,mac,false,0); assert(ar.bss_peer==s);
 ath11k_nss_mec_handler(&vif,payload); assert(ast_calls==1);
 vif.vdev_id=43; ath11k_nss_mec_handler(&vif,payload); assert(ast_calls==1); vif.vdev_id=42;
 ath11k_peer_unmap_event(&ar,1); assert(!ar.bss_peer && list_empty(&ar.peers));
 ar.num_peers=0; s=new_peer(&ar,3,42); bind_peer(&ar,&sta,s);
 ath11k_peer_cleanup(&ar,42); assert(!ar.bss_peer && !ar.num_peers && list_empty(&ar.peers));
 s=calloc(1,sizeof(*s)); assert(s); s->vdev_id=42; ar.bss_peer=s; delete_on_lock=1;
 ath11k_nss_mec_handler(&vif,payload); assert(!ar.bss_peer && ast_calls==1 && !ab.base_lock);
 return 0;
}
'''
    c_test("STA MEC peer identity, all release paths and receive/unmap lock race", harness + code + main)


def test_rxrate(backports):
    ath = backports / "drivers/net/wireless/ath/ath11k"
    nss = (ath / "nss.c").read_text()
    mac = (ath / "mac.c").read_text()
    harness = LIST + r'''
#define ATH11K_LEGACY_NUM 12
#define ATH11K_HT_MCS_NUM 32
#define ATH11K_VHT_MCS_MAX 9
#define ATH11K_HE_MCS_MAX 11
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define __cpu_to_le16(x) (x)
enum { WMI_RATE_PREAMBLE_OFDM, WMI_RATE_PREAMBLE_CCK, WMI_RATE_PREAMBLE_HT,
       WMI_RATE_PREAMBLE_VHT, WMI_RATE_PREAMBLE_HE };
enum { HAL_RX_GI_0_8_US, HAL_RX_GI_0_4_US, HAL_RX_GI_1_6_US, HAL_RX_GI_3_2_US };
enum { HAL_RX_BW_20MHZ, HAL_RX_BW_40MHZ, HAL_RX_BW_80MHZ, HAL_RX_BW_160MHZ, HAL_RX_BW_MAX };
enum { RX_MSDU_START_SGI_0_8_US, RX_MSDU_START_SGI_0_4_US,
       RX_MSDU_START_SGI_1_6_US, RX_MSDU_START_SGI_3_2_US };
enum nl80211_he_gi { NL80211_RATE_INFO_HE_GI_0_8, NL80211_RATE_INFO_HE_GI_1_6, NL80211_RATE_INFO_HE_GI_3_2 };
enum { ATH11K_BW_20, ATH11K_BW_40, ATH11K_BW_80, ATH11K_BW_160 };
enum { RATE_INFO_BW_20, RATE_INFO_BW_5, RATE_INFO_BW_10,
       RATE_INFO_BW_40, RATE_INFO_BW_80, RATE_INFO_BW_160 };
enum { RATE_INFO_FLAGS_MCS=1, RATE_INFO_FLAGS_VHT_MCS=2,
       RATE_INFO_FLAGS_SHORT_GI=4, RATE_INFO_FLAGS_HE_MCS=8 };
struct rate_info { u16 legacy; u8 flags,mcs,nss,bw,he_gi,he_dcm,he_ru_alloc; };
struct rx_stats { struct rate_info rxrate; };
struct ath11k_base { struct { bool enabled; } nss; };
struct ath11k { struct ath11k_base *ab; u8 num_rx_chains; };
struct ath11k_vif { struct ath11k *ar; };
struct ath11k_peer { struct ath11k_vif *vif; struct { struct rx_stats *nss_stats; } nss; };
struct hal_rx_mon_ppdu_info { u16 frame_control; u32 preamble_type; u8 mcs,nss,bw,gi,rate,dcm,ru_alloc; };
struct hal_rx_user_status { u32 preamble_type; u8 mcs,nss; };
static int warnings;
#define ath11k_warn(ab,fmt,...) (++warnings)
static bool ieee80211_is_data(u16 fc) { return (fc & 12)==8; }
static struct ath11k_vif *ath11k_vif_to_arvif(struct ath11k_vif *vif) { return vif; }
'''
    code = function(mac, "ath11k_mac_he_gi_to_nl80211_he_gi")
    code += function(mac, "ath11k_mac_bw_to_mac80211_bw")
    code += function(nss, "ath11k_nss_update_sta_rxrate")
    main = r'''
int main(void) {
 struct ath11k_base ab={.nss.enabled=true}; struct ath11k ar={.ab=&ab,.num_rx_chains=2};
 struct ath11k_vif vif={.ar=&ar}; struct rx_stats stats;
 struct ath11k_peer peer={.vif=&vif,.nss.nss_stats=&stats};
 struct hal_rx_mon_ppdu_info p={.frame_control=8};
 struct { u8 pre,mcs,nss,bw,gi,chains; bool valid; } cases[]={
  {2,0,1,0,0,2,true},{2,31,4,1,1,4,true},
  {3,0,1,0,0,2,true},{4,0,1,0,0,2,true},
  {3,9,1,3,1,2,true},{3,9,2,3,0,2,true},
  {3,9,0,3,0,2,false},{3,9,3,3,0,2,false},{3,9,5,3,0,2,false},
  {3,9,2,3,0,1,false},{3,10,2,3,0,2,false},
  {3,9,2,4,0,2,false},{3,9,2,3,2,2,false},
  {2,7,1,1,1,2,true},{2,8,2,1,0,2,true},{2,15,2,0,1,2,true},
  {2,16,3,1,0,2,false},{2,32,1,1,0,2,false},{2,8,1,1,0,2,false},
  {2,7,1,2,0,2,false},{2,7,1,1,2,2,false},
  {4,11,2,3,0,2,true},{4,11,2,3,2,2,true},{4,11,2,3,3,2,true},
  {4,12,2,3,0,2,false},{4,11,2,3,1,2,false},{4,11,2,3,4,2,false},
  {4,11,2,4,0,2,false},{4,11,2,3,0,0,false},{99,0,1,0,0,2,false},
 };
 for(size_t i=0;i<ARRAY_SIZE(cases);++i) {
  memset(&stats,0xa5,sizeof(stats)); struct rate_info old=stats.rxrate;
  p.preamble_type=cases[i].pre; p.mcs=cases[i].mcs; p.nss=cases[i].nss;
  p.bw=cases[i].bw; p.gi=cases[i].gi; p.dcm=1; p.ru_alloc=3;
  ar.num_rx_chains=cases[i].chains; warnings=0;
  ath11k_nss_update_sta_rxrate(&p,&peer,NULL);
  assert(warnings==!cases[i].valid);
  if(!cases[i].valid) { assert(!memcmp(&old,&stats.rxrate,sizeof(old))); continue; }
  assert(!stats.rxrate.legacy && stats.rxrate.mcs==cases[i].mcs && stats.rxrate.nss==cases[i].nss);
  assert(stats.rxrate.bw==ath11k_mac_bw_to_mac80211_bw(p.bw));
  if(p.preamble_type==4) {
   assert(stats.rxrate.flags==RATE_INFO_FLAGS_HE_MCS && stats.rxrate.he_dcm==1 && stats.rxrate.he_ru_alloc==3);
   assert(stats.rxrate.he_gi==ath11k_mac_he_gi_to_nl80211_he_gi(p.gi));
  } else {
   assert(!stats.rxrate.he_gi && !stats.rxrate.he_dcm && !stats.rxrate.he_ru_alloc);
   assert(!!(stats.rxrate.flags & RATE_INFO_FLAGS_SHORT_GI)==!!p.gi);
  }
 }
 /* Legacy indices must match their modulation; unrelated fields are ignored. */
 const u16 legacy[]={10,20,55,60,90,110,120,180,240,360,480,540};
 for(unsigned pre=0;pre<2;++pre) for(unsigned rate=0;rate<13;++rate) {
  bool cck=rate==0 || rate==1 || rate==2 || rate==5;
  bool valid=rate<12 && cck==(pre==1);
  memset(&stats,0xa5,sizeof(stats)); struct rate_info old=stats.rxrate; warnings=0;
  p.preamble_type=pre; p.rate=rate; p.mcs=255; p.nss=255; p.bw=255; p.gi=255;
  ath11k_nss_update_sta_rxrate(&p,&peer,NULL);
  assert(warnings==!valid);
  if(valid) assert(stats.rxrate.legacy==legacy[rate] && !stats.rxrate.flags && !stats.rxrate.nss &&
                   !stats.rxrate.he_ru_alloc && !stats.rxrate.he_gi && !stats.rxrate.he_dcm);
  else assert(!memcmp(&old,&stats.rxrate,sizeof(old)));
 }
 /* MU overrides only MCS/NSS/preamble; BW/GI still belong to this PPDU. */
 ar.num_rx_chains=2; p.preamble_type=99; p.mcs=255; p.nss=255; p.bw=3; p.gi=2;
 struct hal_rx_user_status user={.preamble_type=4,.mcs=11,.nss=2}; warnings=0;
 ath11k_nss_update_sta_rxrate(&p,&peer,&user); assert(!warnings && stats.rxrate.mcs==11 && stats.rxrate.nss==2);
 struct rate_info old=stats.rxrate; user.nss=5; warnings=0;
 ath11k_nss_update_sta_rxrate(&p,&peer,&user); assert(warnings==1 && !memcmp(&old,&stats.rxrate,sizeof(old)));
 p.preamble_type=3; p.mcs=9; p.nss=2; p.gi=0; user.preamble_type=99; warnings=0;
 ath11k_nss_update_sta_rxrate(&p,&peer,&user); assert(warnings==1 && !memcmp(&old,&stats.rxrate,sizeof(old)));
 /* Existing early returns must neither clear the cache nor warn. */
 warnings=0; ab.nss.enabled=false; ath11k_nss_update_sta_rxrate(&p,&peer,NULL);
 assert(!warnings && !memcmp(&old,&stats.rxrate,sizeof(old))); ab.nss.enabled=true;
 p.frame_control=0; ath11k_nss_update_sta_rxrate(&p,&peer,NULL);
 assert(!warnings && !memcmp(&old,&stats.rxrate,sizeof(old))); p.frame_control=8;
 peer.nss.nss_stats=NULL; ath11k_nss_update_sta_rxrate(&p,&peer,NULL); assert(!warnings);
 return 0;
}
'''
    c_test("NSS RX rate bounds, SU/MU selection and preservation of valid samples", harness + code + main)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=Path)
    parser.add_argument("--backports", type=Path)
    parser.add_argument("--kernel", type=Path)
    args = parser.parse_args()
    test_ecm_service()
    if args.kernel:
        test_observers(args.kernel)
    if args.backports:
        test_rx(args.backports)
        test_mec(args.backports)
        test_rxrate(args.backports)
    if args.clients:
        test_bridge(args.clients)
