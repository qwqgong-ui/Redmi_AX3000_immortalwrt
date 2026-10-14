#!/usr/bin/env python3
"""Execute the real key callback with peer-unmap and replacement interleavings."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


def load(filename):
    spec = importlib.util.spec_from_file_location("key_functions", Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extractor = load("test-nss-control.py")

SHIM = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;
	#define ETH_ALEN 6
	#define BITS_PER_LONG (sizeof(unsigned long)*8)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define WMI_MAX_KEY_INDEX 3
#define VLAN_VID_MASK 4095
#define WMI_KEY_PAIRWISE 1
#define WMI_KEY_GROUP 2
#define WMI_VDEV_TYPE_STA 1
#define WMI_VDEV_TYPE_AP 2
#define NL80211_IFTYPE_AP 2
#define NL80211_IFTYPE_AP_VLAN 3
#define ATH11K_STATE_RESTARTED 3
#define IEEE80211_KEY_FLAG_PAIRWISE 1
#define ATH11K_FLAG_HW_CRYPTO_DISABLED 1
#define WLAN_CIPHER_SUITE_AES_CMAC 10
#define WLAN_CIPHER_SUITE_BIP_GMAC_128 11
#define WLAN_CIPHER_SUITE_BIP_GMAC_256 12
#define WLAN_CIPHER_SUITE_BIP_CMAC_256 13
#define WLAN_CIPHER_SUITE_TKIP 1
#define WLAN_CIPHER_SUITE_CCMP 2
#define WLAN_CIPHER_SUITE_CCMP_256 3
#define WLAN_CIPHER_SUITE_GCMP 4
#define WLAN_CIPHER_SUITE_GCMP_256 5
#define HAL_PN_TYPE_NONE 0
#define HAL_PN_TYPE_WPA 1
#define HAL_ENCRYPT_TYPE_OPEN 0
#define IEEE80211_NUM_TIDS 1
#define HAL_REO_CMD_FLG_NEED_STATUS 1
#define HAL_REO_CMD_UPD0_PN 1
#define HAL_REO_CMD_UPD0_PN_SIZE 2
#define HAL_REO_CMD_UPD0_PN_VALID 4
#define HAL_REO_CMD_UPD0_PN_CHECK 8
#define HAL_REO_CMD_UPD0_SVLD 16
#define HAL_REO_CMD_UPD1_PN_CHECK 1
#define HAL_REO_CMD_UPDATE_RX_QUEUE 1
#define lower_32_bits(x) ((u32)(x))
#define upper_32_bits(x) ((u32)((uint64_t)(x)>>32))
#define ATH11K_NSS_WIFI_VDEV_SECURITY_TYPE_CMD 1
#define ATH11K_DBG_MAC 0
#define READ_ONCE(x) (x)
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define rcu_read_lock() ((void)0)
#define rcu_read_unlock() ((void)0)
#define test_bit(n,p) (!!(*(p)&(1UL<<(n))))
#define set_bit(n,p) (*(p)|=1UL<<(n))
enum set_key_cmd { SET_KEY, DISABLE_KEY };
typedef struct { unsigned value; } refcount_t;
static void refcount_set(refcount_t *r,unsigned value) { r->value=value; }
static void refcount_inc(refcount_t *r) { assert(r->value);r->value++; }
static bool refcount_dec_and_test(refcount_t *r) { assert(r->value);return --r->value==0; }
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(p) ((p)->next=(p),(p)->prev=(p))
#define list_empty(p) ((p)->next==(p))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_for_each_entry_safe(p,n,h,m) for(p=container_of((h)->next,__typeof__(*p),m),n=container_of((p)->m.next,__typeof__(*p),m);&(p)->m!=(h);p=n,n=container_of((n)->m.next,__typeof__(*n),m))
static void list_del(struct list_head *p) { p->prev->next=p->next;p->next->prev=p->prev; }
static void list_add_tail(struct list_head *p,struct list_head *h) { p->prev=h->prev;p->next=h;h->prev->next=p;h->prev=p; }
struct ieee80211_key_conf { u32 cipher,flags;unsigned keyidx,hw_key_idx,vlan_id; };
struct ath11k_vif;
struct ath11k_nss_peer_state { unsigned refs; };
static struct ath11k_nss_peer_state key_state;
struct ath11k_sta { struct ath11k_vif *arvif;int pn_type; };
struct ieee80211_sta { u8 addr[6];struct ath11k_sta priv; };
struct ieee80211_vif { u8 addr[6];int type;struct { u8 bssid[6]; } bss_conf;struct ath11k_vif *priv; };
struct dp_rx_tid { bool active;uintptr_t paddr;int frag_timer; };
struct ath11k_hal_reo_cmd { u32 flag,upd0,upd1,pn_size,addr_lo,addr_hi; };
struct ath11k_peer { struct list_head list;refcount_t refs;int vdev_id,peer_id;u8 addr[6];struct ieee80211_key_conf *keys[4];unsigned ucast_keyidx,mcast_keyidx,sec_type,sec_type_grp;struct dp_rx_tid rx_tid[2]; };
struct ath11k;struct ath11k_pdev { struct ath11k *ar; };
struct ath11k_base { int base_lock;unsigned long dev_flags;bool wmi_key_admitting;unsigned num_radios;struct ath11k_pdev pdevs[1];struct { bool enabled,ownership_uncertain;struct list_head retained_host_peers; } nss; };
struct ath11k { struct ath11k_base *ab;int conf_mutex,data_lock,state; };
struct ath11k_vif { struct ath11k *ar;struct ieee80211_vif *vif;unsigned vdev_id,vdev_type,num_stations;u16 *vlan_keyid_map;unsigned long free_groupidx_map[1];bool reinstall_group_keys;struct list_head dyn_vlan_cfg;struct { struct ath11k_vif *ap_vif; } nss; };
struct ath11k_dyn_vlan_cfg { struct list_head cfg_list;struct ieee80211_sta *sta; };
struct ieee80211_hw { struct ath11k *priv; };
static struct ath11k_peer *lookup_peer,*replacement,*retired_peer;
static unsigned frees,wmi_calls,pn_calls,nss_calls,dyn_calls,recover_calls;
static int nss_fail_call;
static int wmi_result;
static int pn_result;
static bool key_channel_open=true;
static struct ieee80211_hw *unregister_hw;
static struct ieee80211_vif *unregister_vif;
static struct ieee80211_sta *unregister_sta;
static struct ieee80211_key_conf *unregister_key;
static unsigned key_frees;
static void (*wmi_hook)(struct ath11k *);
static void (*fragment_hook)(struct ath11k *);
static void (*dyn_hook)(struct ath11k *);
static struct ath11k *fragment_ar;
static unsigned timer_drains,fragment_cleanups;
static void spin_lock_bh(int *lock) { assert(!*lock);*lock=1; }
static void spin_unlock_bh(int *lock) { assert(*lock);*lock=0; }
static void mutex_lock(int *lock) { assert(!*lock);*lock=1; }
static void mutex_unlock(int *lock) { assert(*lock);*lock=0; }
#define lockdep_assert_held(p) assert(*(p))
static void kfree(void *p) { if(p){frees++;free(p);} }
static struct ath11k_peer *ath11k_peer_find(struct ath11k *ar,unsigned vdev,const u8 *addr) { assert(ar->ab->base_lock);return lookup_peer&&lookup_peer->vdev_id==(int)vdev&&!memcmp(lookup_peer->addr,addr,6)?lookup_peer:NULL; }
static struct ath11k_vif *ath11k_vif_to_arvif(struct ieee80211_vif *vif) { return vif->priv; }
static struct ath11k_sta *ath11k_sta_to_arsta(struct ieee80211_sta *sta) { return &sta->priv; }
static struct ath11k_vif *ath11k_mac_get_ap_arvif_by_addr(struct ath11k_base *ab,const u8 *addr) { (void)ab;(void)addr;return NULL; }
static unsigned ath11k_dp_tx_get_encrypt_type(u32 cipher) { return cipher; }
static int ath11k_get_vlan_groupkey_index(struct ath11k_vif *vif,struct ieee80211_key_conf *key) { (void)vif;(void)key;return -ENOSPC; }
static int ath11k_nss_ext_vdev_configure(struct ath11k_vif *vif) { (void)vif;return 0; }
static int ath11k_nss_ext_vdev_cfg_dyn_vlan(struct ath11k_vif *vif,unsigned id) { (void)vif;(void)id;return 0; }
static int ath11k_nss_dyn_vlan_set_group_key(struct ath11k_vif *vif,unsigned id,unsigned key) { (void)vif;(void)id;(void)key;return 0; }
static int ath11k_nss_ext_vdev_up(struct ath11k_vif *vif) { (void)vif;return 0; }
static int ath11k_mac_cfg_dyn_vlan(struct ath11k *ar,struct ath11k_vif *vif,struct ieee80211_sta *sta) { (void)vif;(void)sta;dyn_calls++;if(dyn_hook)dyn_hook(ar);return 0; }
static int ath11k_install_key(struct ath11k_vif *vif,struct ieee80211_key_conf *key,enum set_key_cmd cmd,const u8 *addr,u32 flags) { (void)key;(void)cmd;(void)addr;(void)flags;assert(vif->ar->conf_mutex&&!vif->ar->ab->base_lock);if(!key_channel_open)return -ESHUTDOWN;wmi_calls++;if(wmi_hook)wmi_hook(vif->ar);return wmi_result; }
static bool ath11k_mac_key_install_available_locked(struct ath11k *ar) { assert(ar->ab->base_lock);return key_channel_open; }
static void ath11k_mac_key_install_close(struct ath11k *ar) { (void)ar;key_channel_open=false; }
static void ath11k_nss_reoq_stop(struct ath11k_base *ab) { (void)ab; }
static int ath11k_mac_op_set_key(struct ieee80211_hw *hw,enum set_key_cmd cmd,struct ieee80211_vif *vif,struct ieee80211_sta *sta,struct ieee80211_key_conf *key);
static void __ath11k_mac_unregister(struct ath11k *ar) {
 assert(ar==unregister_hw->priv && !ar->ab->wmi_key_admitting && !key_channel_open);
 assert(ath11k_mac_op_set_key(unregister_hw,DISABLE_KEY,unregister_vif,unregister_sta,unregister_key)==-ESHUTDOWN);
 assert(!lookup_peer->keys[unregister_key->keyidx]);free(unregister_key);unregister_key=NULL;key_frees++;
}
static void ath11k_peer_rhash_tbl_destroy(struct ath11k *ar) { (void)ar; }
static int ath11k_dp_tx_send_reo_cmd(struct ath11k_base *ab,struct dp_rx_tid *tid,unsigned type,struct ath11k_hal_reo_cmd *cmd,void *callback) {
 assert(ab->base_lock&&lookup_peer&&tid==&lookup_peer->rx_tid[0]&&type==HAL_REO_CMD_UPDATE_RX_QUEUE&&!callback&&cmd->addr_lo==tid->paddr);
 assert(cmd->pn_size==((cmd->upd1&HAL_REO_CMD_UPD1_PN_CHECK)?48:0));pn_calls++;return 0;
}
/* The native REO/HAL implementation executes in test-reo-pn-completion.py.
 * Here its result is injected at the actual MAC-to-NSS control boundary.
 */
static int ath11k_dp_peer_rx_pn_replay_config(struct ath11k_vif *vif,const u8 *addr,
 enum set_key_cmd command,struct ieee80211_key_conf *key,struct ath11k_peer *expected) {
 (void)command;assert(vif->ar->conf_mutex&&!vif->ar->ab->base_lock);
 if(!(key->flags&IEEE80211_KEY_FLAG_PAIRWISE))return 0;
 spin_lock_bh(&vif->ar->ab->base_lock);
 struct ath11k_peer *p=ath11k_peer_find(vif->ar,vif->vdev_id,addr);
 bool current=p&&p==expected;spin_unlock_bh(&vif->ar->ab->base_lock);
 if(!current)return -ENOENT;pn_calls++;return pn_result;
}
static struct ath11k_nss_peer_state *ath11k_nss_key_get(struct ath11k *ar,struct ath11k_peer *peer) { assert(ar->ab->base_lock&&peer==lookup_peer);if(!ar->ab->nss.enabled)return NULL;key_state.refs++;return &key_state; }
static void ath11k_nss_key_put(struct ath11k_nss_peer_state *state) { if(state){assert(state==&key_state&&state->refs);state->refs--;} }
static int ath11k_nss_key_check(struct ath11k *ar,struct ath11k_peer *peer,struct ath11k_nss_peer_state *state) { assert(ar->ab->base_lock&&peer==lookup_peer);assert((bool)state==ar->ab->nss.enabled);return 0; }
static int ath11k_nss_key_config(struct ath11k_vif *vif,struct ath11k_peer *peer,struct ath11k_nss_peer_state *state,struct ieee80211_key_conf *key) {
 (void)key;assert(vif->ar->conf_mutex&&!vif->ar->ab->base_lock&&peer==lookup_peer);
 if(!state)return 0;for(unsigned i=0;i<3;i++){nss_calls++;if(nss_fail_call==(int)nss_calls)return 1;}return 0;
}
static void ath11k_nss_key_recover(struct ath11k_vif *vif,struct ath11k_peer *peer,struct ath11k_nss_peer_state *state) { assert(vif->ar->conf_mutex&&!vif->ar->ab->base_lock&&peer);if(state)recover_calls++; }
static void timer_delete_sync(int *timer) { (void)timer;assert(!fragment_ar->ab->base_lock);timer_drains++;if(fragment_hook){void(*hook)(struct ath11k *)=fragment_hook;fragment_hook=NULL;hook(fragment_ar);} }
static void ath11k_dp_rx_frags_cleanup(struct dp_rx_tid *tid,bool flush) { (void)tid;assert(flush&&fragment_ar->ab->base_lock);fragment_cleanups++; }
static void ath11k_nss_peer_detach(struct ath11k *ar,struct ath11k_peer *peer) { (void)ar;(void)peer; }
static void ath11k_peer_ast_cleanup(struct ath11k *ar,struct ath11k_peer *peer,bool local,unsigned count) { (void)ar;(void)peer;(void)local;(void)count; }
"""

