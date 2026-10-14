#!/usr/bin/env python3
"""Exercise actual wired-NSS control functions without touching a router."""
from pathlib import Path
import argparse
import runpy

ROOT = Path(__file__).resolve().parents[2]
helpers = runpy.run_path(str(ROOT / "scripts/tests/test-nss-relay.py"))
function, structure = helpers["function"], helpers["structure"]
c_test, LIST = helpers["c_test"], helpers["LIST"]


def test_nodes():
    text = (ROOT / "package/kernel/qca-dsa-nss/src/qca_dsa_nss.c").read_text()
    harness = LIST + r'''
#define DSA_NSS_MAX_NODES 32
#define DSA_NSS_MAX_CONDUITS 4
#define ETH_ALEN 6
#define NSS_MAX_PHYSICAL_INTERFACES 4
#define NSS_DYNAMIC_INTERFACE_TYPE_VLAN 1
#define NSS_TX_SUCCESS 0
#define ETH_P_8021Q 0x8100
#define THIS_MODULE NULL
#define EXPORT_SYMBOL_GPL(x)
struct net_device { unsigned mtu; unsigned char dev_addr[6]; int refs,ifnum; };
enum dsa_nss_phase { DSA_NSS_FREE, DSA_NSS_CONFIGURING, DSA_NSS_READY,
 DSA_NSS_REVOKING, DSA_NSS_UNKNOWN };
static int table_lock,pins,config_count,fail_config,fail_join,fail_leave,fail_dealloc,fail_alloc_node;
static int publications,withdrawals,unregistrations,deallocations,joins,syncs;
static bool ready,pinned,paused,allocation_uncertain;
static void (*pause_fn)(bool);
static bool physical_ready=true;
static bool nss_data_plane_is_ready(struct net_device *d) { return physical_ready; }
static void fake_pause(bool p) {}
static void spin_lock_bh(int *p) { assert(!*p); *p=1; }
static void spin_unlock_bh(int *p) { assert(*p); *p=0; }
static void __module_get(void *m) { ++pins; }
static void module_put(void *m) { assert(pins); --pins; }
static void dev_hold(struct net_device *d) { ++d->refs; }
static void dev_put(struct net_device *d) { assert(d->refs>1); --d->refs; }
static void ether_addr_copy(unsigned char *d,const unsigned char *s) { memcpy(d,s,6); }
static int nss_cmn_get_interface_number_by_dev(struct net_device *d) { return d->ifnum; }
static int nss_dynamic_interface_alloc_node(int t) { return fail_alloc_node ? -1 : 32; }
static void *nss_vlan_prepare_if(int n,void *p) { return (void *)1; }
static int configure(void) { ++config_count; return config_count==fail_config ? 1 : 0; }
static int nss_vlan_tx_set_mac_addr_msg(int n,void *m) { return configure(); }
static int nss_vlan_tx_set_mtu_msg(int n,unsigned m) { return configure(); }
static int nss_vlan_tx_add_tag_msg(int n,unsigned tag,int next,int phys) {
 assert(tag==((0x8100u<<16)|3089) && next==2 && phys==2); return configure();
}
static void nss_vlan_publish_if(int n,void *cb,struct net_device *d,int f,void *p) {
 assert(config_count==3 && !fail_config); ++publications;
}
static int nss_bridge_mgr_offload_port_join(struct net_device *d) { ++joins; return fail_join; }
static int nss_bridge_mgr_offload_port_revoke(struct net_device *d,int n) {
 assert(n==32); return fail_leave;
}
static void nss_vlan_withdraw_if(int n) { ++withdrawals; }
static void synchronize_net(void) { ++syncs; }
static void nss_unregister_vlan_if(int n) { ++unregistrations; }
static int nss_dynamic_interface_dealloc_node(int n,int type) { ++deallocations; return fail_dealloc; }
'''
    code = ""
    for name in ("dsa_nss_node", "dsa_nss_conduit", "dsa_nss_want"):
        code += structure(text, name)
    code += "static struct dsa_nss_node nodes[DSA_NSS_MAX_NODES];\n"
    code += "static struct dsa_nss_conduit conduits[DSA_NSS_MAX_CONDUITS];\n"
    for name in ("owner_pin", "owner_has_resources", "owner_unpin_if_empty",
                 "node_create", "node_destroy", "qca_dsa_nss_if_num"):
        code += function(text, name)
    main = r'''
int main(void) {
 struct net_device port={.mtu=1500,.refs=1,.ifnum=32}, phys={.refs=1,.ifnum=2};
 struct dsa_nss_want w={.dev=&port,.conduit=&phys,.vid=3089};
 for(int i=0;i<DSA_NSS_MAX_NODES;i++) nodes[i].ifnum=-1;
 /* Every configuration failure precedes publication; ownership is still saved. */
 for(int failure=1;failure<=3;failure++) {
  fail_config=failure; config_count=0;
  assert(node_create(&nodes[0],&w)==-EIO && nodes[0].ifnum==32);
  assert(!publications && !joins && pinned && pins==1 && port.refs==2);
  assert(!node_destroy(&nodes[0]) && port.refs==1);
  owner_unpin_if_empty(); assert(!pins && !pinned);
 }
 fail_config=0; config_count=0; fail_join=-EIO;
 assert(node_create(&nodes[0],&w)==-EIO && nodes[0].published && port.refs==2);
 /* Failed leave must not withdraw a published ID or attempt deallocation. */
 int old_dealloc=deallocations,old_withdraw=withdrawals;
 fail_leave=-ETIMEDOUT;
 assert(node_destroy(&nodes[0])==-ETIMEDOUT && nodes[0].phase==DSA_NSS_UNKNOWN);
 assert(nodes[0].published && nodes[0].ifnum==32 && port.refs==2);
 assert(deallocations==old_dealloc && withdrawals==old_withdraw && pins==1);
 fail_leave=0; fail_dealloc=1;
 assert(node_destroy(&nodes[0])==-EIO && nodes[0].ifnum==32 && port.refs==2);
 assert(!nodes[0].published && !nodes[0].handler);
 int old_unregister=unregistrations;
 fail_dealloc=0; assert(!node_destroy(&nodes[0]) && nodes[0].ifnum==-1);
 assert(unregistrations==old_unregister && port.refs==1);
 owner_unpin_if_empty(); assert(!pins);
 fail_join=0; config_count=0;
 assert(!node_create(&nodes[0],&w) && nodes[0].phase==DSA_NSS_READY);
 assert(qca_dsa_nss_if_num(&phys,3089)==-1);
 ready=true; assert(qca_dsa_nss_if_num(&phys,3089)==-1);
 pause_fn=fake_pause; assert(qca_dsa_nss_if_num(&phys,3089)==32);
 physical_ready=false; assert(qca_dsa_nss_if_num(&phys,3089)==-1);
 physical_ready=true;
 assert(qca_dsa_nss_if_num(&phys,3090)==-1);
 nodes[0].phase=DSA_NSS_REVOKING; assert(qca_dsa_nss_if_num(&phys,3089)==-1);
 assert(!node_destroy(&nodes[0])); ready=false; owner_unpin_if_empty();
 /* A timed-out allocation has no safe reusable ID. Even with no listed node,
  * it must prevent module reload and blind allocation retries this boot. */
 fail_alloc_node=1;
 assert(node_create(&nodes[0],&w)==-EIO && allocation_uncertain && nodes[0].ifnum<0);
 owner_unpin_if_empty(); assert(pinned && pins==1 && owner_has_resources());
 return 0;
}
'''
    c_test("DSA configuration ACK gates, failed revoke/dealloc ownership and readiness", harness + code + main)


