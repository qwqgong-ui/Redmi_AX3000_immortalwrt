#!/usr/bin/env python3
"""Exercise actual NSS key leases, guarded replies and failed-interface isolation."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


def load(filename):
    spec = importlib.util.spec_from_file_location(filename, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


functions = load("test-nss-control.py")
structures = load("test-nss-wifili.py")

SHIM = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uintptr_t nss_ptr_t;
typedef int nss_tx_status_t;
#define ETH_ALEN 6
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_EMSG 1
#define NSS_CMN_RESPONSE_NOTIFY 5
#define NSS_WIFILI_PEER_SECURITY_TYPE_MSG 21
#define NSS_WIFILI_PEER_UPDATE_AUTH_FLAG 44
#define NSS_WIFI_VDEV_INTERFACE_CONFIGURE_MSG 10000
#define NSS_WIFI_VDEV_INTERFACE_CMD_MSG 10003
#define NSS_WIFI_VDEV_SECURITY_TYPE_CMD 15
#define PEER_SEC_TYPE_TKIP 4
#define NSS_WIFILI_MIC_KEY_LEN 8
#define NL80211_TKIP_DATA_OFFSET_RX_MIC_KEY 24
#define IEEE80211_KEY_FLAG_PAIRWISE 1
#define ATH11K_NSS_MSG_TIMEOUT_MS 1000
#define ATH11K_FLAG_UNREGISTERING 1
#define GFP_KERNEL 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define smp_load_acquire(p) (*(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define WARN_ON_ONCE(v) assert(!(v))
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define ath11k_err(...) ((void)0)
#define WMI_VDEV_TYPE_MONITOR 3
#define NL80211_IFTYPE_STATION 2
#define NL80211_IFTYPE_AP 3
#define ENOTSUPP EOPNOTSUPP
#define ATH11K_NSS_WIFI_VDEV_CFG_MCBC_EXC_TO_HOST_CMD 1
#define ATH11K_NSS_WIFI_VDEV_CFG_WDS_BACKHAUL_CMD 2
#define ATH11K_NSS_ENABLE_MCBC_EXC 1
#define test_bit(n,p) (!!(*(p)&(1UL<<(n))))
struct list_head { struct list_head *next,*prev; };
struct nss_wifili_peer_memory;
typedef struct { unsigned refs; } refcount_t;
static void refcount_inc(refcount_t *r) { assert(r->refs);r->refs++; }
static bool refcount_dec_and_test(refcount_t *r) { assert(r->refs);return --r->refs==0; }
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done=false; }
static void complete(struct completion *c) { c->done=true; }
static bool completion_done(struct completion *c) { return c->done; }
static unsigned msecs_to_jiffies(unsigned n) { return n; }
static int base_locked;
static unsigned allocations,live_allocations,fail_allocation,submissions,cancels,stop_requests,deletes;
static void *kzalloc(size_t size,int gfp) { assert(gfp==GFP_KERNEL&&!base_locked);allocations++;if(allocations==fail_allocation)return NULL;void *p=calloc(1,size);assert(p);live_allocations++;return p; }
static void kfree(void *p) { if(p){assert(live_allocations);live_allocations--;free(p);} }
static void spin_lock_bh(int *p) { assert(!*p);*p=1;base_locked=1; }
static void spin_unlock_bh(int *p) { assert(*p);*p=0;base_locked=0; }
#define lockdep_assert_held(p) assert(*(p))
struct ath11k_nss_peer_state;
struct ath11k_vif;
struct wireless_dev { void *netdev; };
struct ieee80211_vif { struct ath11k_vif *priv;struct wireless_dev wdev;int type; };
struct ieee80211_hw { void *wiphy; };
struct ath11k_peer { u16 peer_id;u32 vdev_id;u8 addr[6];struct ieee80211_vif *vif;struct { struct ath11k_nss_peer_state *state; } nss; };
struct ath11k_base { int base_lock;unsigned long dev_flags;struct { bool enabled,quiescing,ownership_uncertain,registered;u32 if_num; } nss; };
struct ath11k { struct ath11k_base *ab;struct ieee80211_hw *hw;int conf_mutex;struct { void *ctx; } nss; };
struct ath11k_vif { struct ath11k *ar;struct ieee80211_vif *vif;u32 vdev_id,vdev_type;struct { unsigned if_num;bool created,key_failed,format_ready,format_failed;struct ath11k_vif *ap_vif; } nss; };
struct ieee80211_key_conf { u32 flags,cipher;u8 key[32]; };
struct nss_cmn_msg { u32 interface,type,len,response,error;nss_ptr_t cb,app_data; };
struct nss_wifili_peer_security_type_msg { u16 peer_id;u8 pkt_type,security_type,mic_key[8]; };
struct nss_wifili_peer_update_auth_flag { u16 peer_id;u8 auth_flag; };
struct nss_wifili_msg { struct nss_cmn_msg cm;union { struct nss_wifili_peer_security_type_msg securitymsg;struct nss_wifili_peer_update_auth_flag peer_auth; } msg; };
struct nss_wifi_vdev_msg { struct nss_cmn_msg cm;union { struct { u32 cmd,value; } vdev_cmd; } msg; };
typedef void nss_wifi_vdev_msg_callback_t(void *,struct nss_cmn_msg *);
typedef void nss_wifili_msg_callback_t(void *,struct nss_wifili_msg *);
static struct ath11k_base ab;static struct ath11k ar;static struct ath11k_vif vif;
static struct ieee80211_vif mac_vif;static struct ieee80211_hw hw;
static struct ath11k_vif *ath11k_vif_to_arvif(struct ieee80211_vif *v) { return v->priv; }
static struct wireless_dev *ieee80211_vif_to_wdev_relaxed(struct ieee80211_vif *v) { return &v->wdev; }
static unsigned create_calls;static bool configure_fail;
static int ath11k_nss_vdev_alloc(struct ath11k_vif *v,void *dev) { assert(v==&vif&&dev==mac_vif.wdev.netdev);create_calls++;return 0; }
static int ath11k_nss_vdev_register(struct ath11k_vif *v,void *dev) { (void)v;(void)dev;return 0; }
static int ath11k_nss_vdev_configure(struct ath11k_vif *v) { (void)v;return configure_fail?-EIO:0; }
static int ath11k_nss_vdev_set_cmd(struct ath11k_vif *v,int cmd,int value) { (void)v;(void)cmd;(void)value;return 0; }
static void ath11k_nss_vdev_unregister(struct ath11k_vif *v) { (void)v; }
static void ath11k_nss_vdev_free(struct ath11k_vif *v) { (void)v; }
static struct ath11k_peer peer,replacement,*lookup;
static struct ath11k_nss_peer_state *active_state;
static struct nss_wifili_msg pending_soc;static struct nss_wifi_vdev_msg pending_vdev;
static bool soc_pending,vdev_pending,edge_ack;
static unsigned reply_stage,reply_kind,unmap_stage,close_stage;
static bool key_channel_open;
static bool ath11k_mac_key_install_available_locked(struct ath11k *radio) { assert(radio==&ar&&ab.base_lock);return key_channel_open; }
static struct ath11k_peer *ath11k_peer_find(struct ath11k *radio,u32 vdev,const u8 *addr) { assert(radio==&ar&&ab.base_lock);return lookup&&lookup->vdev_id==vdev&&!memcmp(lookup->addr,addr,6)?lookup:NULL; }
static int ath11k_nss_cipher_type(struct ath11k_base *base,u32 cipher) { assert(base==&ab);return cipher; }
static void nss_cmn_msg_init(struct nss_cmn_msg *cm,u32 ifnum,u32 type,u32 len,void *cb,void *data) { cm->interface=ifnum;cm->type=type;cm->len=len;cm->cb=(uintptr_t)cb;cm->app_data=(uintptr_t)data; }
static void nss_wifi_vdev_msg_init(struct nss_wifi_vdev_msg *msg,u32 ifnum,u32 type,u32 len,void *cb,void *data) { nss_cmn_msg_init(&msg->cm,ifnum,type,len,cb,data); }
static nss_tx_status_t nss_wifili_tx_msg_tracked(void *ctx,struct nss_wifili_msg *msg,u32 *cookie) { (void)ctx;assert(base_locked&&!soc_pending&&!vdev_pending);pending_soc=*msg;soc_pending=true;*cookie=++submissions;return NSS_TX_SUCCESS; }
static nss_tx_status_t nss_wifi_vdev_tx_msg_tracked(void *ctx,struct nss_wifi_vdev_msg *msg,u32 *cookie) { (void)ctx;assert(base_locked&&!soc_pending&&!vdev_pending);pending_vdev=*msg;vdev_pending=true;*cookie=++submissions;return NSS_TX_SUCCESS; }
static void deliver(void) {
 unsigned kind=submissions==reply_stage?reply_kind:0;
 if(kind==2)return;
 if(soc_pending){struct nss_wifili_msg msg=pending_soc;msg.cm.response=kind==1?NSS_CMN_RESPONSE_EMSG:NSS_CMN_RESPONSE_ACK;if(kind==3)msg.msg.securitymsg.peer_id++;((nss_wifili_msg_callback_t *)msg.cm.cb)(NULL,&msg);}
 else if(vdev_pending){struct nss_wifi_vdev_msg msg=pending_vdev;msg.cm.response=kind==1?NSS_CMN_RESPONSE_EMSG:NSS_CMN_RESPONSE_ACK;((nss_wifi_vdev_msg_callback_t *)msg.cm.cb)((void *)msg.cm.app_data,&msg.cm);}
}
static void nss_wifili_cancel_msg(u32 cookie) { assert(!base_locked);if(cookie){assert(soc_pending);if(edge_ack)deliver();soc_pending=false;cancels++;} }
static void nss_wifi_vdev_cancel_msg(u32 cookie) { assert(!base_locked);if(cookie){assert(vdev_pending);if(edge_ack)deliver();vdev_pending=false;cancels++;} }
static int wait_for_completion_timeout(struct completion *c,unsigned timeout);
static int ath11k_nss_peer_submit_delete(struct ath11k_base *base,struct ath11k_nss_peer_state *state);
static void cfg80211_stop_iface(void *wiphy,struct wireless_dev *wdev,int gfp) { assert(!base_locked&&wiphy==hw.wiphy&&wdev==&mac_vif.wdev&&gfp==GFP_KERNEL&&vif.nss.key_failed);stop_requests++; }
"""

