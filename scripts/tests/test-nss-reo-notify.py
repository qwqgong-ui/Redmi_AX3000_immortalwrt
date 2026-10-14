#!/usr/bin/env python3
"""Execute NSS REO notifications, WMI-only rebinding and cancellation under ASan/UBSan."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile
import importlib.util

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

base = load("reo_notify_fixture", "test-reo-queue-query.py")

WORK_SHIM = r'''
#define ATH11K_STATE_ON 1
#define ATH11K_STATE_RESTARTED 3
#define U16_MAX UINT16_MAX
#define NSS_CMN_RESPONSE_NOTIFY 5
#define NSS_WIFILI_TID_REOQ_SETUP_MSG 18
#define NSS_WIFILI_INTERNAL_INTERFACE 77
#define NSS_WIFILI_EXTERNAL_INTERFACE0 78
#define NSS_WIFILI_EXTERNAL_INTERFACE1 79
struct workqueue_struct {unsigned unused;};
struct ath11k_pdev {struct ath11k *ar;};
static bool hash_dead;
#define ath11k_err(...) ((void)0)
#define ATH11K_WIFILI_TARGET_TYPE_UNKNOWN 0
#define NSS_ETH_RX_INTERFACE 10
#define NSS_TX_SUCCESS 0
#define ENOTSUPP ENOTSUP
struct nss_cmn_msg {u16 version,len;u32 interface,response,type,error;u64 cb,app_data;};
struct nss_wifili_msg {struct nss_cmn_msg cm;union {struct {u32 tid;u16 peer_id;} reotidqmsg;} msg;};
static void init_work(struct work_struct *w,void (*fn)(struct work_struct *)){
 memset(w,0,sizeof(*w));w->fn=fn;pthread_mutex_init(&w->lock,NULL);pthread_cond_init(&w->done,NULL);
}
#define INIT_WORK(w,fn) init_work(w,fn)
static bool queue_work(struct workqueue_struct *q,struct work_struct *w){
 (void)q;pthread_mutex_lock(&w->lock);bool queued=!w->pending;w->pending=true;pthread_mutex_unlock(&w->lock);return queued;
}
static void cancel_work_sync(struct work_struct *w){
 pthread_mutex_lock(&w->lock);w->pending=false;while(w->running)pthread_cond_wait(&w->done,&w->lock);pthread_mutex_unlock(&w->lock);
}
static void *run_work(void *arg){
 struct work_struct *w=arg;pthread_mutex_lock(&w->lock);w->pending=false;w->running=true;pthread_mutex_unlock(&w->lock);
 w->fn(w);pthread_mutex_lock(&w->lock);w->running=false;pthread_cond_broadcast(&w->done);pthread_mutex_unlock(&w->lock);return NULL;
}
'''

CASES = r'''
static struct nss_wifili_msg notice(unsigned peer,unsigned tid){
 return (struct nss_wifili_msg){.cm={.len=8,.type=18,.interface=77,.response=5},
  .msg.reotidqmsg={.tid=tid,.peer_id=peer}};
}
static void notify_init(struct ath11k_base *ab,struct ath11k *ar,struct device *dev){
 init(ab,ar,dev);ar->state=ATH11K_STATE_ON;ab->nss.enabled=true;ab->nss.if_num=77;
 ath11k_nss_reoq_init(ab);ab->nss.registered=true;ath11k_nss_reoq_start(ab);
}
static struct ath11k_reo_queue *make_queue(struct ath11k *ar,struct ath11k_peer *p,unsigned tid){
 assert(!ath11k_peer_rx_tid_setup_instance(ar,p,p->addr,p->vdev_id,tid,64,733,HAL_PN_TYPE_NONE));
 return p->rx_tid[tid].reo_queue;
}
static void notify_cases(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;notify_init(&ab,&ar,&dev);
 struct ath11k_peer *p=peer_new(&ar);struct ath11k_reo_queue *q=make_queue(&ar,p,0);
 unsigned char saved[192];memcpy(saved,q->vaddr_unaligned,192);
 struct nss_wifili_msg m=notice(p->peer_id,0);unsigned calls=wmi_calls,submitted=ab.dp.reo_cmd_stats.submitted;
 ath11k_nss_reoq_receive(&ab,&m);ath11k_nss_reoq_receive(&ab,&m);
 assert(ab.nss.reoq_stats.received==2&&ab.nss.reoq_stats.notify==2&&ab.nss.reoq_stats.duplicate==1);
 assert(ab.nss.reoq_stats.pending==1&&atomic_load(&q->refs.value)==2&&atomic_load(&p->refs.value)==2);
 p->rx_tid[0].ba_win_sz=32; /* Negotiation changed while the immutable owner stayed current. */
 run_work(&ab.nss.reoq_work);
 assert(wmi_calls==calls+1&&last_wmi_addr==q->paddr&&last_wmi_window==32&&last_wmi_tid==0);
 assert(!memcmp(saved,q->vaddr_unaligned,192)&&ab.dp.reo_cmd_stats.submitted==submitted);
 assert(ab.nss.reoq_stats.sent==1&&!ab.nss.reoq_stats.pending&&!ab.nss.reoq_stats.running);
 assert(!ab.nss.reoq_stats.injected&&atomic_load(&q->refs.value)==1&&atomic_load(&p->refs.value)==1);
 m.cm.len=7;ath11k_nss_reoq_receive(&ab,&m);assert(ab.nss.reoq_stats.invalid==1);
 m=notice(p->peer_id,17);ath11k_nss_reoq_receive(&ab,&m);assert(ab.nss.reoq_stats.invalid==2);
 m=notice(p->peer_id,0);m.cm.response=0;ath11k_nss_reoq_receive(&ab,&m);assert(ab.nss.reoq_stats.invalid==3);
 m=notice(p->peer_id,0);ath11k_nss_reoq_receive(&ab,&m);ab.dp.reo_cmd_epoch++;
 run_work(&ab.nss.reoq_work);assert(wmi_calls==calls+1&&ab.nss.reoq_stats.closed==1);
 assert(!ath11k_nss_reoq_enqueue(&ab,p->peer_id,0,true));wmi_result=-ENOMEM;
 run_work(&ab.nss.reoq_work);wmi_result=0;
 assert(ab.nss.reoq_stats.failed==1&&q->phase==ATH11K_REO_QUEUE_PUBLISHED&&q->dma_live);
 assert(ab.nss.reoq_stats.injected==1&&ab.nss.reoq_stats.received==6);
 q->wmi_inflight=1;assert(!ath11k_nss_reoq_enqueue(&ab,p->peer_id,0,true));
 run_work(&ab.nss.reoq_work);q->wmi_inflight=0;assert(ab.nss.reoq_stats.busy==1);
 ath11k_nss_reoq_stop(&ab);assert(ath11k_nss_reoq_enqueue(&ab,p->peer_id,0,true)==-ESHUTDOWN);
 retire_peer_fixture(&ar,p);assert(dev.refs==1);
}
static void reuse_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;notify_init(&ab,&ar,&dev);
 struct ath11k_peer *old=peer_new(&ar);struct ath11k_reo_queue *q=make_queue(&ar,old,0);
 u64 generation=q->generation;unsigned calls=wmi_calls,freed=dma_frees;
 struct nss_wifili_msg m=notice(old->peer_id,0);ath11k_nss_reoq_receive(&ab,&m);
 retire_peer_fixture(&ar,old);assert(dma_frees==freed);
 struct ath11k_peer *fresh=peer_new(&ar);struct ath11k_reo_queue *current=make_queue(&ar,fresh,0);
 assert(current->generation>generation);calls=wmi_calls;
 run_work(&ab.nss.reoq_work);assert(wmi_calls==calls&&ab.nss.reoq_stats.stale==1&&dma_frees==freed+1);
 assert(current==fresh->rx_tid[0].reo_queue&&atomic_load(&current->refs.value)==1);
 ath11k_nss_reoq_stop(&ab);retire_peer_fixture(&ar,fresh);assert(dev.refs==1);
}
static void full_and_cancel_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;notify_init(&ab,&ar,&dev);
 struct ath11k_peer *p=peer_new(&ar),*second=peer_new(&ar);second->addr[5]=8;second->peer_id=43;
 for(unsigned tid=0;tid<17;tid++){make_queue(&ar,p,tid);make_queue(&ar,second,tid);}
 for(unsigned tid=0;tid<17;tid++)assert(!ath11k_nss_reoq_enqueue(&ab,42,tid,true));
 for(unsigned tid=0;tid<15;tid++)assert(!ath11k_nss_reoq_enqueue(&ab,43,tid,true));
 assert(ab.nss.reoq_stats.pending==32&&ath11k_nss_reoq_enqueue(&ab,43,15,true)==-ENOSPC);
 unsigned calls=wmi_calls;ath11k_nss_reoq_stop(&ab);
 assert(ab.nss.reoq_stats.cancelled==32&&!ab.nss.reoq_stats.pending&&wmi_calls==calls);
 assert(atomic_load(&p->refs.value)==1&&atomic_load(&second->refs.value)==1);
 retire_peer_fixture(&ar,p);retire_peer_fixture(&ar,second);assert(dev.refs==1);
}
static atomic_bool stop_done;
static void *stop_thread(void *arg){ath11k_nss_reoq_stop(arg);atomic_store(&stop_done,true);return NULL;}
static void close_wait_case(void){
 struct ath11k_base ab;struct ath11k ar;struct device dev;notify_init(&ab,&ar,&dev);
 struct ath11k_peer *p=peer_new(&ar);struct ath11k_reo_queue *q=make_queue(&ar,p,0);
 assert(!ath11k_nss_reoq_enqueue(&ab,p->peer_id,0,true));
 pthread_mutex_lock(&ar.conf_mutex);pthread_t worker,stop;unsigned calls=wmi_calls;
 assert(!pthread_create(&worker,NULL,run_work,&ab.nss.reoq_work));
 bool running=false;for(unsigned i=0;i<2000;i++){spin_lock_bh(&ab.base_lock);running=ab.nss.reoq_stats.running;spin_unlock_bh(&ab.base_lock);if(running)break;usleep(100);}assert(running);
 atomic_store(&stop_done,false);assert(!pthread_create(&stop,NULL,stop_thread,&ab));
 bool closed=false;for(unsigned i=0;i<2000;i++){spin_lock_bh(&ab.base_lock);closed=!ab.nss.reoq_admitting;spin_unlock_bh(&ab.base_lock);if(closed)break;usleep(100);}assert(closed&&!atomic_load(&stop_done));
 assert(atomic_load(&q->refs.value)==2);pthread_mutex_unlock(&ar.conf_mutex);
 pthread_join(worker,NULL);pthread_join(stop,NULL);
 assert(atomic_load(&stop_done)&&wmi_calls==calls&&!ab.nss.reoq_stats.pending&&!ab.nss.reoq_stats.running);
 assert(atomic_load(&q->refs.value)==1&&atomic_load(&p->refs.value)==1);
 retire_peer_fixture(&ar,p);assert(dev.refs==1);
}
static void driver_bounds_case(void){
 assert(sizeof(struct nss_cmn_msg)==40&&sizeof(((struct nss_wifili_msg*)0)->msg.reotidqmsg)==8);
 struct nss_wifili_msg *m=malloc(48);*m=notice(42,0);
 assert(nss_core_wifili_reoq_status_valid(&m->cm,48));
 for(unsigned n=0;n<48;n++)assert(!nss_core_wifili_reoq_status_valid(&m->cm,n));
 m->cm.len=9;assert(!nss_core_wifili_reoq_status_valid(&m->cm,48));
 m->cm.len=7;assert(!nss_core_wifili_reoq_status_valid(&m->cm,48));
 m->cm.len=8;m->cm.type=1;assert(nss_core_wifili_reoq_status_valid(&m->cm,40));free(m);
}
static unsigned failure_stage;
static void early_notice(struct ath11k_base *ab){struct nss_wifili_msg m=notice(42,0);ath11k_nss_reoq_receive(ab,&m);}
static unsigned ath11k_nss_get_target_type(struct ath11k_base *ab){(void)ab;return 1;}
static bool nss_cmn_get_nss_enabled(void){return true;}
static int ath11k_nss_init(struct ath11k_base *ab){ab->nss.registered=true;early_notice(ab);return 0;}
static int ath11k_nss_pdev_init(struct ath11k_base *ab,unsigned radio){(void)radio;early_notice(ab);return 0;}
static int ath11k_nss_start(struct ath11k_base *ab){early_notice(ab);return 0;}
static int ath11k_nss_stop(struct ath11k_base *ab){(void)ab;return 0;}
static int ath11k_nss_pdev_deinit(struct ath11k_base *ab,unsigned radio){(void)ab;(void)radio;return 0;}
static int ath11k_nss_reset(struct ath11k_base *ab){ath11k_nss_reoq_stop(ab);ab->nss.registered=false;return 0;}
static void ath11k_nss_tx_desc_mem_free(struct ath11k_base *ab){assert(!ab->nss.reoq_admitting);}
static void nss_unregister_wifili_radio_if(unsigned interface){(void)interface;}
static int nss_wifi_vdev_base_set_next_hop(void *ctx,unsigned interface){(void)ctx;(void)interface;return 0;}
static int ath11k_debugfs_pdev_create(struct ath11k_base *ab){(void)ab;return 0;}
static int ath11k_dp_pdev_alloc(struct ath11k_base *ab){(void)ab;return 0;}
static void ath11k_debugfs_pdev_destroy(struct ath11k_base *ab){(void)ab;}
static void ath11k_dp_pdev_free(struct ath11k_base *ab){assert(!ab->nss.reoq_admitting&&!ab->nss.reoq_stats.pending);}
static int ath11k_mac_register(struct ath11k_base *ab){
 assert(!ab->nss.reoq_admitting);hash_dead=true;early_notice(ab);
 if(failure_stage==1){early_notice(ab);return -ENOMEM;}hash_dead=false;return 0;
}
static int ath11k_thermal_register(struct ath11k_base *ab){early_notice(ab);return failure_stage==2?-EINVAL:0;}
static void ath11k_thermal_unregister(struct ath11k_base *ab){(void)ab;}
static int ath11k_spectral_init(struct ath11k_base *ab){early_notice(ab);return failure_stage==3?-EIO:0;}
static int ath11k_nss_teardown(struct ath11k_base *ab){ath11k_nss_reoq_stop(ab);ab->nss.registered=false;return 0;}
static void __ath11k_mac_unregister(struct ath11k *ar){assert(!ar->ab->nss.reoq_admitting);}
static void ath11k_mac_key_install_close(struct ath11k *ar){assert(!ar->ab->wmi_key_admitting);}
static void ath11k_peer_rhash_tbl_destroy(struct ath11k *ar){hash_dead=true;early_notice(ar->ab);}
'''

LIFECYCLE_CASES = r'''
static void initialization_failure_cases(void){
 for(failure_stage=0;failure_stage<4;failure_stage++){
  struct ath11k_base ab;struct ath11k ar;struct device dev;notify_init(&ab,&ar,&dev);
  struct ath11k_peer *p=peer_new(&ar);make_queue(&ar,p,0);ath11k_nss_reoq_stop(&ab);hash_dead=true;
  int ret=ath11k_core_pdev_create(&ab);
  assert((failure_stage==0)==(ret==0));assert(!ab.nss.reoq_stats.queued);
  if(!ret){assert(ab.nss.reoq_admitting);ath11k_mac_unregister(&ab);}
  assert(!ab.nss.reoq_admitting&&!ab.nss.reoq_stats.pending);
  retire_peer_fixture(&ar,p);assert(dev.refs==1);
 }
 hash_dead=false;
}
int main(void){
 assert(!base_main());
 driver_bounds_case();notify_cases();reuse_case();full_and_cancel_case();close_wait_case();
 initialization_failure_cases();
 assert(dma_allocations==dma_frees&&!warnings);
 puts("NSS REO notify: WMI-only rebind, immutable SSN/DMA, peer reuse, epoch close, bounded jobs, send failure, threaded cancellation and native MAC registration failure chains passed");
 return 0;
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backports", type=Path, required=True)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--draft", type=Path)
    args = parser.parse_args()
    source = args.backports / "drivers/net/wireless/ath/ath11k"
    draft = args.draft or source
    code = base.build_fixture(source, draft).replace("int main(void)", "static int base_main(void)")
    nss_header = (draft / "nss.h").read_text()
    declarations = "\n".join(re.findall(r"(?m)^#define ATH11K_NSS_(?:REOQ_JOBS|MAX_NUMBER_OF_PAGE) .*$", nss_header))
    declarations += "\n" + "\n".join(base.types.declaration(nss_header, "struct", n) for n in
                                     ("ath11k_nss_reoq_job", "ath11k_nss_reoq_stats", "ath11k_soc_nss"))
    code = code.replace("struct work_struct {void (*fn)(struct work_struct *);};",
                        "struct work_struct {void (*fn)(struct work_struct *);pthread_mutex_t lock;pthread_cond_t done;bool pending,running;};")
    code = code.replace("struct ath11k {struct ath11k_base *ab;", "struct ath11k {unsigned state;void *rhead_peer_id;unsigned rhash_peer_id_param;struct {void *ctx;int if_num;} nss;struct ath11k_base *ab;")
    code = code.replace("ar->ab=ab;ab->num_radios=1;", "ar->ab=ab;ar->rhead_peer_id=ar;ab->num_radios=1;")
    code = code.replace("struct {bool ownership_uncertain;struct list_head retained_host_peers;} nss;",
                        "struct ath11k_soc_nss nss;struct workqueue_struct *workqueue_aux;")
    code = code.replace("struct {struct ath11k *ar;} pdevs[1]", "struct ath11k_pdev pdevs[1]")
    marker = "struct ath11k_base {struct device *dev;"
    code = code.replace(marker, WORK_SHIM + declarations + "\n" + marker + "bool wmi_key_admitting;")
    code = code.replace("static unsigned wmi_calls;", "static unsigned wmi_calls;static dma_addr_t last_wmi_addr;static unsigned last_wmi_window,last_wmi_tid;")
    code = code.replace("(void)addr;(void)tid;(void)enable;(void)window;wmi_calls++;",
                        "last_wmi_addr=addr;last_wmi_window=window;last_wmi_tid=tid;assert(enable==1);wmi_calls++;")
    native_lookup = base.extract.function((source / "core.h").read_text(), "ath11k_peer_find_by_id")
    hash_shim = r'''
static struct ath11k_peer *rhashtable_lookup_fast(void *table,const void *key,unsigned params){
 (void)params;assert(!hash_dead);struct ath11k *ar=table;struct ath11k_peer *p;lockdep_assert_held(&ar->ab->base_lock);
 list_for_each_entry(p,&ar->peers,list)if(p->peer_id==*(const int *)key)return p;return NULL;
}
'''
    functions = hash_shim + native_lookup + base.extract.function((draft / "dp_rx.c").read_text(), "ath11k_dp_reo_queue_rebind")
    functions += "\n".join(base.extract.function((draft / "nss.c").read_text(), n) for n in
                          ("ath11k_nss_reoq_job_put", "ath11k_nss_reoq_work", "ath11k_nss_reoq_init", "ath11k_nss_reoq_start",
                           "ath11k_nss_reoq_stop", "ath11k_nss_reoq_enqueue", "ath11k_nss_reoq_receive"))
    functions += base.extract.function((args.driver / "nss_core.c").read_text(), "nss_core_wifili_reoq_status_valid")
    lifecycle = base.extract.function((draft / "nss.c").read_text(), "ath11k_nss_setup")
    lifecycle += base.extract.function((draft / "mac.c").read_text(), "ath11k_mac_unregister")
    lifecycle += base.extract.function((draft / "core.c").read_text(), "ath11k_core_pdev_create")
    code += "\n" + functions + "\n" + CASES + "\n" + lifecycle + "\n" + LIFECYCLE_CASES
    with tempfile.TemporaryDirectory(prefix="nss-reo-notify-") as directory:
        root = Path(directory)
        c, binary = root / "test.c", root / "test"
        c.write_text(code)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-pthread", "-Wall", "-Werror",
                        "-Wno-unused-function", "-Wno-misleading-indentation", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", str(c), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=25, env=dict(os.environ,
                       ASAN_OPTIONS="detect_leaks=1", UBSAN_OPTIONS="halt_on_error=1"))

if __name__ == "__main__":
    main()
