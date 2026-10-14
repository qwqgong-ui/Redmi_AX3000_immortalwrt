#!/usr/bin/env python3
"""Run provider retention and real QMI admission/cleanup functions with faults."""
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


functions = load('quarantine_functions', 'test-nss-control.py')
structures = load('quarantine_structures', 'test-nss-wifili.py')

PROVIDER = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#define NSS_CORE_MAX 2
#define NSS_MAX_NET_INTERFACES 16
#define ARRAY_SIZE(a) (sizeof(a)/sizeof(*(a)))
#define READ_ONCE(v) (v)
#define BIT(n) (1UL<<(n))
#define THIS_MODULE ((void *)1)
#define nss_warning(...) ((void)0)
#define EXPORT_SYMBOL(x)
struct nss_ctx_instance { unsigned id; };
static unsigned module_refs;static int nss_wifili_peer_memory_lock;
static void spin_lock_bh(int *p) { assert(!*p);*p=1; }
static void spin_unlock_bh(int *p) { assert(*p);*p=0; }
static bool test_and_set_bit(unsigned bit,unsigned long *p) { bool old=*p&BIT(bit);*p|=BIT(bit);return old; }
static void __module_get(void *module) { assert(module==THIS_MODULE);module_refs++; }
static unsigned long nss_wifili_unsafe_targets;
'''

PROVIDER_CASES = r'''
int main(void) {
 struct nss_ctx_instance ctx={0},bad={2};int metadata[3]={0};
 assert(!nss_wifili_target_quarantined(29)&&!nss_wifili_target_quarantined(30));
 nss_wifili_soc_quarantine(&bad,3,29,metadata);nss_wifili_soc_quarantine(&ctx,16,29,metadata);nss_wifili_soc_quarantine(&ctx,3,32,metadata);nss_wifili_soc_quarantine(&ctx,3,29,NULL);assert(module_refs==0);
 nss_wifili_soc_quarantine(&ctx,3,29,metadata);assert(module_refs==1&&nss_wifili_target_quarantined(29)&&!nss_wifili_target_quarantined(30));
 nss_wifili_soc_quarantine(&ctx,3,29,metadata);assert(module_refs==1&&nss_wifili_retained_socs[0].metadata==metadata&&!nss_wifili_retained_socs[1].metadata);
 nss_wifili_soc_quarantine(&ctx,4,30,metadata+1);assert(module_refs==2&&nss_wifili_target_quarantined(30)&&nss_wifili_retained_socs[1].metadata==metadata+1);
 nss_wifili_soc_quarantine(&ctx,5,30,metadata+2);assert(module_refs==2&&nss_wifili_retained_socs[2].metadata==metadata+2);
 assert(!nss_wifili_target_quarantined(32)&&!nss_wifili_target_quarantined(255));
 puts("quarantine provider: hardware exclusion, opaque metadata, duplicate publication and one pin per target passed");return 0;
}
'''

QMI = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
typedef uint32_t u32;typedef uintptr_t dma_addr_t;
#define READ_ONCE(v) (v)
#define GFP_ATOMIC 0
#define GFP_KERNEL 1
#define __GFP_NOWARN 0
#define ATH11K_FLAG_FIXED_MEM_RGN 0
#define ATH11K_QMI_RESP_LEN_MAX 64
#define ATH11K_QMI_WLFW_SERVICE_ID_V01 1
#define ATH11K_QMI_WLFW_SERVICE_VERS_V01 1
#define ATH11K_QMI_WLANFW_MAX_NUM_MEM_SEG_V01 2
#define ATH11K_QMI_FW_MEM_REQ_SEGMENT_CNT 5
#define ATH11K_QMI_EVENT_REQUEST_MEM 1
#define ath11k_warn(...) ((void)0)
#define ath11k_err(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define EXPORT_SYMBOL(x)
enum ath11k_qmi_event_type { EVENT_REQUEST=1 };
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(h) ((h)->next=(h),(h)->prev=(h))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_entry(p,t,m) container_of(p,t,m)
#define list_for_each_entry_safe(p,n,h,m) for(p=list_entry((h)->next,__typeof__(*p),m),n=list_entry((p)->m.next,__typeof__(*p),m);&(p)->m!=(h);p=n,n=list_entry((n)->m.next,__typeof__(*n),m))
static void list_add_tail(struct list_head *n,struct list_head *h) { n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n; }
static void list_del(struct list_head *n) { n->prev->next=n->next;n->next->prev=n->prev; }
struct work_struct { bool initialized; };struct workqueue_struct { int alive; };struct qmi_handle { int initialized; };
struct sockaddr_qrtr { int unused; };struct qmi_txn { int unused; };struct target_info { int unused; };
struct target_mem_chunk { u32 size,type,prev_size,prev_type;uintptr_t paddr;union { u32 *vaddr;void *iaddr,*anyaddr; }; };
struct m3_mem_region { u32 size;uintptr_t paddr;void *vaddr; };
struct ath11k_base;
struct ath11k_qmi { struct ath11k_base *ab;struct qmi_handle handle;struct target_info target;struct target_mem_chunk target_mem[2];struct m3_mem_region m3_mem;unsigned mem_seg_count,target_mem_mode,service_ins_id;bool target_mem_delayed,handle_live,event_work_initialized,event_live;struct work_struct event_work;struct workqueue_struct *event_wq;struct list_head event_list;int event_lock;pthread_mutex_t mem_lock; };
struct ath11k_base { struct { bool ownership_uncertain,init_submitted,registered; } nss;struct ath11k_qmi qmi;struct { bool fixed_mem_region,m3_fw_support;unsigned fw_mem_mode; } hw_params;unsigned long dev_flags;void *dev; };
struct ath11k_qmi_driver_event { struct list_head list;enum ath11k_qmi_event_type type;void *data; };
struct qmi_wlanfw_request_mem_ind_msg_v01 { unsigned mem_seg_len;struct { unsigned type,size; } mem_seg[2]; };
static int ath11k_qmi_ops,ath11k_qmi_msg_handlers[1],handle_failure,queue_failure,lookup_failure,assign_result;
static unsigned handle_releases,cancels,destroys,posts,live_events,dma_frees,dma_allocations,assigns;
static struct ath11k_base *active;static struct workqueue_struct queue;
static void spin_lock(int *p) { assert(!*p);*p=1; }static void spin_unlock(int *p) { assert(*p);*p=0; }
#define mutex_lock(p) assert(pthread_mutex_lock(p)==0)
#define mutex_unlock(p) assert(pthread_mutex_unlock(p)==0)
#define spin_lock_init(p) (*(p)=0)
#define INIT_WORK(w,fn) ((w)->initialized=true)
static bool test_bit(unsigned n,unsigned long *v) { return *v&(1UL<<n); }
static void *kzalloc(size_t size,int flags) { (void)flags;void *p=calloc(1,size);assert(p);live_events++;return p; }
static void kfree(void *p) { if(p){assert(live_events);live_events--;free(p);} }
static int qmi_handle_init(struct qmi_handle *h,unsigned size,void *ops,void *handlers) { (void)size;(void)ops;(void)handlers;if(handle_failure)return -EIO;h->initialized=1;return 0; }
static void qmi_handle_release(struct qmi_handle *h) { assert(h->initialized&&!active->qmi.event_live);h->initialized=0;handle_releases++; }
static struct workqueue_struct *alloc_ordered_workqueue(const char *name,unsigned flags) { (void)name;(void)flags;if(queue_failure)return NULL;queue.alive=1;return &queue; }
static void cancel_work_sync(struct work_struct *w) { assert(w->initialized&&!active->qmi.event_live);cancels++; }
static void destroy_workqueue(struct workqueue_struct *w) { assert(w&&w->alive&&!active->qmi.event_live);w->alive=0;destroys++; }
static int qmi_add_lookup(struct qmi_handle *h,unsigned service,unsigned version,unsigned instance) { (void)h;(void)service;(void)version;(void)instance;return lookup_failure?-ENOENT:0; }
static void queue_work(struct workqueue_struct *w,struct work_struct *work) { assert(w&&w->alive&&work->initialized&&active->qmi.event_live&&active->qmi.event_lock);posts++; }
static void iounmap(void *p) { assert(p&&!active->nss.ownership_uncertain);dma_frees++; }
static void dma_free_coherent(void *dev,size_t size,void *p,uintptr_t addr) { (void)dev;(void)size;(void)addr;assert(p&&!active->nss.ownership_uncertain);dma_frees++; }
static void *dma_alloc_coherent(void *dev,size_t size,uintptr_t *addr,unsigned flags) { (void)dev;(void)size;(void)flags;assert(!active->nss.ownership_uncertain);*addr=0x1000;dma_allocations++;return (void *)0x1000; }
static int ath11k_qmi_assign_target_mem_chunk(struct ath11k_base *ab) { assert(ab==active);assigns++;return assign_result; }
'''