def test_phy(drv):
    text = (drv / "nss_phys_if.c").read_text()
    harness = LIST + r'''
typedef uintptr_t nss_ptr_t;
typedef int nss_tx_status_t;
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_PHYS_IF_TX_TIMEOUT 3000
struct semaphore { int locked; };
struct completion { int done; };
struct nss_ctx_instance { int dummy; };
struct nss_phys_if_msg { struct { nss_ptr_t app_data; int response; } cm; };
static int phif_sync_lock,scenario,send_failure;
static unsigned phif_timeouts,phif_stale_responses;
static nss_ptr_t abandoned;
static void spin_lock_bh(int *p) { assert(!*p); *p=1; }
static void spin_unlock_bh(int *p) { assert(*p); *p=0; }
static void down(struct semaphore *s) { assert(!s->locked); s->locked=1; }
static void up(struct semaphore *s) { assert(s->locked); s->locked=0; }
static void reinit_completion(struct completion *c) { c->done=0; }
static void complete(struct completion *c) { ++c->done; }
#define msecs_to_jiffies(x) (x)
static int nss_phys_if_msg(struct nss_ctx_instance *ctx,struct nss_phys_if_msg *m) {
 if(scenario==1) abandoned=m->cm.app_data;
 return send_failure;
}
static unsigned wait_for_completion_timeout(struct completion *c,unsigned timeout);
'''
    # This is the actual static transaction structure, not a second implementation.
    start = text.index("static struct nss_phys_if_pvt {")
    end = text.index("} phif;", start) + len("} phif;")
    code = text[start:end] + "\n" + function(text, "nss_phys_if_callback")
    code += function(text, "nss_phys_if_msg_sync")
    main = r'''
static unsigned wait_for_completion_timeout(struct completion *c,unsigned timeout) {
 struct nss_phys_if_msg reply={.cm.response=NSS_CMN_RESPONSE_ACK};
 if(scenario==1) return 0;
 if(scenario==2) {
  reply.cm.response=99; nss_phys_if_callback((void *)abandoned,&reply);
  assert(!c->done && phif.waiting && phif.response==NSS_TX_FAILURE);
 }
 reply.cm.response=NSS_CMN_RESPONSE_ACK;
 nss_phys_if_callback((void *)phif.serial,&reply);
 assert(c->done==1 && !phif.waiting);
 nss_phys_if_callback((void *)phif.serial,&reply); assert(c->done==1);
 return 1;
}
int main(void) {
 struct nss_ctx_instance ctx={0}; struct nss_phys_if_msg msg={0};
 scenario=1; assert(nss_phys_if_msg_sync(&ctx,&msg)==NSS_TX_FAILURE);
 assert(phif_timeouts==1 && !phif.waiting && !phif.sem.locked);
 scenario=2; assert(nss_phys_if_msg_sync(&ctx,&msg)==NSS_TX_SUCCESS);
 assert(phif_stale_responses==2 && !phif.waiting && !phif.sem.locked);
 struct nss_phys_if_msg reply={.cm.response=99};
 nss_phys_if_callback((void *)phif.serial,&reply); assert(phif.response==NSS_TX_SUCCESS);
 send_failure=7; assert(nss_phys_if_msg_sync(&ctx,&msg)==7 && !phif.waiting);
 send_failure=0; scenario=0; phif.serial=(nss_ptr_t)-1;
 assert(!nss_phys_if_msg_sync(&ctx,&msg) && phif.serial==1);
 assert(!phif_sync_lock && !phif.sem.locked);
 return 0;
}
'''
    c_test("PHY timeout, late/duplicate ACK isolation, send failure and serial wrap", harness + code + main)


