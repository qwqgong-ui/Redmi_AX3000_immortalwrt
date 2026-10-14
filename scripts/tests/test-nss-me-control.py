#!/usr/bin/env python3
"""Exercise actual ME request callbacks, admission and cancel-before-free flow."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

def helper(filename):
    spec = importlib.util.spec_from_file_location(filename, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

extract = helper('test-nss-control.py')
layout = helper('test-nss-wifili.py')

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <stddef.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { int64_t counter; } atomic64_t;
#define ETH_ALEN 6
#define NSS_WIFI_VDEV_IPV6_ADDR_WORDS 4
#define NSS_WIFI_VDEV_IPV6_ADDR_LENGTH 16
#define NSS_WIFI_MAX_SRCS 4
#define GFP_KERNEL 0
#define U32_MAX UINT32_MAX
#define READ_ONCE(x) (x)
#define smp_load_acquire(p) (*(p))
#define lockdep_assert_held(p) ((void)(p))
#define spin_lock_bh(p) ((void)(p))
#define spin_unlock_bh(p) ((void)(p))
#define struct_size(p, m, n) (sizeof(*(p))+(n)*sizeof((p)->m[0]))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define msecs_to_jiffies(n) (n)
#define ATH11K_NSS_MSG_TIMEOUT_MS 5000
#define ATH11K_STATE_ON 1
#define ATH11K_STATE_RESTARTED 2
#define ATH11K_FLAG_CRASH_FLUSH 0
#define NL80211_IFTYPE_AP 3
#define HAL_TCL_ENCAP_TYPE_ETHERNET 2
#define ATH11K_HW_TXRX_ETHERNET 2
#define NSS_WIFI_VDEV_CFG_MCBC_EXC_TO_HOST_CMD 22
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_NACK 1
#define NSS_CMN_RESPONSE_NOTIFY 2
#define NSS_WIFI_VDEV_INTERFACE_CMD_MSG 10003
typedef int nss_tx_status_t;
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done=false; }
static void complete(struct completion *c) { c->done=true; }
static bool completion_done(struct completion *c) { return c->done; }
static unsigned allocations;
static void *kzalloc(size_t size, int flags) { (void)flags; allocations++; return calloc(1,size); }
static void kfree(void *p) { assert(p && allocations); allocations--; free(p); }
static bool test_bit(unsigned bit, unsigned long *flags) { return !!(*flags & (1ul << bit)); }
struct nss_cmn_msg { u32 type,interface,response,error,len; };
typedef void nss_wifi_vdev_msg_callback_t(void *,struct nss_cmn_msg *);
'''

PLATFORM = r'''
struct nss_wifi_vdev_msg {
 struct nss_cmn_msg cm;
 union {
  struct nss_wifi_vdev_cmd_msg vdev_cmd;
  struct nss_wifi_vdev_me_snptbl_grp_create_msg vdev_grp_list_create;
  struct nss_wifi_vdev_me_snptbl_grp_mbr_add_msg vdev_grp_member_add;
 } msg;
};
struct ath11k_base { int base_lock; unsigned long dev_flags;
 struct { bool enabled,registered,quiescing,ownership_uncertain; } nss;
};
struct ieee80211_vif { int type; };
struct ath11k { struct ath11k_base *ab; int state,conf_mutex; struct {void *ctx;} nss; };
struct ath11k_vif { struct ath11k *ar; struct ieee80211_vif *vif;
 struct { bool created,format_ready,format_failed,key_failed; int encap,decap; u32 if_num; struct ath11k_nss_me_state me; } nss;
};
struct ath11k_peer { bool is_authorized; struct ieee80211_vif *vif; };
struct ath11k_nss_peer_state { bool valid; };
static bool ath11k_nss_vdev_key_failed(struct ath11k_vif *v) { return v->nss.key_failed || v->nss.format_failed; }
static int ath11k_nss_key_check(struct ath11k *ar, struct ath11k_peer *peer, struct ath11k_nss_peer_state *s) {
 (void)ar;(void)peer;return s && s->valid ? 0 : -ENOENT;
}
enum scenario { GOOD, SUBMIT_FAIL, TIMEOUT, CANCEL_COMPLETES, NACK, ACK_ERROR, SHORT,
 LONG, BAD_ECHO, WRONG_IF, WRONG_TYPE, NOTIFY, STOPPED_AFTER_REPLY, REUSED_IF, KEY_REVOKED };
static enum scenario scenario;
static nss_wifi_vdev_msg_callback_t *pending_cb;
static void *pending_data;
static struct nss_wifi_vdev_msg pending_msg;
static struct ath11k_vif *current_vif;
static struct ath11k_peer *current_peer;
static struct ath11k_nss_peer_state *current_state;
static unsigned submissions,cancellations;
static void nss_wifi_vdev_msg_init(struct nss_wifi_vdev_msg *m,u32 iface,u32 type,u32 len,
 nss_wifi_vdev_msg_callback_t *cb,void *data) {
 m->cm.interface=iface;m->cm.type=type;m->cm.len=len;pending_cb=cb;pending_data=data;
}
static nss_tx_status_t nss_wifi_vdev_tx_msg_tracked(void *ctx,struct nss_wifi_vdev_msg *m,u32 *cookie) {
 (void)ctx;submissions++;
 if(scenario==SUBMIT_FAIL)return NSS_TX_FAILURE;
 *cookie=17;pending_msg=*m;return NSS_TX_SUCCESS;
}
static void reply(void) {
 struct nss_wifi_vdev_msg m=pending_msg;
 m.cm.response=NSS_CMN_RESPONSE_ACK;m.cm.error=0;
 if(scenario==NACK)m.cm.response=NSS_CMN_RESPONSE_NACK;
 if(scenario==ACK_ERROR)m.cm.error=25;
 if(scenario==SHORT)m.cm.len--;
 if(scenario==LONG)m.cm.len++;
 if(scenario==BAD_ECHO)m.msg.vdev_cmd.value++;
 if(scenario==WRONG_IF)m.cm.interface++;
 if(scenario==WRONG_TYPE)m.cm.type++;
 if(scenario==NOTIFY)m.cm.response=NSS_CMN_RESPONSE_NOTIFY;
 pending_cb(pending_data,&m.cm);
}
static unsigned long wait_for_completion_timeout(struct completion *c,unsigned long timeout) {
 (void)timeout;
 if(scenario!=TIMEOUT && scenario!=CANCEL_COMPLETES)reply();
 if(scenario==STOPPED_AFTER_REPLY)current_vif->ar->ab->nss.quiescing=true;
 if(scenario==REUSED_IF)current_vif->nss.if_num++;
 if(scenario==KEY_REVOKED){current_peer->is_authorized=false;current_state->valid=false;}
 return c->done;
}
static void nss_wifi_vdev_cancel_msg(u32 cookie) {
 cancellations++;
 if(cookie && scenario==CANCEL_COMPLETES)reply();
 pending_cb=NULL;pending_data=NULL;
}
'''

CASES = r'''
static struct ath11k_base ab;
static struct ath11k ar;
static struct ieee80211_vif vif;
static struct ath11k_vif arvif;
static struct ath11k_peer peer;
static struct ath11k_nss_peer_state state;
static void fresh(enum scenario selected) {
 assert(!allocations);memset(&ab,0,sizeof(ab));memset(&arvif,0,sizeof(arvif));
 ab.nss.enabled=ab.nss.registered=true;ar.ab=&ab;ar.state=ATH11K_STATE_ON;
 vif.type=NL80211_IFTYPE_AP;arvif.ar=&ar;arvif.vif=&vif;arvif.nss.created=arvif.nss.format_ready=true;
 arvif.nss.encap=HAL_TCL_ENCAP_TYPE_ETHERNET;arvif.nss.decap=ATH11K_HW_TXRX_ETHERNET;
 arvif.nss.if_num=35;arvif.nss.me.mode_known=true;arvif.nss.me.global_mode=6;
 peer.vif=&vif;peer.is_authorized=true;state.valid=true;
 current_vif=&arvif;current_peer=&peer;current_state=&state;
 scenario=selected;submissions=cancellations=0;pending_cb=NULL;pending_data=NULL;
}
static int exchange(bool use_peer,u32 len) {
 struct nss_wifi_vdev_msg m={0};m.msg.vdev_cmd.cmd=3;m.msg.vdev_cmd.value=5;
 return ath11k_nss_me_exchange(&arvif,&m,10003,len,use_peer?&peer:NULL,use_peer?&state:NULL);
}
static void expect(enum scenario s,int result,bool uncertain) {
 fresh(s);assert(exchange(s==KEY_REVOKED,8)==result);
 assert(submissions==1 && cancellations==1 && !allocations && !pending_data);
 assert(arvif.nss.me.attempts==1 && arvif.nss.me.result==result && arvif.nss.me.uncertain==uncertain);
 assert(arvif.nss.format_ready && !arvif.nss.format_failed);
 if(uncertain)assert(!arvif.nss.me.mode_known && !arvif.nss.me.global_mode);
}
static void denied(void) {
 fresh(GOOD);ab.nss.quiescing=true;assert(exchange(false,8)==-ESHUTDOWN);assert(!submissions && cancellations==1 && !allocations);
 fresh(GOOD);arvif.nss.format_ready=false;assert(exchange(false,8)==-ESHUTDOWN);assert(!submissions && !allocations);
 fresh(GOOD);vif.type=1;assert(exchange(false,8)==-EOPNOTSUPP);assert(!submissions && !allocations);
 fresh(GOOD);peer.is_authorized=false;assert(exchange(true,8)==-ENOENT);assert(!submissions && !allocations);
 fresh(GOOD);assert(exchange(false,sizeof(pending_msg.msg)+1)==-EINVAL);assert(!submissions && !cancellations && !allocations);
}
static void zero_payload(void) {
 fresh(GOOD);struct nss_wifi_vdev_msg m={0};
 assert(!ath11k_nss_me_exchange(&arvif,&m,10013,0,NULL,NULL));
 assert(arvif.nss.me.echo_match && !arvif.nss.me.len && !allocations);
}
static void host_rx(void) {
 fresh(GOOD);assert(!ath11k_nss_me_host_rx(&arvif));
 assert(submissions==1 && cancellations==1 && !allocations);
 assert(pending_msg.msg.vdev_cmd.cmd==22 && pending_msg.msg.vdev_cmd.value==1);
 assert(arvif.nss.me.rx_mcbc_known && arvif.nss.me.rx_mcbc==1);
 assert(!ath11k_nss_me_host_rx(&arvif));assert(submissions==1);
 ab.nss.quiescing=true;
 assert(ath11k_nss_me_host_rx(&arvif)==-ESHUTDOWN && submissions==1 && !allocations);
 fresh(TIMEOUT);assert(ath11k_nss_me_host_rx(&arvif)==-ETIMEDOUT);
 assert(!arvif.nss.me.rx_mcbc_known && arvif.nss.me.uncertain && !allocations);
 fresh(BAD_ECHO);assert(ath11k_nss_me_host_rx(&arvif)==-EPROTO);
 assert(!arvif.nss.me.rx_mcbc_known && !allocations);
 fresh(SUBMIT_FAIL);assert(ath11k_nss_me_host_rx(&arvif)==-EIO);
 assert(!arvif.nss.me.rx_mcbc_known && !arvif.nss.me.uncertain && !allocations);
 fresh(GOOD);arvif.nss.format_ready=false;
 assert(ath11k_nss_me_host_rx(&arvif)==-ESHUTDOWN && !submissions && !allocations);
 fresh(GOOD);arvif.nss.decap=1;
 assert(!ath11k_nss_me_host_rx(&arvif) && !submissions && !allocations);
 fresh(GOOD);ar.state=ATH11K_STATE_RESTARTED;
 assert(!ath11k_nss_me_host_rx(&arvif) && submissions==1 && !allocations);
 fresh(GOOD);ar.state=0;
 assert(ath11k_nss_me_host_rx(&arvif)==-ESHUTDOWN && !submissions && !allocations);
 fresh(GOOD);vif.type=1;
 assert(!ath11k_nss_me_host_rx(&arvif) && !submissions && !allocations);
}
int main(void) {
 _Static_assert(sizeof(struct nss_wifi_vdev_cmd_msg)==8,"real command payload");
 _Static_assert(sizeof(struct nss_wifi_vdev_me_snptbl_grp_create_msg)==28,"real group payload");
 _Static_assert(sizeof(struct nss_wifi_vdev_me_snptbl_grp_mbr_add_msg)==112,"real member payload");
 expect(GOOD,0,false);expect(SUBMIT_FAIL,-EIO,false);expect(TIMEOUT,-ETIMEDOUT,true);
 expect(CANCEL_COMPLETES,0,false);expect(NACK,-EREMOTEIO,true);expect(ACK_ERROR,-EREMOTEIO,true);
 expect(SHORT,-EMSGSIZE,true);expect(LONG,-EMSGSIZE,true);expect(BAD_ECHO,-EPROTO,true);
 expect(WRONG_IF,-ETIMEDOUT,true);expect(WRONG_TYPE,-ETIMEDOUT,true);expect(NOTIFY,-ETIMEDOUT,true);
 expect(STOPPED_AFTER_REPLY,-ESHUTDOWN,true);expect(REUSED_IF,-ESHUTDOWN,true);expect(KEY_REVOKED,-ENOENT,true);
 denied();zero_payload();host_rx();
 puts("PASS actual ME callback/exchange: ACK/error/length/echo, wrong identity/NOTIFY, cancel-time completion, timeout, lifecycle and peer revalidation, zero payload and real 8/28/112-byte structures");
 return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ath11k-source', type=Path, required=True)
    parser.add_argument('--nss-source', type=Path, required=True)
    args = parser.parse_args()
    source = (args.ath11k_source/'nss_me.c').read_text()
    types = (args.ath11k_source/'nss.h').read_text()
    export = (args.nss_source/'exports/nss_wifi_vdev.h').read_text()
    definitions = layout.structure(types,'ath11k_nss_me_state')
    for name in ('nss_wifi_vdev_cmd_msg','nss_wifi_vdev_me_snptbl_grp_create_msg',
                 'nss_wifi_vdev_me_mbr_ra_info','nss_wifi_vdev_me_snptbl_grp_mbr_add_msg'):
        definitions += layout.structure(export,name)
    request = layout.structure(source,'ath11k_nss_me_request')
    functions = '\n'.join(extract.function(source,name) for name in
        ('ath11k_nss_me_reply','ath11k_nss_me_admit','ath11k_nss_me_exchange',
         'ath11k_nss_me_host_rx'))
    with tempfile.TemporaryDirectory(prefix='nss-me-control-') as directory:
        cfile=Path(directory)/'test.c'; binary=Path(directory)/'test'
        cfile.write_text(SHIM+definitions+PLATFORM+request+functions+CASES)
        subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Werror','-O1','-g',
                        '-fsanitize=address,undefined','-fno-pie','-no-pie',str(cfile),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
if __name__=='__main__':
    main()