QMI_CASES = r'''
static void fresh(struct ath11k_base *ab) { assert(!live_events);memset(ab,0,sizeof(*ab));active=ab;ab->qmi.ab=ab;pthread_mutex_init(&ab->qmi.mem_lock,NULL);handle_releases=cancels=destroys=posts=dma_frees=dma_allocations=assigns=0;handle_failure=queue_failure=lookup_failure=assign_result=0; }
int main(void) {
 struct ath11k_base ab;struct qmi_wlanfw_request_mem_ind_msg_v01 msg={.mem_seg_len=1,.mem_seg={{.type=7,.size=64}}};
 fresh(&ab);ath11k_qmi_deinit_service(&ab);assert(!handle_releases&&!cancels&&!destroys);
 fresh(&ab);handle_failure=1;assert(ath11k_qmi_init_service(&ab)==-EIO&&!ab.qmi.handle_live&&!handle_releases);
 fresh(&ab);queue_failure=1;assert(ath11k_qmi_init_service(&ab)==-EFAULT&&!ab.qmi.handle_live&&!ab.qmi.event_wq&&handle_releases==1&&!cancels&&!destroys);
 fresh(&ab);lookup_failure=1;assert(ath11k_qmi_init_service(&ab)==-ENOENT&&!ab.qmi.handle_live&&!ab.qmi.event_work_initialized&&!ab.qmi.event_wq&&handle_releases==1&&cancels==1&&destroys==1);
 fresh(&ab);assert(ath11k_qmi_init_service(&ab)==0);assert(ath11k_qmi_init_service(&ab)==-EALREADY);
 ath11k_qmi_msg_mem_request_cb(&ab.qmi.handle,NULL,NULL,&msg);assert(posts==1&&ab.qmi.mem_seg_count==1&&ab.qmi.target_mem[0].type==7&&dma_allocations==1);
 ab.nss.init_submitted=ab.nss.registered=true;msg.mem_seg[0].type=9;ath11k_qmi_msg_mem_request_cb(&ab.qmi.handle,NULL,NULL,&msg);assert(ab.qmi.target_mem[0].type==7&&posts==1&&dma_allocations==1);
 ab.nss.ownership_uncertain=true;ab.hw_params.m3_fw_support=true;ab.qmi.m3_mem.vaddr=(void *)0x2000;ab.qmi.m3_mem.size=64;
 assert(ath11k_qmi_driver_event_post(&ab.qmi,EVENT_REQUEST,NULL)==-ESHUTDOWN);assert(ath11k_qmi_alloc_target_mem_chunk(&ab)==-ESHUTDOWN);
 ath11k_qmi_msg_mem_request_cb(&ab.qmi.handle,NULL,NULL,&msg);assert(ab.qmi.target_mem[0].type==7&&posts==1);
 ath11k_qmi_deinit_service(&ab);assert(handle_releases==1&&cancels==1&&destroys==1&&!live_events&&!dma_frees&&ab.qmi.target_mem[0].vaddr==(void *)0x1000&&ab.qmi.m3_mem.vaddr==(void *)0x2000);
 ath11k_qmi_deinit_service(&ab);assert(handle_releases==1&&cancels==1&&destroys==1&&!dma_frees);
 assert(ath11k_qmi_init_service(&ab)==-ESHUTDOWN&&ab.qmi.target_mem[0].vaddr==(void *)0x1000);
 fresh(&ab);assert(ath11k_qmi_init_service(&ab)==0);ab.hw_params.fixed_mem_region=true;assign_result=-EIO;ath11k_qmi_msg_mem_request_cb(&ab.qmi.handle,NULL,NULL,&msg);assert(assigns==1&&!posts);assert(pthread_mutex_trylock(&ab.qmi.mem_lock)==0);pthread_mutex_unlock(&ab.qmi.mem_lock);
 msg.mem_seg_len=0;ath11k_qmi_msg_mem_request_cb(&ab.qmi.handle,NULL,NULL,&msg);assert(assigns==1);ath11k_qmi_deinit_service(&ab);
 fresh(&ab);assert(ath11k_qmi_init_service(&ab)==0);ab.qmi.mem_seg_count=1;ab.qmi.target_mem[0].vaddr=(void *)1;ab.qmi.target_mem[0].prev_size=64;ab.hw_params.m3_fw_support=true;ab.qmi.m3_mem.vaddr=(void *)2;ab.qmi.m3_mem.size=64;
 ath11k_qmi_deinit_service(&ab);assert(dma_frees==2&&!ab.qmi.target_mem[0].vaddr&&!ab.qmi.m3_mem.vaddr);ath11k_qmi_deinit_service(&ab);assert(dma_frees==2&&handle_releases==1&&destroys==1);
 puts("QMI: initialized-stage rollback, event closure/drain, private memory lock, retained DMA and normal/repeated deinit passed");return 0;
}
'''