def test_control(drv, kind):
    text = (drv / ("nss_" + kind + ".c")).read_text()
    prefix, pvt = "nss_" + kind, kind + "_pvt"
    harness = LIST + r'''
#include <pthread.h>
typedef uintptr_t nss_ptr_t;
typedef int nss_tx_status_t;
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_TX_FAILURE_NOT_READY 8
#define NSS_CMN_RESPONSE_ACK 0
#define TX_TIMEOUT 100
struct semaphore { pthread_mutex_t lock; };
struct completion { pthread_mutex_t lock; pthread_cond_t cond; int done; };
struct nss_ctx_instance { int dummy; };
struct MSG { struct { nss_ptr_t cb,app_data; int response; } cm; };
typedef void (*CALLBACK)(void *,struct MSG *);
static pthread_mutex_t SYNC_LOCK=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t ctl=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cond=PTHREAD_COND_INITIALIZER;
static int mode,sent,callback_started,timeout_observed,active_waited,release_callback,sender_done;
static nss_ptr_t cookie,abandoned;
static void spin_lock_bh(pthread_mutex_t *p) { assert(!pthread_mutex_lock(p)); }
static void spin_unlock_bh(pthread_mutex_t *p) { assert(!pthread_mutex_unlock(p)); }
static void down(struct semaphore *s) { assert(!pthread_mutex_lock(&s->lock)); }
static void up(struct semaphore *s) { assert(!pthread_mutex_unlock(&s->lock)); }
static void reinit_completion(struct completion *c) {
 pthread_mutex_lock(&c->lock); c->done=0; pthread_mutex_unlock(&c->lock);
}
static void complete(struct completion *c) {
 pthread_mutex_lock(&c->lock); ++c->done; pthread_cond_broadcast(&c->cond); pthread_mutex_unlock(&c->lock);
}
static void wait_for_completion(struct completion *c) {
 pthread_mutex_lock(&ctl); active_waited=1; pthread_cond_broadcast(&cond); pthread_mutex_unlock(&ctl);
 pthread_mutex_lock(&c->lock); while(!c->done) pthread_cond_wait(&c->cond,&c->lock); pthread_mutex_unlock(&c->lock);
}
#define msecs_to_jiffies(x) (x)
static int TX_MSG(struct nss_ctx_instance *c,struct MSG *m);
static unsigned wait_for_completion_timeout(struct completion *c,unsigned timeout);
'''
    start = text.index("static struct " + prefix + "_pvt {")
    end = text.index("} " + pvt + ";", start) + len("} " + pvt + ";")
    code = text[start:end] + "\n" + function(text, prefix + "_callback")
    code += function(text, prefix + "_tx_msg_sync")
    main = r'''
static int TX_MSG(struct nss_ctx_instance *c,struct MSG *m) {
 pthread_mutex_lock(&ctl); cookie=m->cm.app_data; sent=1; pthread_cond_broadcast(&cond); pthread_mutex_unlock(&ctl);
 if(mode==4) return 9;
 return 0;
}
static unsigned wait_for_completion_timeout(struct completion *c,unsigned timeout) {
 struct MSG reply={.cm.response=NSS_CMN_RESPONSE_ACK};
 if(mode==1) { abandoned=cookie; return 0; }
 if(mode==3) {
  pthread_mutex_lock(&ctl);
  while(!callback_started) pthread_cond_wait(&cond,&ctl);
  timeout_observed=1; pthread_cond_broadcast(&cond); pthread_mutex_unlock(&ctl); return 0;
 }
 if(mode==2) {
  reply.cm.response=99; CALLBACK_FN((void *)abandoned,&reply);
  assert(!c->done && PVT.waiting && PVT.response==NSS_TX_FAILURE);
 }
 reply.cm.response=NSS_CMN_RESPONSE_ACK;
 CALLBACK_FN((void *)cookie,&reply); assert(c->done==1 && !PVT.callback_active);
 CALLBACK_FN((void *)cookie,&reply); assert(c->done==1);
 return 1;
}
static void original(void *data,struct MSG *msg) {
 assert(*(int *)data==42);
 pthread_mutex_lock(&ctl); callback_started=1; pthread_cond_broadcast(&cond);
 while(!release_callback) pthread_cond_wait(&cond,&ctl);
 pthread_mutex_unlock(&ctl); assert(*(int *)data==42);
}
static void *sender(void *arg) {
 struct nss_ctx_instance ctx={0}; int owned_stack=42;
 struct MSG msg={.cm.cb=(nss_ptr_t)original,.cm.app_data=(nss_ptr_t)&owned_stack};
 assert(TX_SYNC(&ctx,&msg)==NSS_TX_SUCCESS);
 pthread_mutex_lock(&ctl); sender_done=1; pthread_cond_broadcast(&cond); pthread_mutex_unlock(&ctl);
 return NULL;
}
static void *receiver(void *arg) {
 struct MSG reply={.cm.response=NSS_CMN_RESPONSE_ACK}; nss_ptr_t id;
 pthread_mutex_lock(&ctl); while(!sent) pthread_cond_wait(&cond,&ctl); id=cookie; pthread_mutex_unlock(&ctl);
 CALLBACK_FN((void *)id,&reply); return NULL;
}
int main(void) {
 pthread_mutex_init(&PVT.sem.lock,NULL); pthread_mutex_init(&PVT.complete.lock,NULL);
 pthread_cond_init(&PVT.complete.cond,NULL);
 struct nss_ctx_instance ctx={0}; struct MSG msg={0};
 assert(TX_SYNC(&ctx,&msg)==NSS_TX_FAILURE_NOT_READY); PVT.registered=true;
 mode=1; assert(TX_SYNC(&ctx,&msg)==NSS_TX_FAILURE && !PVT.waiting);
 mode=2; assert(TX_SYNC(&ctx,&msg)==NSS_TX_SUCCESS);
 mode=4; assert(TX_SYNC(&ctx,&msg)==9 && !PVT.waiting && !PVT.callback_active);
 mode=3; sent=0; pthread_t tx,rx;
 assert(!pthread_create(&tx,NULL,sender,NULL)); assert(!pthread_create(&rx,NULL,receiver,NULL));
 pthread_mutex_lock(&ctl);
 while(!timeout_observed || !active_waited) pthread_cond_wait(&cond,&ctl);
 assert(!sender_done); release_callback=1; pthread_cond_broadcast(&cond); pthread_mutex_unlock(&ctl);
 assert(!pthread_join(tx,NULL) && !pthread_join(rx,NULL));
 assert(sender_done && !PVT.callback_active && !PVT.waiting);
 return 0;
}
'''
    replacements = {"MSG": prefix + "_msg", "CALLBACK": prefix + "_msg_callback_t",
                    "TX_TIMEOUT": "NSS_" + kind.upper() + "_TX_TIMEOUT",
                    "SYNC_LOCK": kind + "_sync_lock", "TX_MSG": prefix + "_tx_msg",
                    "PVT": pvt, "CALLBACK_FN": prefix + "_callback",
                    "TX_SYNC": prefix + "_tx_msg_sync"}
    # Whole identifier substitution leaves the extracted functions untouched.
    import re
    def substitute(s):
        return re.sub(r"\b(" + "|".join(replacements) + r")\b",
                      lambda m: replacements[m.group()], s)
    c_test(kind + " late ACK isolation and in-flight callback lifetime after timeout",
           substitute(harness) + code + substitute(main))


