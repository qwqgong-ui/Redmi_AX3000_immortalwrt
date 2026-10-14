#!/usr/bin/env python3
"""Run real cold VDEV format transactions and monitor header observation under ASan/UBSan."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile


def load(filename):
    spec = importlib.util.spec_from_file_location(filename, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extractor = load("test-nss-control.py")
structures = load("test-nss-wifili.py")

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint16_t __le16;typedef uint32_t u32;
typedef uintptr_t nss_ptr_t;typedef int nss_tx_status_t;
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_EMSG 1
#define NSS_CMN_RESPONSE_NOTIFY 5
#define NSS_WIFI_VDEV_INTERFACE_CMD_MSG 10003
#define NSS_WIFI_VDEV_ENCAP_TYPE_CMD 1
#define NSS_WIFI_VDEV_DECAP_TYPE_CMD 2
#define NSS_DYNAMIC_IF_START 32
#define NSS_MAX_DYNAMIC_INTERFACES 64
#define NSS_DYNAMIC_INTERFACE_TYPE_VAP 1
#define ATH11K_NSS_MSG_TIMEOUT_MS 1000
#define ATH11K_HW_TXRX_RAW 0
#define ATH11K_HW_TXRX_NATIVE_WIFI 1
#define ATH11K_HW_TXRX_ETHERNET 2
#define ATH11K_FLAG_RAW_MODE 0
#define ATH11K_FLAG_CRASH_FLUSH 1
#define ATH11K_FLAG_MONITOR_STARTED 0
#define WMI_VDEV_TYPE_MONITOR 3
#define WMI_VDEV_PARAM_TX_ENCAP_TYPE 1
#define WMI_VDEV_PARAM_RX_DECAP_TYPE 2
#define IEEE80211_OFFLOAD_ENCAP_ENABLED 1
#define IEEE80211_OFFLOAD_DECAP_ENABLED 2
#define NL80211_IFTYPE_STATION 2
#define NL80211_IFTYPE_AP 3
#define NL80211_IFTYPE_AP_VLAN 4
#define ATH11K_NSS_WIFI_VDEV_ENCAP_TYPE_CMD 1
#define ATH11K_NSS_WIFI_VDEV_DECAP_TYPE_CMD 2
#define GFP_KERNEL 1
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,x) ((v)=(x))
#define smp_load_acquire(p) (*(p))
#define smp_store_release(p,x) (*(p)=(x))
#define test_bit(n,p) (!!(*(p)&(1UL<<(n))))
#define set_bit(n,p) (*(p)|=1UL<<(n))
#define clear_bit(n,p) (*(p)&=~(1UL<<(n)))
#define lockdep_assert_held(p) assert(*(p))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define ath11k_dbg(...) ((void)0)
#define ath11k_warn(...) ((void)0)
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done=false; }
static void complete(struct completion *c) { c->done=true; }
static bool completion_done(struct completion *c) { return c->done; }
static unsigned msecs_to_jiffies(unsigned n) { return n; }
static int base_locked;
static unsigned allocations,live_allocations,fail_allocation,submissions,cancels,wmi_calls,wmi_fail;
static void *kzalloc(size_t size,int flags) { assert(flags==GFP_KERNEL&&!base_locked);allocations++;if(allocations==fail_allocation)return NULL;void *p=calloc(1,size);assert(p);live_allocations++;return p; }
static void kfree(void *p) { if(p){assert(live_allocations);live_allocations--;free(p);} }
static void spin_lock_bh(int *p) { assert(!*p&&!base_locked);*p=base_locked=1; }
static void spin_unlock_bh(int *p) { assert(*p&&base_locked);*p=base_locked=0; }
typedef struct { int64_t value; } atomic64_t;
static void atomic64_inc(atomic64_t *p) { p->value++; }
struct ath11k_vif;
struct ieee80211_vif { struct ath11k_vif *priv;int type;u32 offload_flags; };
struct ath11k_base { int base_lock;unsigned long dev_flags;struct { bool enabled,registered,quiescing,ownership_uncertain; } nss; };
struct ath11k { struct ath11k_base *ab;int conf_mutex;struct { void *ctx; } nss;atomic64_t monitor_observation[32];unsigned long monitor_flags;unsigned num_started_vdevs;int monitor_vdev_id,monitor_last_errno; };
struct ath11k_vif { struct ath11k *ar;struct ieee80211_vif *vif;u32 vdev_id,vdev_type;bool is_started,is_up;struct { u32 if_num;int encap,decap;bool created,key_failed,format_ready,format_failed;struct ath11k_vif *ap_vif; } nss; };
struct nss_ctx_instance { unsigned type; };
static unsigned nss_dynamic_interface_get_type(struct nss_ctx_instance *ctx,unsigned ifnum) { assert(ifnum>=32&&ifnum<96);return ctx->type; }
struct nss_cmn_msg { u32 interface,type,len,response,error;nss_ptr_t cb,app_data; };
struct nss_wifi_vdev_msg { struct nss_cmn_msg cm;union { struct { u32 cmd,value; } vdev_cmd; } msg; };
typedef void nss_wifi_vdev_msg_callback_t(void *,struct nss_cmn_msg *);
static void nss_wifi_vdev_msg_init(struct nss_wifi_vdev_msg *m,u32 ifnum,u32 type,u32 len,void *cb,void *data) { m->cm=(struct nss_cmn_msg){.interface=ifnum,.type=type,.len=len,.cb=(uintptr_t)cb,.app_data=(uintptr_t)data}; }
static struct ath11k_base ab;static struct ath11k ar;static struct ath11k_vif vif;static struct ieee80211_vif mac_vif;
static struct ath11k_vif *ath11k_vif_to_arvif(struct ieee80211_vif *v) { return v->priv; }
static int ath11k_frame_mode=ATH11K_HW_TXRX_ETHERNET;
struct cfg80211_chan_def { int dummy; };
static struct cfg80211_chan_def channel;
static bool monitor_start_fail,monitor_stop_fail,monitor_ring_fail;
static unsigned monitor_deletes,monitor_stops,monitor_ring_restores;
#define ieee80211_iter_chan_contexts_atomic(hw,fn,data) (*(struct cfg80211_chan_def **)(data)=&channel)
static int ath11k_mac_monitor_vdev_start(struct ath11k *radio,int id,struct cfg80211_chan_def *ch) { assert(radio==&ar&&id==ar.monitor_vdev_id&&ch==&channel);return monitor_start_fail?-EIO:0; }
static int ath11k_mac_monitor_vdev_delete(struct ath11k *radio) { assert(radio==&ar);monitor_deletes++;return 0; }
static int ath11k_mac_monitor_vdev_stop(struct ath11k *radio) { assert(radio==&ar);monitor_stops++;return monitor_stop_fail?-EIO:0; }
static int ath11k_dp_tx_htt_monitor_mode_ring_config(struct ath11k *radio,bool clear) { assert(radio==&ar);if(clear){monitor_ring_restores++;return 0;}return monitor_ring_fail?-EIO:0; }
static struct nss_wifi_vdev_msg pending;static bool pending_active,send_fail,edge_ack;
enum reply_kind { ACK,NAK,ERROR_CODE,WRONG_TYPE,WRONG_IF,NOTIFY,SHORT_LENGTH,WRONG_CMD,WRONG_VALUE,NO_REPLY,QUIESCE,RECYCLE,CRASH,TRUNCATED };
static enum reply_kind reply;static unsigned reply_stage;
static nss_tx_status_t nss_wifi_vdev_tx_msg_tracked(void *ctx,struct nss_wifi_vdev_msg *msg,u32 *cookie) { assert(ctx==&ar&&base_locked&&!pending_active&&!vif.nss.format_ready);submissions++;if(send_fail)return NSS_TX_FAILURE;pending=*msg;pending_active=true;*cookie=submissions;return NSS_TX_SUCCESS; }
static void deliver(void);
static void nss_wifi_vdev_cancel_msg(u32 cookie) { assert(!base_locked);if(cookie){assert(pending_active);if(edge_ack)deliver();pending_active=false;cancels++;} }
static int wait_for_completion_timeout(struct completion *c,unsigned timeout) { assert(!base_locked&&timeout==1000);if(!edge_ack)deliver();if(!c->done)return 0;c->done=false;return 1; }
static int ath11k_wmi_vdev_set_param_cmd(struct ath11k *radio,u32 id,u32 param,u32 mode) { assert(radio==&ar&&id==vif.vdev_id&&!base_locked);assert(param==WMI_VDEV_PARAM_TX_ENCAP_TYPE||param==WMI_VDEV_PARAM_RX_DECAP_TYPE);assert(mode<=2);assert(!vif.nss.format_ready);wmi_calls++;return wmi_calls==wmi_fail?-EIO:0; }
#define IEEE80211_FCTL_VERS 3
#define IEEE80211_BAR_CTRL_MULTI_TID 2
#define IEEE80211_BAR_CTRL_CBMTID_COMPRESSED_BA 4
#define cpu_to_le16(v) (v)
#define le16_to_cpu(v) (v)
struct ieee80211_hdr { __le16 frame_control;unsigned char rest[34]; };
struct sk_buff { unsigned char *data;unsigned len,linear; };
static int skb_copy_bits(struct sk_buff *skb,unsigned offset,void *out,unsigned len) { if(offset>skb->len||len>skb->len-offset)return -EFAULT;memcpy(out,skb->data+offset,len);return 0; }
static bool pskb_may_pull(struct sk_buff *skb,unsigned len) { if(len>skb->len)return false;skb->linear=len;return true; }
static bool ieee80211_is_data(__le16 fc) { return (fc&0x0c)==0x08; }
static bool ieee80211_is_ctl(__le16 fc) { return (fc&0x0c)==0x04; }
static bool ieee80211_is_mgmt(__le16 fc) { return (fc&0x0c)==0; }
static bool ieee80211_is_back(__le16 fc) { return (fc&0xfc)==0x94; }
static unsigned ieee80211_hdrlen(__le16 fc) { if(ieee80211_is_ctl(fc))return (fc&0xe0)==0xc0?10:16;unsigned n=24;if(ieee80211_is_data(fc)){if((fc&0x300)==0x300)n+=6;if(fc&0x80){n+=2;if(fc&0x8000)n+=4;}}return n; }
'''

SUPPORT = r'''
static struct nss_ctx_instance ctx={.type=NSS_DYNAMIC_INTERFACE_TYPE_VAP};
static void deliver(void) {
 assert(pending_active&&!base_locked);enum reply_kind kind=submissions==reply_stage?reply:ACK;
 if(kind==NO_REPLY)return;
 struct nss_wifi_vdev_msg m=pending;m.cm.response=NSS_CMN_RESPONSE_ACK;
 if(kind==NAK)m.cm.response=NSS_CMN_RESPONSE_EMSG;
 if(kind==ERROR_CODE)m.cm.error=7;
 if(kind==WRONG_TYPE)m.cm.type++;
 if(kind==WRONG_IF)m.cm.interface++;
 if(kind==NOTIFY)m.cm.response=NSS_CMN_RESPONSE_NOTIFY;
 if(kind==SHORT_LENGTH)m.cm.len=7;
 if(kind==WRONG_CMD)m.msg.vdev_cmd.cmd++;
 if(kind==WRONG_VALUE)m.msg.vdev_cmd.value++;
 if(kind==QUIESCE)ab.nss.quiescing=true;
 if(kind==RECYCLE)vif.nss.if_num++;
 if(kind==CRASH)ab.dev_flags|=1UL<<ATH11K_FLAG_CRASH_FLUSH;
 unsigned actual=kind==TRUNCATED?sizeof(m.cm)+7:sizeof(m);
 if(!nss_core_wifi_vdev_cmd_status_valid(&ctx,&m.cm,actual))return;
 ((nss_wifi_vdev_msg_callback_t *)m.cm.cb)((void *)m.cm.app_data,&m.cm);
}
static int ath11k_nss_vdev_set_cmd(struct ath11k_vif *v,int cmd,int value) { return ath11k_nss_vdev_set_format(v,cmd,value); }
static void fresh(void) {
 assert(!live_allocations&&!pending_active&&!base_locked);
 memset(&ab,0,sizeof(ab));memset(&ar,0,sizeof(ar));memset(&vif,0,sizeof(vif));memset(&mac_vif,0,sizeof(mac_vif));
 ab.nss.enabled=ab.nss.registered=true;ar.ab=&ab;ar.conf_mutex=1;ar.nss.ctx=&ar;
 vif.ar=&ar;vif.vif=&mac_vif;vif.vdev_id=4;vif.nss.if_num=36;vif.nss.created=true;
 vif.nss.encap=vif.nss.decap=1;mac_vif.priv=&vif;mac_vif.type=NL80211_IFTYPE_STATION;mac_vif.offload_flags=3;
 allocations=fail_allocation=submissions=cancels=wmi_calls=wmi_fail=0;send_fail=edge_ack=false;reply=ACK;reply_stage=1;
 monitor_start_fail=monitor_stop_fail=monitor_ring_fail=false;monitor_deletes=monitor_stops=monitor_ring_restores=0;
}
'''

CASES = r'''
int main(void) {
 struct nss_cmn_msg api={.len=8};assert(nss_cmn_get_msg_len(&api)==sizeof(api)+8);
 fresh();assert(ath11k_nss_vdev_key_failed(&vif));assert(!ath11k_mac_update_vif_offload(&ar,&mac_vif));assert(vif.nss.format_ready&&!vif.nss.format_failed&&vif.nss.encap==2&&vif.nss.decap==2&&submissions==2&&cancels==2&&!live_allocations);assert(!ath11k_nss_vdev_key_failed(&vif));
 unsigned sent=submissions,wmi=wmi_calls;assert(!ath11k_mac_update_vif_offload(&ar,&mac_vif)&&submissions==sent&&wmi_calls==wmi);
 mac_vif.offload_flags=1;assert(ath11k_mac_update_vif_offload(&ar,&mac_vif)==-EOPNOTSUPP&&mac_vif.offload_flags==3&&submissions==sent&&wmi_calls==wmi&&!vif.nss.format_failed);
 fresh();mac_vif.offload_flags=1;assert(!ath11k_mac_update_vif_offload(&ar,&mac_vif)&&vif.nss.encap==2&&vif.nss.decap==1&&vif.nss.format_ready);
 for(unsigned stage=1;stage<=2;stage++)for(enum reply_kind k=NAK;k<=TRUNCATED;k++) { fresh();reply_stage=stage;reply=k;int ret=ath11k_mac_update_vif_offload(&ar,&mac_vif);assert(ret<0&&!vif.nss.format_ready&&vif.nss.format_failed&&ath11k_nss_vdev_key_failed(&vif)&&!live_allocations&&!pending_active);assert(vif.nss.decap==1);if(stage==1)assert(vif.nss.encap==1);else assert(vif.nss.encap==2);assert(ath11k_nss_vdev_set_format(&vif,1,2)==-ESHUTDOWN); }
 for(unsigned n=1;n<=4;n++){fresh();fail_allocation=n;assert(ath11k_mac_update_vif_offload(&ar,&mac_vif)==-ENOMEM&&!vif.nss.format_ready&&vif.nss.format_failed&&!live_allocations);}
 for(unsigned n=1;n<=2;n++){fresh();wmi_fail=n;assert(ath11k_mac_update_vif_offload(&ar,&mac_vif)==-EIO&&!vif.nss.format_ready&&vif.nss.format_failed&&!live_allocations);}
 fresh();send_fail=true;assert(ath11k_mac_update_vif_offload(&ar,&mac_vif)==-EIO&&vif.nss.encap==1&&submissions==1&&!live_allocations);
 fresh();edge_ack=true;assert(!ath11k_mac_update_vif_offload(&ar,&mac_vif)&&vif.nss.format_ready&&cancels==2);
 fresh();assert(ath11k_nss_vdev_set_format(&vif,1,3)==-EINVAL&&allocations==0);assert(ath11k_nss_vdev_set_format(&vif,1,(u32)-1)==-EINVAL&&allocations==0);
 fresh();vif.is_up=true;assert(ath11k_mac_update_vif_offload(&ar,&mac_vif)==-EOPNOTSUPP&&submissions==0&&wmi_calls==0);
 struct ath11k_vif child={.nss.ap_vif=&vif};assert(ath11k_nss_vdev_key_failed(&child));
 unsigned char bytes[160]={0};struct sk_buff skb={.data=bytes};
 for(unsigned n=0;n<24;n++){skb.len=n;bytes[0]=8;assert(ath11k_nss_80211_header_len(&skb)==-EMSGSIZE);}
 skb.len=24;assert(ath11k_nss_80211_header_len(&skb)==24);bytes[0]=0x88;bytes[1]=3;skb.len=31;assert(ath11k_nss_80211_header_len(&skb)==-EMSGSIZE);skb.len=32;assert(ath11k_nss_80211_header_len(&skb)==32);bytes[1]=0x83;skb.len=35;assert(ath11k_nss_80211_header_len(&skb)==-EMSGSIZE);skb.len=36;assert(ath11k_nss_80211_header_len(&skb)==36);bytes[0]=9;assert(ath11k_nss_80211_header_len(&skb)==-EINVAL);
 memset(ar.monitor_observation,0,sizeof(ar.monitor_observation));bytes[0]=0xd4;bytes[1]=0;skb.len=10;ath11k_dp_rx_mon_observe_header(&ar,&skb);assert(ar.monitor_observation[ATH11K_MON_HEADER_CONTROL].value==1);bytes[0]=0x94;bytes[16]=4;skb.len=27;ath11k_dp_rx_mon_observe_header(&ar,&skb);assert(ar.monitor_observation[ATH11K_MON_BA_OTHER].value==1);skb.len=28;ath11k_dp_rx_mon_observe_header(&ar,&skb);assert(ar.monitor_observation[ATH11K_MON_BA_COMPLETE].value==1);bytes[16]=0;skb.len=147;ath11k_dp_rx_mon_observe_header(&ar,&skb);assert(ar.monitor_observation[ATH11K_MON_BA_OTHER].value==2);skb.len=148;ath11k_dp_rx_mon_observe_header(&ar,&skb);assert(ar.monitor_observation[ATH11K_MON_BA_COMPLETE].value==2);bytes[0]=8;skb.len=23;ath11k_dp_rx_mon_observe_header(&ar,&skb);assert(ar.monitor_observation[ATH11K_MON_HEADER_SHORT].value==1);bytes[0]=9;skb.len=24;ath11k_dp_rx_mon_observe_header(&ar,&skb);assert(ar.monitor_observation[ATH11K_MON_HEADER_INVALID].value==1);
 fresh();assert(!ath11k_mac_monitor_start(&ar)&&ar.num_started_vdevs==1&&test_bit(ATH11K_FLAG_MONITOR_STARTED,&ar.monitor_flags)&&ar.monitor_observation[ATH11K_MON_STARTS].value==1);assert(!ath11k_mac_monitor_start(&ar)&&ar.num_started_vdevs==1);
 fresh();monitor_start_fail=true;assert(ath11k_mac_monitor_start(&ar)==-EIO&&ar.monitor_last_errno==-EIO&&monitor_deletes==1&&!ar.num_started_vdevs&&!ar.monitor_flags);
 fresh();monitor_ring_fail=true;assert(ath11k_mac_monitor_start(&ar)==-EIO&&ar.monitor_last_errno==-EIO&&monitor_stops==1&&monitor_ring_restores==1&&!ar.num_started_vdevs&&!ar.monitor_flags&&!ar.monitor_observation[ATH11K_MON_STARTS].value);
 fresh();monitor_ring_fail=monitor_stop_fail=true;assert(ath11k_mac_monitor_start(&ar)==-EIO&&ar.monitor_last_errno==-EIO&&ar.num_started_vdevs==1&&test_bit(ATH11K_FLAG_MONITOR_STARTED,&ar.monitor_flags)&&!ar.monitor_observation[ATH11K_MON_STARTS].value);
 puts("PASS real cold format ACKs, real buffer boundary, partial-side failures, cancel-edge ACK, close/reuse gates, no live format switch, native/header/BA bounds and monitor-start unwind");return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ath11k-source", type=Path, required=True)
    parser.add_argument("--nss-source", type=Path, required=True)
    args = parser.parse_args()
    nss = (args.ath11k_source / "nss.c").read_text()
    mac = (args.ath11k_source / "mac.c").read_text()
    core = (args.ath11k_source / "core.h").read_text()
    dp_rx = (args.ath11k_source / "dp_rx.c").read_text()
    driver = (args.nss_source / "nss_core.c").read_text()
    cmn = (args.nss_source / "exports/nss_cmn.h").read_text()
    enum = re.search(r"enum ath11k_monitor_observation\s*\{[^}]+\};", core).group()
    defs = enum + structures.structure(nss, "ath11k_nss_vdev_request") + structures.structure(nss, "ath11k_nss_vdev_format_request")
    defs += extractor.function(driver, "nss_core_wifi_vdev_cmd_status_valid")
    defs += extractor.function(cmn, "nss_cmn_get_msg_len")
    defs += extractor.function(nss, "ath11k_nss_vdev_format_cb")
    defs += extractor.function(nss, "ath11k_nss_vdev_set_format")
    defs += extractor.function(nss, "ath11k_nss_vdev_key_failed")
    defs += extractor.function(nss, "ath11k_nss_80211_header_len")
    defs += extractor.function(dp_rx, "ath11k_dp_rx_mon_observe_header")
    with tempfile.TemporaryDirectory(prefix="nss-vdev-format-") as tmp:
        path = Path(tmp) / "test.c"
        binary = Path(tmp) / "test"
        path.write_text(SHIM + defs + SUPPORT + extractor.function(mac, "ath11k_mac_update_vif_offload") + extractor.function(mac, "ath11k_mac_monitor_start") + CASES)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1", "-Wall", "-Werror",
                        "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
