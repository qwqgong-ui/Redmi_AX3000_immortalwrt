#!/usr/bin/env python3
"""Execute real BASE broker, DP publication and core RX with owner reuse races."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "nss_base_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SUPPORT = r'''
#define NSS_PHYSICAL_IF_START 0
#define NSS_IF_TX_TIMEOUT 3000
#define NSS_HLOS_MESSAGE_VERSION 1
#define unlikely(v) (v)
typedef uint16_t u16;
typedef void *nss_phys_if_rx_callback_t;
typedef void *nss_phys_if_rx_ext_data_callback_t;
typedef void (*nss_core_rx_callback_t)(struct nss_ctx_instance *,struct nss_cmn_msg *,void *);
struct net_device { unsigned id; };
struct nss_if_msg { struct nss_cmn_msg cm;unsigned char payload[32]; };
struct skb_fragment { void *data;unsigned size; };
struct skb_shared_info { unsigned nr_frags;struct skb_fragment frags[1]; };
struct sk_buff { void *data;unsigned len;struct skb_shared_info info; };
static struct skb_shared_info *skb_shinfo(struct sk_buff *skb) { return &skb->info; }
static void *skb_frag_address(struct skb_fragment *frag) { return frag->data; }
static unsigned skb_frag_size(struct skb_fragment *frag) { return frag->size; }
#define DEFINE_PER_CPU(type,name) type name
#define this_cpu_ptr(p) (p)
static unsigned preempt_depth,wire_capacity;
static void preempt_disable(void) { preempt_depth++; }
static void preempt_enable(void) { assert(preempt_depth);preempt_depth--; }
static void (*tx_hook)(void);
static void nss_if_log_tx_msg(struct nss_if_msg *msg) {
 (void)msg;if(tx_hook){void(*hook)(void)=tx_hook;tx_hook=NULL;hook();}
}
static nss_tx_status_t nss_if_tx_msg_with_size_tracked(struct nss_ctx_instance *,struct nss_if_msg *,uint32_t,uint32_t *);
static nss_tx_status_t nss_if_tx_msg_tracked(struct nss_ctx_instance *,struct nss_if_msg *,uint32_t *);
static void nss_if_cancel_msg(uint32_t);
/* Shaper stats replies are covered by test-nss-short-stats-reply.py. */
static bool nss_if_short_stats_reply(struct nss_ctx_instance *ctx,struct nss_cmn_msg *cm,uint32_t len) { (void)ctx;(void)cm;(void)len;return false; }
'''

TEST = r'''
struct observer { struct nss_ctx_instance *ctx;unsigned calls,length; };
static struct observer observed[NSS_CORE_MAX],replacement;
static struct net_device devices[NSS_CORE_MAX],new_device;
static unsigned family_calls,legacy_calls;
static pthread_mutex_t callback_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t callback_cond=PTHREAD_COND_INITIALIZER;
static bool callback_block,callback_entered,callback_release;
static _Atomic bool closed,closing;
static struct wire_copy saved;
static void response(void *data,struct nss_cmn_msg *cm) {
 struct observer *o=data;
 assert(o&&cm->app_data==(uintptr_t)o&&preempt_depth);
 unsigned length=nss_if_rx_msg_buf_len(o->ctx);
 assert(!nss_if_rx_msg_buf_len(&nss_top_main.nss[1-o->ctx->id]));
 assert(length>=sizeof(*cm)+cm->len);
 if(o->length)assert(o->length==length);
 o->calls++;
 pthread_mutex_lock(&callback_lock);
 if(callback_block){callback_entered=true;pthread_cond_broadcast(&callback_cond);while(!callback_release)pthread_cond_wait(&callback_cond,&callback_lock);}
 pthread_mutex_unlock(&callback_lock);
}
static void family_handler(struct nss_ctx_instance *ctx,struct nss_cmn_msg *cm,void *data) {
 (void)data;family_calls++;
 if(cm->response==NSS_CMN_RESPONSE_NOTIFY){notify_callbacks++;return;}
 if(cm->cb==(uintptr_t)nss_control_wire_callback)
  assert(nss_control_receive(ctx,cm,NSS_CONTROL_WIFI_EXT_VDEV,NULL));
 else{legacy_calls++;((void(*)(void *,struct nss_cmn_msg *))(uintptr_t)cm->cb)((void *)(uintptr_t)cm->app_data,cm);}
}
static struct nss_if_msg request(unsigned core,unsigned number) {
 return (struct nss_if_msg){.cm={.version=1,.interface=number,.type=0,.len=4,
  .cb=(uintptr_t)response,.app_data=(uintptr_t)&observed[core]}};
}
static void deliver(struct wire_copy copy,unsigned response_type,unsigned body,unsigned extra,bool fragment) {
 struct nss_cmn_msg *wire_cm=(void *)copy.payload.data;
 unsigned size=sizeof(*wire_cm)+body+extra;
 void *buffer=calloc(1,size);assert(buffer);
 memcpy(buffer,copy.payload.data,size<copy.size?size:copy.size);
 struct nss_cmn_msg *cm=buffer;cm->response=response_type;cm->len=body;
 struct sk_buff skb={.data=buffer,.len=size};
 if(fragment){skb.info.nr_frags=1;skb.info.frags[0]=(struct skb_fragment){buffer,size};skb.len=0;}
 nss_core_handle_nss_status_pkt(copy.ctx,&skb);assert(!preempt_depth);
 assert(!nss_core_rx_msg_buf_len(copy.ctx));free(buffer);
}
static void acknowledge(void) { deliver(wire,NSS_CMN_RESPONSE_ACK,0,0,false); }
static void reject(void) { deliver(wire,NSS_CMN_RESPONSE_EMSG,0,0,false); }
static void late_reply(void) { deliver(saved,NSS_CMN_RESPONSE_ACK,0,0,false); }
static void fresh(void) {
 for(unsigned i=0;i<NSS_CORE_MAX;i++){
  struct nss_ctx_instance *ctx=&nss_top_main.nss[i];ctx->id=i;
  nss_control_close_core(ctx);memset(ctx->subsys_dp_register,0,sizeof(ctx->subsys_dp_register));
  memset(ctx->nss_rx_interface_handlers,0,sizeof(ctx->nss_rx_interface_handlers));
  nss_control_init_core(ctx);observed[i]=(struct observer){.ctx=ctx};
  ctx->subsys_dp_register[6].type=71;ctx->subsys_dp_register[6].xmit_cb=&devices[i];
  nss_core_register_subsys_dp(ctx,6,NULL,NULL,&observed[i],&devices[i],0x1234);
  nss_core_register_subsys_dp(ctx,1,NULL,NULL,&observed[i],&devices[i],0x1234);
  ctx->nss_rx_interface_handlers[6].cb=family_handler;
 }
 assert(!live_allocations);
 allocations=fail_allocation=submissions=family_calls=legacy_calls=wire_capacity=0;
 force_wait_timeout=send_failure=send_block=send_entered=send_release=false;
 callback_block=callback_entered=callback_release=false;wait_hook=tx_hook=NULL;
 atomic_store(&sync_entered,false);atomic_store(&closed,false);atomic_store(&closing,false);
}
static void owner_change(void) {
 struct nss_ctx_instance *ctx=&nss_top_main.nss[0];
 nss_core_unregister_subsys_dp(ctx,6);
 replacement=(struct observer){.ctx=ctx};
 nss_core_register_subsys_dp(ctx,6,NULL,NULL,&replacement,&new_device,0x5678);
}
static void leases(void) {
 fresh();struct nss_ctx_instance *ctx=&nss_top_main.nss[0];
 uint64_t old=nss_control_base_lease(ctx,6);assert(old);
 struct nss_if_msg msg=request(0,6);uint32_t cookie=123;
 assert(!nss_control_open(ctx,NSS_CONTROL_BASE_IF,6));
 assert(nss_control_send(ctx,&msg,sizeof(msg),2048,NSS_CONTROL_BASE_IF,&cookie)==NSS_TX_FAILURE_BAD_PARAM&&!cookie);
 nss_core_unregister_subsys_dp(ctx,6);assert(!nss_control_base_lease(ctx,6));
 unsigned before=submissions;
 assert(nss_control_base_send(ctx,&msg,sizeof(msg),2048,old,&cookie)==NSS_TX_FAILURE_NOT_READY&&!cookie);
 nss_core_register_subsys_dp(ctx,6,NULL,NULL,&observed[0],&new_device,0x5678);
 assert(nss_control_base_lease(ctx,6)!=old);
 assert(nss_control_base_send(ctx,&msg,sizeof(msg),2048,old,&cookie)==NSS_TX_FAILURE_NOT_READY&&submissions==before);
 assert(!nss_if_tx_msg_tracked(ctx,&msg,&cookie));acknowledge();assert(observed[0].calls==1);
 fresh();old=nss_control_base_lease(ctx,6);msg=request(0,6);
 assert(!nss_if_tx_msg_tracked(ctx,&msg,&cookie));
 nss_core_register_subsys_dp(ctx,6,&observed[0],NULL,&observed[0],&devices[0],0x99);
 assert(nss_control_base_lease(ctx,6)==old&&ctx->subsys_dp_register[6].type==71);
 assert(ctx->subsys_dp_register[6].xmit_cb==&devices[0]&&ctx->subsys_dp_register[6].features==0x99);
 acknowledge();assert(observed[0].calls==1);
 nss_core_unregister_subsys_dp(ctx,6);assert(ctx->subsys_dp_register[6].xmit_cb==&devices[0]&&!ctx->subsys_dp_register[6].type);
 nss_core_register_subsys_dp(ctx,6,NULL,NULL,&observed[0],NULL,0x55);
 assert(!nss_control_base_lease(ctx,6)&&ctx->subsys_dp_register[6].features==0x55);
 fresh();msg=request(0,6);before=submissions;tx_hook=owner_change;
 assert(nss_if_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE_NOT_READY&&!cookie&&submissions==before);
 assert(!observed[0].calls&&!replacement.calls);
 fresh();old=nss_control_base_lease(ctx,6);nss_control_close_core(ctx);
 nss_core_register_subsys_dp(ctx,6,NULL,NULL,&observed[0],&devices[0],0x77);
 assert(!nss_control_base_lease(ctx,6));nss_control_init_core(ctx);
 assert(!nss_control_base_lease(ctx,6));
 nss_core_register_subsys_dp(ctx,6,NULL,NULL,&observed[0],&devices[0],0x88);
 assert(nss_control_base_lease(ctx,6)&&nss_control_base_lease(ctx,6)!=old);
}
static void routing_and_waits(void) {
 fresh();struct nss_ctx_instance *ctx=&nss_top_main.nss[0];
 struct nss_if_msg msg=request(0,6),original=msg;uint32_t cookie;
 wait_hook=acknowledge;assert(!nss_if_msg_sync(ctx,&msg)&&!memcmp(&msg,&original,sizeof(msg))&&!observed[0].calls);
 wait_hook=reject;assert(nss_if_msg_sync(ctx,&msg)==NSS_TX_FAILURE);
 assert(nss_if_msg_sync(ctx,&msg)==NSS_TX_FAILURE&&!live_allocations);saved=wire;
 wait_hook=late_reply;assert(nss_if_msg_sync(ctx,&msg)==NSS_TX_FAILURE&&!live_allocations);
 force_wait_timeout=true;wait_hook=acknowledge;assert(!nss_if_msg_sync(ctx,&msg));force_wait_timeout=false;
 send_failure=true;assert(nss_if_msg_sync(ctx,&msg)==NSS_TX_FAILURE);send_failure=false;
 fail_allocation=allocations+1;assert(nss_if_msg_sync(ctx,&msg)==NSS_TX_FAILURE&&!live_allocations);fail_allocation=0;
 /* Raw public APIs are broker-owned too, including receive-buffer capacity. */
 assert(!nss_if_tx_msg_with_size(ctx,&msg,4096)&&wire_capacity==4096);
 saved=wire;observed[0].length=sizeof(struct nss_cmn_msg)+4+16;
 deliver(wire,NSS_CMN_RESPONSE_ACK,4,16,true);assert(observed[0].calls==1&&!family_calls);
 observed[0].length=0;late_reply();assert(observed[0].calls==1&&!family_calls);
 assert(!nss_if_tx_msg(ctx,&msg));saved=wire;owner_change();late_reply();assert(observed[0].calls==1&&!family_calls);
 fresh();msg=request(0,6);ctx->nss_rx_interface_handlers[6].cb=NULL;
 assert(!nss_if_tx_msg_tracked(ctx,&msg,&cookie));acknowledge();assert(observed[0].calls==1);
 for(unsigned core=0;core<2;core++)for(unsigned physical=0;physical<2;physical++){
  unsigned number=physical?1:6;msg=request(core,number);
  assert(!nss_if_tx_msg_tracked(&nss_top_main.nss[core],&msg,&cookie));acknowledge();
 }
 assert(observed[0].calls==3&&observed[1].calls==2);
 fresh();msg=request(0,6);assert(!nss_if_tx_msg_tracked(ctx,&msg,&cookie));saved=wire;
 struct wire_copy wrong=wire;((struct nss_cmn_msg *)(void *)wrong.payload.data)->type=10001;
 deliver(wrong,NSS_CMN_RESPONSE_ACK,0,0,false);
 wrong=wire;wrong.ctx=&nss_top_main.nss[1];deliver(wrong,NSS_CMN_RESPONSE_ACK,0,0,false);
 assert(!family_calls&&!observed[0].calls&&!observed[1].calls);
 acknowledge();assert(observed[0].calls==1);
 assert(nss_control_open(ctx,NSS_CONTROL_WIFI_EXT_VDEV,6));
 assert(!nss_control_send(ctx,&msg,sizeof(msg),2048,NSS_CONTROL_WIFI_EXT_VDEV,&cookie));
 acknowledge();assert(family_calls==1&&observed[0].calls==2);
 /* A non-broker physical/family reply keeps its existing callback route. */
 saved=wire;struct nss_cmn_msg *legacy=(void *)saved.payload.data;
 legacy->cb=(uintptr_t)response;legacy->app_data=(uintptr_t)&observed[0];
 late_reply();assert(family_calls==2&&legacy_calls==1&&observed[0].calls==3);
}
static void geometry(void) {
 fresh();struct nss_ctx_instance *ctx=&nss_top_main.nss[0];uint32_t cookie;
 struct nss_if_msg msg=request(0,6);
 assert(!nss_if_tx_msg_tracked(ctx,&msg,&cookie));struct wire_copy original=wire;
 struct nss_if_msg packet=msg;packet.cm=(struct nss_cmn_msg){.version=1,.interface=6,.type=0,.len=4,.response=NSS_CMN_RESPONSE_ACK};
 struct sk_buff skb={.data=&packet,.len=sizeof(packet.cm)-1};
 nss_core_handle_nss_status_pkt(ctx,&skb);
 skb.len=sizeof(packet.cm);packet.cm.len=1;nss_core_handle_nss_status_pkt(ctx,&skb);
 packet.cm.len=0;packet.cm.version=2;nss_core_handle_nss_status_pkt(ctx,&skb);
 packet.cm.version=1;packet.cm.interface=NSS_MAX_NET_INTERFACES;nss_core_handle_nss_status_pkt(ctx,&skb);
 assert(!observed[0].calls&&!family_calls&&!preempt_depth&&live_allocations==1);
 struct wire_copy wrong=original;struct nss_cmn_msg *cm=(void *)wrong.payload.data;
 cm->app_data=UINT64_MAX;deliver(wrong,NSS_CMN_RESPONSE_ACK,0,0,false);
 wrong=original;cm=(void *)wrong.payload.data;cm->interface=1;deliver(wrong,NSS_CMN_RESPONSE_ACK,0,0,false);
 wrong=original;cm=(void *)wrong.payload.data;cm->app_data=0;deliver(wrong,NSS_CMN_RESPONSE_ACK,0,0,false);
 assert(!observed[0].calls&&!family_calls&&live_allocations==1);
 deliver(original,NSS_CMN_RESPONSE_NOTIFY,0,0,false);
 assert(notify_callbacks==1&&!observed[0].calls&&live_allocations==1);
 deliver(original,NSS_CMN_RESPONSE_ACK,0,0,false);
 assert(observed[0].calls==1&&!live_allocations);
}
static void *receiver(void *arg) { (void)arg;late_reply();return NULL; }
static void *unregisterer(void *arg) {
 struct nss_ctx_instance *ctx=arg;atomic_store(&closing,true);
 nss_core_unregister_subsys_dp(ctx,6);atomic_store(&closed,true);return NULL;
}
static void *sender(void *arg) {
 struct nss_if_msg *msg=arg;assert(!nss_if_tx_msg(&nss_top_main.nss[0],msg));return NULL;
}
static void drains(void) {
 fresh();struct nss_ctx_instance *ctx=&nss_top_main.nss[0];uint32_t cookie;
 struct observer *heap=calloc(1,sizeof(*heap));assert(heap);heap->ctx=ctx;
 struct nss_if_msg msg=request(0,6);msg.cm.app_data=(uintptr_t)heap;
 assert(!nss_if_tx_msg_tracked(ctx,&msg,&cookie));saved=wire;callback_block=true;
 pthread_t rx,close;pthread_create(&rx,NULL,receiver,NULL);
 pthread_mutex_lock(&callback_lock);while(!callback_entered)pthread_cond_wait(&callback_cond,&callback_lock);pthread_mutex_unlock(&callback_lock);
 pthread_create(&close,NULL,unregisterer,ctx);
 while(!atomic_load(&sync_entered))sched_yield();
 assert(!atomic_load(&closed));
 pthread_mutex_lock(&callback_lock);callback_release=true;pthread_cond_broadcast(&callback_cond);pthread_mutex_unlock(&callback_lock);
 pthread_join(rx,NULL);pthread_join(close,NULL);
 assert(heap->calls==1&&atomic_load(&closed)&&!live_allocations);free(heap);late_reply();
 fresh();msg=request(0,6);send_block=true;pthread_t tx;
 pthread_create(&tx,NULL,sender,&msg);
 pthread_mutex_lock(&send_lock);while(!send_entered)pthread_cond_wait(&send_cond,&send_lock);pthread_mutex_unlock(&send_lock);
 pthread_create(&close,NULL,unregisterer,ctx);while(!atomic_load(&closing))sched_yield();assert(!atomic_load(&closed));
 pthread_mutex_lock(&send_lock);send_release=true;pthread_cond_broadcast(&send_cond);pthread_mutex_unlock(&send_lock);
 pthread_join(tx,NULL);pthread_join(close,NULL);saved=wire;late_reply();assert(!live_allocations&&!observed[0].calls);
}
int main(void) {
 leases();routing_and_waits();geometry();drains();
 fresh();struct nss_ctx_instance *ctx=&nss_top_main.nss[0];
 nss_control_base_generation[0][6]=U64_MAX-1;nss_core_unregister_subsys_dp(ctx,6);
 nss_core_register_subsys_dp(ctx,6,NULL,NULL,&observed[0],&devices[0],0);
 assert(!nss_control_base_lease(ctx,6));
 atomic_store(&nss_control_sequence.value,U32_MAX);
 struct nss_if_msg msg=request(0,1);uint32_t cookie;
 assert(nss_if_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE&&!cookie&&!live_allocations);
 puts("PASS actual BASE control: DP generations/reuse, send-entry ABA, same-owner updates, private waits, raw APIs, core routing/RX context, callback/enqueue drains, exhaustion");
}
'''


def run(driver, ablate=False):
    control = (driver / "nss_control.c").read_text()
    core = (driver / "nss_core.c").read_text()
    base = (driver / "nss_if.c").read_text()
    shim = extract.SHIM.replace(
        "uint32_t interface,type,len,response,error;",
        "uint32_t version,interface,type,len,response,error;")
    shim = shim.replace("NSS_MAX_NET_INTERFACES]; };\nstatic struct { unsigned wifi_handler_id;",
                        "NSS_MAX_NET_INTERFACES];struct { void *cb,*app_data; } nss_rx_interface_handlers[NSS_MAX_NET_INTERFACES]; };\nstatic struct { unsigned wifi_handler_id;")
    shim = shim.replace("static nss_tx_status_t nss_core_send_cmd(",
                        "static unsigned wire_capacity;\nstatic nss_tx_status_t nss_core_send_cmd(")
    shim = shim.replace("payload==NSS_NBUF_PAYLOAD_SIZE", "payload>=size")
    shim = shim.replace("wire.ctx=ctx;wire.size=size;", "wire_capacity=payload;wire.ctx=ctx;wire.size=size;")
    prefix = SUPPORT.replace("preempt_depth,wire_capacity", "preempt_depth")
    control = re.sub(r"(?m)^#include[^\n]*", "", control)
    if ablate:
        old = """\tif (family == NSS_CONTROL_BASE_IF &&
\t    (!generation || generation == U64_MAX ||
\t     generation != nss_control_base_generation[ctx->id][cm->interface]))
\t\tgoto unlock;"""
        assert old in control
        control = control.replace(old, "")
    definitions = extract.structures.structure(core, "nss_core_rx_msg_context")
    definitions += "\nstatic DEFINE_PER_CPU(struct nss_core_rx_msg_context, nss_core_rx_msg_context);\n"
    functions = "".join(extract.function(core, name) for name in (
        "nss_core_register_subsys_dp", "nss_core_unregister_subsys_dp",
        "nss_core_rx_msg_buf_len", "nss_core_handle_nss_status_pkt"))
    functions += extract.structures.structure(base, "nss_if_wait")
    functions += "".join(extract.function(base, name) for name in (
        "nss_if_rx_msg_buf_len", "nss_if_callback", "nss_if_tx_msg_with_size_tracked", "nss_if_tx_msg_tracked",
        "nss_if_cancel_msg", "nss_if_msg_sync", "nss_if_tx_msg_with_size", "nss_if_tx_msg"))
    program = shim + prefix + (driver / "nss_control.h").read_text() + control
    program += definitions + functions + TEST
    with tempfile.TemporaryDirectory(prefix="nss-base-owner-") as directory:
        cfile = Path(directory) / "base.c"
        binary = cfile.with_suffix("")
        cfile.write_text(program)
        subprocess.run(["cc", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                        "-Werror=implicit-function-declaration", "-Wno-unused-function",
                        "-Wno-unused-variable", "-Wno-type-limits",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie", "-pthread", str(cfile), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30,
                       env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--ablate-generation", action="store_true")
    args = parser.parse_args()
    run(args.driver, args.ablate_generation)