def test_dp(dp):
    text = (dp / "nss_dp_attach.c").read_text()
    header = (dp / "include/nss_dp_dev.h").read_text()
    # IPQ50xx compiles the non-EDMA-v2 helper, the second definition.
    helper = header[header.rindex("static inline uint32_t nss_dp_get_idx_from_macid"):]
    harness = LIST + r'''
#define NSS_DP_START_IFNUM 0
#define NSS_DP_MAX_INTERFACES 2
#define NSS_DP_HAL_MAX_PORTS 2
#define EXPORT_SYMBOL(x)
#define EXPORT_SYMBOL_GPL(x)
#define ASSERT_RTNL() ((void)0)
#define pr_err(...) ((void)0)
struct net_device;
struct nss_dp_dev { unsigned macid; struct net_device *netdev; };
struct net_device { struct nss_dp_dev *priv; };
struct nss_dp_data_plane_ctx { struct net_device *dev; };
struct nss_dp_data_plane_ops { int (*quiesce_dma)(struct nss_dp_data_plane_ctx *); };
static struct nss_dp_data_plane_ctx dp_global_data_plane_ctx[2];
static struct { struct nss_dp_dev *nss_dp[2]; } dp_global_ctx;
static struct nss_dp_data_plane_ops host;
static unsigned touched,disabled,carrier_off;
static void *netdev_priv(struct net_device *d) { return d->priv; }
static struct nss_dp_data_plane_ops *nss_dp_hal_get_data_plane_ops(void) { return &host; }
static void netif_tx_disable(struct net_device *d) { ++disabled; }
static void netif_carrier_off(struct net_device *d) { ++carrier_off; }
static int stop(struct nss_dp_data_plane_ctx *ctx) {
 touched=ctx->dev->priv->macid; return 0;
}
'''
    code = function(helper, "nss_dp_get_idx_from_macid")
    code += function(text, "nss_dp_get_netdev_by_nss_if_num")
    code += function(text, "nss_dp_quiesce_dma")
    main = r'''
int main(void) {
 struct net_device a,b; struct nss_dp_dev da={.macid=1,.netdev=&a},db={.macid=2,.netdev=&b};
 a.priv=&da; b.priv=&db; host.quiesce_dma=stop;
 dp_global_ctx.nss_dp[0]=&da; dp_global_ctx.nss_dp[1]=&db;
 dp_global_data_plane_ctx[0].dev=&a; dp_global_data_plane_ctx[1].dev=&b;
 assert(nss_dp_get_netdev_by_nss_if_num(-1)==NULL);
 assert(nss_dp_get_netdev_by_nss_if_num(0)==&a);
 assert(nss_dp_get_netdev_by_nss_if_num(1)==&b);
 assert(nss_dp_get_netdev_by_nss_if_num(2)==NULL);
 assert(!nss_dp_quiesce_dma(&a) && touched==1);
 assert(!nss_dp_quiesce_dma(&b) && touched==2);
 assert(disabled==2 && carrier_off==0);
 dp_global_data_plane_ctx[1].dev=&a; touched=0;
 assert(nss_dp_quiesce_dma(&b)==-ENODEV && !touched && disabled==2 && carrier_off==0);
 host.quiesce_dma=NULL; assert(nss_dp_quiesce_dma(&a)==-EOPNOTSUPP);
 return 0;
}
'''
    c_test("IPQ50xx GMAC macid/NSS numbering, both DMA contexts and interface bounds", harness + code + main)


