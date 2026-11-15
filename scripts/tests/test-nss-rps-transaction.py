#!/usr/bin/env python3
"""Run the real RPS transactions and sysctl handlers with injected responses."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sys/types.h>
typedef uint32_t u32;
typedef uintptr_t nss_ptr_t;
typedef int nss_tx_status_t;
#define compat_const const
#define NSS_DRV_IPV4_ENABLE
#define NSS_DRV_IPV6_ENABLE
#define NSS_MAX_NUM_PRI 4
#define NSS_HOST_CORES 4
#define NSS_RPS_MAX_CORE_HASH_BITMAP 15
#define NSS_RPS_PRI_MAP_PARAM_FIELD_COUNT 2
#define NSS_RPS_UNCERTAIN_ENABLE 1
#define NSS_RPS_UNCERTAIN_HASH 2
#define NSS_RPS_UNCERTAIN_PRI 4
#define NSS_NBUF_PAYLOAD_SIZE 2048
#define NSS_CONN_CFG_TIMEOUT 1000
#define NSS_CONTROL_RPS 1
#define NSS_TX_SUCCESS 0
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_N2H_INTERFACE 1
#define NSS_IPV4_RX_INTERFACE 2
#define NSS_IPV6_RX_INTERFACE 3
#define NSS_TX_METADATA_TYPE_N2H_RPS_CFG 1
#define NSS_TX_METADATA_TYPE_N2H_RPS_PRI_MAP_CFG 2
#define NSS_IPV4_TX_RPS_HASH_BITMAP_CFG_MSG 3
#define NSS_IPV6_TX_RPS_HASH_BITMAP_CFG_MSG 4
#define NSS_SUCCESS 0
#define NSS_N2H_RPS_PRI_DEFAULT -1
#define GFP_KERNEL 0
#define nss_warning(...) ((void)0)
#define nss_info(...) ((void)0)
#define nss_info_always(...) ((void)0)
#define lockdep_assert_held(p) ((void)0)
#define msecs_to_jiffies(v) (v)
#define scnprintf snprintf
static pthread_mutex_t nss_rps_mutex=PTHREAD_MUTEX_INITIALIZER;
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done=false; }
static void complete(struct completion *c) { c->done=true; }
static bool completion_done(struct completion *c) { return c->done; }
static unsigned wait_for_completion_timeout(struct completion *c,unsigned t) { return c->done; }
struct nss_cmn_msg { unsigned interface,type,response,error; nss_ptr_t cb,app_data; };
struct nss_n2h_rps { int enable; };
struct nss_n2h_rps_pri_map { int pri_map[NSS_MAX_NUM_PRI]; };
struct nss_n2h_msg { struct nss_cmn_msg cm;union { struct nss_n2h_rps rps_cfg; struct nss_n2h_rps_pri_map rps_pri_map; } msg; };
struct nss_ipv4_msg { struct nss_cmn_msg cm;struct { struct { int hash_bitmap; } rps_hash_bitmap; } msg; };
struct nss_ipv6_msg { struct nss_cmn_msg cm;struct { struct { int hash_bitmap; } rps_hash_bitmap; } msg; };
struct nss_ctx_instance { int rps_en; };
struct { unsigned num_nss;struct nss_ctx_instance nss[2]; } nss_top_main={.num_nss=1};
struct ctl_table { void *data; };
struct nss_rps_pri_map_parse_data { uint8_t pri;int8_t core; };
struct nss_rps_request { struct completion complete;int result; };
static int nss_rps_config,nss_rps_hash_bitmap=15,nss_rps_pri_map[NSS_MAX_NUM_PRI],nss_rps_uncertain;
static void *kzalloc(size_t n,int f) { return calloc(1,n); }
#define kfree free
static size_t memory_read_from_buffer(void *d,size_t n,loff_t *p,const void *s,size_t l) {
 if(*p>=l)return 0;if(n>l-*p)n=l-*p;memcpy(d,(const char*)s+*p,n);*p+=n;return n;
}
static int proc_dointvec(const struct ctl_table *t,int write,void *buffer,size_t *len,loff_t *pos) {
 if(write)memcpy(t->data,buffer,sizeof(int));else memcpy(buffer,t->data,sizeof(int));return 0;
}
static void msg_init(void *m,unsigned interface,unsigned type) {
 struct nss_cmn_msg *cm=m;cm->interface=interface;cm->type=type;
}
#define nss_n2h_msg_init(m,i,t,l,c,a) msg_init(m,i,t)
#define nss_ipv4_msg_init(m,i,t,l,c,a) msg_init(m,i,t)
#define nss_ipv6_msg_init(m,i,t,l,c,a) msg_init(m,i,t)
static int outcomes[8],outcome_count,outcome_index,submitted[8],values[8],cancels;
static bool gate=true;
static bool nss_control_open(struct nss_ctx_instance *ctx,int family,unsigned interface) { return gate; }
static int nss_control_send(struct nss_ctx_instance *ctx,void *m,u32 size,unsigned cap,int family,u32 *cookie) {
 struct nss_cmn_msg *cm=m;
 assert(size<=cap&&outcome_index<outcome_count);
 int result=outcomes[outcome_index];submitted[outcome_index]=cm->type;
 if(cm->type==1)values[outcome_index]=((struct nss_n2h_msg*)m)->msg.rps_cfg.enable;
 if(cm->type==3)values[outcome_index]=((struct nss_ipv4_msg*)m)->msg.rps_hash_bitmap.hash_bitmap;
 if(cm->type==4)values[outcome_index]=((struct nss_ipv6_msg*)m)->msg.rps_hash_bitmap.hash_bitmap;
 *cookie=++outcome_index;
 if(result==-ENOSPC)return 1;
 if(result!=-ETIMEDOUT) {
  cm->response=result?1:0;
  ((void(*)(void*,struct nss_cmn_msg*))cm->cb)((void*)cm->app_data,cm);
 }
 return 0;
}
static void nss_control_cancel(u32 cookie) { assert(cookie);cancels++; }
static void plan(int a,int b,int c,int count) {
 outcomes[0]=a;outcomes[1]=b;outcomes[2]=c;outcome_count=count;outcome_index=0;
}
'''

TEST = r'''
static int write_value(int (*handler)(const struct ctl_table*,int,void*,size_t*,loff_t*),int *global,int value) {
 struct ctl_table ctl={global};size_t n=sizeof(value);loff_t pos=0;
 return handler(&ctl,1,&value,&n,&pos);
}
int main(void) {
 plan(0,0,0,1);
 assert(!write_value(nss_rps_cfg_handler,&nss_rps_config,1)&&nss_rps_config==1&&nss_top_main.nss[0].rps_en==1);
 assert(write_value(nss_rps_cfg_handler,&nss_rps_config,0)==-EOPNOTSUPP);
 assert(write_value(nss_rps_cfg_handler,&nss_rps_config,2)==-EINVAL&&outcome_index==1);
 plan(0,-EIO,0,3);
 assert(write_value(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,3)==-EIO);
 assert(nss_rps_hash_bitmap==15&&!nss_rps_uncertain&&values[0]==3&&values[1]==3&&values[2]==15);
 plan(0,-ETIMEDOUT,0,3);
 assert(write_value(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,5)==-ETIMEDOUT);
 assert(nss_rps_hash_bitmap==15&&(nss_rps_uncertain&2));
 plan(0,0,0,2);
 assert(!write_value(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,5));
 assert(nss_rps_hash_bitmap==5&&!nss_rps_uncertain);
 plan(0,-EIO,-ETIMEDOUT,3);
 assert(write_value(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,7)==-EIO);
 assert(nss_rps_hash_bitmap==5&&(nss_rps_uncertain&2));
 plan(-ENOSPC,0,0,1);int previous=cancels;
 assert(write_value(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,7)==-EIO&&cancels==previous);
 struct ctl_table ctl={nss_rps_pri_map};size_t n=4;loff_t pos=0;char input[]="2 -1";
 plan(-ETIMEDOUT,0,0,1);
 assert(nss_rps_pri_map_cfg_handler(&ctl,1,input,&n,&pos)==-ETIMEDOUT&&nss_rps_pri_map[2]==0&&(nss_rps_uncertain&4));
 plan(0,0,0,1);n=4;
 assert(!nss_rps_pri_map_cfg_handler(&ctl,1,input,&n,&pos)&&nss_rps_pri_map[2]==-1&&!(nss_rps_uncertain&4));
 gate=false;
 assert(write_value(nss_rps_cfg_handler,&nss_rps_config,1)==-ESHUTDOWN);
 puts("PASS actual RPS: ACK-only shadow commit, NACK rollback, partial/timeout uncertainty, resync, enqueue failure, private completion and parser");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--drv', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source = (args.drv / 'nss_rps.c').read_text()
    names = ('nss_rps_response', 'nss_rps_exchange', 'nss_rps_pri_map_usage',
             'nss_rps_pri_map_print', 'nss_rps_pri_map_parse', 'nss_rps_cfg',
             'nss_rps_ipv4_hash_bitmap_cfg', 'nss_rps_ipv6_hash_bitmap_cfg',
             'nss_rps_pri_map_cfg', 'nss_rps_cfg_handler',
             'nss_rps_hash_bitmap_cfg_handler', 'nss_rps_pri_map_cfg_handler')
    functions = ''.join(helper.function(source, name) for name in names)
    with tempfile.TemporaryDirectory(prefix='nss-rps-transaction-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(SHIM + functions + TEST)
        subprocess.run(['cc', '-std=gnu11', '-g', '-O1', '-pthread',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-fno-pie', '-no-pie', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=15)


if __name__ == '__main__':
    main()