MAIN = r"""
static struct ath11k_peer *new_peer(void) {
 struct ath11k_peer *p=calloc(1,sizeof(*p));assert(p);p->refs.value=1;p->vdev_id=7;p->peer_id=19;p->addr[0]=1;p->rx_tid[0]=(struct dp_rx_tid){.active=true,.paddr=0x18000};return p;
}
static void replace_peer(struct ath11k *ar) {
 spin_lock_bh(&ar->ab->base_lock);struct ath11k_peer *old=lookup_peer;assert(old&&old->refs.value==2);
 lookup_peer=NULL;ath11k_peer_release(ar,old);retired_peer=old;replacement=new_peer();lookup_peer=replacement;spin_unlock_bh(&ar->ab->base_lock);
}
static void replace_then_quarantine(struct ath11k *ar) { replace_peer(ar);spin_lock_bh(&ar->ab->base_lock);ar->ab->nss.ownership_uncertain=true;spin_unlock_bh(&ar->ab->base_lock); }
static void reset_counts(void) { assert(!key_state.refs);wmi_calls=pn_calls=nss_calls=dyn_calls=recover_calls=timer_drains=fragment_cleanups=0;nss_fail_call=wmi_result=pn_result=0;key_channel_open=true;wmi_hook=fragment_hook=dyn_hook=NULL; }
int main(void) {
 struct ath11k_base ab={0};INIT_LIST_HEAD(&ab.nss.retained_host_peers);
 struct ath11k ar={.ab=&ab};struct ieee80211_hw hw={.priv=&ar};fragment_ar=&ar;
 struct ieee80211_vif vif={.type=NL80211_IFTYPE_AP,.addr={1}};
 struct ath11k_vif av={.ar=&ar,.vif=&vif,.vdev_id=7,.vdev_type=WMI_VDEV_TYPE_AP,.num_stations=1};vif.priv=&av;INIT_LIST_HEAD(&av.dyn_vlan_cfg);
 struct ieee80211_sta sta={.addr={1}};sta.priv.arvif=&av;
 struct ieee80211_key_conf ptk={.cipher=WLAN_CIPHER_SUITE_CCMP,.flags=IEEE80211_KEY_FLAG_PAIRWISE,.keyidx=0};
 struct ieee80211_key_conf gtk1={.cipher=WLAN_CIPHER_SUITE_CCMP,.keyidx=1},gtk2={.cipher=WLAN_CIPHER_SUITE_GCMP,.keyidx=2};
 assert(ath11k_mac_op_set_key(&hw,SET_KEY,&vif,&sta,&ptk)==-EOPNOTSUPP&&!wmi_calls&&!ab.base_lock&&!ar.conf_mutex);
 assert(ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,&ptk)==0);
 for(unsigned offload=0;offload<2;offload++) {
  reset_counts();ab.nss.enabled=offload;lookup_peer=new_peer();
  assert(!ath11k_mac_op_set_key(&hw,SET_KEY,&vif,&sta,&ptk));
  assert(lookup_peer->keys[0]==&ptk&&lookup_peer->refs.value==1&&sta.priv.pn_type==HAL_PN_TYPE_WPA&&wmi_calls==1&&pn_calls==1&&nss_calls==offload*3);
  unsigned before=frees;ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;assert(frees==before+1);
  reset_counts();lookup_peer=new_peer();fragment_hook=replace_peer;before=frees;
  assert(ath11k_mac_op_set_key(&hw,SET_KEY,&vif,&sta,&ptk)==-EOPNOTSUPP);
  assert(frees==before+1&&!wmi_calls&&!pn_calls&&!nss_calls&&lookup_peer==replacement&&!lookup_peer->keys[0]&&lookup_peer->refs.value==1&&timer_drains==2&&fragment_cleanups==2);
  ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
  reset_counts();lookup_peer=new_peer();wmi_hook=replace_peer;before=frees;
  assert(ath11k_mac_op_set_key(&hw,SET_KEY,&vif,&sta,&ptk)==-ENOENT);
  assert(frees==before+1&&wmi_calls==1&&!pn_calls&&!nss_calls&&lookup_peer==replacement&&!lookup_peer->keys[0]&&lookup_peer->refs.value==1);
  ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
 }
	 /* Unmap can retire the list owner before RESET publishes quarantine. */
	 const int pn_errors[]={-EIO,-ETIMEDOUT,-ESHUTDOWN,-ESTALE,-ENOMEM};
	 for(unsigned i=0;i<ARRAY_SIZE(pn_errors);i++) {
	  reset_counts();ab.nss.enabled=true;lookup_peer=new_peer();pn_result=pn_errors[i];sta.priv.pn_type=HAL_PN_TYPE_NONE;
	  assert(ath11k_mac_op_set_key(&hw,SET_KEY,&vif,&sta,&ptk)==pn_errors[i]);
	  assert(wmi_calls==1&&pn_calls==1&&!nss_calls&&!lookup_peer->keys[0]&&sta.priv.pn_type==HAL_PN_TYPE_NONE);
	  assert(recover_calls==1&&lookup_peer->refs.value==1&&!key_state.refs);ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
	 }
 reset_counts();lookup_peer=new_peer();wmi_hook=replace_then_quarantine;unsigned before=frees;
 assert(ath11k_mac_op_set_key(&hw,SET_KEY,&vif,&sta,&ptk)==-ENOENT);
 assert(frees==before&&retired_peer->refs.value==1&&retired_peer->rx_tid[0].active&&!list_empty(&ab.nss.retained_host_peers));
 assert(ab.nss.retained_host_peers.next==&retired_peer->list&&ab.nss.retained_host_peers.prev==&retired_peer->list);
 /* Test teardown after simulating a separately confirmed safe reset. */
 ab.nss.ownership_uncertain=false;list_del(&retired_peer->list);ath11k_peer_put(&ar,retired_peer);
 ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;assert(frees==before+2&&list_empty(&ab.nss.retained_host_peers));
 reset_counts();ab.nss.enabled=true;lookup_peer=new_peer();lookup_peer->keys[0]=&ptk;lookup_peer->ucast_keyidx=0;lookup_peer->sec_type=2;
 lookup_peer->keys[1]=&gtk1;lookup_peer->keys[2]=&gtk2;lookup_peer->mcast_keyidx=2;lookup_peer->sec_type_grp=4;sta.priv.pn_type=HAL_PN_TYPE_WPA;
 assert(!ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,&gtk1));
 assert(!lookup_peer->keys[1]&&lookup_peer->keys[2]==&gtk2&&lookup_peer->mcast_keyidx==2&&lookup_peer->sec_type_grp==4&&sta.priv.pn_type==HAL_PN_TYPE_WPA&&!wmi_calls&&!pn_calls&&!nss_calls);
 /* A removal for a replaced key in the same slot must be a complete no-op. */
 struct ieee80211_key_conf replacement_key=gtk2;lookup_peer->keys[2]=&replacement_key;
 assert(!ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,&gtk2));
 assert(lookup_peer->keys[2]==&replacement_key&&lookup_peer->mcast_keyidx==2&&!wmi_calls&&!pn_calls&&!nss_calls);
 /* When the current group slot goes away, keep the surviving GTK selected. */
 lookup_peer->keys[1]=&gtk1;lookup_peer->keys[2]=&gtk2;
 assert(!ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,&gtk2));
 assert(lookup_peer->keys[1]==&gtk1&&!lookup_peer->keys[2]&&lookup_peer->mcast_keyidx==1&&lookup_peer->sec_type_grp==2&&sta.priv.pn_type==HAL_PN_TYPE_WPA);
 assert(!ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,&ptk));
 assert(!lookup_peer->keys[0]&&lookup_peer->sec_type==HAL_ENCRYPT_TYPE_OPEN&&sta.priv.pn_type==HAL_PN_TYPE_NONE&&wmi_calls==1&&pn_calls==1&&!nss_calls);
	ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
	/* Transport failure must not request software fallback or publish a key. */
 /* Actual unregister closes the key channel, invokes DISABLE_KEY, then the
  * upper layer frees the object even though the command returned an error. */
 reset_counts();lookup_peer=new_peer();unregister_key=calloc(1,sizeof(*unregister_key));assert(unregister_key);
 *unregister_key=ptk;lookup_peer->keys[0]=unregister_key;lookup_peer->sec_type=2;sta.priv.pn_type=HAL_PN_TYPE_WPA;
 unregister_hw=&hw;unregister_vif=&vif;unregister_sta=&sta;ab.wmi_key_admitting=true;ab.num_radios=1;ab.pdevs[0].ar=&ar;
 ath11k_mac_unregister(&ab);
 assert(key_frees==1 && !lookup_peer->keys[0] && sta.priv.pn_type==HAL_PN_TYPE_NONE && !wmi_calls && !pn_calls);
 mutex_lock(&ar.conf_mutex);assert(!ath11k_clear_peer_keys(&av,sta.addr));mutex_unlock(&ar.conf_mutex);
 /* A closed clear_peer_keys must not inspect borrowed key metadata. */
 struct ieee80211_key_conf *dead=malloc(sizeof(*dead));assert(dead);lookup_peer->keys[1]=dead;free(dead);
 mutex_lock(&ar.conf_mutex);assert(ath11k_clear_peer_keys(&av,sta.addr)==-ESHUTDOWN);mutex_unlock(&ar.conf_mutex);
 assert(!lookup_peer->keys[1] && !wmi_calls);
 ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
 /* A pinned old peer can enter DMA quarantine while DISABLE waits. The
  * upper layer still frees the key, so that retained peer must drop it too. */
 reset_counts();lookup_peer=new_peer();struct ieee80211_key_conf *retired_key=malloc(sizeof(*retired_key));assert(retired_key);*retired_key=ptk;
 lookup_peer->keys[0]=retired_key;lookup_peer->ucast_keyidx=0;sta.priv.pn_type=HAL_PN_TYPE_WPA;wmi_hook=replace_then_quarantine;before=frees;
 assert(ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,retired_key)==-ENOENT);
 assert(frees==before && retired_peer->refs.value==1 && !retired_peer->keys[0] && !lookup_peer->keys[0] && sta.priv.pn_type==HAL_PN_TYPE_WPA);
 free(retired_key);ab.nss.ownership_uncertain=false;list_del(&retired_peer->list);ath11k_peer_put(&ar,retired_peer);ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
 assert(list_empty(&ab.nss.retained_host_peers));
 /* Failed GTK removal preserves PTK and a surviving GTK's VLAN group slot. */
 reset_counts();lookup_peer=new_peer();av.vlan_keyid_map=calloc(4096,sizeof(u16));assert(av.vlan_keyid_map);
 gtk1.vlan_id=gtk2.vlan_id=2048;gtk1.hw_key_idx=gtk2.hw_key_idx=12;
 av.vlan_keyid_map[2048]=12;av.free_groupidx_map[0]=0;av.num_stations=0;key_channel_open=false;
 lookup_peer->keys[0]=&ptk;lookup_peer->keys[1]=&gtk1;lookup_peer->keys[2]=&gtk2;lookup_peer->mcast_keyidx=2;sta.priv.pn_type=HAL_PN_TYPE_WPA;
 assert(ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,&gtk1)==-ESHUTDOWN);
 assert(!lookup_peer->keys[1] && lookup_peer->keys[2]==&gtk2 && av.vlan_keyid_map[2048]==12 && !(av.free_groupidx_map[0]&(1UL<<12)) && sta.priv.pn_type==HAL_PN_TYPE_WPA);
 assert(ath11k_mac_op_set_key(&hw,DISABLE_KEY,&vif,&sta,&gtk2)==-ESHUTDOWN);
 assert(!lookup_peer->keys[2] && !av.vlan_keyid_map[2048] && (av.free_groupidx_map[0]&(1UL<<12)) && sta.priv.pn_type==HAL_PN_TYPE_WPA);
 free(av.vlan_keyid_map);av.vlan_keyid_map=NULL;gtk1.vlan_id=gtk2.vlan_id=0;av.num_stations=1;
 ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
 for(int stage=1;stage<=3;stage++) {
  reset_counts();lookup_peer=new_peer();nss_fail_call=stage;
  assert(ath11k_mac_op_set_key(&hw,SET_KEY,&vif,&sta,&ptk)==-EIO);
  assert(nss_calls==(unsigned)stage&&!lookup_peer->keys[0]&&lookup_peer->refs.value==1&&!ab.base_lock&&!ar.conf_mutex);
  assert(recover_calls==1&&!key_state.refs);
  ath11k_peer_put(&ar,lookup_peer);lookup_peer=NULL;
 }
 puts("PASS actual key callback: peer references, unmap/ID reuse, GTK replacement/PN and transport errors");
 return 0;
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", required=True, type=Path)
    parser.add_argument("--mac-source", type=Path)
    args = parser.parse_args()
    ath = args.backports / "drivers/net/wireless/ath/ath11k"
    peer = (ath / "peer.c").read_text()
    mac = (args.mac_source or ath / "mac.c").read_text()
    bodies = "".join(extractor.function(peer, name) for name in
                     ("ath11k_peer_get", "ath11k_peer_put_locked", "ath11k_peer_put", "ath11k_peer_release"))
    rx = (ath / "dp_rx.c").read_text()
    bodies += extractor.function(rx, "ath11k_peer_frags_flush")
    pn = extractor.function(rx, "ath11k_dp_peer_rx_pn_replay_config")
    bodies += extractor.function(mac, "ath11k_mac_peer_key_remove")
    bodies += extractor.function(mac, "ath11k_mac_key_detach_failed_delete")
    bodies += extractor.function(mac, "ath11k_mac_op_set_key")
    bodies += extractor.function(mac, "ath11k_clear_peer_keys")
    bodies += extractor.function(mac, "ath11k_mac_unregister")
    for name in ("ath11k_peer_map_event", "ath11k_peer_map_v2_event"):
        assert extractor.function(peer, name).count("refcount_set(&peer->refs, 1)") == 1
    assert "peer != key_peer" in pn
    with tempfile.TemporaryDirectory(prefix="nss-key-") as temp:
        source, binary = Path(temp) / "test.c", Path(temp) / "test"
        source.write_text(SHIM + bodies + MAIN)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True,
                       env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1"})


if __name__ == "__main__":
    main()