def compile_case(name, source):
    with tempfile.TemporaryDirectory(prefix='nss-quarantine-') as tmp:
        path = Path(tmp)/(name+'.c');path.write_text(source);binary = path.with_suffix('')
        # Existing QMI callback signatures include unused transport arguments,
        # and its original loops compare int indexes with u32 segment counts.
        extra = ['-Wno-sign-compare', '-Wno-unused-parameter'] if name == 'qmi' else []
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                        '-Werror', *extra, '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-no-pie', '-pthread', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


def main():
    p = argparse.ArgumentParser();p.add_argument('--drv', required=True, type=Path)
    p.add_argument('--backports', required=True, type=Path);a = p.parse_args()
    def read(path):
        text = re.sub(r'/\*.*?\*/', '', path.read_text(), flags=re.S)
        return re.sub(r'(?m)^static (int|void)\s*\n(ath11k_\w+\s*\()', r'static \1 \2', text)
    driver = read(a.drv/'nss_wifili.c')
    record = structures.structure(driver, 'nss_wifili_soc_quarantine')
    globals_ = 'static struct nss_wifili_soc_quarantine nss_wifili_retained_socs[NSS_MAX_NET_INTERFACES*NSS_CORE_MAX];\n'
    body = '\n'.join(functions.function(driver, n) for n in ['nss_wifili_soc_quarantine', 'nss_wifili_target_quarantined'])
    compile_case('provider', PROVIDER + record + globals_ + body + PROVIDER_CASES)
    root = a.backports/'drivers/net/wireless/ath/ath11k';qmi = read(root/'qmi.c')
    names = ['ath11k_qmi_free_target_mem_chunk', 'ath11k_qmi_alloc_target_mem_chunk',
             'ath11k_qmi_m3_free', 'ath11k_qmi_driver_event_post', 'ath11k_qmi_msg_mem_request_cb',
             'ath11k_qmi_stop_service', 'ath11k_qmi_init_service', 'ath11k_qmi_deinit_service']
    compile_case('qmi', QMI + '\n'.join(functions.function(qmi,n) for n in names) + QMI_CASES)
    nss = read(root/'nss.c');reset = functions.function(nss, 'ath11k_nss_reset')
    assert reset.index('mutex_lock(&ab->qmi.mem_lock)') < reset.index('ath11k_dp_dma_quarantine(ab)') < reset.index('mutex_unlock(&ab->qmi.mem_lock)')
    init = functions.function(nss, 'ath11k_nss_init')
    assert init.index('mutex_lock(&ab->qmi.mem_lock)') < init.index('ath11k_nss_command_send(nss_contex') < init.index('mutex_unlock(&ab->qmi.mem_lock)')
    probe = functions.function(read(root/'ahb.c'), 'ath11k_ahb_probe')
    assert probe.index('ath11k_nss_hw_quarantined') < probe.index('dma_set_mask_and_coherent') < probe.index('ath11k_core_alloc')
    print('PASS source ordering: ownership transitions use memory lock; AHB quarantine precedes hardware operations')


if __name__ == '__main__':
    main()
