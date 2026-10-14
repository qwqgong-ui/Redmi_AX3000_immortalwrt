#!/usr/bin/env python3
"""Run real WIFILI request registry, cancellation and DMA quarantine functions."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('nss_functions', Path(__file__).with_name('test-nss-multicast.py'))
functions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(functions)


def structure(source, name):
    start = re.search(r'\bstruct\s+' + re.escape(name) + r'\s*\{', source).start()
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + ';\n'


SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
typedef uint64_t dma_addr_t,nss_ptr_t;
typedef int nss_tx_status_t;
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_EMSG 1
#define NSS_CMN_RESPONSE_NOTIFY 2
#define NSS_MAX_NET_INTERFACES 16
#define NSS_WIFILI_INTERNAL_INTERFACE 3
#define NSS_WIFILI_EXTERNAL_INTERFACE0 4
#define NSS_WIFILI_EXTERNAL_INTERFACE1 5
#define NSS_WIFILI_MAX_MSG 32
#define NSS_NBUF_PAYLOAD_SIZE 2048
#define NSS_WIFILI_TX_TIMEOUT 1000
#define U32_MAX UINT32_MAX
#define BITS_PER_LONG (sizeof(unsigned long)*8)
#define BIT(n) (1UL<<(n))
#define GFP_ATOMIC 0
#define GFP_KERNEL 1
#define DMA_TO_DEVICE 1
#define READ_ONCE(x) (x)
#define WARN_ON_ONCE(x) (x)
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define upper_32_bits(v) ((uint64_t)(v)>>32)
#define nss_warning(...) ((void)0)
#define nss_info(...) ((void)0)
#define nss_assert(x) assert(x)
#define nss_wifili_log_tx_msg(...) ((void)0)
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(h) ((h)->next=(h),(h)->prev=(h))
#define LIST_HEAD(n) struct list_head n={&n,&n}
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_entry(p,t,m) container_of(p,t,m)
#define list_for_each_entry(p,h,m) for(p=list_entry((h)->next,__typeof__(*p),m);&(p)->m!=(h);p=list_entry((p)->m.next,__typeof__(*p),m))
#define list_for_each_entry_safe(p,n,h,m) for(p=list_entry((h)->next,__typeof__(*p),m),n=list_entry((p)->m.next,__typeof__(*p),m);&(p)->m!=(h);p=n,n=list_entry((n)->m.next,__typeof__(*n),m))
static void list_add_tail(struct list_head *n,struct list_head *h) { n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n; }
static void list_del(struct list_head *n) { n->prev->next=n->next;n->next->prev=n->prev; }
static void list_move_tail(struct list_head *n,struct list_head *h) { list_del(n);list_add_tail(n,h); }
static void __set_bit(unsigned bit,unsigned long *p) { *p|=BIT(bit); }
static void __clear_bit(unsigned bit,unsigned long *p) { *p&=~BIT(bit); }
typedef struct { _Atomic uint64_t value; } atomic64_t;
#define ATOMIC64_INIT(x) {.value=x}
static uint64_t atomic64_inc_return(atomic64_t *v) { return atomic_fetch_add(&v->value,1)+1; }
#define DEFINE_SPINLOCK(n) pthread_mutex_t n=PTHREAD_MUTEX_INITIALIZER
#define spin_lock_bh(p) assert(pthread_mutex_lock(p)==0)
#define spin_unlock_bh(p) assert(pthread_mutex_unlock(p)==0)
static pthread_mutex_t reader_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t reader_cond=PTHREAD_COND_INITIALIZER;
static unsigned readers;
static _Atomic bool sync_entered;
static void rcu_read_lock_bh(void) { pthread_mutex_lock(&reader_lock);readers++;pthread_mutex_unlock(&reader_lock); }
static void rcu_read_unlock_bh(void) { pthread_mutex_lock(&reader_lock);assert(readers);readers--;pthread_cond_broadcast(&reader_cond);pthread_mutex_unlock(&reader_lock); }
static void synchronize_net(void) { atomic_store(&sync_entered,true);pthread_mutex_lock(&reader_lock);while(readers)pthread_cond_wait(&reader_cond,&reader_lock);pthread_mutex_unlock(&reader_lock); }
struct semaphore { int held; };
static void down(struct semaphore *s) { assert(!s->held);s->held=1; }
static void up(struct semaphore *s) { assert(s->held);s->held=0; }
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done=false; }
static void complete(struct completion *c) { c->done=true; }
static unsigned msecs_to_jiffies(unsigned n) { return n; }
static int wait_for_completion_timeout(struct completion *c,unsigned timeout);
static unsigned allocations,live_allocations,fail_allocation,unmaps,maps;
static void *kzalloc(size_t size,int flag) { (void)flag;allocations++;if(allocations==fail_allocation)return NULL;void *p=calloc(1,size);assert(p);live_allocations++;return p; }
static void kfree(void *p) { if(p){assert(live_allocations);live_allocations--;free(p);} }
struct device { int refs; };
static struct device *get_device(struct device *d) { d->refs++;return d; }
static void put_device(struct device *d) { assert(d->refs>0);d->refs--; }
static bool map_error,high_address,allow_dma_free=true;
static dma_addr_t dma_map_single(struct device *d,void *p,size_t size,int dir) { (void)d;(void)p;(void)size;assert(dir==DMA_TO_DEVICE);maps++;return high_address?UINT64_C(0x100001000):0x18000000+maps*0x1000; }
static bool dma_mapping_error(struct device *d,dma_addr_t p) { (void)d;(void)p;return map_error; }
static void dma_unmap_single(struct device *d,dma_addr_t p,size_t size,int dir) { (void)d;(void)p;(void)size;assert(dir==DMA_TO_DEVICE&&allow_dma_free);unmaps++; }
struct nss_wifili_msg;
typedef void (*nss_wifili_msg_callback_t)(void *,struct nss_wifili_msg *);
typedef void (*nss_wifili_callback_t)(void);
struct nss_cmn_msg { uint32_t interface,type,len,response,error;nss_ptr_t cb,app_data; };
struct nss_wifili_msg { struct nss_cmn_msg cm;unsigned char payload[64]; };
struct net_device { int unused; };
struct nss_top_instance;
struct nss_ctx_instance { unsigned id;struct nss_top_instance *nss_top;struct { void *ndev; } subsys_dp_register[NSS_MAX_NET_INTERFACES]; };
struct nss_top_instance { unsigned wifi_handler_id;struct nss_ctx_instance nss[2];nss_wifili_msg_callback_t wifili_msg_callback; };
static struct nss_top_instance nss_top_main;
static void nss_core_register_subsys_dp(struct nss_ctx_instance *ctx,unsigned ifnum,nss_wifili_callback_t cb,nss_wifili_callback_t ext,void *x,struct net_device *dev,unsigned features) { (void)cb;(void)ext;(void)x;(void)features;ctx->subsys_dp_register[ifnum].ndev=dev; }
static void nss_core_unregister_subsys_dp(struct nss_ctx_instance *ctx,unsigned ifnum) { ctx->subsys_dp_register[ifnum].ndev=NULL;synchronize_net(); }
static void nss_wifili_release_external_if(unsigned ifnum) { (void)ifnum; }
static void nss_wifili_request_receive(void *,struct nss_wifili_msg *);
static struct nss_wifili_msg wire;
static bool send_failure,auto_reply;
static pthread_t auto_thread;
static bool auto_pending;
static struct nss_ctx_instance *auto_ctx;
static struct nss_wifili_msg auto_response;
static void *auto_receive(void *unused) {
 (void)unused;struct nss_wifili_msg response=auto_response;response.cm.response=NSS_CMN_RESPONSE_ACK;
 nss_wifili_request_receive(auto_ctx->subsys_dp_register[response.cm.interface].ndev,&response);return NULL;
}
static nss_tx_status_t nss_core_send_cmd(struct nss_ctx_instance *ctx,struct nss_wifili_msg *msg,size_t size,unsigned payload) {
 assert(size==sizeof(*msg)&&payload==NSS_NBUF_PAYLOAD_SIZE);wire=*msg;
 if(send_failure)return NSS_TX_FAILURE;
 if(auto_reply){assert(!auto_pending);auto_pending=true;auto_ctx=ctx;auto_response=wire;pthread_create(&auto_thread,NULL,auto_receive,NULL);}
 return NSS_TX_SUCCESS;
}
static int wait_for_completion_timeout(struct completion *c,unsigned timeout) {
 (void)timeout;if(auto_pending){pthread_join(auto_thread,NULL);auto_pending=false;}return c->done;
}
'''

CASES = r'''
static unsigned callback_count;static nss_ptr_t expected_data;static void *expected_ctx;
static pthread_mutex_t callback_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t callback_cond=PTHREAD_COND_INITIALIZER;
static bool block_callback,callback_entered,callback_release;
static _Atomic bool cancel_finished;
static void client_callback(void *ctx,struct nss_wifili_msg *msg) {
 assert(ctx==expected_ctx&&msg->cm.app_data==expected_data);callback_count++;
 pthread_mutex_lock(&callback_lock);
 if(block_callback){callback_entered=true;pthread_cond_broadcast(&callback_cond);while(!callback_release)pthread_cond_wait(&callback_cond,&callback_lock);}
 pthread_mutex_unlock(&callback_lock);
}
static void sync_client_callback(void *ctx,struct nss_wifili_msg *msg) {
 assert(ctx==(void *)(uintptr_t)expected_data&&msg->cm.app_data==expected_data);callback_count++;
}
static struct nss_wifili_msg request(void) {
 return (struct nss_wifili_msg){.cm={.interface=NSS_WIFILI_INTERNAL_INTERFACE,.type=7,
  .cb=(uintptr_t)client_callback,.app_data=expected_data}};
}
static void *receive_thread(void *unused) { (void)unused;struct nss_wifili_msg response=wire;response.cm.response=NSS_CMN_RESPONSE_ACK;nss_wifili_request_receive(expected_ctx,&response);return NULL; }
static void *cancel_thread(void *cookie) { nss_wifili_cancel_msg((uintptr_t)cookie);atomic_store(&cancel_finished,true);return NULL; }
int main(void) {
 struct net_device netdev={0};struct device dev={0};struct nss_ctx_instance *ctx=&nss_top_main.nss[0];ctx->nss_top=&nss_top_main;
 expected_ctx=&netdev;expected_data=UINT64_C(0xfedcba9876543210);
 assert(nss_register_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE,NULL,NULL,NULL,&netdev,0)==ctx);
 struct nss_wifili_msg msg=request();uint32_t cookie=0;
 assert(nss_wifili_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_SUCCESS&&cookie);
 assert(msg.cm.cb==(uintptr_t)client_callback&&msg.cm.app_data==expected_data);
 assert(wire.cm.app_data==cookie&&wire.cm.app_data<=U32_MAX&&wire.cm.cb==(uintptr_t)nss_wifili_request_receive);
 struct nss_wifili_msg original=wire,response=wire;response.cm.response=NSS_CMN_RESPONSE_NOTIFY;
 nss_wifili_request_receive(expected_ctx,&response);assert(!callback_count);
 response=original;response.cm.type++;nss_wifili_request_receive(expected_ctx,&response);assert(!callback_count);
 response=original;response.cm.interface++;nss_wifili_request_receive(expected_ctx,&response);assert(!callback_count);
 response=original;response.cm.response=NSS_CMN_RESPONSE_ACK;nss_wifili_request_receive(expected_ctx,&response);assert(callback_count==1);
 response=original;nss_wifili_request_receive(expected_ctx,&response);assert(callback_count==1&&live_allocations==0);
 msg=request();assert(nss_wifili_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_SUCCESS);original=wire;
 nss_wifili_cancel_msg(cookie);response=original;nss_wifili_request_receive(expected_ctx,&response);assert(callback_count==1&&live_allocations==0);
 msg=request();assert(nss_wifili_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_SUCCESS);original=wire;
 nss_unregister_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE);assert(live_allocations==0);
 assert(nss_register_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE,NULL,NULL,NULL,&netdev,0)==ctx);
 response=original;nss_wifili_request_receive(expected_ctx,&response);assert(callback_count==1);
 msg=request();send_failure=true;assert(nss_wifili_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE&&cookie==0&&live_allocations==0);send_failure=false;
 allocations=0;fail_allocation=1;msg=request();assert(nss_wifili_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE&&live_allocations==0);fail_allocation=0;
 msg=request();assert(nss_wifili_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_SUCCESS);block_callback=true;
 pthread_t receiver,canceller;pthread_create(&receiver,NULL,receive_thread,NULL);
 pthread_mutex_lock(&callback_lock);while(!callback_entered)pthread_cond_wait(&callback_cond,&callback_lock);pthread_mutex_unlock(&callback_lock);
 atomic_store(&sync_entered,false);pthread_create(&canceller,NULL,cancel_thread,(void *)(uintptr_t)cookie);
 while(!atomic_load(&sync_entered)&&!atomic_load(&cancel_finished))sched_yield();
 pthread_mutex_lock(&reader_lock);assert(readers==1&&!atomic_load(&cancel_finished));pthread_mutex_unlock(&reader_lock);
 pthread_mutex_lock(&callback_lock);callback_release=true;pthread_cond_broadcast(&callback_cond);pthread_mutex_unlock(&callback_lock);
 pthread_join(receiver,NULL);pthread_join(canceller,NULL);assert(atomic_load(&cancel_finished)&&live_allocations==0);block_callback=false;
 msg=request();msg.cm.cb=(uintptr_t)sync_client_callback;auto_reply=true;assert(nss_wifili_tx_msg_sync(ctx,&msg)==NSS_TX_SUCCESS);auto_reply=false;
 unsigned saved_count=callback_count;msg=request();msg.cm.cb=(uintptr_t)sync_client_callback;assert(nss_wifili_tx_msg_sync(ctx,&msg)==NSS_TX_FAILURE);original=wire;
 response=original;response.cm.response=NSS_CMN_RESPONSE_ACK;nss_wifili_request_receive(expected_ctx,&response);assert(callback_count==saved_count&&live_allocations==0);
 struct nss_wifili_peer_memory *memory;
 for(unsigned fail=1;fail<=2;fail++){allocations=0;fail_allocation=fail;memory=nss_wifili_peer_memory_alloc(ctx,NSS_WIFILI_INTERNAL_INTERFACE,&dev,64);assert(IS_ERR(memory)&&dev.refs==0&&live_allocations==0);}fail_allocation=0;
 map_error=true;unsigned before=unmaps;memory=nss_wifili_peer_memory_alloc(ctx,NSS_WIFILI_INTERNAL_INTERFACE,&dev,64);assert(IS_ERR(memory)&&unmaps==before&&dev.refs==0);map_error=false;
 high_address=true;memory=nss_wifili_peer_memory_alloc(ctx,NSS_WIFILI_INTERNAL_INTERFACE,&dev,64);assert(PTR_ERR(memory)==-ERANGE&&unmaps==before+1&&dev.refs==0);high_address=false;
 memory=nss_wifili_peer_memory_alloc(ctx,NSS_WIFILI_INTERNAL_INTERFACE,&dev,64);assert(!IS_ERR(memory)&&dev.refs==1&&nss_wifili_peer_memory_address(memory)&&nss_wifili_peer_memory_dma(memory));
 allow_dma_free=false;before=unmaps;nss_wifili_peer_memory_quarantine(memory);assert(dev.refs==1&&unmaps==before);
 nss_unregister_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE);assert(!nss_register_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE,NULL,NULL,NULL,&netdev,0));
 assert(PTR_ERR(nss_wifili_peer_memory_alloc(ctx,NSS_WIFILI_INTERNAL_INTERFACE,&dev,64))==-EBUSY);
 struct nss_ctx_instance other={.id=1};nss_wifili_peer_memory_reclaim(&other);assert(dev.refs==1&&unmaps==before);
 allow_dma_free=true;nss_wifili_peer_memory_reclaim(ctx);assert(dev.refs==0&&unmaps==before+1&&live_allocations==0);
 assert(nss_register_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE,NULL,NULL,NULL,&netdev,0)==ctx);
 nss_unregister_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE);
 atomic_store(&nss_wifili_request_sequence.value,U32_MAX);assert(nss_register_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE,NULL,NULL,NULL,&netdev,0)==ctx);
 msg=request();assert(nss_wifili_tx_msg_tracked(ctx,&msg,&cookie)==NSS_TX_FAILURE&&cookie==0&&live_allocations==0);
 nss_unregister_wifili_if(NSS_WIFILI_INTERNAL_INTERFACE);
 puts("WIFILI: request identity, duplicate/stale/NOTIFY rejection, callback cancellation race, private sync wait, DMA bounds and quarantine passed");
 return 0;
}
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--drv', required=True, type=Path)
    args = p.parse_args()
    source = re.sub(r'/\*.*?\*/', '', (args.drv/'nss_wifili.c').read_text(), flags=re.S)
    structs = ''.join(structure(source, name) for name in ['nss_wifili_request', 'nss_wifili_peer_memory', 'nss_wifili_sync_request'])
    globals_ = r'''
static LIST_HEAD(nss_wifili_peer_quarantine);
static DEFINE_SPINLOCK(nss_wifili_peer_memory_lock);
static unsigned long nss_wifili_blocked_interfaces[NSS_MAX_NET_INTERFACES];
static bool nss_wifili_registered_interfaces[NSS_MAX_NET_INTERFACES];
static LIST_HEAD(nss_wifili_requests);
static atomic64_t nss_wifili_request_sequence=ATOMIC64_INIT(0);
static struct { struct semaphore sem; } wifili_pvt;
'''
    names = ['nss_wifili_request_receive', 'nss_wifili_forget_msg', 'nss_wifili_cancel_msg',
        'nss_wifili_requests_unregister', 'nss_wifili_interface_quarantine', 'nss_wifili_peer_memory_alloc',
        'nss_wifili_peer_memory_address', 'nss_wifili_peer_memory_dma', 'nss_wifili_peer_memory_free',
        'nss_wifili_peer_memory_quarantine', 'nss_wifili_peer_memory_reclaim', 'nss_register_wifili_if',
        'nss_unregister_wifili_if', 'nss_wifili_tx_msg_tracked', 'nss_wifili_tx_msg',
        'nss_wifili_callback', 'nss_wifili_tx_msg_sync']
    bodies = [functions.function(source, name) for name in names]
    index = names.index('nss_wifili_peer_memory_alloc')
    if not bodies[index].startswith('struct nss_wifili_peer_memory *'):
        bodies[index] = 'struct nss_wifili_peer_memory *\n' + bodies[index]
    body = '\n'.join(bodies)
    handler = functions.function(source, 'nss_wifili_handler')
    assert 'ncm->cb != (nss_ptr_t)(uintptr_t)nss_wifili_request_receive' in handler
    hal = re.sub(r'/\*.*?\*/', '', (args.drv/'nss_hal/nss_hal.c').read_text(), flags=re.S)
    remove = functions.function(hal, 'nss_hal_remove')
    assert remove.index('nss_hal_clean_up_irq(') < remove.index('nss_wifili_peer_memory_reclaim(')
    with tempfile.TemporaryDirectory(prefix='nss-wifili-') as tmp:
        path = Path(tmp)/'wifili.c'
        path.write_text(SHIM + structs + globals_ + body + CASES)
        binary = path.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-pthread',
            '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
            '-no-pie', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
