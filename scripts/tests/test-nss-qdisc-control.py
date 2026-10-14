#!/usr/bin/env python3
"""Run the real NSS base-interface transaction code with controlled ACKs."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile


def new_side(path):
    return '\n'.join(line[1:] for line in path.read_text().splitlines()
                     if line[:1] in (' ', '+') and not line.startswith('+++'))


SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
typedef uint16_t u16;
typedef uintptr_t nss_ptr_t;
typedef enum { NSS_TX_SUCCESS, NSS_TX_FAILURE, NSS_TX_FAILURE_QUEUE } nss_tx_status_t;
enum { NSS_CMN_RESPONSE_ACK, NSS_CMN_RESPONSE_NACK };
struct nss_ctx_instance { int unused; };
struct nss_cmn_msg { u16 interface,type; unsigned response; nss_ptr_t cb,app_data; };
struct nss_if_msg { struct nss_cmn_msg cm; int payload; };
struct completion { pthread_mutex_t lock; pthread_cond_t cond; bool done; };
#define DEFINE_MUTEX(n) pthread_mutex_t n = PTHREAD_MUTEX_INITIALIZER
#define DEFINE_SPINLOCK(n) pthread_mutex_t n = PTHREAD_MUTEX_INITIALIZER
#define DECLARE_COMPLETION(n) struct completion n = { PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER, false }
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define spin_lock_bh pthread_mutex_lock
#define spin_unlock_bh pthread_mutex_unlock
#define NSS_IF_TX_TIMEOUT 3000
#define msecs_to_jiffies(x) (x)
#define nss_warning(...) do {} while (0)
static void reinit_completion(struct completion *c) {
 pthread_mutex_lock(&c->lock);c->done=false;pthread_mutex_unlock(&c->lock);
}
static void complete(struct completion *c) {
 pthread_mutex_lock(&c->lock);c->done=true;pthread_cond_signal(&c->cond);pthread_mutex_unlock(&c->lock);
}
static unsigned long wait_for_completion_timeout(struct completion *c, unsigned ignored) {
 struct timespec until;clock_gettime(CLOCK_REALTIME,&until);until.tv_nsec+=20000000;
 if(until.tv_nsec>=1000000000){until.tv_sec++;until.tv_nsec-=1000000000;}
 pthread_mutex_lock(&c->lock);
 while(!c->done && !pthread_cond_timedwait(&c->cond,&c->lock,&until)) {}
 bool done=c->done;pthread_mutex_unlock(&c->lock);return done;
}
static nss_tx_status_t nss_if_tx_msg(struct nss_ctx_instance *, struct nss_if_msg *);
'''

TEST = r'''
enum { ACK_NOW, NACK_NOW, SEND_FAIL, NO_ACK, LATE_AND_ACK, BAD_ID_AND_ACK };
static unsigned mode, sends;
static struct nss_if_msg old_request, last_request;
static void reply(struct nss_if_msg request, unsigned response) {
 request.cm.response=response;
 ((void (*)(void *,struct nss_if_msg *))request.cm.cb)((void *)request.cm.app_data,&request);
}
static nss_tx_status_t nss_if_tx_msg(struct nss_ctx_instance *ctx, struct nss_if_msg *req) {
 sends++;last_request=*req;
 assert(req->cm.cb==(nss_ptr_t)nss_if_callback && req->cm.app_data);
 if(mode==SEND_FAIL)return NSS_TX_FAILURE_QUEUE;
 if(mode==NO_ACK){old_request=*req;return NSS_TX_SUCCESS;}
 if(mode==LATE_AND_ACK){
  reply(old_request,NSS_CMN_RESPONSE_ACK);
  assert(nss_if.pending && nss_if.response==NSS_TX_FAILURE);
 }
 if(mode==BAD_ID_AND_ACK){
  struct nss_if_msg bad=*req;bad.cm.interface++;reply(bad,NSS_CMN_RESPONSE_ACK);
  assert(nss_if.pending);bad=*req;bad.cm.type++;reply(bad,NSS_CMN_RESPONSE_ACK);
  assert(nss_if.pending);
 }
 reply(*req,mode==NACK_NOW?NSS_CMN_RESPONSE_NACK:NSS_CMN_RESPONSE_ACK);
 return NSS_TX_SUCCESS;
}
static void forbidden_client_callback(void *data,struct nss_if_msg *msg) { assert(false); }
static void run(unsigned behavior,nss_tx_status_t expected) {
 struct nss_ctx_instance ctx={0};
 struct nss_if_msg request={.cm={.interface=34,.type=7,.cb=(nss_ptr_t)forbidden_client_callback,.app_data=99},.payload=123};
 struct nss_if_msg original=request;
 mode=behavior;assert(nss_if_msg_sync(&ctx,&request)==expected);
 assert(!memcmp(&request,&original,sizeof(request)));
 assert(!nss_if.pending && !nss_if.cookie);
}
int main(void) {
 run(ACK_NOW,NSS_TX_SUCCESS);
 run(NACK_NOW,NSS_TX_FAILURE);
 run(SEND_FAIL,NSS_TX_FAILURE_QUEUE);
 run(NO_ACK,NSS_TX_FAILURE);
 nss_ptr_t expired=old_request.cm.app_data;
 run(LATE_AND_ACK,NSS_TX_SUCCESS);assert(last_request.cm.app_data!=expired);
 reply(old_request,NSS_CMN_RESPONSE_ACK);assert(!nss_if.pending && !nss_if.cookie);
 run(BAD_ID_AND_ACK,NSS_TX_SUCCESS);
 nss_if.sequence=UINTPTR_MAX;run(ACK_NOW,NSS_TX_SUCCESS);assert(last_request.cm.app_data==1);
 assert(sends==7);
 puts("PASS actual NSS IF control: ACK/NACK/send failure/timeout/late ACK/interface+type identity/cookie wrap/client callback isolation");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--driver', type=Path, help='Actual patched qca-nss-drv directory')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if args.driver:
        source = (args.driver / 'nss_if.c').read_text()
    else:
        source = new_side(repo / 'package/kernel/qca-nss-drv/patches/0216-base-interface-correlate-synchronous-ACKs.patch')
    spec = importlib.util.spec_from_file_location('nss_control_extract', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    globals_ = '\n'.join(re.findall(r'^static (?:DEFINE_MUTEX|DEFINE_SPINLOCK|DECLARE_COMPLETION)\([^\n]+', source, re.M))
    globals_ += '\n' + re.search(r'static struct \{.*?\} nss_if;', source, re.S).group()
    functions = helper.function(source, 'nss_if_callback') + helper.function(source, 'nss_if_msg_sync')
    with tempfile.TemporaryDirectory(prefix='nss-qdisc-control-') as directory:
        path = Path(directory)
        (path / 'control.c').write_text(SHIM + globals_ + functions + TEST)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-pthread', '-g', '-O1',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-Werror=implicit-function-declaration', str(path / 'control.c'),
                        '-o', str(path / 'control')], check=True)
        subprocess.run([str(path / 'control')], check=True)


if __name__ == '__main__':
    main()