SUPPORT = r"""
static int wait_for_completion_timeout(struct completion *c,unsigned timeout) {
 assert(!base_locked&&timeout==ATH11K_NSS_MSG_TIMEOUT_MS);
 if(c==&active_state->deleted){active_state->delete_result=0;return 1;}
 if(!edge_ack)deliver();
	 if(unmap_stage==submissions){lookup=&replacement;peer.nss.state=NULL;active_state->peer=NULL;unmap_stage=0;}
	 if(close_stage==submissions)key_channel_open=false;
 if(edge_ack||!c->done)return 0;
 /* Real successful waits consume complete()'s done count. */
 c->done=false;return 1;
}
static int ath11k_nss_peer_submit_delete(struct ath11k_base *base,struct ath11k_nss_peer_state *state) {
 assert(base==&ab&&base_locked&&state==active_state&&state->peer==&peer&&lookup==&peer);
 if(ab.nss.quiescing)return -ESHUTDOWN;
 state->delete_submitted=true;state->delete_result=-EINPROGRESS;deletes++;return 0;
}
static struct ath11k_nss_peer_state state;
static void fresh(void) {
 assert(!live_allocations&&!soc_pending&&!vdev_pending);
 memset(&ab,0,sizeof(ab));memset(&ar,0,sizeof(ar));memset(&vif,0,sizeof(vif));memset(&peer,0,sizeof(peer));memset(&state,0,sizeof(state));
 ab.nss.enabled=ab.nss.registered=true;ab.nss.if_num=3;ar.ab=&ab;ar.hw=&hw;ar.conf_mutex=1;ar.nss.ctx=&ar;
 mac_vif.priv=&vif;mac_vif.wdev.netdev=&mac_vif;mac_vif.type=NL80211_IFTYPE_STATION;vif.vif=&mac_vif;vif.ar=&ar;vif.vdev_id=7;vif.nss.if_num=36;vif.nss.created=true;vif.nss.format_ready=true;
 peer.peer_id=42;peer.vdev_id=7;peer.addr[0]=1;peer.vif=&mac_vif;peer.nss.state=&state;lookup=&peer;replacement=peer;
 state.refs.refs=1;state.peer=&peer;state.peer_id=42;state.vdev_id=7;state.addr[0]=1;state.create_done=true;
 active_state=&state;allocations=fail_allocation=submissions=cancels=stop_requests=deletes=reply_stage=reply_kind=unmap_stage=create_calls=close_stage=0;edge_ack=configure_fail=false;key_channel_open=true;
}
int main(void) {
 struct ieee80211_key_conf key={.flags=IEEE80211_KEY_FLAG_PAIRWISE,.cipher=6};
 fresh();spin_lock_bh(&ab.base_lock);struct ath11k_nss_peer_state *lease=ath11k_nss_key_get(&ar,&peer);spin_unlock_bh(&ab.base_lock);
 assert(lease==&state&&state.refs.refs==2);ath11k_nss_key_put(lease);assert(state.refs.refs==1);
 assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==0&&submissions==3&&cancels==3&&!live_allocations);
 for(unsigned stage=1;stage<=3;stage++) {
  fresh();reply_stage=stage;reply_kind=1;int ret=ath11k_nss_key_config(&vif,&peer,&state,&key);
  assert(ret==(stage==1?-EIO:-EREMOTEIO)&&submissions==stage&&cancels==stage&&!live_allocations);
  fresh();reply_stage=stage;reply_kind=2;assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==-ETIMEDOUT&&submissions==stage&&cancels==stage&&!live_allocations);
 }
 fresh();reply_stage=2;reply_kind=3;assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==-EPROTO&&submissions==2&&!live_allocations);
 fresh();edge_ack=true;assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==0&&submissions==3&&cancels==3&&!live_allocations);
	 for(unsigned stage=1;stage<=3;stage++){fresh();unmap_stage=stage;assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==-ENOENT&&submissions==stage&&cancels==stage&&!live_allocations);}
	 for(unsigned stage=1;stage<=3;stage++){fresh();close_stage=stage;assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==-ESHUTDOWN&&submissions==stage&&cancels==stage&&!live_allocations);}
	 fresh();key_channel_open=false;assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==-ESHUTDOWN&&!submissions&&!live_allocations);
 for(unsigned failure=1;failure<=6;failure++){fresh();fail_allocation=failure;assert(ath11k_nss_key_config(&vif,&peer,&state,&key)==-ENOMEM&&!live_allocations);}
 fresh();state.create_done=false;spin_lock_bh(&ab.base_lock);assert(PTR_ERR(ath11k_nss_key_get(&ar,&peer))==-EAGAIN);spin_unlock_bh(&ab.base_lock);
 fresh();state.create_result=-EREMOTEIO;spin_lock_bh(&ab.base_lock);assert(PTR_ERR(ath11k_nss_key_get(&ar,&peer))==-EREMOTEIO);spin_unlock_bh(&ab.base_lock);
 fresh();ab.nss.enabled=false;spin_lock_bh(&ab.base_lock);assert(ath11k_nss_key_get(&ar,&peer)==NULL);spin_unlock_bh(&ab.base_lock);assert(!ath11k_nss_key_config(&vif,&peer,NULL,&key)&&!submissions);
 fresh();ath11k_nss_key_recover(&vif,&peer,&state);assert(deletes==1&&stop_requests==1&&!ab.nss.quiescing&&vif.nss.key_failed);ath11k_nss_key_recover(&vif,&peer,&state);assert(deletes==1&&stop_requests==1);
 spin_lock_bh(&ab.base_lock);assert(ath11k_nss_key_check(&ar,&peer,&state)==-ESHUTDOWN);spin_unlock_bh(&ab.base_lock);
 struct ath11k_vif vlan={.nss.ap_vif=&vif};assert(ath11k_nss_vdev_key_failed(&vlan));
 fresh();lookup=&replacement;state.peer=NULL;peer.nss.state=NULL;ath11k_nss_key_recover(&vif,&peer,&state);assert(!deletes&&stop_requests==1);
 fresh();ab.nss.quiescing=true;ath11k_nss_key_recover(&vif,&peer,&state);assert(stop_requests==1&&vif.nss.key_failed);
 fresh();ath11k_nss_key_recover(&vif,&peer,NULL);assert(!stop_requests&&!vif.nss.key_failed);
 fresh();vif.nss.key_failed=true;assert(!ath11k_nss_vdev_create(&vif)&&vif.nss.key_failed&&!create_calls);
 vif.nss.created=false;configure_fail=true;assert(ath11k_nss_vdev_create(&vif)==-EIO&&vif.nss.key_failed&&!vif.nss.created);
 configure_fail=false;assert(!ath11k_nss_vdev_create(&vif)&&!vif.nss.key_failed&&vif.nss.created&&!vif.nss.format_ready&&ath11k_nss_vdev_key_failed(&vif));
 puts("PASS actual NSS key ACKs: NACK/timeout, identity, deadline drain, peer reuse, allocation/CREATE failures and interface isolation without hardware reset");
 return 0;
}
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backports", type=Path, required=True)
    p.add_argument("--nss-source", type=Path)
    a = p.parse_args()
    source = (a.nss_source or a.backports / "drivers/net/wireless/ath/ath11k/nss.c").read_text()
    defs = "".join(structures.structure(source, name) for name in
                   ("ath11k_nss_peer_state", "ath11k_nss_vdev_request", "ath11k_nss_key_request"))
    names = ("ath11k_nss_peer_state_put", "ath11k_nss_vdev_key_failed", "ath11k_nss_key_check", "ath11k_nss_key_get",
             "ath11k_nss_key_put", "ath11k_nss_vdev_cfg_cb", "ath11k_nss_key_response",
             "ath11k_nss_key_send", "ath11k_nss_key_vdev_security", "ath11k_nss_set_peer_sec_type",
             "ath11k_nss_set_peer_authorize", "ath11k_nss_key_config", "ath11k_nss_key_recover",
             "ath11k_nss_vdev_create")
    bodies = "".join(functions.function(source, name) for name in names)
    with tempfile.TemporaryDirectory(prefix="nss-key-ack-") as temp:
        path, binary = Path(temp) / "test.c", Path(temp) / "test"
        path.write_text(SHIM + defs + bodies + SUPPORT)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                        str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1"})
        header = (a.backports / "drivers/net/wireless/ath/ath11k/nss.h").read_text()
        # REO stubs precede TX in the NSS-disabled branch; select the actual
        # TX definition rather than assuming it is adjacent to #else.
        stubs = header[header.index("static inline int ath11k_nss_tx"):]
        stubs = stubs.replace("static inline struct ath11k_nss_peer_state *\n",
                              "static inline struct ath11k_nss_peer_state * ")
        stub_names = ("ath11k_nss_key_get", "ath11k_nss_key_put", "ath11k_nss_key_check",
                      "ath11k_nss_key_config", "ath11k_nss_key_recover", "ath11k_nss_vdev_key_failed")
        stub_bodies = "".join(functions.function(stubs, name) for name in stub_names)
        stub_main = r'''
int main(void) {
 ab.nss.enabled=true;ar.ab=&ab;vif.ar=&ar;
 assert(ath11k_nss_key_get(&ar,&peer)==NULL);
 ath11k_nss_key_put(NULL);
 assert(!ath11k_nss_key_check(&ar,&peer,NULL));
 struct ieee80211_key_conf key={0};
 assert(!ath11k_nss_key_config(&vif,&peer,NULL,&key));
 ath11k_nss_key_recover(&vif,&peer,NULL);
 assert(!ath11k_nss_vdev_key_failed(&vif)&&!stop_requests&&!submissions);
 puts("PASS actual compile-time NSS-disabled key stubs");
}
'''
        path.write_text(SHIM + defs + stub_bodies + stub_main)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1",
                        "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                        str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
