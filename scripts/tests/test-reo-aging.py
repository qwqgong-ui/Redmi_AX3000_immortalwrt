#!/usr/bin/env python3
"""Execute guarded REO aging MMIO and its debugfs parser under sanitizers."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location("query_fixture", Path(__file__).with_name("test-reo-queue-query.py"))
query = importlib.util.module_from_spec(spec)
spec.loader.exec_module(query)

SHIM = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/types.h>
typedef uint32_t u32;typedef uint64_t u64;typedef pthread_mutex_t spinlock_t;
#define __user
#define READ_ONCE(x) (x)
#define ATH11K_FLAG_CRASH_FLUSH 0
#define ATH11K_FLAG_QMI_FAIL 1
#define ATH11K_FLAG_UNREGISTERING 2
#define ATH11K_FLAG_RECOVERY 3
#define ATH11K_FLAG_REGISTERED 4
#define ATH11K_AHB_RECOVERY_TIMEOUT 20
#define ath11k_warn(...) ((void)0)
static bool suspend_config;
#define IS_ENABLED(x) suspend_config
#define test_bit(n,p) (!!(*(p)&(1ul<<(n))))
#define set_bit(n,p) (*(p)|=1ul<<(n))
#define spin_lock_bh(p) assert(!pthread_mutex_lock(p))
#define spin_unlock_bh(p) assert(!pthread_mutex_unlock(p))
#define mutex_lock(p) spin_lock_bh(p)
#define mutex_unlock(p) spin_unlock_bh(p)
#define lockdep_assert_held(p) do {int rc=pthread_mutex_trylock(p);assert(rc==EBUSY);} while(0)
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
#define scnprintf snprintf
struct file {void *private_data;};
static bool allocation_fail;
static unsigned allocated,freed;
static void *memdup_user_nul(const void *p,size_t n){
 if(allocation_fail)return (void *)(intptr_t)-ENOMEM;
 char *b=malloc(n+1);assert(b);memcpy(b,p,n);b[n]=0;allocated++;return b;
}
static void kfree(void *p){assert(p&&!IS_ERR(p));free(p);freed++;}
static int kstrtou64(const char *p,unsigned base,u64 *value){
 if(!*p||*p=='-')return -EINVAL;errno=0;char *end;unsigned long long v=strtoull(p,&end,base);
 if(errno==ERANGE)return -ERANGE;if(*end)return -EINVAL;*value=v;return 0;
}
static int kstrtou32(const char *p,unsigned base,u32 *value){
 u64 v;int ret=kstrtou64(p,base,&v);if(ret)return ret;if(v>UINT32_MAX)return -ERANGE;*value=v;return 0;
}
static ssize_t simple_read_from_buffer(void *out,size_t count,loff_t *pos,const void *buf,size_t len){
 if(*pos<0)return -EINVAL;if((size_t)*pos>=len)return 0;
 if(count>len-(size_t)*pos)count=len-(size_t)*pos;memcpy(out,(const char *)buf+*pos,count);*pos+=count;return count;
}
'''

STRUCTURES = r'''
struct work_struct {unsigned id;};
struct ath11k_dp {spinlock_t reo_cmd_lock;bool reo_cmd_accepting;u64 reo_cmd_epoch;};
struct ath11k_base {spinlock_t base_lock;struct ath11k_dp dp;unsigned long dev_flags;
 struct {bool ownership_uncertain;} nss;struct {const struct ath11k_hw_regs *regs;bool supports_suspend;} hw_params;
 struct {bool event_work_initialized;struct work_struct event_work;} qmi;
 struct work_struct restart_work,reset_work,dump_work,wmi_ast_work;unsigned driver_recovery;};
struct ath11k {struct ath11k_base *ab;spinlock_t conf_mutex;enum ath11k_state state;};
struct platform_device {struct ath11k_base *ab;};struct pci_dev {struct ath11k_base *ab;};struct ath11k_pci {unsigned unused;};
static struct ath11k_pci pci_private;
static bool powered=true,nss_stopped;static unsigned cancellations,destructions,power_downs;
static struct ath11k_base *platform_get_drvdata(struct platform_device *p){return p->ab;}
static struct ath11k_base *pci_get_drvdata(struct pci_dev *p){return p->ab;}
static struct ath11k_pci *ath11k_pci_priv(struct ath11k_base *ab){(void)ab;return &pci_private;}
static void cancel_work_sync(struct work_struct *w){assert(w->id<5);cancellations|=1u<<w->id;}
static unsigned wait_for_completion_timeout(unsigned *completion,unsigned timeout){(void)completion;(void)timeout;return 1;}
static void ath11k_nss_reoq_stop(struct ath11k_base *ab){spin_lock_bh(&ab->base_lock);nss_stopped=true;spin_unlock_bh(&ab->base_lock);}
static void power_down(struct ath11k_base *ab,bool force){
 assert(!force&&nss_stopped&&!ab->dp.reo_cmd_accepting&&cancellations==31);
 assert(!pthread_mutex_trylock(&ab->dp.reo_cmd_lock));assert(!pthread_mutex_unlock(&ab->dp.reo_cmd_lock));
 powered=false;power_downs++;
}
static void ath11k_ahb_power_down(struct ath11k_base *ab,bool force){power_down(ab,force);}
static void ath11k_pci_power_down(struct ath11k_base *ab,bool force){power_down(ab,force);}
static void ath11k_debugfs_soc_destroy(struct ath11k_base *ab){assert(!powered&&!ab->dp.reo_cmd_accepting);destructions++;}
static void ath11k_qmi_deinit_service(struct ath11k_base *ab){assert(!powered&&!ab->dp.reo_cmd_accepting);}
static void ath11k_core_pm_notifier_unregister(struct ath11k_base *ab){(void)ab;}
static void ath11k_fw_destroy(struct ath11k_base *ab){assert(nss_stopped&&!ab->dp.reo_cmd_accepting);}
static void ath11k_ahb_free_resources(struct ath11k_base *ab){assert(nss_stopped&&!ab->dp.reo_cmd_accepting);powered=false;}
static void ath11k_core_deinit(struct ath11k_base *ab){(void)ab;assert(!"Unexpected normal deinit in QMI failure case");}
static void ath11k_pci_set_irq_affinity_hint(struct ath11k_pci *p,void *v){(void)p;assert(!v);}
static void ath11k_mhi_unregister(struct ath11k_pci *p){(void)p;assert(!powered);}
static void ath11k_pcic_free_irq(struct ath11k_base *ab){assert(!powered&&!ab->dp.reo_cmd_accepting);}
static void ath11k_pci_free_msi(struct ath11k_pci *p){(void)p;assert(!powered);}
static void ath11k_pci_free_region(struct ath11k_pci *p){(void)p;assert(!powered);}
static void ath11k_hal_srng_deinit(struct ath11k_base *ab){assert(!powered&&!ab->dp.reo_cmd_accepting);}
static void ath11k_ce_free_pipes(struct ath11k_base *ab){assert(!powered&&!ab->dp.reo_cmd_accepting);}
static void ath11k_core_free(struct ath11k_base *ab){assert(!powered&&!ab->dp.reo_cmd_accepting);}
static const struct ath11k_hw_regs regs={.hal_reo1_aging_thresh_ix_0=0x564,
 .hal_reo1_aging_thresh_ix_1=0x568,.hal_reo1_aging_thresh_ix_2=0x56c,.hal_reo1_aging_thresh_ix_3=0x570};
static struct ath11k *active_ar;
static u32 hardware[4];static unsigned reads,writes;static bool fail_readback,block_write,write_entered;
static pthread_mutex_t barrier=PTHREAD_MUTEX_INITIALIZER;static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static void mmio_locks(struct ath11k_base *ab){
 assert(ab==active_ar->ab&&ab->hw_params.regs==&regs);lockdep_assert_held(&active_ar->conf_mutex);
 lockdep_assert_held(&ab->base_lock);lockdep_assert_held(&ab->dp.reo_cmd_lock);
 assert(ab->dp.reo_cmd_accepting&&powered);
}
static unsigned index_of(u32 address){u32 off=address-HAL_SEQ_WCSS_UMAC_REO_REG;
 assert(off>=0x564&&off<=0x570&&!((off-0x564)%4));return (off-0x564)/4;}
static u32 ath11k_hif_read32(struct ath11k_base *ab,u32 address){
 mmio_locks(ab);reads++;return hardware[index_of(address)]^(fail_readback&&writes?64:0);
}
static void ath11k_hif_write32(struct ath11k_base *ab,u32 address,u32 value){
 mmio_locks(ab);unsigned i=index_of(address);assert(value>=40000&&value<=200000);
 assert(!pthread_mutex_lock(&barrier));write_entered=true;assert(!pthread_cond_broadcast(&changed));
 while(block_write)assert(!pthread_cond_wait(&changed,&barrier));assert(!pthread_mutex_unlock(&barrier));
 hardware[i]=value;writes++;
}
'''

CASES = r'''
static struct ath11k_base ab;static struct ath11k ar;
static const u32 baseline[4]={40000,40000,40000,40000},long_be[4]={100000,40000,40000,40000};
static void reset(void){
 ar.state=ATH11K_STATE_ON;ab.hw_params.regs=&regs;ab.dp.reo_cmd_epoch=1;ab.dp.reo_cmd_accepting=true;
 ab.hw_params.supports_suspend=false;suspend_config=false;powered=true;nss_stopped=false;cancellations=destructions=power_downs=0;
 ab.qmi.event_work_initialized=true;ab.qmi.event_work.id=0;ab.reset_work.id=1;ab.dump_work.id=2;ab.restart_work.id=3;ab.wmi_ast_work.id=4;
 ab.dev_flags=0;ab.nss.ownership_uncertain=false;memcpy(hardware,baseline,sizeof(hardware));
 reads=writes=0;fail_readback=block_write=write_entered=false;
}
static int replace(u64 epoch,const u32 *old,const u32 *next){
 mutex_lock(&ar.conf_mutex);int ret=ath11k_dp_reo_aging_replace(&ar,epoch,old,next);mutex_unlock(&ar.conf_mutex);return ret;
}
static int snapshot(u64 *epoch,u32 *values){
 mutex_lock(&ar.conf_mutex);int ret=ath11k_dp_reo_aging_read(&ar,epoch,values);mutex_unlock(&ar.conf_mutex);return ret;
}
static ssize_t request(const char *text,size_t n){
 struct file f={.private_data=&ar};loff_t pos=0;return ath11k_debugfs_reo_aging_write(&f,text,n,&pos);
}
static atomic_bool close_started,close_done;
static void *writer(void *unused){(void)unused;assert(!replace(1,baseline,long_be));return NULL;}
static void *closer(void *unused){(void)unused;atomic_store(&close_started,true);
 ath11k_dp_reo_cmd_close(&ab.dp);atomic_store(&close_done,true);return NULL;}
static bool use_pci;
static void *failed_remove(void *unused){
 (void)unused;set_bit(ATH11K_FLAG_QMI_FAIL,&ab.dev_flags);atomic_store(&close_started,true);
 if(use_pci){struct pci_dev dev={.ab=&ab};ath11k_pci_remove(&dev);}
 else{struct platform_device dev={.ab=&ab};ath11k_ahb_remove(&dev);}
 atomic_store(&close_done,true);return NULL;
}
int main(void){
 memset(&ab,0,sizeof(ab));memset(&ar,0,sizeof(ar));ar.ab=&ab;active_ar=&ar;
 assert(!pthread_mutex_init(&ar.conf_mutex,NULL));assert(!pthread_mutex_init(&ab.base_lock,NULL));assert(!pthread_mutex_init(&ab.dp.reo_cmd_lock,NULL));
 reset();u64 epoch=0;u32 got[4];assert(!snapshot(&epoch,got)&&epoch==1&&!memcmp(got,baseline,sizeof(got))&&reads==4);
 assert(!replace(epoch,baseline,long_be)&&writes==1&&hardware[0]==100000&&hardware[3]==40000);
 assert(!replace(epoch,long_be,baseline)&&writes==2&&!memcmp(hardware,baseline,sizeof(hardware)));
 reset();hardware[2]=100000;assert(replace(1,baseline,long_be)==-EAGAIN&&writes==0);
 for(unsigned gate=0;gate<6;gate++){
  reset();if(gate==0)ab.dp.reo_cmd_accepting=false;if(gate==1)ab.dp.reo_cmd_epoch=2;
  if(gate==2)ab.nss.ownership_uncertain=true;if(gate==3)ab.dev_flags=1;
  if(gate==4)ab.dev_flags=1ul<<ATH11K_FLAG_QMI_FAIL;if(gate==5)ab.dev_flags=1ul<<ATH11K_FLAG_UNREGISTERING;
  assert(replace(1,baseline,long_be)==-ESHUTDOWN&&reads==0&&writes==0);
  if(gate!=1)assert(snapshot(&epoch,got)==-ESHUTDOWN&&reads==0);
 }
 reset();ar.state=ATH11K_STATE_OFF;ab.hw_params.regs=NULL;
 assert(replace(1,baseline,long_be)==-ENETDOWN&&snapshot(&epoch,got)==-ENETDOWN&&!reads&&!writes);
 for(unsigned pm=0;pm<2;pm++){reset();ab.hw_params.regs=NULL;
  if(pm==0)ab.hw_params.supports_suspend=true;else suspend_config=true;
  assert(replace(1,baseline,long_be)==-EOPNOTSUPP&&snapshot(&epoch,got)==-EOPNOTSUPP&&!reads&&!writes);
 }
 for(unsigned value=0;value<3;value++){
  reset();u32 bad[4]={40000,40000,40000,40000};bad[0]=value==0?0:value==1?39999:200001;
  assert(replace(1,baseline,bad)==-EINVAL&&!reads&&!writes);
 }
 reset();fail_readback=true;assert(replace(1,baseline,long_be)==-EIO&&writes==1);
 fail_readback=false;assert(!snapshot(&epoch,got));assert(!replace(epoch,got,baseline));
 reset();const char *good="1 40000 40000 40000 40000 100000 40000 40000 40000";
 assert(request(good,strlen(good))==(ssize_t)strlen(good)&&writes==1);
 struct file f={.private_data=&ar};char out[128]={0};loff_t pos=0;
 assert(ath11k_debugfs_reo_aging_read(&f,out,sizeof(out)-1,&pos)>0&&strstr(out,"epoch: 1")&&strstr(out,"100000 40000 40000 40000"));
 const char *bad[]={"", "1 40000", "1 40000 40000 40000 40000 0 40000 40000 40000",
  "1 40000 40000 40000 40000 100000 40000 40000 40000 x",
  "-1 40000 40000 40000 40000 100000 40000 40000 40000",
  "1 40000 40000 40000 40000 4294967296 40000 40000 40000"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++){reset();assert(request(bad[i],strlen(bad[i]))<0&&!reads&&!writes);}
 char embedded[192];snprintf(embedded,sizeof(embedded),"%s",good);embedded[strlen(good)+1]='x';
 reset();assert(request(embedded,strlen(good)+2)==-EINVAL&&!reads&&!writes);
 reset();allocation_fail=true;assert(request(good,strlen(good))==-ENOMEM&&!reads&&!writes);allocation_fail=false;
 assert(allocated==freed);
 reset();block_write=true;atomic_store(&close_started,false);atomic_store(&close_done,false);pthread_t w,c;
 assert(!pthread_create(&w,NULL,writer,NULL));assert(!pthread_mutex_lock(&barrier));
 while(!write_entered)assert(!pthread_cond_wait(&changed,&barrier));assert(!pthread_mutex_unlock(&barrier));
 assert(!pthread_create(&c,NULL,closer,NULL));while(!atomic_load(&close_started)){}
 assert(pthread_mutex_trylock(&ab.dp.reo_cmd_lock)==EBUSY&&!atomic_load(&close_done));
 assert(!pthread_mutex_lock(&barrier));block_write=false;assert(!pthread_cond_broadcast(&changed));assert(!pthread_mutex_unlock(&barrier));
 assert(!pthread_join(w,NULL)&&!pthread_join(c,NULL)&&atomic_load(&close_done)&&ab.dp.reo_cmd_epoch==2);
 unsigned old_reads=reads,old_writes=writes;assert(replace(1,long_be,baseline)==-ESHUTDOWN&&reads==old_reads&&writes==old_writes);
 ab.dp.reo_cmd_accepting=true;assert(replace(1,long_be,baseline)==-ESHUTDOWN&&reads==old_reads&&writes==old_writes);
 for(unsigned bus=0;bus<2;bus++){
  reset();use_pci=bus;block_write=true;atomic_store(&close_started,false);atomic_store(&close_done,false);
  assert(!pthread_create(&w,NULL,writer,NULL));assert(!pthread_mutex_lock(&barrier));
  while(!write_entered)assert(!pthread_cond_wait(&changed,&barrier));assert(!pthread_mutex_unlock(&barrier));
  assert(!pthread_create(&c,NULL,failed_remove,NULL));while(!atomic_load(&close_started)){}
  assert(!atomic_load(&close_done)&&powered);
  assert(!pthread_mutex_lock(&barrier));block_write=false;assert(!pthread_cond_broadcast(&changed));assert(!pthread_mutex_unlock(&barrier));
  assert(!pthread_join(w,NULL)&&!pthread_join(c,NULL)&&!powered&&power_downs==1&&destructions==1);
  old_reads=reads;old_writes=writes;assert(snapshot(&epoch,got)==-ESHUTDOWN&&reads==old_reads&&writes==old_writes);
 }
 reset();struct pci_dev pcidev={.ab=&ab};ath11k_pci_shutdown(&pcidev);assert(!powered&&power_downs==1&&!ab.dp.reo_cmd_accepting);
 reset();struct platform_device ahbdev={.ab=&ab};ath11k_ahb_shutdown(&ahbdev);assert(!powered&&!ab.dp.reo_cmd_accepting&&nss_stopped);
 assert(!pthread_mutex_destroy(&ar.conf_mutex)&&!pthread_mutex_destroy(&ab.base_lock)&&!pthread_mutex_destroy(&ab.dp.reo_cmd_lock));
 puts("REO aging: bounded CAS/parser, PM/OFF/crash/QMI/stale gates, concurrent close and real AHB/PCI failed-remove/shutdown ordering passed");return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backports", type=Path, required=True)
    p.add_argument("--draft", type=Path)
    args = p.parse_args()
    source = args.backports / "drivers/net/wireless/ath/ath11k"
    draft = args.draft or source
    def read(name):
        path = draft / name
        return (path if path.exists() else source / name).read_text()
    hal = read("hal.h")
    macros = "\n".join(re.findall(r"(?m)^#define[ \t]+(?:HAL_SEQ_WCSS_UMAC_REO_REG|HAL_DEFAULT_REO_TIMEOUT_USEC)[ \t]+[^\n]+", hal))
    decl = query.types.declaration(read("core.h"), "enum", "ath11k_state")
    decl += query.types.declaration(read("hw.h"), "struct", "ath11k_hw_regs")
    tx, debug = read("dp_tx.c"), read("debugfs.c")
    functions = "\n".join(query.extract.function(tx, name) for name in
                          ("ath11k_dp_reo_aging_read_locked", "ath11k_dp_reo_aging_read", "ath11k_dp_reo_aging_replace"))
    functions += query.extract.function(read("dp.h"), "ath11k_dp_reo_cmd_close")
    functions += "\n".join(query.extract.function(debug, name) for name in
                            ("ath11k_debugfs_reo_aging_read", "ath11k_debugfs_reo_aging_write"))
    for name in ("ath11k_ahb_remove_prepare", "ath11k_ahb_remove", "ath11k_ahb_shutdown"):
        functions += query.extract.function(read("ahb.c"), name)
    for name in ("ath11k_pci_remove_prepare", "ath11k_pci_remove", "ath11k_pci_shutdown"):
        functions += query.extract.function(read("pci.c"), name)
    code = SHIM + macros + "\n" + decl + STRUCTURES + functions + CASES
    with tempfile.TemporaryDirectory(prefix="reo-aging-") as directory:
        root = Path(directory)
        c, binary = root / "test.c", root / "test"
        c.write_text(code)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-pthread", "-Wall", "-Werror",
                        "-Wno-unused-function", "-Wno-misleading-indentation", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", str(c), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=20,
                       env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1", UBSAN_OPTIONS="halt_on_error=1"))


if __name__ == "__main__":
    main()
