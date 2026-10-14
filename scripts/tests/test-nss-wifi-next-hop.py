#!/usr/bin/env python3
"""Test actual driver-owned Wi-Fi next-hop ACK/error/timeout/cancel lifetime."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t nss_ptr_t;
typedef enum { NSS_TX_SUCCESS,NSS_TX_FAILURE,NSS_TX_FAILURE_BAD_PARAM } nss_tx_status_t;
enum { NSS_CMN_RESPONSE_ACK,NSS_CMN_RESPONSE_NACK };
enum { NSS_DYNAMIC_INTERFACE_TYPE_VAP=1,NSS_DYNAMIC_INTERFACE_TYPE_IGS };
#define NSS_DYNAMIC_IF_START 4
#define NSS_MAX_DYNAMIC_INTERFACES 8
#define NSS_MAX_NET_INTERFACES 64
#define NSS_WIFI_VDEV_SET_NEXT_HOP 10001
#define NSS_IF_TX_TIMEOUT 3000
#define GFP_KERNEL 0
#define msecs_to_jiffies(x) (x)
struct completion { bool done; };
struct nss_cmn_msg { unsigned type,interface,len,response,error; nss_ptr_t cb,app_data; };
struct nss_wifi_vdev_msg { struct nss_cmn_msg cm; union { struct { unsigned ifnumber; } next_hop; } msg; };
struct nss_ctx_instance { unsigned type; };
typedef void (*nss_wifi_vdev_msg_callback_t)(void *,struct nss_cmn_msg *);
static unsigned mode,cancels,allocs,frees,submits;
static struct nss_cmn_msg pending;
static void init_completion(struct completion *c) { c->done=false; }
static void complete(struct completion *c) { c->done=true; }
static unsigned wait_for_completion_timeout(struct completion *c,unsigned timeout) { return c->done; }
static void *kzalloc(size_t n,unsigned flags) { allocs++;return calloc(1,n); }
static void kfree(void *p) { if(p){frees++;free(p);} }
static unsigned nss_dynamic_interface_get_type(struct nss_ctx_instance *ctx,int i) { return ctx->type; }
static void nss_wifi_vdev_msg_init(struct nss_wifi_vdev_msg *msg,unsigned iface,unsigned type,unsigned len,nss_wifi_vdev_msg_callback_t *cb,void *data) {
 msg->cm.interface=iface;msg->cm.type=type;msg->cm.len=len;msg->cm.cb=(uintptr_t)cb;msg->cm.app_data=(uintptr_t)data;
}
static nss_tx_status_t nss_wifi_vdev_tx_msg_tracked(struct nss_ctx_instance *,struct nss_wifi_vdev_msg *,uint32_t *);
static void nss_wifi_vdev_cancel_msg(uint32_t);
'''
TEST = r'''
static void respond(struct nss_cmn_msg msg) { ((nss_wifi_vdev_msg_callback_t)msg.cb)((void *)msg.app_data,&msg); }
static nss_tx_status_t nss_wifi_vdev_tx_msg_tracked(struct nss_ctx_instance *ctx,struct nss_wifi_vdev_msg *msg,uint32_t *cookie) {
 submits++;assert(msg->cm.type==NSS_WIFI_VDEV_SET_NEXT_HOP && msg->msg.next_hop.ifnumber==16);
 if(mode==3){*cookie=0;return NSS_TX_FAILURE;}
 *cookie=42;pending=msg->cm;
 if(mode<3){pending.response=mode==1?NSS_CMN_RESPONSE_NACK:NSS_CMN_RESPONSE_ACK;pending.error=mode==2?9:0;respond(pending);}
 return NSS_TX_SUCCESS;
}
static void nss_wifi_vdev_cancel_msg(uint32_t cookie) {
 assert(cookie==42);cancels++;
 if(mode==5){pending.response=NSS_CMN_RESPONSE_ACK;pending.error=0;respond(pending);}
 /* Represents cancellation plus synchronize_net(): callback has finished here. */
 memset(&pending,0,sizeof(pending));
}
int main(void) {
 struct nss_ctx_instance ctx={.type=NSS_DYNAMIC_INTERFACE_TYPE_VAP};
 for(mode=0;mode<6;mode++){
  nss_tx_status_t result=nss_wifi_vdev_set_next_hop_sync(&ctx,6,16);
  assert(result==(mode==0?NSS_TX_SUCCESS:NSS_TX_FAILURE));
 }
 assert(submits==6 && cancels==5 && allocs==frees);
 ctx.type=NSS_DYNAMIC_INTERFACE_TYPE_IGS;
 assert(nss_wifi_vdev_set_next_hop_sync(&ctx,6,16)==NSS_TX_FAILURE_BAD_PARAM);
 ctx.type=NSS_DYNAMIC_INTERFACE_TYPE_VAP;
 assert(nss_wifi_vdev_set_next_hop_sync(&ctx,3,16)==NSS_TX_FAILURE_BAD_PARAM);
 assert(nss_wifi_vdev_set_next_hop_sync(&ctx,6,64)==NSS_TX_FAILURE_BAD_PARAM);
 assert(submits==6 && allocs==frees);
 puts("PASS actual Wi-Fi next-hop sync: ACK/NACK/ACK-error/send failure/timeout/late callback drain/input identity");
}
'''

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--driver',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('extract_nss',Path(__file__).with_name('test-nss-control.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    source=(args.driver/'nss_wifi_vdev.c').read_text()
    declaration=re.search(r'struct nss_wifi_vdev_next_hop_wait \{.*?\};',source,re.S).group()
    body=helper.function(source,'nss_wifi_vdev_next_hop_response')+helper.function(source,'nss_wifi_vdev_set_next_hop_sync')
    with tempfile.TemporaryDirectory(prefix='nss-wifi-next-hop-') as directory:
        path=Path(directory);(path/'test.c').write_text(SHIM+declaration+body+TEST)
        subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer','-Werror=implicit-function-declaration',str(path/'test.c'),'-o',str(path/'test')],check=True)
        subprocess.run([str(path/'test')],check=True)

if __name__=='__main__':
    main()
