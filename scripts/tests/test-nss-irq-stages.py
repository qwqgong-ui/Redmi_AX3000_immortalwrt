#!/usr/bin/env python3
"""Fault-inject actual AHB/PCIC IRQ setup, mask accounting and stage rollback."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('irq_extract', Path(__file__).with_name('test-nss-control.py'))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;typedef uint16_t u16;typedef uint8_t u8;typedef int irqreturn_t;
#define ATH11K_EXT_IRQ_GRP_NUM_MAX 3
#define ATH11K_EXT_IRQ_NUM_MAX 1
#define ATH11K_IRQ_CE0_OFFSET 0
#define ATH11K_PCI_IRQ_CE0_OFFSET 0
#define ATH11K_PCI_IRQ_DP_OFFSET 8
#define ATH11K_FLAG_MULTI_MSI_VECTORS 0
#define ATH11K_FLAG_CE_IRQ_ENABLED 1
#define ATH11K_FLAG_EXT_IRQ_ENABLED 2
#define ATH11K_FLAG_CRASH_FLUSH 3
#define CE_ATTR_DIS_INTR 1
#define CE_HOST_IE_3_SHIFT 8
#define IRQ_NOAUTOEN 1
#define IRQ_DISABLE_UNLAZY 2
#define IRQF_TRIGGER_RISING 4
#define IRQF_SHARED 8
#define IRQF_NOBALANCING 16
#define IRQ_HANDLED 1
#define READ_ONCE(v) (v)
#define BIT(n) (1UL<<(n))
#define EXPORT_SYMBOL(x)
#define ath11k_err(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define from_tasklet(p,t,m) container_of(t,__typeof__(*p),m)
static unsigned long jiffies;
enum { wbm2host_tx_completions_ring1=9,reo2host_destination_ring1=10,reo2host_exception=11,wbm2host_rx_release=12,reo2host_status=13,rxdma2host_destination_ring_mac1=14,host2rxdma_host_buf_ring_mac1=15,ppdu_end_interrupts_mac1=16,rxdma2host_monitor_status_ring_mac1=17 };
static const char *irq_name[32]={"0","1","2","3","4","5","6","7","8","9","10","11","12","13","14","15","16","17"};
struct tasklet_struct { bool initialized,pending;void (*callback)(struct tasklet_struct *); };
struct napi_struct { bool added,enabled,scheduled;int (*poll)(struct napi_struct *,int); };
struct net_device { char name[32]; };
struct ce_attr { unsigned src_nentries,dest_nentries,flags; };
struct ce_ie_addr { unsigned ie1_reg_addr,ie2_reg_addr,ie3_reg_addr; };
struct ring_mask { unsigned tx[3],rx[3],rx_err[3],rx_wbm_rel[3],reo_status[3],rxdma2host[3],host2rxdma[3],rx_mon_status[3]; };
struct ath11k_hw_params { unsigned ce_count,max_radios;bool hybrid_bus_type;struct ring_mask *ring_mask;struct ce_ie_addr *ce_ie_addr;struct ce_attr host_ce_config[3]; };
struct ath11k_base;
struct ath11k_ce_pipe { struct ath11k_base *ab;unsigned pipe_num;struct tasklet_struct intr_tq;bool tasklet_initialized,irq_requested,irq_enabled;unsigned long timestamp; };
struct ath11k_ext_irq_grp { struct ath11k_base *ab;unsigned grp_id,num_irq,num_irq_requested,irqs[16];struct napi_struct napi;struct net_device *napi_ndev;bool napi_added,napi_enabled,irq_enabled;unsigned long timestamp; };
struct ath11k_base { struct ath11k_hw_params hw_params;struct { struct ath11k_ce_pipe ce_pipe[3]; } ce;struct ath11k_ext_irq_grp ext_irq_grp[3];int irq_num[32];unsigned long dev_flags;struct { bool enabled; } nss;void *pdev; };
struct action { int irq;void *owner;bool live; };
static struct action actions[32];static int depth[64],irq_status[64];
static unsigned action_count,requests,allocations,live_netdevs,live_napi;
static unsigned request_failure,allocation_failure,lookup_failure,lookups,msi_count=1;
static bool is_pcic,tasklet_setup_seen;
static bool test_bit(unsigned bit,const unsigned long *p) { return *p&BIT(bit); }
static void set_bit(unsigned bit,unsigned long *p) { *p|=BIT(bit); }
static void clear_bit(unsigned bit,unsigned long *p) { *p&=~BIT(bit); }
static bool test_and_set_bit(unsigned bit,unsigned long *p) { bool old=test_bit(bit,p);set_bit(bit,p);return old; }
static bool test_and_clear_bit(unsigned bit,unsigned long *p) { bool old=test_bit(bit,p);clear_bit(bit,p);return old; }
static unsigned owners(int irq) { unsigned n=0;for(unsigned i=0;i<32;i++)n+=actions[i].live&&actions[i].irq==irq;return n; }
static int request_irq(int irq,irqreturn_t (*handler)(int,void *),unsigned long flags,const char *name,void *owner) {
 assert(irq>0&&irq<64&&handler&&name&&owner);requests++;if(request_failure==requests)return -EIO;
 unsigned count=owners(irq);if(count)assert(flags&IRQF_SHARED);else depth[irq]=(irq_status[irq]&IRQ_NOAUTOEN)?1:0;
 for(unsigned i=0;i<32;i++)if(!actions[i].live){actions[i]=(struct action){irq,owner,true};action_count++;return 0;}abort();
}
static void free_irq(int irq,void *owner) { for(unsigned i=0;i<32;i++)if(actions[i].live&&actions[i].irq==irq&&actions[i].owner==owner){actions[i].live=false;action_count--;return;}abort(); }
static void enable_irq(int irq) { assert(owners(irq)&&depth[irq]>0);depth[irq]--; }
static void disable_irq_nosync(int irq) { assert(owners(irq));depth[irq]++; }
static void synchronize_irq(int irq) { assert(owners(irq)); }
static void irq_set_status_flags(int irq,unsigned flags) { assert(irq>0&&irq<64);irq_status[irq]|=flags; }
static int platform_get_irq_byname(void *pdev,const char *name) { (void)pdev;lookups++;if(lookups==lookup_failure)return -ENXIO;return atoi(name)+20; }
static int ath11k_pcic_get_user_msi_assignment(struct ath11k_base *ab,const char *name,void *count,u32 *data,u32 *base) { (void)ab;*(u32 *)count=msi_count;*data=0;*base=!strcmp(name,"CE")?0:4;return 0; }
static int ath11k_pcic_get_msi_irq(struct ath11k_base *ab,unsigned vector) { (void)ab;lookups++;if(lookups==lookup_failure)return -ENXIO;return msi_count==1?40:(int)vector+40; }
static unsigned ath11k_ce_get_attr_flags(struct ath11k_base *ab,unsigned i) { return ab->hw_params.host_ce_config[i].flags; }
static unsigned ath11k_hw_get_mac_from_pdev_id(struct ath11k_hw_params *hw,unsigned i) { (void)hw;return i; }
static void ath11k_ahb_setbit32(struct ath11k_base *ab,u8 bit,u32 offset) { (void)ab;(void)bit;(void)offset;assert(tasklet_setup_seen); }
static void ath11k_ahb_clearbit32(struct ath11k_base *ab,u8 bit,u32 offset) { (void)ab;(void)bit;(void)offset; }
static void tasklet_setup(struct tasklet_struct *t,void (*callback)(struct tasklet_struct *)) { assert(!t->initialized);t->initialized=true;t->callback=callback;tasklet_setup_seen=true; }
static void tasklet_schedule(struct tasklet_struct *t) { assert(t->initialized);t->pending=true; }
static void tasklet_kill(struct tasklet_struct *t) { assert(t->initialized);if(t->pending){t->pending=false;t->callback(t);} }
static void ath11k_ce_per_engine_service(struct ath11k_base *ab,unsigned id) { assert(ab&&id<3); }
static struct net_device *alloc_netdev_dummy(unsigned size) { (void)size;allocations++;if(allocations==allocation_failure)return NULL;live_netdevs++;return calloc(1,sizeof(struct net_device)); }
static void free_netdev(struct net_device *dev) { assert(dev&&live_netdevs);live_netdevs--;free(dev); }
static void netif_napi_add(struct net_device *dev,struct napi_struct *n,int (*poll)(struct napi_struct *,int)) { assert(dev&&!n->added);n->added=true;n->poll=poll;live_napi++; }
static void netif_napi_del(struct napi_struct *n) { assert(n->added&&!n->enabled&&!n->scheduled&&live_napi);n->added=false;live_napi--; }
static void dev_set_threaded(struct net_device *dev,bool enable) { assert(dev&&enable); }
static void napi_enable(struct napi_struct *n) { assert(n->added&&!n->enabled);n->enabled=true; }
static bool napi_schedule_prep(struct napi_struct *n) { if(!n->enabled||n->scheduled)return false;n->scheduled=true;return true; }
static void __napi_schedule(struct napi_struct *n) { assert(n->enabled&&n->scheduled); }
static bool napi_complete_done(struct napi_struct *n,int work) { (void)work;if(!n->scheduled)return false;n->scheduled=false;return true; }
static void napi_synchronize(struct napi_struct *n) { assert(n->added);if(n->scheduled)n->poll(n,64); }
static void napi_disable(struct napi_struct *n) { assert(n->enabled&&!n->scheduled);n->enabled=false; }
static int ath11k_dp_service_srng(struct ath11k_base *ab,struct ath11k_ext_irq_grp *grp,int budget) { (void)ab;(void)grp;(void)budget;return 0; }
'''

CASES = r'''
static void reset(struct ath11k_base *ab,bool pcic,bool multi) {
 static struct ring_mask masks;static struct ce_ie_addr addr;
 assert(!action_count&&!live_napi&&!live_netdevs);memset(ab,0,sizeof(*ab));memset(&masks,0,sizeof(masks));memset(depth,0,sizeof(depth));memset(irq_status,0,sizeof(irq_status));
 requests=allocations=lookups=0;request_failure=allocation_failure=lookup_failure=0;is_pcic=pcic;tasklet_setup_seen=false;msi_count=multi?3:1;
 ab->hw_params=(struct ath11k_hw_params){.ce_count=3,.max_radios=1,.ring_mask=&masks,.ce_ie_addr=&addr};
 for(unsigned i=0;i<3;i++){ab->ce.ce_pipe[i].ab=ab;ab->ce.ce_pipe[i].pipe_num=i;ab->hw_params.host_ce_config[i].src_nentries=1;}
 masks.reo_status[0]=1;masks.rxdma2host[1]=1;masks.rx_mon_status[2]=1;
 if(multi)set_bit(ATH11K_FLAG_MULTI_MSI_VECTORS,&ab->dev_flags);
}
static int configure(struct ath11k_base *ab) { return is_pcic?ath11k_pcic_config_irq(ab):ath11k_ahb_config_irq(ab); }
static void destroy(struct ath11k_base *ab) { if(is_pcic)ath11k_pcic_free_irq(ab);else ath11k_ahb_free_irq(ab); }
static void start(struct ath11k_base *ab) { if(is_pcic){ath11k_pcic_ce_irqs_enable(ab);ath11k_pcic_ext_irq_enable(ab);}else{ath11k_ahb_ce_irqs_enable(ab);ath11k_ahb_ext_irq_enable(ab);} }
static void stop(struct ath11k_base *ab) { if(is_pcic){ath11k_pcic_ce_irq_disable_sync(ab);ath11k_pcic_ext_irq_disable(ab);}else{ath11k_ahb_ce_irqs_disable(ab);ath11k_ahb_ext_irq_disable(ab);} }
static void assert_stages_empty(struct ath11k_base *ab) {
 assert(!action_count&&!live_netdevs&&!live_napi);
 for(unsigned i=0;i<3;i++){assert(!ab->ce.ce_pipe[i].irq_requested&&!ab->ce.ce_pipe[i].tasklet_initialized);assert(!ab->ext_irq_grp[i].num_irq_requested&&!ab->ext_irq_grp[i].napi_added&&!ab->ext_irq_grp[i].napi_ndev);}
}
int main(void) {
 struct ath11k_base ab;
 for(unsigned pcic=0;pcic<2;pcic++)for(unsigned multi=0;multi<2;multi++) {
  reset(&ab,pcic,multi);assert(configure(&ab)==0);unsigned request_total=requests,lookup_total=lookups;destroy(&ab);destroy(&ab);assert_stages_empty(&ab);
  for(unsigned failure=1;failure<=request_total;failure++){reset(&ab,pcic,multi);request_failure=failure;assert(configure(&ab)==-EIO);destroy(&ab);assert_stages_empty(&ab);}
  for(unsigned failure=1;failure<=lookup_total;failure++){reset(&ab,pcic,multi);lookup_failure=failure;assert(configure(&ab)==-ENXIO);destroy(&ab);assert_stages_empty(&ab);}
  for(unsigned failure=1;failure<=3;failure++){reset(&ab,pcic,multi);allocation_failure=failure;assert(configure(&ab)==-ENOMEM);destroy(&ab);assert_stages_empty(&ab);}
  reset(&ab,pcic,multi);assert(!configure(&ab));start(&ab);start(&ab);
  for(unsigned i=0;i<64;i++)if(owners(i))assert(depth[i]==0);
  struct ath11k_ext_irq_grp *grp=&ab.ext_irq_grp[0];int irq=ab.irq_num[grp->irqs[0]];
  if(pcic){ath11k_pcic_ext_interrupt_handler(irq,grp);ath11k_pcic_ext_interrupt_handler(irq,grp);}else{ath11k_ahb_ext_interrupt_handler(irq,grp);ath11k_ahb_ext_interrupt_handler(irq,grp);}
  assert(grp->napi.scheduled&&depth[irq]==1);grp->napi.poll(&grp->napi,64);assert(!grp->napi.scheduled&&!depth[irq]);
  /* A duplicate completion must not unmask twice. */
  grp->napi.poll(&grp->napi,64);assert(!depth[irq]);
  if(pcic)ath11k_pcic_ext_interrupt_handler(irq,grp);else ath11k_ahb_ext_interrupt_handler(irq,grp);
  stop(&ab);int stopped[64];memcpy(stopped,depth,sizeof(depth));stop(&ab);assert(!memcmp(stopped,depth,sizeof(depth)));
  start(&ab);for(unsigned i=0;i<64;i++)if(owners(i))assert(!depth[i]);
  destroy(&ab);destroy(&ab);assert_stages_empty(&ab);
 }
 reset(&ab,true,true);msi_count=0;assert(configure(&ab)==-EINVAL);destroy(&ab);assert_stages_empty(&ab);
 puts("IRQ stages: all request/lookup/NAPI-allocation failure prefixes, shared one-vector actions, repeated stop/free and NAPI temporary-mask balance passed");return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', required=True, type=Path)
    args = parser.parse_args()
    root = args.backports / 'drivers/net/wireless/ath/ath11k'
    ahb, pcic = [(root / name).read_text() for name in ('ahb.c', 'pcic.c')]
    ahb_names = ['ath11k_ahb_ext_grp_disable', '__ath11k_ahb_ext_irq_disable',
                 'ath11k_ahb_ext_grp_enable', 'ath11k_ahb_ce_irq_enable',
                 'ath11k_ahb_ce_irq_disable', 'ath11k_ahb_sync_ext_irqs',
                 'ath11k_ahb_ce_irqs_enable', 'ath11k_ahb_ce_irqs_disable',
                 'ath11k_ahb_ext_irq_enable', 'ath11k_ahb_ext_irq_disable',
                 'ath11k_ahb_free_ext_irq', 'ath11k_ahb_free_irq',
                 'ath11k_ahb_ce_tasklet', 'ath11k_ahb_ce_interrupt_handler',
                 'ath11k_ahb_ext_grp_napi_poll', 'ath11k_ahb_ext_interrupt_handler',
                 'ath11k_ahb_config_ext_irq', 'ath11k_ahb_config_irq']
    pcic_names = ['ath11k_pcic_free_ext_irq', 'ath11k_pcic_free_irq',
                  'ath11k_pcic_ce_irq_enable', 'ath11k_pcic_ce_irq_disable',
                  'ath11k_pcic_ce_irqs_disable', 'ath11k_pcic_sync_ce_irqs',
                  'ath11k_pcic_ce_tasklet', 'ath11k_pcic_ce_interrupt_handler',
                  'ath11k_pcic_ext_grp_disable', '__ath11k_pcic_ext_irq_disable',
                  'ath11k_pcic_ext_grp_enable', 'ath11k_pcic_ext_irq_enable',
                  'ath11k_pcic_sync_ext_irqs', 'ath11k_pcic_ext_irq_disable',
                  'ath11k_pcic_ext_grp_napi_poll', 'ath11k_pcic_ext_interrupt_handler',
                  'ath11k_pcic_ext_irq_config', 'ath11k_pcic_config_irq',
                  'ath11k_pcic_ce_irqs_enable', 'ath11k_pcic_kill_tasklets',
                  'ath11k_pcic_ce_irq_disable_sync']
    bodies = [extractor.function(text, name) for text, names in
              [(ahb, ahb_names), (pcic, pcic_names)] for name in names]
    declarations = '\n'.join(body[:body.index('{')].strip() + ';' for body in bodies)
    probe = extractor.function(ahb, 'ath11k_ahb_probe')
    assert probe.index('ath11k_ahb_config_irq(ab)') < probe.index('ath11k_core_init(ab)')
    assert 'goto err_irq_free' in probe and 'err_irq_free:' in probe
    with tempfile.TemporaryDirectory(prefix='nss-irq-stages-') as temp:
        source, binary = Path(temp) / 'test.c', Path(temp) / 'test'
        source.write_text(SHIM + declarations + '\n'.join(bodies) + CASES)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Werror',
                        '-Wno-unused-function', '-Wno-unused-parameter',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-g', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15)

if __name__ == '__main__':
    main()
