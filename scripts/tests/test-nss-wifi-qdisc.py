#!/usr/bin/env python3
"""Exercise the real VAP dispatcher with base shaper/IGS and private controls."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t nss_ptr_t;
enum { NSS_CMN_RESPONSE_ACK,NSS_CMN_RESPONSE_NACK,NSS_CMN_RESPONSE_NOTIFY };
#define NSS_DYNAMIC_IF_START 4
#define NSS_MAX_DYNAMIC_INTERFACES 8
#define NSS_IF_MAX_MSG_TYPES 9999
#define NSS_WIFI_VDEV_MAX_MSG 10030
#define NSS_CONTROL_WIFI_VDEV 1
#define BUG_ON(x) assert(!(x))
#define nss_info(...) do {} while(0)
#define nss_warning(...) do {} while(0)
struct nss_cmn_msg { unsigned interface,type,len,response; nss_ptr_t cb,app_data; };
struct nss_ctx_instance { struct { void *ndev; } subsys_dp_register[16]; };
struct nss_wifi_vdev_msg { char data[24]; };
typedef void (*nss_wifi_vdev_msg_callback_t)(void *,struct nss_cmn_msg *);
static unsigned base_calls,base_valid,private_calls,notify_calls;
static unsigned nss_cmn_get_msg_len(struct nss_cmn_msg *m) { return m->len; }
static void nss_core_log_msg_failures(struct nss_ctx_instance *c,struct nss_cmn_msg *m) {}
static void nss_if_msg_handler(struct nss_ctx_instance *c,struct nss_cmn_msg *m,void *data) {
 base_calls++;assert(m->type<NSS_IF_MAX_MSG_TYPES);
 if(m->len<=128)base_valid++;
}
static void nss_control_receive(struct nss_ctx_instance *c,struct nss_cmn_msg *m,unsigned family,void *data) {
 assert(family==NSS_CONTROL_WIFI_VDEV && m->type>NSS_IF_MAX_MSG_TYPES);private_calls++;
}
static void notify(void *data,struct nss_cmn_msg *m) { assert(data && m->response==NSS_CMN_RESPONSE_NOTIFY);notify_calls++; }
static nss_wifi_vdev_msg_callback_t nss_core_get_msg_handler(struct nss_ctx_instance *c,unsigned i) { return notify; }
'''
TEST = r'''
int main(void) {
 struct nss_ctx_instance ctx={0};ctx.subsys_dp_register[6].ndev=&ctx;
 struct nss_cmn_msg msg={.interface=6,.type=7,.len=64,.response=NSS_CMN_RESPONSE_ACK,.cb=11,.app_data=22};
 nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(base_calls==1 && base_valid==1 && !private_calls);
 assert(msg.cb==11 && msg.app_data==22);
 msg.response=NSS_CMN_RESPONSE_NACK;nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(base_calls==2);
 msg.len=129;nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(base_calls==3 && base_valid==2);
 ctx.subsys_dp_register[6].ndev=NULL;nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(base_calls==3);
 ctx.subsys_dp_register[6].ndev=&ctx;msg.type=10000;msg.len=16;msg.response=NSS_CMN_RESPONSE_ACK;
 nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(private_calls==1 && base_calls==3);
 msg.response=NSS_CMN_RESPONSE_NACK;nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(private_calls==2);
 msg.response=NSS_CMN_RESPONSE_NOTIFY;nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(notify_calls==1);
 msg.len=25;nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(notify_calls==1);
 msg.len=16;msg.type=NSS_WIFI_VDEV_MAX_MSG;nss_wifi_vdev_handler(&ctx,&msg,NULL);assert(notify_calls==1 && private_calls==2);
 puts("PASS actual Wi-Fi VDEV dispatcher: base ACK/NACK and layout, registration gate, private controls and NOTIFY isolation");
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--driver', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    body = helper.function((args.driver / 'nss_wifi_vdev.c').read_text(), 'nss_wifi_vdev_handler')
    with tempfile.TemporaryDirectory(prefix='nss-wifi-qdisc-') as directory:
        path = Path(directory)
        (path / 'test.c').write_text(SHIM + body + TEST)
        subprocess.run([os.environ.get('CC','cc'), '-std=gnu11', '-g', '-O1', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-Werror=implicit-function-declaration', str(path/'test.c'), '-o', str(path/'test')], check=True)
        subprocess.run([str(path/'test')], check=True)

if __name__ == '__main__':
    main()
