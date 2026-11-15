#!/usr/bin/env python3
"""Exercise real ext-vdev broker routing, header-only replies and private waits."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile
import importlib.util

spec = importlib.util.spec_from_file_location(
    "nss_control_test", Path(__file__).with_name("test-nss-control.py"))
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)

SUPPORT = r'''
#define NSS_CMN_RESPONSE_LAST 3
#define NSS_WIFI_EXT_VDEV_TX_TIMEOUT 3000
#define NSS_CORE_STATUS_FAILURE 1
#define __maybe_unused __attribute__((unused))
#define DEFINE_MUTEX(n) pthread_mutex_t n=PTHREAD_MUTEX_INITIALIZER
#define mutex_lock(p) assert(!pthread_mutex_lock(p))
#define mutex_unlock(p) assert(!pthread_mutex_unlock(p))
#define ETH_ALEN 6
#define NSS_IF_ERROR_TYPE_MAX 9999
#define NSS_MAX_NUM_PRI 4
#define NSS_PHYSICAL_IF_START 0
#define NSS_VIRTUAL_IF_START 4
struct net_device { unsigned ifindex; };
struct nss_cmn_node_stats { uint32_t rx_packets,rx_bytes,tx_packets,tx_bytes,rx_dropped[4]; };
struct nss_shaper_configure { uint32_t request_type,response_type; };
struct nss_if_msg;
typedef void (*nss_if_msg_callback_t)(void *,struct nss_if_msg *);
static bool nss_is_dynamic_interface(unsigned n) { return n>=4&&n<12; }
typedef void (*nss_wifi_ext_vdev_msg_callback_t)(void *,struct nss_cmn_msg *);
typedef void (*nss_wifi_ext_vdev_data_callback_t)(void);
typedef void (*nss_wifi_ext_vdev_ext_data_callback_t)(void);
struct nss_ctx_instance *nss_wifi_ext_vdev_get_ctx(void);
static unsigned base_messages,stats_messages,log_messages,registered_stats;
static unsigned registration_failure,registration_step;
static unsigned dynamic_type[NSS_MAX_NET_INTERFACES];
static struct { void *cb,*event,*data; } registered[NSS_MAX_NET_INTERFACES];
static unsigned nss_dynamic_interface_get_type(struct nss_ctx_instance *ctx,unsigned number) {
 assert(ctx==&nss_top_main.nss[0]&&number<NSS_MAX_NET_INTERFACES);return dynamic_type[number];
}
static int nss_core_register_msg_handler(struct nss_ctx_instance *ctx,unsigned number,void *event) {
 (void)ctx;
 if(++registration_step==registration_failure||registered[number].event)return 1;
 registered[number].event=event;return 0;
}
static int nss_core_unregister_msg_handler(struct nss_ctx_instance *ctx,unsigned number) {
 (void)ctx;registered[number].event=NULL;return 0;
}
static int nss_core_register_handler(struct nss_ctx_instance *ctx,unsigned number,
 void (*cb)(struct nss_ctx_instance *,struct nss_cmn_msg *,void *),void *data) {
 (void)ctx;
 if(++registration_step==registration_failure||registered[number].cb)return 1;
 registered[number].cb=cb;registered[number].data=data;return 0;
}
static int nss_core_unregister_handler(struct nss_ctx_instance *ctx,unsigned number) {
 (void)ctx;registered[number].cb=NULL;registered[number].data=NULL;return 0;
}
static void nss_core_register_subsys_dp(struct nss_ctx_instance *ctx,unsigned number,
 void *cb,void *ext,void *data,struct net_device *dev,unsigned features);
static void nss_core_unregister_subsys_dp(struct nss_ctx_instance *ctx,unsigned number);
typedef void *nss_phys_if_rx_callback_t;
typedef void *nss_phys_if_rx_ext_data_callback_t;
static void *nss_cmn_get_interface_dev(struct nss_ctx_instance *ctx,unsigned number) {
 return ctx->subsys_dp_register[number].ndev;
}
static void nss_wifi_ext_vdev_stats_register(unsigned number,struct net_device *dev) {
 assert(number==6&&dev);registered_stats++;
}
static void nss_wifi_ext_vdev_stats_unregister(unsigned number,struct net_device *dev) {
 assert(number==6&&dev&&registered_stats);registered_stats--;
}
struct semaphore { unsigned unused; };
static inline void down(struct semaphore *p) { (void)p; }
static inline void up(struct semaphore *p) { (void)p; }
'''

AFTER_HEADER = r'''
static void nss_wifi_ext_vdev_stats_sync(struct nss_ctx_instance *ctx,
 struct nss_wifi_ext_vdev_stats *stats,unsigned number) {
 assert(ctx&&number==6);volatile uint32_t last=stats->nxt_hop_drp;(void)last;stats_messages++;
}
static const char *nss_cmn_response_str[]={"ACK","EMSG","NOTIFY"};
__attribute__((noinline,noipa)) static void log_record(const char *format,...) {
 assert(format);log_messages++;
}
#undef nss_info
#undef nss_trace
#define nss_info(...) log_record(__VA_ARGS__)
#define nss_trace(...) log_record(__VA_ARGS__)
static void nss_if_msg_handler(struct nss_ctx_instance *ctx,struct nss_cmn_msg *cm,void *data);
'''

CASES = r'''
static unsigned callbacks;
static int owner;
static struct net_device netdev;
static struct wire_copy old_reply;
static void callback(void *data,struct nss_cmn_msg *cm) {
 assert(data==&owner&&cm->app_data==(uintptr_t)&owner);callbacks++;
}
static struct nss_wifi_ext_vdev_msg request(unsigned type) {
 struct nss_wifi_ext_vdev_msg msg={.cm={.interface=6,.type=type,.cb=(uintptr_t)callback,.app_data=(uintptr_t)&owner}};
 msg.cm.len=type==NSS_WIFI_EXT_VDEV_MSG_CONFIGURE_WDS?sizeof(msg.msg.wmsg):sizeof(msg.msg.cmsg);
 if(type<NSS_IF_MAX_MSG_TYPES)msg.cm.len=4;
 return msg;
}
static void deliver(struct wire_copy copy,unsigned response,bool header_only) {
 struct nss_cmn_msg *cm=(void *)copy.payload.data;cm->response=response;
 if(header_only)cm->len=0;
 /* Allocate only actual received bytes; logger/union overreads are ASan-visible. */
 struct nss_cmn_msg *received=malloc(sizeof(*cm)+cm->len);assert(received);
 memcpy(received,cm,sizeof(*cm)+cm->len);
 nss_wifi_ext_vdev_handler(copy.ctx,received,NULL);free(received);
}
static void acknowledge(void) { deliver(wire,NSS_CMN_RESPONSE_ACK,true); }
static void acknowledge_error_ignored(void) {
 struct wire_copy copy=wire;((struct nss_cmn_msg *)(void *)copy.payload.data)->error=10000;
 deliver(copy,NSS_CMN_RESPONSE_ACK,true);
}
static void reject(void) { deliver(wire,NSS_CMN_RESPONSE_EMSG,true); }
static void late_reply(void) { deliver(old_reply,NSS_CMN_RESPONSE_ACK,true); }
static void nss_if_msg_handler(struct nss_ctx_instance *ctx,struct nss_cmn_msg *cm,void *data) {
 base_messages++;nss_if_msg_handler_actual(ctx,cm,data);
}
static void fresh(void) {
 struct nss_ctx_instance *ctx=&nss_top_main.nss[0];
 nss_control_close_core(ctx);nss_control_init_core(ctx);
 memset(registered,0,sizeof(registered));memset(dynamic_type,0,sizeof(dynamic_type));
 memset(ctx->subsys_dp_register,0,sizeof(ctx->subsys_dp_register));
 dynamic_type[6]=NSS_DYNAMIC_INTERFACE_TYPE_WIFI_EXT_VDEV_WDS;
 callbacks=base_messages=stats_messages=log_messages=registered_stats=registration_step=registration_failure=notify_callbacks=0;
 force_wait_timeout=send_failure=false;wait_hook=NULL;
 assert(!live_allocations);
 assert(nss_wifi_ext_vdev_register_if(6,NULL,NULL,event_callback,&netdev,0,&owner)==ctx);
}
int main(void) {
 struct nss_ctx_instance *ctx=&nss_top_main.nss[0];uint32_t cookie;
 fresh();struct nss_wifi_ext_vdev_msg msg=request(NSS_WIFI_EXT_VDEV_MSG_CONFIGURE_IF);
 assert(nss_wifi_ext_vdev_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_SUCCESS);
 unsigned logs=log_messages;
 acknowledge();assert(callbacks==1&&log_messages==logs&&!base_messages&&!live_allocations);
 acknowledge();assert(callbacks==1);
 /* Base-numbered EXT OPEN/CLOSE must beat independent BASE_IF routing. */
 for(unsigned type=0;type<2;type++){
  msg=request(type);assert(!nss_wifi_ext_vdev_tx_msg_tracked(ctx,&msg,&cookie));acknowledge();
  assert(callbacks==type+2&&!base_messages);
 }
 msg=request(0);uint64_t lease=nss_control_base_lease(ctx,6);assert(lease);
 assert(!nss_control_base_send(ctx,&msg,sizeof(msg),NSS_NBUF_PAYLOAD_SIZE,lease,&cookie));
 acknowledge();assert(callbacks==4&&base_messages==1);
 msg=request(0);assert(!nss_wifi_ext_vdev_tx_msg_tracked(ctx,&msg,&cookie));old_reply=wire;
 nss_wifi_ext_vdev_cancel_msg(cookie);late_reply();assert(callbacks==4&&base_messages==2);
 msg=request(NSS_WIFI_EXT_VDEV_MSG_CONFIGURE_WDS);
 assert(!nss_wifi_ext_vdev_tx_msg_tracked(ctx,&msg,&cookie));old_reply=wire;
 nss_wifi_ext_vdev_cancel_msg(cookie);late_reply();assert(callbacks==4);
 assert(nss_wifi_ext_vdev_unregister_if(6)&&!registered_stats);
 assert(nss_wifi_ext_vdev_register_if(6,NULL,NULL,event_callback,&netdev,0,&owner)==ctx);
 assert(!nss_wifi_ext_vdev_tx_msg_tracked(ctx,&msg,&cookie));struct wire_copy current=wire;
 late_reply();assert(callbacks==4);deliver(current,NSS_CMN_RESPONSE_ACK,true);assert(callbacks==5);
 /* Independent private waiters reject late, duplicate and NACK replies. */
 fresh();msg=request(NSS_WIFI_EXT_VDEV_MSG_CONFIGURE_IF);wait_hook=acknowledge;
 assert(!nss_wifi_ext_vdev_tx_msg_sync(ctx,&msg)&&callbacks==1);
 assert(msg.cm.cb==(uintptr_t)callback&&msg.cm.app_data==(uintptr_t)&owner);
 wait_hook=reject;assert(nss_wifi_ext_vdev_tx_msg_sync(ctx,&msg)==NSS_TX_FAILURE&&callbacks==2);
 assert(nss_wifi_ext_vdev_tx_msg_sync(ctx,&msg)==NSS_TX_FAILURE);old_reply=wire;
 wait_hook=late_reply;assert(nss_wifi_ext_vdev_tx_msg_sync(ctx,&msg)==NSS_TX_FAILURE&&callbacks==2);
 force_wait_timeout=true;wait_hook=acknowledge;
 assert(!nss_wifi_ext_vdev_tx_msg_sync(ctx,&msg)&&callbacks==3);force_wait_timeout=false;
 wait_hook=acknowledge_error_ignored;
 assert(!nss_wifi_ext_vdev_tx_msg_sync(ctx,&msg)&&callbacks==4);
 send_failure=true;assert(nss_wifi_ext_vdev_tx_msg_sync(ctx,&msg)==NSS_TX_FAILURE&&!live_allocations);send_failure=false;
 /* A stats ACK has no stats body. A truncated NOTIFY must not reach any body consumer. */
 fresh();struct wire_copy stats={.ctx=ctx};struct nss_cmn_msg *cm=(void *)stats.payload.data;
 cm->interface=6;cm->type=NSS_WIFI_EXT_VDEV_MSG_STATS_SYNC;cm->cb=(uintptr_t)callback;cm->app_data=(uintptr_t)&owner;
 for(unsigned length=0;length<sizeof(struct nss_wifi_ext_vdev_stats);length++){
  cm->len=length;deliver(stats,NSS_CMN_RESPONSE_NOTIFY,false);
 }
 deliver(stats,NSS_CMN_RESPONSE_ACK,true);
 assert(!stats_messages&&!notify_callbacks&&!callbacks&&!log_messages);
 cm->len=sizeof(struct nss_wifi_ext_vdev_stats);deliver(stats,NSS_CMN_RESPONSE_NOTIFY,false);
 assert(stats_messages==1&&notify_callbacks==1&&!callbacks);
 cm->type=NSS_IF_CLOSE;cm->app_data=0xbad;
 deliver(stats,NSS_CMN_RESPONSE_NOTIFY,true);
 assert(notify_callbacks==2&&!callbacks);
 cm->type=NSS_WIFI_EXT_VDEV_MSG_STATS_SYNC;cm->len=sizeof(struct nss_wifi_ext_vdev_stats);
 /* Registration rollback must not remove an existing owner or publish a half registration. */
 assert(!nss_wifi_ext_vdev_register_if(6,NULL,NULL,event_callback,&netdev,0,&owner));
 assert(registered_stats==1&&ctx->subsys_dp_register[6].ndev==&netdev);
 assert(nss_wifi_ext_vdev_unregister_if(6));
 assert(nss_wifi_ext_vdev_register_if(6,NULL,NULL,NULL,&netdev,0,&owner)==ctx);
 unsigned notified=notify_callbacks;
 deliver(stats,NSS_CMN_RESPONSE_NOTIFY,false);
 assert(stats_messages==2&&notify_callbacks==notified);
 assert(nss_wifi_ext_vdev_unregister_if(6));
 for(unsigned step=1;step<=2;step++){
  registration_step=0;registration_failure=step;
  assert(!nss_wifi_ext_vdev_register_if(6,NULL,NULL,event_callback,&netdev,0,&owner));
  assert(!registered_stats&&!registered[6].cb&&!registered[6].event&&!ctx->subsys_dp_register[6].ndev);
 }
 registration_failure=0;nss_control_close_core(ctx);
 assert(!nss_wifi_ext_vdev_register_if(6,NULL,NULL,event_callback,&netdev,0,&owner));
 assert(!registered_stats&&!ctx->subsys_dp_register[6].ndev&&!live_allocations);
 for(unsigned type=0;type<=NSS_IF_PPE_PORT_DESTROY;type++)
  for(unsigned length=0;length<=sizeof(union nss_if_msgs);length++){
   struct nss_if_msg *short_msg=calloc(1,sizeof(struct nss_cmn_msg)+length);assert(short_msg);
   short_msg->cm.type=type;short_msg->cm.len=length;short_msg->cm.response=NSS_CMN_RESPONSE_ACK;
   nss_if_log_rx_msg(short_msg);free(short_msg);
  }
 struct nss_if_msg invalid={.cm.type=NSS_IF_MAX_MSG_TYPES};nss_if_log_rx_msg(&invalid);
 puts("PASS actual ext-vdev: header-only ACK, EXT/base routing, cancel/reuse, private timeout/NACK waits, short stats rejection, registration rollback");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drv", type=Path, required=True)
    parser.add_argument("--reply-geometry-only", action="store_true")
    args = parser.parse_args()
    source = (args.drv / "nss_wifi_ext_vdev.c").read_text()
    header = (args.drv / "exports/nss_wifi_ext_vdev_if.h").read_text()
    shim = control.SHIM
    shim = shim.replace("#define NSS_IF_MAX_MSG_TYPES 2", "")
    shim = shim.replace("NSS_DYNAMIC_INTERFACE_TYPE_MAX };",
                        "NSS_DYNAMIC_INTERFACE_TYPE_WIFI_EXT_VDEV_WDS,NSS_DYNAMIC_INTERFACE_TYPE_WIFI_EXT_VDEV_VLAN,NSS_DYNAMIC_INTERFACE_TYPE_MAX };")
    shim = shim.replace("struct { void *ndev; } subsys_dp_register",
                        "struct { void *ndev,*app_data; } subsys_dp_register")
    shim = shim.replace("return cm->len; }", "return cm->len+sizeof(*cm); }")
    for name in ("nss_core_register_handler", "nss_core_get_msg_handler", "nss_if_msg_handler"):
        old = control.function(shim, name)
        shim = shim.replace(old, "")
    shim += "\nstatic void *nss_core_get_msg_handler(struct nss_ctx_instance *,unsigned);\n"
    base_header = (args.drv / "exports/nss_if.h").read_text()
    definitions = re.search(r"enum nss_if_message_types \{.*?\n\};", base_header, re.S).group()
    for name in ("nss_if_open", "nss_if_close", "nss_if_link_state_notify", "nss_if_mtu_change",
                 "nss_if_pause_on_off", "nss_if_mac_address_set", "nss_if_shaper_assign",
                 "nss_if_shaper_unassign", "nss_if_shaper_configure", "nss_if_vsi_assign",
                 "nss_if_vsi_unassign", "nss_if_set_nexthop", "nss_if_igs_config", "nss_if_ppe_port_create"):
        definitions += control.structures.structure(base_header, name)
    definitions += re.search(r"union nss_if_msgs \{.*?\n\};", base_header, re.S).group()
    definitions += control.structures.structure(base_header, "nss_if_msg")
    definitions += re.search(r"enum nss_wifi_ext_vdev_msg_types \{.*?\n\};", header, re.S).group()
    for name in ("nss_wifi_ext_vdev_wds_msg", "nss_wifi_ext_vdev_stats",
                 "nss_wifi_ext_vdev_configure_if_msg", "nss_wifi_ext_vdev_set_next_hop_msg",
                 "nss_wifi_ext_vdev_vlan_msg", "nss_wifi_ext_vdev_msg"):
        definitions += control.structures.structure(header, name)
    core = re.sub(r"(?m)^#include[^\n]*", "", (args.drv / "nss_control.c").read_text())
    log = re.sub(r"(?m)^#include[^\n]*", "", (args.drv / "nss_wifi_ext_vdev_log.c").read_text())
    bodies = "static DEFINE_MUTEX(nss_wifi_ext_vdev_registration_lock);\n"
    if "struct nss_wifi_ext_vdev_wait {" in source:
        bodies += control.structures.structure(source, "nss_wifi_ext_vdev_wait")
    names = ("nss_wifi_ext_vdev_get_ctx", "nss_wifi_ext_vdev_ignore_notify", "nss_wifi_ext_vdev_verify_if_num",
             "nss_wifi_ext_vdev_payload_valid", "nss_wifi_ext_vdev_handler",
             "nss_wifi_ext_vdev_tx_msg_tracked", "nss_wifi_ext_vdev_tx_msg", "nss_wifi_ext_vdev_cancel_msg",
             "nss_wifi_ext_vdev_callback", "nss_wifi_ext_vdev_tx_msg_sync",
             "nss_wifi_ext_vdev_register_if", "nss_wifi_ext_vdev_unregister_if")
    if args.reply_geometry_only:
        names = tuple(name for name in names if name not in (
            "nss_wifi_ext_vdev_callback", "nss_wifi_ext_vdev_tx_msg_sync"))
    for name in names:
        try:
            bodies += control.function(source, name)
        except ValueError:
            if not args.reply_geometry_only:
                raise
    program = shim + SUPPORT + definitions + (args.drv / "nss_control.h").read_text() + core
    core_source = (args.drv / "nss_core.c").read_text()
    program += "".join(control.function(core_source, name) for name in
                       ("nss_core_register_subsys_dp", "nss_core_unregister_subsys_dp"))
    program += AFTER_HEADER + log
    base_log = re.sub(r"(?m)^#include[^\n]*", "", (args.drv / "nss_if_log.c").read_text())
    program += base_log
    base_handler = control.function((args.drv / "nss_if.c").read_text(), "nss_if_msg_handler")
    program += base_handler.replace("nss_if_msg_handler(", "nss_if_msg_handler_actual(", 1)
    program += "\nstatic void *nss_core_get_msg_handler(struct nss_ctx_instance *ctx,unsigned n) { (void)ctx;return registered[n].event; }\n"
    cases = CASES
    if args.reply_geometry_only:
        cases = CASES[:CASES.index("int main(void)")] + r'''
int main(void) {
 fresh();
 struct nss_wifi_ext_vdev_msg msg=request(NSS_WIFI_EXT_VDEV_MSG_CONFIGURE_IF);
 assert(!nss_wifi_ext_vdev_tx_msg(&nss_top_main.nss[0],&msg));
 unsigned logs=log_messages;acknowledge();
 assert(callbacks==1&&log_messages==logs);
 puts("PASS actual ext-vdev header-only ACK geometry");
}
'''
    program += bodies + cases
    with tempfile.TemporaryDirectory(prefix="nss-ext-control-") as directory:
        cfile = Path(directory) / "ext.c"
        binary = cfile.with_suffix("")
        cfile.write_text(program)
        subprocess.run(["cc", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-function", "-Wno-unused-variable", "-Wno-pointer-sign", "-Wno-type-limits",
                        *(["-Wno-unused-parameter"] if args.reply_geometry_only else []),
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie", "-pthread", str(cfile), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30,
                       env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})


if __name__ == "__main__":
    main()