def test_rings(dp):
    text = (dp / "hal/dp_ops/syn_gmac_dp/syn_dp.c").read_text()
    harness = LIST + r'''
#define __iomem
#define INIT_OVERRIDE 1
#define NSS_DP_PRIV_FLAG(n) (n)
#define SYN_MAC_CONFIGURATION 0
#define SYN_MAC_CST 0x02000000
#define SYN_DMA_RX_DESCRIPTOR_LIST_ADDRESS 0x100c
#define SYN_DMA_TX_DESCRIPTOR_LIST_ADDRESS 0x1010
#define SYN_DMA_CURRENT_HOST_TX_DESCRIPTOR 0x1048
#define SYN_DMA_CURRENT_HOST_RX_DESCRIPTOR 0x104c
#define SYN_DMA_STATUS 0x1014
#define SYN_DMA_TX_STATE 0x700000
#define SYN_DMA_RX_STATE 0xe0000
#define netdev_err(...) ((void)0)
#define netdev_info(...) ((void)0)
struct net_device;
struct ctx { unsigned char *mac_base; };
struct ops { int (*stop)(struct ctx *); };
struct nss_dp_dev {
 struct ctx *gmac_hal_ctx; struct ops *gmac_hal_ops; unsigned drv_flags;
 u32 syn_host_rx_base,syn_host_tx_base,syn_fw_rx_base,syn_fw_tx_base,syn_fw_rx_resume,syn_fw_tx_resume;
 bool syn_fw_known,syn_fw_resume_valid,syn_fw_active;
};
struct net_device { struct nss_dp_dev *priv; };
struct nss_dp_data_plane_ctx { struct net_device *dev; };
static bool mac_enabled=true; static unsigned mac_stops;
static void *netdev_priv(struct net_device *d) { return d->priv; }
static u32 readl(void *p) { return *(u32 *)p; }
static void writel(u32 v,void *p) { *(u32 *)p=v; }
static int stop_mac(struct ctx *c) { mac_enabled=false; ++mac_stops; return 0; }
static void syn_disable_dma_interrupt(void *b) {}
static void syn_disable_dma_rx(void *b) {}
static void syn_disable_dma_tx(void *b) {}
#define readl_poll_timeout(p,v,cond,a,t) ({ (v)=readl(p); (cond)?0:-ETIMEDOUT; })
'''
    code = "".join(function(text, name) for name in ("syn_dp_quiesce_dma",
                       "syn_dp_prepare_override_open", "syn_dp_complete_override_open"))
    main = r'''
int main(void) {
 u32 regs[0x1100/4]={0}; struct ctx c={.mac_base=(unsigned char *)regs};
 struct ops o={.stop=stop_mac}; struct nss_dp_dev d={.gmac_hal_ctx=&c,.gmac_hal_ops=&o};
 struct net_device dev={.priv=&d}; struct nss_dp_data_plane_ctx p={.dev=&dev};
 writel(0x02700c0c,c.mac_base+SYN_MAC_CONFIGURATION);
 writel(0x1200,c.mac_base+0x100c); writel(0x2200,c.mac_base+0x1010);
 assert(!syn_dp_quiesce_dma(&p) && mac_enabled && !mac_stops);
 assert(d.syn_host_rx_base==0x1200 && d.syn_host_tx_base==0x2200);
 assert(!syn_dp_prepare_override_open(&p) && mac_enabled);
 assert(readl(c.mac_base+SYN_MAC_CONFIGURATION)==0x00700c0c);
 assert(syn_dp_complete_override_open(&p)==-EIO && !d.syn_fw_known);
 writel(0x8000,c.mac_base+0x100c); writel(0x9000,c.mac_base+0x1010);
 assert(!syn_dp_complete_override_open(&p) && d.syn_fw_known && d.syn_fw_active);
 d.drv_flags=INIT_OVERRIDE;
 writel(0x8080,c.mac_base+0x104c); writel(0x9180,c.mac_base+0x1048);
 assert(!syn_dp_quiesce_dma(&p) && d.syn_fw_resume_valid && !d.syn_fw_active && mac_enabled);
 writel(0x1600,c.mac_base+0x100c); writel(0x2500,c.mac_base+0x1010);
 assert(!syn_dp_prepare_override_open(&p) && !mac_enabled && mac_stops==1);
 assert(readl(c.mac_base+0x100c)==0x8080 && readl(c.mac_base+0x1010)==0x9180);
 assert(!syn_dp_complete_override_open(&p) && !d.syn_fw_resume_valid && d.syn_fw_active);
 assert(readl(c.mac_base+0x100c)==0x8000 && readl(c.mac_base+0x1010)==0x9000);
 d.syn_fw_resume_valid=false;
 assert(syn_dp_prepare_override_open(&p)==-EUCLEAN);
 writel(0x8888,c.mac_base+0x100c);
 assert(syn_dp_quiesce_dma(&p)==-EUCLEAN && !d.syn_fw_resume_valid);
 writel(1<<20,c.mac_base+0x1014);
 assert(syn_dp_quiesce_dma(&p)==-ETIMEDOUT);
 return 0;
}
'''
    c_test("live MAC preservation, firmware ring verification, saved indices and wrap restore", harness + code + main)


