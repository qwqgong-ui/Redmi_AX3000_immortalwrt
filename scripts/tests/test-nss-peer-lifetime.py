#!/usr/bin/env python3
"""Execute actual peer ownership, ACK wait, detach and reset-retirement functions."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

functions = load('nss_functions', 'test-nss-multicast.py')
wifili = load('nss_driver_tests', 'test-nss-wifili.py')

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;typedef uint32_t u32;typedef uint64_t u64,dma_addr_t,nss_ptr_t;
typedef int nss_tx_status_t;
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_EMSG 1
#define NSS_CMN_RESPONSE_NOTIFY 2
#define NSS_WIFILI_PEER_CREATE_MSG 7
#define NSS_WIFILI_PEER_DELETE_MSG 8
#define NSS_WIFILI_SOC_RESET_MSG 9
#define ETH_ALEN 6
#define U32_MAX UINT32_MAX
#define WIFILI_NSS_PEER_BYTE_SIZE 64
#define ATH11K_NSS_MSG_TIMEOUT_MS 1000
#define ATH11K_AST_TYPE_STATIC 0
#define ATH11K_DBG_NSS 0
#define GFP_ATOMIC 0
#define GFP_KERNEL 1
#define ENOTSUPP EOPNOTSUPP
#define READ_ONCE(v) (v)
#define WARN_ON_ONCE(v) assert(!(v))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(h) ((h)->next=(h),(h)->prev=(h))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_entry(p,t,m) container_of(p,t,m)
#define list_for_each_entry(p,h,m) for(p=list_entry((h)->next,__typeof__(*p),m);&(p)->m!=(h);p=list_entry((p)->m.next,__typeof__(*p),m))
#define list_for_each_entry_safe(p,n,h,m) for(p=list_entry((h)->next,__typeof__(*p),m),n=list_entry((p)->m.next,__typeof__(*p),m);&(p)->m!=(h);p=n,n=list_entry((n)->m.next,__typeof__(*n),m))
static void list_add_tail(struct list_head *n,struct list_head *h) { assert(h->next&&h->prev);n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n; }
static void list_del(struct list_head *n) { n->prev->next=n->next;n->next->prev=n->prev; }
static void list_del_init(struct list_head *n) { list_del(n);INIT_LIST_HEAD(n); }
typedef struct { u64 value; } atomic64_t;
#define ATOMIC64_INIT(x) {.value=x}
static u64 atomic64_inc_return(atomic64_t *v) { return ++v->value; }
typedef struct { int refs; } refcount_t;
static void refcount_set(refcount_t *r,int n) { r->refs=n; }
static void refcount_inc(refcount_t *r) { assert(r->refs>0);r->refs++; }
static bool refcount_dec_and_test(refcount_t *r) { assert(r->refs>0);return --r->refs==0; }
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done=false; }
static void complete_all(struct completion *c) { c->done=true; }
static unsigned msecs_to_jiffies(unsigned n) { return n; }
static void (*wait_hook)(void);
static int wait_for_completion_timeout(struct completion *c,unsigned timeout) { (void)timeout;if(wait_hook){void(*hook)(void)=wait_hook;wait_hook=NULL;hook();}return c->done; }
static unsigned allocations,live_allocations,fail_allocation,lease_frees,quarantines,submissions;
static void *kzalloc(size_t size,int gfp) { (void)gfp;allocations++;if(allocations==fail_allocation)return NULL;void *p=calloc(1,size);assert(p);live_allocations++;return p; }
static void kfree(void *p) { if(p){assert(live_allocations);live_allocations--;free(p);} }
static void spin_lock_bh(int *lock) { assert(!*lock);*lock=1; }
static void spin_unlock_bh(int *lock) { assert(*lock);*lock=0; }
#define lockdep_assert_held(p) assert(*(p))
static void ether_addr_copy(u8 *to,const u8 *from) { memcpy(to,from,6); }
static bool ether_addr_equal(const u8 *a,const u8 *b) { return !memcmp(a,b,6); }
struct device { int unused; };
struct peer_stats { int unused; };
struct ath11k_nss_peer_state;
struct ath11k_ast_entry { struct list_head list; };
struct ath11k_nss_peer { u32 *vaddr;dma_addr_t paddr;struct ath11k_nss_peer_state *state;struct peer_stats *nss_stats;int create_result; };
struct ath11k_peer { struct list_head list,ast_entry_list;struct ath11k_ast_entry *self_ast_entry;struct ath11k_nss_peer nss;u32 peer_id,vdev_id,hw_peer_id,ast_hash;u8 addr[6]; };
struct ath11k_base { int base_lock;struct device *dev;struct { bool enabled,peers_initialized,ownership_uncertain,quiescing,registered;u32 if_num;void *ctx;struct list_head peers; } nss; };
struct ath11k { struct ath11k_base *ab;struct list_head peers; };
struct nss_wifili_peer_msg { u32 peer_id,vdev_id,hw_ast_idx,tx_ast_hash,nss_peer_mem,psta_vdev_id;u8 peer_mac_addr[6]; };
struct nss_wifili_msg { struct { u32 interface,type,len,response;nss_ptr_t cb,app_data; } cm;union { struct nss_wifili_peer_msg peermsg; } msg; };
typedef void (*nss_wifili_msg_callback_t)(void *,struct nss_wifili_msg *);
static void nss_cmn_msg_init(void *cm,u32 ifnum,u32 type,size_t size,nss_wifili_msg_callback_t cb,void *data) { struct nss_wifili_msg *msg=cm;msg->cm.interface=ifnum;msg->cm.type=type;msg->cm.len=size;msg->cm.cb=(uintptr_t)cb;msg->cm.app_data=(uintptr_t)data; }
struct nss_wifili_peer_memory { void *vaddr;dma_addr_t paddr;bool firmware_owned; };
static bool lease_error,tx_error;
static struct nss_wifili_peer_memory *retained[64];static unsigned retained_count;
static struct nss_wifili_peer_memory *nss_wifili_peer_memory_alloc(void *ctx,u32 ifnum,struct device *dev,u32 size) {
 (void)ctx;(void)ifnum;(void)dev;if(lease_error)return ERR_PTR(-ENOMEM);
 struct nss_wifili_peer_memory *m=kzalloc(sizeof(*m),0);if(!m)return ERR_PTR(-ENOMEM);
 m->vaddr=kzalloc(size,0);if(!m->vaddr){kfree(m);return ERR_PTR(-ENOMEM);}m->paddr=0x18000000+allocations*0x1000;return m;
}
static void *nss_wifili_peer_memory_address(struct nss_wifili_peer_memory *m) { return m->vaddr; }
static u64 nss_wifili_peer_memory_dma(struct nss_wifili_peer_memory *m) { return m->paddr; }
static void nss_wifili_peer_memory_free(struct nss_wifili_peer_memory *m) { if(m){assert(!m->firmware_owned);kfree(m->vaddr);kfree(m);lease_frees++;} }
static void nss_wifili_peer_memory_quarantine(struct nss_wifili_peer_memory *m) { assert(m&&retained_count<64);retained[retained_count++]=m;quarantines++; }
static void nss_wifili_forget_msg(u32 cookie) { (void)cookie; }
static struct nss_wifili_msg sent[128];static u32 next_cookie;
static nss_tx_status_t nss_wifili_tx_msg_tracked(void *ctx,struct nss_wifili_msg *msg,u32 *cookie) { (void)ctx;assert(submissions<128);void *request=kzalloc(sizeof(u32),0);if(!request||tx_error){kfree(request);*cookie=0;return NSS_TX_FAILURE;}*cookie=++next_cookie;sent[submissions++]=*msg;kfree(request);return NSS_TX_SUCCESS; }
static struct ath11k_peer *ath11k_peer_find(struct ath11k *ar,u32 vdev,const u8 *addr) { struct ath11k_peer *p;list_for_each_entry(p,&ar->peers,list)if(p->vdev_id==vdev&&ether_addr_equal(p->addr,addr))return p;return NULL; }
static int ast_error;
static int ath11k_peer_add_ast(struct ath11k *ar,struct ath11k_peer *peer,u8 *addr,int type) { (void)addr;lockdep_assert_held(&ar->ab->base_lock);assert(type==ATH11K_AST_TYPE_STATIC);if(ast_error)return ast_error;struct ath11k_ast_entry *entry=kzalloc(sizeof(*entry),0);if(!entry)return -ENOMEM;list_add_tail(&entry->list,&peer->ast_entry_list);peer->self_ast_entry=entry;return 0; }
static void ath11k_peer_del_ast(struct ath11k *ar,struct ath11k_ast_entry *entry) { lockdep_assert_held(&ar->ab->base_lock);list_del(&entry->list);kfree(entry); }
'''

CASES = r'''
static struct ath11k_base ab;static struct ath11k ar;static struct device dev;static struct ath11k_peer *active;
static void setup(void) { assert(!live_allocations);memset(&ab,0,sizeof(ab));memset(&ar,0,sizeof(ar));ar.ab=&ab;ab.dev=&dev;ab.nss.enabled=ab.nss.peers_initialized=true;ab.nss.if_num=3;ab.nss.ctx=&ab;INIT_LIST_HEAD(&ab.nss.peers);INIT_LIST_HEAD(&ar.peers);allocations=fail_allocation=lease_frees=quarantines=submissions=retained_count=0;lease_error=tx_error=false;ast_error=0;wait_hook=NULL; }
static struct ath11k_peer *new_peer(void) { struct ath11k_peer *p=kzalloc(sizeof(*p),0);p->peer_id=42;p->vdev_id=3;p->addr[0]=2;p->addr[5]=42;INIT_LIST_HEAD(&p->ast_entry_list);list_add_tail(&p->list,&ar.peers);return p; }
static int create(struct ath11k_peer *p) { ab.base_lock=1;int result=ath11k_nss_peer_create(&ar,p);ab.base_lock=0;p->nss.create_result=result;return result; }
static void delete_host(struct ath11k_peer *p) { ab.base_lock=1;ath11k_nss_peer_detach(&ar,p);if(p->self_ast_entry){ath11k_peer_del_ast(&ar,p->self_ast_entry);p->self_ast_entry=NULL;}list_del(&p->list);kfree(p);ab.base_lock=0; }
static void response(unsigned index,u32 kind) {
 struct nss_wifili_msg msg=sent[index];msg.cm.response=kind;
 if(kind==NSS_CMN_RESPONSE_ACK&&msg.cm.type==NSS_WIFILI_PEER_DELETE_MSG){struct ath11k_nss_peer_state *s;list_for_each_entry(s,&ab.nss.peers,list)if(s->instance==msg.cm.app_data)s->memory->firmware_owned=false;}
 ath11k_nss_peer_response(&ab,&msg);
}
static void mark_firmware(struct ath11k_peer *p) { p->nss.state->memory->firmware_owned=true; }
static void acknowledge_delete_during_wait(void) { delete_host(active);response(submissions-1,NSS_CMN_RESPONSE_ACK); }
static void purge_safe(void) { struct ath11k_nss_peer_state *s;list_for_each_entry(s,&ab.nss.peers,list)s->memory->firmware_owned=false;ath11k_nss_peer_states_purge(&ab,false); }
int main(void) {
 for(unsigned fail=1;fail<=7;fail++) {
  setup();active=new_peer();allocations=0;fail_allocation=fail;
  int result=create(active);assert(result<0&&submissions==0&&!active->nss.state&&!active->nss.vaddr&&!active->nss.nss_stats&&!active->self_ast_entry);
  fail_allocation=0;delete_host(active);assert(!live_allocations);
 }
 setup();active=new_peer();tx_error=true;assert(create(active)==-EIO&&!active->nss.state&&!active->self_ast_entry&&lease_frees==1);tx_error=false;delete_host(active);assert(!live_allocations);
 setup();active=new_peer();ast_error=-ENOBUFS;assert(create(active)==-ENOBUFS&&submissions==0&&lease_frees==1);ast_error=0;delete_host(active);
 setup();active=new_peer();ab.nss.quiescing=true;assert(create(active)==-ESHUTDOWN&&submissions==0);delete_host(active);
 setup();active=new_peer();assert(create(active)==0);mark_firmware(active);assert(ath11k_nss_peer_wait_created(&ar,3,active->addr)==-ETIMEDOUT);
 struct nss_wifili_msg wrong=sent[0];wrong.cm.response=NSS_CMN_RESPONSE_NOTIFY;ath11k_nss_peer_response(&ab,&wrong);assert(!active->nss.state->create_done);
 wrong=sent[0];wrong.cm.interface++;ath11k_nss_peer_response(&ab,&wrong);assert(!active->nss.state->create_done);
 wrong=sent[0];wrong.msg.peermsg.peer_id++;ath11k_nss_peer_response(&ab,&wrong);assert(active->nss.state->create_result==-EPROTO&&lease_frees==0);
 delete_host(active);assert(submissions==2);response(1,NSS_CMN_RESPONSE_ACK);assert(!live_allocations&&lease_frees==1);
 setup();active=new_peer();assert(create(active)==0);mark_firmware(active);response(0,NSS_CMN_RESPONSE_ACK);assert(ath11k_nss_peer_wait_created(&ar,3,active->addr)==0);
 wait_hook=acknowledge_delete_during_wait;assert(ath11k_nss_peer_delete(&ar,3,active->addr)==0);assert(!live_allocations&&lease_frees==1);
 setup();active=new_peer();assert(create(active)==0);mark_firmware(active);response(0,NSS_CMN_RESPONSE_EMSG);assert(ath11k_nss_peer_wait_created(&ar,3,active->addr)==-EREMOTEIO&&lease_frees==0);
 assert(ath11k_nss_peer_delete(&ar,3,active->addr)==-ETIMEDOUT);response(1,NSS_CMN_RESPONSE_EMSG);assert(ath11k_nss_peer_delete(&ar,3,active->addr)==-EREMOTEIO&&lease_frees==0);
 delete_host(active);struct ath11k_peer *replacement=new_peer();assert(create(replacement)==-EBUSY&&submissions==2);delete_host(replacement);
 ath11k_nss_peer_states_purge(&ab,true);assert(quarantines==1&&lease_frees==0);
 retained[0]->firmware_owned=false;nss_wifili_peer_memory_free(retained[0]);assert(!live_allocations);
 setup();active=new_peer();assert(create(active)==0);mark_firmware(active);response(0,NSS_CMN_RESPONSE_ACK);delete_host(active);struct nss_wifili_msg old_create=sent[0],old_delete=sent[1];response(1,NSS_CMN_RESPONSE_ACK);
 replacement=new_peer();assert(create(replacement)==0);mark_firmware(replacement);unsigned before=lease_frees;
 old_delete.cm.response=NSS_CMN_RESPONSE_ACK;ath11k_nss_peer_response(&ab,&old_delete);old_create.cm.response=NSS_CMN_RESPONSE_EMSG;ath11k_nss_peer_response(&ab,&old_create);
 assert(lease_frees==before&&replacement->nss.state&&!replacement->nss.state->create_done);
 response(2,NSS_CMN_RESPONSE_ACK);delete_host(replacement);response(3,NSS_CMN_RESPONSE_ACK);assert(!live_allocations);
 setup();active=new_peer();assert(create(active)==0);mark_firmware(active);ab.nss.quiescing=true;unsigned count=submissions;delete_host(active);assert(submissions==count);purge_safe();assert(!live_allocations);
 puts("ath11k NSS peers: allocation/TX failures, matching CREATE ACK, detach during DELETE wait, NACK/timeout retention, ID reuse rejection, stale response rejection and quiescing passed");
 return 0;
}
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--backports', required=True, type=Path)
    args = p.parse_args()
    directory = args.backports/'drivers/net/wireless/ath/ath11k'
    source = re.sub(r'/\*.*?\*/', '', (directory/'nss.c').read_text(), flags=re.S)
    structure = wifili.structure(source, 'ath11k_nss_peer_state')
    globals_ = 'static atomic64_t ath11k_nss_peer_sequence=ATOMIC64_INIT(0);\n'
    names = ['ath11k_nss_peer_state_put', 'ath11k_nss_peer_state_retire', 'ath11k_nss_peer_response',
        'ath11k_nss_peer_submit_delete', 'ath11k_nss_peer_detach', 'ath11k_nss_peer_wait_created',
        'ath11k_nss_peer_states_purge', 'ath11k_nss_peer_delete', 'ath11k_nss_peer_create']
    body = '\n'.join(functions.function(source, name) for name in names)
    peer = re.sub(r'/\*.*?\*/', '', (directory/'peer.c').read_text(), flags=re.S)
    for name in ['ath11k_peer_unmap_event', 'ath11k_peer_unmap_v2_event', 'ath11k_peer_cleanup']:
        assert 'ath11k_nss_peer_detach(ar, peer)' in functions.function(peer, name)
    creator = functions.function(peer, 'ath11k_peer_create')
    assert creator.index('ath11k_nss_peer_wait_created(') < creator.index('ret = ath11k_peer_rhash_add(ar, peer)')
    with tempfile.TemporaryDirectory(prefix='nss-peer-lifetime-') as tmp:
        path = Path(tmp)/'peer.c';path.write_text(SHIM + structure + globals_ + body + CASES)
        binary = path.with_suffix('')
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
            '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
            str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
