#!/usr/bin/env python3
"""Execute actual shared-ring retention and CPU-cleanup bodies after RESET failure."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    'nss_shared_function_extraction', Path(__file__).with_name('test-nss-control.py'))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define READ_ONCE(v) (v)
	#define WRITE_ONCE(v,x) ((v)=(x))
	#define RCU_INIT_POINTER(p,v) ((p)=(v))
#define DMA_FROM_DEVICE 1
#define DP_TCL_NUM_RING_MAX 2
#define DP_IDLE_SCATTER_BUFS_MAX 2
#define DP_LINK_DESC_BANKS_MAX 2
#define DP_TX_IDR_SIZE 4
#define HAL_SRNG_RING_ID_MAX 4
#define HAL_SRNG_NUM_LMAC_RINGS 2
#define HAL_WBM_IDLE_SCATTER_BUF_SIZE_MAX 64
#define HAL_WBM_IDLE_LINK 1
#define HAL_CE_DESC_SRC 1
#define HAL_CE_DESC_DST 2
#define HAL_CE_DESC_DST_STATUS 3
#define CE_DESC_RING_ALIGN 8
#define CE_ATTR_DIS_INTR 1
#define ath11k_warn(...) ((void)0)
typedef uint32_t u32;typedef uint16_t u16;typedef uint8_t u8;typedef uint64_t u64;
static void spin_lock_bh(int *lock) { assert(!*lock);*lock=1; }
static void spin_unlock_bh(int *lock) { assert(*lock);*lock=0; }
struct device { unsigned refs; };
struct dp_srng { void *vaddr_unaligned;uintptr_t paddr_unaligned;size_t size;bool cached;unsigned ring_id; };
struct dp_link_desc_bank { void *vaddr_unaligned;uintptr_t paddr_unaligned;size_t size; };
struct hal_wbm_idle_scatter_list { void *vaddr;uintptr_t paddr; };
struct dp_tx_ring { struct dp_srng tcl_data_ring,tcl_comp_ring;void *idr_pool,*tx_status; };
struct ath11k_dp {
 int reo_cmd_lock;bool reo_cmd_accepting;u64 reo_cmd_epoch;
	 bool reo_query_outstanding,reo_ownership_uncertain;unsigned reo_retained_count,reo_wmi_inflight,reo_pn_outstanding;
 struct dp_srng wbm_desc_rel_ring,tcl_cmd_ring,tcl_status_ring,reo_reinject_ring,rx_rel_ring,reo_except_ring,reo_cmd_ring,reo_status_ring;
 struct dp_tx_ring tx_ring[2];struct dp_link_desc_bank link_desc_banks[2];struct hal_wbm_idle_scatter_list scatter_list[2];
};
struct ath11k_base;
struct ath11k { struct ath11k_base *ab;void *hw;int fw_stats,conf_mutex; };
struct ath11k_pdev { struct ath11k *ar; };
struct ath11k_hal {
 struct hal_srng {int initialized,lock;} srng_list[4];u32 shadow_reg_addr[4];
 struct { u32 *vaddr; } rdp,wrp;void *srng_config;
 unsigned avail_blk_resource,current_blk_index,num_shadow_reg_configured;
};
struct ath11k_base {
	 int base_lock;
	 bool wmi_key_admitting;
 struct device *dev;struct { bool enabled,ownership_uncertain,dma_metadata_retained; } nss;
	 struct ath11k_dp dp;struct ath11k_hal hal;struct ath11k_pdev pdevs[2];struct ath11k *pdevs_active[2];int num_radios,mon_reap_timer;
 void *workqueue_aux,*workqueue;
 struct { unsigned ce_count;struct ce_attr { unsigned src_nentries; } host_ce_config[2]; } hw_params;
 struct { struct ath11k_ce_pipe { struct ath11k_ce_ring { unsigned nentries;void *base_addr_owner_space_unaligned;uintptr_t base_addr_ce_space_unaligned; } *src_ring,*dest_ring,*status_ring;unsigned attr_flags;void *recv_cb; } ce_pipe[2];int hp_timer[2]; } ce;
};
static unsigned dma_frees,heap_frees,shadow_stops,mon_stops,debug_removes,pdev_frees,mon_detaches,key_removes,workqueue_destroys,hw_frees,stats_frees;
static struct ath11k_base *active;
static void kfree(void *ptr) { assert(!active->nss.ownership_uncertain);if(ptr)heap_frees++; }
static void dma_free_coherent(struct device *dev,size_t size,void *ptr,uintptr_t dma) { (void)dev;(void)size;(void)dma;assert(ptr&&!active->nss.ownership_uncertain);dma_frees++; }
static void dma_free_noncoherent(struct device *dev,size_t size,void *ptr,uintptr_t dma,int dir) { assert(dir==DMA_FROM_DEVICE);dma_free_coherent(dev,size,ptr,dma); }
static void ath11k_dp_stop_shadow_timers(struct ath11k_base *ab) { assert(ab==active);shadow_stops++; }
/* The notification worker/queued references run in test-nss-reo-notify.py. */
static void ath11k_nss_reoq_stop(struct ath11k_base *ab) { assert(ab==active); }
/* The WMI installer/RCU races execute actual code in test-wmi-key-lifetime.py. */
static void ath11k_mac_key_install_close(struct ath11k *ar) { assert(ar->ab==active&&!active->wmi_key_admitting); }
static void mutex_lock(int *lock) { assert(!*lock);*lock=1; }
static void mutex_unlock(int *lock) { assert(*lock);*lock=0; }
static void synchronize_rcu(void) {}
static void timer_delete_sync(int *timer) { assert(timer==&active->mon_reap_timer);mon_stops++; }
static void ath11k_debugfs_unregister(struct ath11k *ar) { assert(ar);debug_removes++; }
static void ath11k_dp_rx_pdev_free(struct ath11k_base *ab,int i) { assert(ab==active&&i>=0&&!ab->nss.ownership_uncertain);pdev_frees++; }
static void ath11k_dp_rx_pdev_mon_detach(struct ath11k *ar) { assert(ar&&!ar->ab->nss.ownership_uncertain);mon_detaches++; }
static void ath11k_hal_unregister_srng_key(struct ath11k_base *ab) { assert(ab==active&&!ab->nss.ownership_uncertain);key_removes++; }
static void ath11k_hal_free_cont_rdp(struct ath11k_base *ab) { assert(!ab->nss.ownership_uncertain);dma_frees++;ab->hal.rdp.vaddr=NULL; }
static void ath11k_hal_free_cont_wrp(struct ath11k_base *ab) { assert(!ab->nss.ownership_uncertain);dma_frees++;ab->hal.wrp.vaddr=NULL; }
static void ath11k_fw_stats_free(int *stats) { (void)stats;assert(!active->nss.ownership_uncertain);stats_frees++; }
static void ieee80211_free_hw(void *hw) { assert(hw&&!active->nss.ownership_uncertain);hw_frees++; }
static void destroy_workqueue(void *queue) { assert(queue);workqueue_destroys++; }
static struct device *get_device(struct device *dev) { dev->refs++;return dev; }
static unsigned ce_stops,ce_rx_cleanups,ce_tx_callbacks,ce_rx_callbacks;
static void ath11k_ce_stop_shadow_timers(struct ath11k_base *ab) { assert(ab==active);ce_stops++; }
static bool ath11k_ce_need_shadow_fix(unsigned i) { (void)i;return false; }
static void ath11k_dp_shadow_stop_timer(struct ath11k_base *ab,int *timer) { assert(ab==active&&timer); }
static unsigned ath11k_hal_ce_get_desc_size(unsigned kind) { assert(kind>=1&&kind<=3);return 16; }
static void ath11k_ce_rx_pipe_cleanup(struct ath11k_ce_pipe *pipe) { assert(pipe&&!active->nss.ownership_uncertain);ce_rx_cleanups++; }
static void ath11k_ce_tx_process_cb(struct ath11k_ce_pipe *pipe) { assert(pipe&&!active->nss.ownership_uncertain);ce_tx_callbacks++; }
static void ath11k_ce_recv_process_cb(struct ath11k_ce_pipe *pipe) { assert(pipe&&!active->nss.ownership_uncertain);ce_rx_callbacks++; }
'''

CASES = r'''
static void setup(struct ath11k_base *ab,struct ath11k *ar,struct device *dev,bool uncertain) {
 memset(ab,0,sizeof(*ab));memset(ar,0,2*sizeof(*ar));memset(dev,0,sizeof(*dev));active=ab;ab->dev=dev;ab->nss.enabled=true;ab->nss.ownership_uncertain=uncertain;ab->num_radios=2;
 ab->workqueue_aux=(void *)1;ab->workqueue=(void *)2;ab->dp.reo_cmd_accepting=true;
 for(unsigned i=0;i<2;i++){ar[i].ab=ab;ar[i].hw=(void *)(uintptr_t)(i+1);ab->pdevs[i].ar=&ar[i];}
 dma_frees=heap_frees=shadow_stops=mon_stops=debug_removes=pdev_frees=mon_detaches=key_removes=workqueue_destroys=hw_frees=stats_frees=0;
 ce_stops=ce_rx_cleanups=ce_tx_callbacks=ce_rx_callbacks=0;ab->hw_params.ce_count=1;ab->hw_params.host_ce_config[0].src_nentries=1;ab->ce.ce_pipe[0].attr_flags=CE_ATTR_DIS_INTR;ab->ce.ce_pipe[0].recv_cb=(void *)1;
}
int main(void) {
 struct ath11k_base ab;struct ath11k ar[2];struct device dev;u32 rdp[4]={11,22,33,44},wrp[2]={55,66};
 setup(&ab,ar,&dev,true);struct dp_srng ring={.vaddr_unaligned=(void *)1,.paddr_unaligned=0x1000,.size=64};
 ath11k_dp_srng_cleanup(&ab,&ring);assert(ring.vaddr_unaligned==(void *)1&&dma_frees==0);
 ab.nss.enabled=false;ath11k_dp_srng_cleanup(&ab,&ring);assert(ring.vaddr_unaligned==(void *)1&&dma_frees==0);
 ab.dp.tx_ring[0].idr_pool=(void *)1;ath11k_dp_srng_common_cleanup(&ab);assert(shadow_stops==1&&ab.dp.tx_ring[0].idr_pool==(void *)1&&heap_frees==0);
 assert(!ab.dp.reo_cmd_accepting&&ab.dp.reo_cmd_epoch==1&&!ab.dp.reo_cmd_lock);
 ab.dp.scatter_list[0].vaddr=(void *)1;ath11k_dp_scatter_idle_link_desc_cleanup(&ab);assert(ab.dp.scatter_list[0].vaddr==(void *)1&&dma_frees==0);
 ab.dp.link_desc_banks[0].vaddr_unaligned=(void *)2;ath11k_dp_link_desc_bank_free(&ab,ab.dp.link_desc_banks);assert(ab.dp.link_desc_banks[0].vaddr_unaligned==(void *)2&&dma_frees==0);
 ath11k_dp_pdev_free(&ab);assert(mon_stops==1&&debug_removes==2&&pdev_frees==0&&mon_detaches==0);
 ab.hal.rdp.vaddr=rdp;ab.hal.wrp.vaddr=wrp;ab.hal.srng_config=(void *)3;ab.hal.srng_list[0].initialized=1;ab.hal.shadow_reg_addr[0]=77;ab.hal.avail_blk_resource=9;
 ath11k_hal_srng_clear(&ab);assert(rdp[0]==11&&wrp[0]==55&&ab.hal.srng_list[0].initialized==1&&ab.hal.shadow_reg_addr[0]==77&&ab.hal.avail_blk_resource==9);
 ath11k_hal_srng_deinit(&ab);assert(ab.hal.srng_config==(void *)3&&ab.hal.rdp.vaddr==rdp&&ab.hal.wrp.vaddr==wrp&&dma_frees==0&&heap_frees==0&&key_removes==0);
 ath11k_mac_destroy(&ab);assert(ab.pdevs[0].ar==ar&&ab.pdevs[1].ar==ar+1&&hw_frees==0&&stats_frees==0);
 struct ath11k_ce_ring ce_ring={.nentries=4,.base_addr_owner_space_unaligned=(void *)1};ab.ce.ce_pipe[0].src_ring=&ce_ring;
 ath11k_ce_cleanup_pipes(&ab);ath11k_ce_free_pipes(&ab);ath11k_ce_per_engine_service(&ab,0);ath11k_ce_poll_send_completed(&ab,0);
 assert(ce_stops==2&&ce_rx_cleanups==0&&ce_tx_callbacks==0&&ce_rx_callbacks==0&&ab.ce.ce_pipe[0].src_ring==&ce_ring&&dma_frees==0&&heap_frees==0);
 ath11k_core_free(&ab);assert(ab.nss.dma_metadata_retained&&dev.refs==1&&workqueue_destroys==2&&heap_frees==0);
 ath11k_core_free(&ab);assert(dev.refs==1&&workqueue_destroys==2&&heap_frees==0);
 setup(&ab,ar,&dev,false);ring.cached=false;ath11k_dp_srng_cleanup(&ab,&ring);assert(!ring.vaddr_unaligned&&dma_frees==1);
 ring.vaddr_unaligned=(void *)1;ring.cached=true;ath11k_dp_srng_cleanup(&ab,&ring);assert(!ring.vaddr_unaligned&&dma_frees==2);
 ath11k_dp_pdev_free(&ab);assert(mon_stops==1&&debug_removes==2&&pdev_frees==2&&mon_detaches==2);
 ab.hal.rdp.vaddr=rdp;ab.hal.wrp.vaddr=wrp;ab.hal.srng_config=(void *)3;ab.hal.srng_list[0].initialized=1;ab.hal.shadow_reg_addr[0]=77;ab.hal.avail_blk_resource=9;
 ath11k_hal_srng_clear(&ab);assert(rdp[0]==0&&wrp[0]==0&&ab.hal.srng_list[0].initialized==0&&ab.hal.shadow_reg_addr[0]==0&&ab.hal.avail_blk_resource==0);
 ath11k_hal_srng_deinit(&ab);assert(!ab.hal.srng_config&&!ab.hal.rdp.vaddr&&!ab.hal.wrp.vaddr&&key_removes==1&&dma_frees==4&&heap_frees==1);
 ath11k_mac_destroy(&ab);assert(!ab.pdevs[0].ar&&!ab.pdevs[1].ar&&hw_frees==2&&stats_frees==2);
 ab.ce.ce_pipe[0].src_ring=&ce_ring;ath11k_ce_cleanup_pipes(&ab);ath11k_ce_free_pipes(&ab);ath11k_ce_per_engine_service(&ab,0);ath11k_ce_poll_send_completed(&ab,0);
 assert(ce_stops==1&&ce_rx_cleanups==1&&ce_tx_callbacks==3&&ce_rx_callbacks==1&&!ab.ce.ce_pipe[0].src_ring&&dma_frees==5&&heap_frees==2);
 ath11k_core_free(&ab);assert(workqueue_destroys==2&&heap_frees==3&&dev.refs==0&&!ab.nss.dma_metadata_retained);
 puts("shared DMA: DP/HAL/CE and ab/ar retention, timers/debugfs, one-time workqueue drain and normal cleanup passed");
 return 0;
}
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--backports', required=True, type=Path)
    args = p.parse_args()
    root = args.backports / 'drivers/net/wireless/ath/ath11k'
    selected = {
        'dp.c': ['ath11k_dp_srng_cleanup', 'ath11k_dp_srng_common_cleanup',
                 'ath11k_dp_scatter_idle_link_desc_cleanup', 'ath11k_dp_link_desc_bank_free',
                 'ath11k_dp_pdev_free'],
        'hal.c': ['ath11k_hal_srng_clear', 'ath11k_hal_srng_deinit'],
        'mac.c': ['ath11k_mac_destroy'],
        'core.c': ['ath11k_core_free'],
        'ce.c': ['ath11k_ce_per_engine_service', 'ath11k_ce_poll_send_completed',
                 'ath11k_ce_cleanup_pipes', 'ath11k_ce_free_pipes'],
    }
    bodies = [extractor.function((root / 'dp.h').read_text(), 'ath11k_dp_reo_cmd_close')]
    bodies += [extractor.function((root / 'dp_rx.c').read_text(), 'ath11k_dp_reo_query_quarantine')]
    for filename, names in selected.items():
        source = re.sub(r'/\*.*?\*/', '', (root/filename).read_text(), flags=re.S)
        source = re.sub(r'(?m)^static void\s*\n(ath11k_\w+\s*\()', r'static void \1', source)
        bodies.extend(extractor.function(source, name) for name in names)
    with tempfile.TemporaryDirectory(prefix='nss-shared-dma-') as tmp:
        source = Path(tmp)/'shared.c'
        source.write_text(SHIM + '\n'.join(bodies) + CASES)
        binary = source.with_suffix('')
        # Existing CE loops use int indexes for the hw_params u32 ce_count.
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-Wall',
                        '-Wextra', '-Werror', '-Wno-sign-compare', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-no-pie', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
