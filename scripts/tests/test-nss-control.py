#!/usr/bin/env python3
"""Execute real dynamic/VDEV request identities, private waits and callback drains."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


functions = load('nss_control_functions', 'test-nss-multicast.py')
structures = load('nss_control_structures', 'test-nss-wifili.py')


def function(source, name):
    # The shared extractor also accepts calls inside an if (...){...} block.
    # Select a declaration line first, then extract its complete actual body.
    pattern = r'(?m)^[ \t]*(?:static[ \t]+)?(?:inline[ \t]+)?[A-Za-z_][\w \t*]*[ \t*]+' + re.escape(name) + r'\s*\('
    for match in re.finditer(pattern, source):
        brace = source.find('{', match.end())
        semicolon = source.find(';', match.end())
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            return functions.function(source[match.start():], name)
    raise ValueError('Missing function definition: ' + name)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
typedef uint32_t u32;typedef uint64_t nss_ptr_t;typedef int nss_tx_status_t;
#define NSS_CORE_MAX 2
#define NSS_CORE_0 0
#define NSS_MAX_NET_INTERFACES 16
#define NSS_DYNAMIC_IF_START 4
#define NSS_MAX_DYNAMIC_INTERFACES 8
#define NSS_SPECIAL_IF_START 12
#define NSS_DYNAMIC_INTERFACE 1
#define NSS_DYNAMIC_INTERFACE_ALLOC_NODE 0
#define NSS_DYNAMIC_INTERFACE_DEALLOC_NODE 1
#define NSS_DYNAMIC_INTERFACE_MAX 2
#define NSS_IF_MAX_MSG_TYPES 2
#define NSS_WIFI_VDEV_INTERFACE_CONFIGURE_MSG 3
#define NSS_WIFI_VDEV_MAX_MSG 16
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_TX_FAILURE_NOT_READY 2
#define NSS_TX_FAILURE_BAD_PARAM 3
#define NSS_CORE_STATUS_SUCCESS 0
#define NSS_NBUF_PAYLOAD_SIZE 2048
#define NSS_DYNAMIC_INTERFACE_COMP_TIMEOUT 1000
#define ATH11K_NSS_MSG_TIMEOUT_MS 1000
#define U32_MAX UINT32_MAX
#define GFP_ATOMIC 0
#define GFP_KERNEL 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define NL80211_IFTYPE_MESH_POINT 4
#define WIFI_VDEV_EXT_MODE_MESH_LINK 1
#define EXPORT_SYMBOL(x)
#define BUG_ON(x) assert(!(x))
#define nss_warning(...) ((void)0)
#define nss_info(...) ((void)0)
#define nss_trace(...) ((void)0)
#define nss_core_log_msg_failures(...) ((void)0)
#define nss_dynamic_interface_log_rx_msg(msg) ((void)(msg))
#define nss_dynamic_interface_log_tx_msg(...) ((void)0)
#define ath11k_warn(...) ((void)0)
#define ath11k_info(...) ((void)0)
enum nss_cmn_response { NSS_CMN_RESPONSE_ACK,NSS_CMN_RESPONSE_EMSG,NSS_CMN_RESPONSE_NOTIFY };
enum nss_dynamic_interface_type { NSS_DYNAMIC_INTERFACE_TYPE_NONE,NSS_DYNAMIC_INTERFACE_TYPE_VAP,NSS_DYNAMIC_INTERFACE_TYPE_RADIO,NSS_DYNAMIC_INTERFACE_TYPE_MAX };
typedef enum nss_dynamic_interface_type nss_dynamic_interface_assigned;
struct list_head { struct list_head *next,*prev; };
#define LIST_HEAD(n) struct list_head n={&n,&n}
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_entry(p,t,m) container_of(p,t,m)
#define list_for_each_entry(p,h,m) for(p=list_entry((h)->next,__typeof__(*p),m);&(p)->m!=(h);p=list_entry((p)->m.next,__typeof__(*p),m))
#define list_for_each_entry_safe(p,n,h,m) for(p=list_entry((h)->next,__typeof__(*p),m),n=list_entry((p)->m.next,__typeof__(*p),m);&(p)->m!=(h);p=n,n=list_entry((n)->m.next,__typeof__(*n),m))
static void list_add_tail(struct list_head *n,struct list_head *h) { n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n; }
static void list_del(struct list_head *n) { n->prev->next=n->next;n->next->prev=n->prev; }
typedef struct { _Atomic uint64_t value; } atomic64_t;
#define ATOMIC64_INIT(x) {.value=x}
static uint64_t atomic64_inc_return(atomic64_t *v) { return atomic_fetch_add(&v->value,1)+1; }
#define DEFINE_SPINLOCK(n) pthread_mutex_t n=PTHREAD_MUTEX_INITIALIZER
#define spin_lock_bh(p) assert(pthread_mutex_lock(p)==0)
#define spin_unlock_bh(p) assert(pthread_mutex_unlock(p)==0)
static pthread_mutex_t reader_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t reader_cond=PTHREAD_COND_INITIALIZER;
static unsigned readers;static _Atomic bool sync_entered;
static void rcu_read_lock_bh(void) { pthread_mutex_lock(&reader_lock);readers++;pthread_mutex_unlock(&reader_lock); }
static void rcu_read_unlock_bh(void) { pthread_mutex_lock(&reader_lock);assert(readers);readers--;pthread_cond_broadcast(&reader_cond);pthread_mutex_unlock(&reader_lock); }
static void synchronize_net(void) { atomic_store(&sync_entered,true);pthread_mutex_lock(&reader_lock);while(readers)pthread_cond_wait(&reader_cond,&reader_lock);pthread_mutex_unlock(&reader_lock); }
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done=false; }
static void complete(struct completion *c) { c->done=true; }
static bool completion_done(struct completion *c) { return c->done; }
static unsigned msecs_to_jiffies(unsigned v) { return v; }
static void (*wait_hook)(void);
static bool force_wait_timeout;
static int wait_for_completion_timeout(struct completion *c,unsigned timeout) { (void)timeout;if(wait_hook){void(*hook)(void)=wait_hook;wait_hook=NULL;hook();}return force_wait_timeout?0:c->done; }
static unsigned allocations,live_allocations,fail_allocation;
static void *kzalloc(size_t size,int flags) { (void)flags;allocations++;if(allocations==fail_allocation)return NULL;void *p=calloc(1,size);assert(p);live_allocations++;return p; }
static void kfree(void *p) { if(p){assert(live_allocations);live_allocations--;free(p);} }
struct nss_cmn_msg { uint32_t interface,type,len,response,error;nss_ptr_t cb,app_data; };
struct nss_dynamic_interface_alloc_node_msg { enum nss_dynamic_interface_type type;int if_num; };
struct nss_dynamic_interface_dealloc_node_msg { enum nss_dynamic_interface_type type;int if_num; };
struct nss_dynamic_interface_msg { struct nss_cmn_msg cm;union { struct nss_dynamic_interface_alloc_node_msg alloc_node;struct nss_dynamic_interface_dealloc_node_msg dealloc_node; } msg; };
struct nss_wifi_vdev_config_msg { u32 radio_ifnum,vdev_id,opmode,vap_ext_mode;unsigned char mac_addr[6]; };
struct nss_wifi_vdev_msg { struct nss_cmn_msg cm;union { struct nss_wifi_vdev_config_msg vdev_config; } msg; };
typedef void (*nss_wifi_vdev_msg_callback_t)(void *,struct nss_cmn_msg *);
struct nss_ctx_instance { unsigned id;struct { void *ndev; } subsys_dp_register[NSS_MAX_NET_INTERFACES]; };
static struct { unsigned wifi_handler_id;struct nss_ctx_instance nss[NSS_CORE_MAX];unsigned dynamic_interface_table[NSS_DYNAMIC_INTERFACE_TYPE_MAX]; } nss_top_main;
static void nss_cmn_msg_init(struct nss_cmn_msg *cm,u32 ifnum,u32 type,u32 len,void *cb,void *data) { cm->interface=ifnum;cm->type=type;cm->len=len;cm->cb=(uintptr_t)cb;cm->app_data=(uintptr_t)data; }
static unsigned nss_cmn_get_msg_len(struct nss_cmn_msg *cm) { return cm->len; }
static void nss_if_msg_handler(struct nss_ctx_instance *ctx,struct nss_cmn_msg *cm,void *data) { (void)ctx;(void)cm;(void)data;assert(false); }
static unsigned dealloc_notifications;
static void nss_dynamic_interface_stats_notify(uint32_t ifnum,uint32_t coreid) { assert(ifnum>=4&&ifnum<12&&coreid<2);dealloc_notifications++; }
static void nss_dynamic_interface_stats_dentry_create(void) {}
static int nss_core_register_handler(struct nss_ctx_instance *ctx,unsigned ifnum,void (*cb)(struct nss_ctx_instance *,struct nss_cmn_msg *,void *),void *data) { (void)ctx;(void)ifnum;(void)cb;(void)data;return 0; }
static unsigned notify_callbacks;
static void event_callback(void *data,struct nss_cmn_msg *cm) { assert(data&&cm->response==NSS_CMN_RESPONSE_NOTIFY);notify_callbacks++; }
static void *nss_core_get_msg_handler(struct nss_ctx_instance *ctx,unsigned ifnum) { (void)ctx;(void)ifnum;return event_callback; }
struct wire_copy { struct nss_ctx_instance *ctx;unsigned size;union { max_align_t alignment;unsigned char data[256]; } payload; };
static struct wire_copy wire;
static unsigned submissions;static bool send_failure,send_block,send_entered,send_release;
static pthread_mutex_t send_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t send_cond=PTHREAD_COND_INITIALIZER;
static nss_tx_status_t nss_core_send_cmd(struct nss_ctx_instance *ctx,void *msg,unsigned size,unsigned payload) {
 assert(size<=sizeof(wire.payload.data)&&payload==NSS_NBUF_PAYLOAD_SIZE);wire.ctx=ctx;wire.size=size;memcpy(wire.payload.data,msg,size);submissions++;
 pthread_mutex_lock(&send_lock);if(send_block){send_entered=true;pthread_cond_broadcast(&send_cond);while(!send_release)pthread_cond_wait(&send_cond,&send_lock);}pthread_mutex_unlock(&send_lock);
 return send_failure?NSS_TX_FAILURE:NSS_TX_SUCCESS;
}
static void ether_addr_copy(unsigned char *to,const unsigned char *from) { memcpy(to,from,6); }
struct ath11k_base { int unused; };
struct ath11k { struct ath11k_base *ab;struct { void *ctx;int if_num; } nss; };
struct ieee80211_vif { int type;unsigned char addr[6]; };
struct ath11k_vif { struct ath11k *ar;struct ieee80211_vif *vif;u32 vdev_id;struct { int if_num,config_result;struct completion complete; } nss; };
static unsigned ath11k_nss_get_vdev_opmode(struct ath11k_vif *vif) { (void)vif;return 2; }
'''

CASES = r'''
static unsigned callback_count;static nss_ptr_t expected_data=UINT64_C(0xfedcba9876543210);
static pthread_mutex_t callback_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t callback_cond=PTHREAD_COND_INITIALIZER;
static bool callback_block,callback_entered,callback_release;
static _Atomic bool close_finished,close_started;
static void client_callback(void *data,struct nss_cmn_msg *cm) {
 assert((uintptr_t)data==expected_data&&cm->app_data==expected_data);callback_count++;
 pthread_mutex_lock(&callback_lock);if(callback_block){callback_entered=true;pthread_cond_broadcast(&callback_cond);while(!callback_release)pthread_cond_wait(&callback_cond,&callback_lock);}pthread_mutex_unlock(&callback_lock);
}
static struct nss_wifi_vdev_msg request(void) { return (struct nss_wifi_vdev_msg){.cm={.interface=6,.type=3,.len=sizeof(struct nss_wifi_vdev_config_msg),.cb=(uintptr_t)client_callback,.app_data=expected_data}}; }
static void deliver(struct wire_copy copy,unsigned response,bool bad) {
 struct nss_cmn_msg *cm=(void *)copy.payload.data;cm->response=response;
 if(cm->interface==NSS_DYNAMIC_INTERFACE){struct nss_dynamic_interface_msg *msg=(void *)cm;if(cm->type==NSS_DYNAMIC_INTERFACE_ALLOC_NODE)msg->msg.alloc_node.if_num=6;if(bad)msg->msg.alloc_node.type=NSS_DYNAMIC_INTERFACE_TYPE_RADIO;nss_dynamic_interface_handler(copy.ctx,cm,NULL);}
 else nss_wifi_vdev_handler(copy.ctx,cm,NULL);
}
static void acknowledge(void) { deliver(wire,NSS_CMN_RESPONSE_ACK,false); }
static void reject(void) { deliver(wire,NSS_CMN_RESPONSE_EMSG,false); }
static void invalid_node(void) { deliver(wire,NSS_CMN_RESPONSE_ACK,true); }
static void truncated_node(void) { struct wire_copy copy=wire;((struct nss_cmn_msg *)(void *)copy.payload.data)->len=0;deliver(copy,NSS_CMN_RESPONSE_ACK,false); }
static void fresh(void) {
 for(unsigned i=0;i<2;i++){nss_top_main.nss[i].id=i;nss_control_close_core(&nss_top_main.nss[i]);nss_control_init_core(&nss_top_main.nss[i]);nss_dynamic_interface_register_handler(&nss_top_main.nss[i]);assert(nss_control_open(&nss_top_main.nss[i],NSS_CONTROL_WIFI_VDEV,6));nss_top_main.nss[i].subsys_dp_register[6].ndev=&nss_top_main;}
 assert(!live_allocations);memset(nss_dynamic_interface_assigned_types,0,sizeof(nss_dynamic_interface_assigned_types));memset(nss_dynamic_interface_assigned_generations,0,sizeof(nss_dynamic_interface_assigned_generations));allocations=fail_allocation=submissions=callback_count=notify_callbacks=dealloc_notifications=0;wait_hook=NULL;force_wait_timeout=send_failure=send_block=send_entered=send_release=false;callback_block=callback_entered=callback_release=false;atomic_store(&close_finished,false);atomic_store(&close_started,false);
}
static void *receiver(void *unused) { (void)unused;acknowledge();return NULL; }
static void *canceller(void *cookie) { nss_control_cancel((uintptr_t)cookie);atomic_store(&close_finished,true);return NULL; }
static void *closer(void *unused) { (void)unused;atomic_store(&close_started,true);nss_control_close(&nss_top_main.nss[0],NSS_CONTROL_WIFI_VDEV,6);atomic_store(&close_finished,true);return NULL; }
static void *sender(void *unused) { (void)unused;struct nss_wifi_vdev_msg msg=request();assert(nss_wifi_vdev_tx_msg_tracked(&nss_top_main.nss[0],&msg,NULL)==NSS_TX_SUCCESS);return NULL; }
static pthread_mutex_t prepare_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t prepare_cond=PTHREAD_COND_INITIALIZER;
static bool prepare_entered,prepare_release;
static struct wire_copy late_copy;
static void paused_prepare(struct nss_ctx_instance *ctx,struct nss_cmn_msg *cm,const void *original,uint32_t generation) {
 pthread_mutex_lock(&prepare_lock);prepare_entered=true;pthread_cond_broadcast(&prepare_cond);while(!prepare_release)pthread_cond_wait(&prepare_cond,&prepare_lock);pthread_mutex_unlock(&prepare_lock);
 nss_dynamic_interface_prepare_reply(ctx,cm,original,generation);
}
static void *late_node_receiver(void *unused) {
 (void)unused;struct wire_copy copy=late_copy;struct nss_dynamic_interface_msg *msg=(void *)copy.payload.data;msg->cm.response=NSS_CMN_RESPONSE_ACK;if(msg->cm.type==NSS_DYNAMIC_INTERFACE_ALLOC_NODE)msg->msg.alloc_node.if_num=6;
 assert(nss_control_receive(copy.ctx,&msg->cm,NSS_CONTROL_DYNAMIC,paused_prepare));return NULL;
}
int main(void) {
 struct nss_ctx_instance *ctx=&nss_top_main.nss[0];struct nss_wifi_vdev_msg msg;uint32_t cookie;
 fresh();msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==0&&cookie);
 assert(msg.cm.app_data==expected_data&&msg.cm.cb==(uintptr_t)client_callback);
 struct wire_copy original=wire;struct nss_cmn_msg *cm=(void *)original.payload.data;
 assert(cm->app_data==cookie&&cm->cb==(uintptr_t)nss_control_wire_callback);
 nss_control_wire_callback((void *)(uintptr_t)cookie,cm);assert(callback_count==0);
 struct wire_copy wrong=original;((struct nss_cmn_msg *)(void *)wrong.payload.data)->type++;
 deliver(wrong,NSS_CMN_RESPONSE_ACK,false);assert(callback_count==0);
 wrong=original;((struct nss_cmn_msg *)(void *)wrong.payload.data)->interface++;
 nss_control_receive(ctx,(void *)wrong.payload.data,NSS_CONTROL_WIFI_VDEV,NULL);assert(callback_count==0);
 nss_control_receive(&nss_top_main.nss[1],cm,NSS_CONTROL_WIFI_VDEV,NULL);
 nss_control_receive(ctx,cm,NSS_CONTROL_DYNAMIC,NULL);assert(callback_count==0);
 deliver(original,NSS_CMN_RESPONSE_NOTIFY,false);assert(notify_callbacks==1&&callback_count==0);
 deliver(original,NSS_CMN_RESPONSE_ACK,false);deliver(original,NSS_CMN_RESPONSE_ACK,false);assert(callback_count==1&&!live_allocations);
 msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==0);original=wire;
 nss_control_cancel(cookie);deliver(original,NSS_CMN_RESPONSE_ACK,false);assert(callback_count==1&&!live_allocations);
 msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==0);original=wire;
 nss_control_close(ctx,NSS_CONTROL_WIFI_VDEV,6);assert(!live_allocations);assert(nss_control_open(ctx,NSS_CONTROL_WIFI_VDEV,6));
 msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==0);struct wire_copy current=wire;
 deliver(original,NSS_CMN_RESPONSE_ACK,false);assert(callback_count==1);deliver(current,NSS_CMN_RESPONSE_ACK,false);assert(callback_count==2&&!live_allocations);
 send_failure=true;msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE&&cookie==0&&!live_allocations);send_failure=false;
 fail_allocation=allocations+1;assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE&&!live_allocations);fail_allocation=0;
 for(unsigned kind=0;kind<2;kind++) {
  fresh();msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==0);callback_block=true;
  pthread_t rx,closing;pthread_create(&rx,NULL,receiver,NULL);
  pthread_mutex_lock(&callback_lock);while(!callback_entered)pthread_cond_wait(&callback_cond,&callback_lock);pthread_mutex_unlock(&callback_lock);
  atomic_store(&sync_entered,false);pthread_create(&closing,NULL,kind?closer:canceller,(void *)(uintptr_t)cookie);
  while(!atomic_load(&sync_entered))sched_yield();
  assert(!atomic_load(&close_finished));
  pthread_mutex_lock(&callback_lock);callback_release=true;pthread_cond_broadcast(&callback_cond);pthread_mutex_unlock(&callback_lock);
  pthread_join(rx,NULL);pthread_join(closing,NULL);assert(atomic_load(&close_finished)&&!live_allocations);
 }
 fresh();send_block=true;pthread_t sending,closing;pthread_create(&sending,NULL,sender,NULL);
 pthread_mutex_lock(&send_lock);while(!send_entered)pthread_cond_wait(&send_cond,&send_lock);pthread_mutex_unlock(&send_lock);
 pthread_create(&closing,NULL,closer,NULL);
 while(!atomic_load(&close_started))sched_yield();
 assert(!atomic_load(&close_finished));
 pthread_mutex_lock(&send_lock);send_release=true;pthread_cond_broadcast(&send_cond);pthread_mutex_unlock(&send_lock);
 pthread_join(sending,NULL);pthread_join(closing,NULL);assert(!live_allocations);
 unsigned before=submissions;msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE_NOT_READY&&submissions==before);
 fresh();wait_hook=acknowledge;assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==6&&!live_allocations);
 assert(nss_dynamic_interface_assigned_types[0][2]==NSS_DYNAMIC_INTERFACE_TYPE_VAP);
 wait_hook=acknowledge;assert(nss_dynamic_interface_dealloc_node(6,NSS_DYNAMIC_INTERFACE_TYPE_VAP)==0&&!live_allocations&&dealloc_notifications==1);
 fresh();assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==-1&&!live_allocations);original=wire;
 wait_hook=acknowledge;assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_RADIO)==6&&!live_allocations);
 deliver(original,NSS_CMN_RESPONSE_ACK,false);assert(nss_dynamic_interface_assigned_types[0][2]==NSS_DYNAMIC_INTERFACE_TYPE_RADIO);
 assert(nss_dynamic_interface_dealloc_node(6,NSS_DYNAMIC_INTERFACE_TYPE_RADIO)!=0&&!live_allocations);original=wire;
 wait_hook=acknowledge;assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==6&&!live_allocations);
 deliver(original,NSS_CMN_RESPONSE_ACK,false);assert(nss_dynamic_interface_assigned_types[0][2]==NSS_DYNAMIC_INTERFACE_TYPE_VAP&&dealloc_notifications==0);
 fresh();wait_hook=reject;assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==-1&&!live_allocations);
 wait_hook=invalid_node;assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==-1&&!live_allocations&&nss_dynamic_interface_assigned_types[0][2]==0);
 wait_hook=truncated_node;assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==-1&&!live_allocations);
 for(unsigned failure=1;failure<=2;failure++){fresh();fail_allocation=failure;assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==-1&&!live_allocations);}
 for(unsigned reverse=0;reverse<2;reverse++) {
  fresh();struct nss_dynamic_interface_msg node={0};
  nss_dynamic_interface_msg_init(&node,1,reverse?NSS_DYNAMIC_INTERFACE_ALLOC_NODE:NSS_DYNAMIC_INTERFACE_DEALLOC_NODE,sizeof(node.msg.alloc_node),(void *)client_callback,(void *)(uintptr_t)expected_data);
  node.msg.alloc_node.type=reverse?NSS_DYNAMIC_INTERFACE_TYPE_RADIO:NSS_DYNAMIC_INTERFACE_TYPE_VAP;node.msg.alloc_node.if_num=6;
  assert(nss_dynamic_interface_tx_tracked(ctx,&node,&cookie)==0);late_copy=wire;prepare_entered=prepare_release=false;
  pthread_t late;pthread_create(&late,NULL,late_node_receiver,NULL);
  pthread_mutex_lock(&prepare_lock);while(!prepare_entered)pthread_cond_wait(&prepare_cond,&prepare_lock);pthread_mutex_unlock(&prepare_lock);
  node.cm.type=reverse?NSS_DYNAMIC_INTERFACE_DEALLOC_NODE:NSS_DYNAMIC_INTERFACE_ALLOC_NODE;node.msg.alloc_node.type=NSS_DYNAMIC_INTERFACE_TYPE_RADIO;
  assert(nss_dynamic_interface_tx_tracked(ctx,&node,NULL)==0);acknowledge();
  pthread_mutex_lock(&prepare_lock);prepare_release=true;pthread_cond_broadcast(&prepare_cond);pthread_mutex_unlock(&prepare_lock);pthread_join(late,NULL);
  assert(nss_dynamic_interface_assigned_types[0][2]==(reverse?NSS_DYNAMIC_INTERFACE_TYPE_NONE:NSS_DYNAMIC_INTERFACE_TYPE_RADIO));
  assert(callback_count==2&&dealloc_notifications==reverse&&!live_allocations);
 }
 fresh();force_wait_timeout=true;wait_hook=acknowledge;
 assert(nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VAP)==6&&!live_allocations);
 fresh();struct ath11k_base ab={0};struct ath11k ar={.ab=&ab,.nss={.ctx=ctx,.if_num=5}};struct ieee80211_vif vif={0};struct ath11k_vif arvif={.ar=&ar,.vif=&vif,.vdev_id=2,.nss={.if_num=6,.config_result=1234}};
 wait_hook=acknowledge;assert(ath11k_nss_vdev_configure(&arvif)==0&&!live_allocations&&arvif.nss.config_result==1234);
 force_wait_timeout=true;wait_hook=acknowledge;assert(ath11k_nss_vdev_configure(&arvif)==0&&!live_allocations);force_wait_timeout=false;
 wait_hook=reject;assert(ath11k_nss_vdev_configure(&arvif)==-EIO&&!live_allocations);
 assert(ath11k_nss_vdev_configure(&arvif)==-ETIMEDOUT&&!live_allocations);original=wire;
 wait_hook=acknowledge;assert(ath11k_nss_vdev_configure(&arvif)==0&&!live_allocations);
 deliver(original,NSS_CMN_RESPONSE_ACK,false);assert(!live_allocations&&arvif.nss.config_result==1234);
 for(unsigned failure=1;failure<=3;failure++){fresh();fail_allocation=failure;assert(ath11k_nss_vdev_configure(&arvif)<0&&!live_allocations);}
 fresh();msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==0);nss_control_close_core(ctx);assert(!live_allocations&&!nss_control_open(ctx,NSS_CONTROL_WIFI_VDEV,6));
 before=submissions;assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE_NOT_READY&&submissions==before);
 fresh();atomic_store(&nss_control_sequence.value,U32_MAX);msg=request();assert(nss_wifi_vdev_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE&&!cookie&&!live_allocations);
 puts("NSS control: identity, stale/duplicate rejection, callback drains, enqueue closure, shadow generations, timeout-edge ACK results and private waits passed");
 return 0;
}
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--drv', required=True, type=Path)
    p.add_argument('--backports', required=True, type=Path)
    args = p.parse_args()
    def read(path):
        return re.sub(r'/\*.*?\*/', '', path.read_text(), flags=re.S)
    core = re.sub(r'^#include.*\n', '', read(args.drv / 'nss_control.c'), flags=re.M)
    header = read(args.drv / 'nss_control.h')
    dynamic = read(args.drv / 'nss_dynamic_interface.c')
    vdev = read(args.drv / 'nss_wifi_vdev.c')
    ath = read(args.backports / 'drivers/net/wireless/ath/ath11k/nss.c')
    definitions = structures.structure(dynamic, 'nss_dynamic_interface_msg_data')
    definitions += '\nstatic nss_dynamic_interface_assigned nss_dynamic_interface_assigned_types[NSS_CORE_MAX][NSS_MAX_DYNAMIC_INTERFACES];\n'
    definitions += 'static uint32_t nss_dynamic_interface_assigned_generations[NSS_CORE_MAX][NSS_MAX_DYNAMIC_INTERFACES];\nstatic DEFINE_SPINLOCK(nss_dynamic_interface_assignment_lock);\n'
    dynamic_names = ['nss_is_dynamic_interface', 'nss_dynamic_interface_msg_init',
                     'nss_dynamic_interface_prepare_reply', 'nss_dynamic_interface_handler',
                     'nss_dynamic_interface_callback', 'nss_dynamic_interface_tx_tracked',
                     'nss_dynamic_interface_tx', 'nss_dynamic_interface_tx_sync',
                     'nss_dynamic_interface_alloc_node', 'nss_dynamic_interface_dealloc_node',
                     'nss_dynamic_interface_register_handler']
    bodies = '\n'.join(function(dynamic, name) for name in dynamic_names)
    bodies += '\n'.join(function(vdev, name) for name in
                        ['nss_wifi_vdev_msg_init', 'nss_wifi_vdev_handler',
                         'nss_wifi_vdev_tx_msg_tracked', 'nss_wifi_vdev_cancel_msg'])
    bodies += structures.structure(ath, 'ath11k_nss_vdev_request')
    bodies += '\n'.join(function(ath, name) for name in
                        ['ath11k_nss_vdev_cfg_cb', 'ath11k_nss_vdev_configure'])
    with tempfile.TemporaryDirectory(prefix='nss-control-') as tmp:
        source = Path(tmp) / 'control.c'
        source.write_text(SHIM + header + core + definitions + bodies + CASES)
        binary = source.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-Wall',
                        '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-no-pie', '-pthread', str(source),
                        '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