def test_crc_policy(dp):
    text = (dp / "hal/gmac_ops/syn/gmac/syn_if.c").read_text()
    harness = LIST + r'''
#define INIT_OVERRIDE 1
#define NSS_DP_PRIV_FLAG(n) (n)
#define SYN_MAC_CONFIGURATION 0
#define SYN_MAC_CST 0x02000000
#define BUG_ON(x) assert(!(x))
#define netdev_dbg(...) ((void)0)
struct nss_dp_dev { unsigned drv_flags; };
struct net_device { struct nss_dp_dev *priv; };
struct nss_gmac_hal_dev { struct net_device *netdev; u32 *mac_base; };
static void *netdev_priv(struct net_device *d) { return d->priv; }
static void syn_tx_enable(struct nss_gmac_hal_dev *g) { *g->mac_base |= 8; }
static void syn_rx_enable(struct nss_gmac_hal_dev *g) { *g->mac_base |= 4; }
static void syn_enable_mac_cst(struct nss_gmac_hal_dev *g) { *g->mac_base |= SYN_MAC_CST; }
static void syn_disable_mac_cst(struct nss_gmac_hal_dev *g) { *g->mac_base &= ~SYN_MAC_CST; }
static u32 hal_read_relaxed_reg(u32 *b,unsigned off) { return *b; }
/* A 98-byte Ethernet IPv4 frame becomes 102 bytes with the DSA tag.
 * Host takes the hardware length; NSS removes the four-byte FCS itself. */
static unsigned received_length(u32 cfg,bool nss) {
 unsigned len=102+4-((cfg&SYN_MAC_CST)?4:0);
 return len-(nss?4:0);
}
'''
    main = r'''
int main(void) {
 u32 cfg=0x00700c0c; struct nss_dp_dev dp={0};
 struct net_device dev={.priv=&dp};
 struct nss_gmac_hal_dev g={.netdev=&dev,.mac_base=&cfg};
 assert(!syn_start(&g));
 assert(cfg==0x02700c0c && received_length(cfg,false)==102);
 dp.drv_flags=INIT_OVERRIDE;
 assert(!syn_start(&g));
 assert(cfg==0x00700c0c && received_length(cfg,true)==102);
 assert(received_length(cfg,true)-4==98);
 assert(!syn_start(&g) && cfg==0x00700c0c);
 dp.drv_flags=0;
 assert(!syn_start(&g));
 assert(cfg==0x02700c0c && received_length(cfg,false)==102);
 return 0;
}
'''
    c_test("host/NSS CRC ownership, tagged IPv4 length and host restoration",
           harness + function(text, "syn_start") + main)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--drv", type=Path)
    parser.add_argument("--dp", type=Path)
    args = parser.parse_args()
    test_nodes()
    if args.drv:
        test_phy(args.drv)
        test_control(args.drv, "vlan")
        test_control(args.drv, "bridge")
    if args.dp:
        test_dp(args.dp)
        test_rings(args.dp)
        test_crc_policy(args.dp)
