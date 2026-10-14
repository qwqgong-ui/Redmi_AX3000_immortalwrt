#!/usr/bin/env python3
"""Execute PROJECT control, firmware geometry and debugfs snapshot paths."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "project_functions", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <ctype.h>
#include <stdarg.h>
#include <pthread.h>
#include <stdatomic.h>
typedef uint64_t nss_ptr_t;
typedef int nss_tx_status_t;
#define __user
#define compat_const const
#define NSS_CORE_MAX 2
#define NSS_MAX_NET_INTERFACES 512
#define NSS_PROJECT_INTERFACE 204
#define NSS_TX_SUCCESS 0
#define NSS_TX_FAILURE 1
#define NSS_TX_FAILURE_NOT_READY 2
#define NSS_TX_FAILURE_BAD_PARAM 3
#define NSS_TX_FAILURE_NOT_SUPPORTED 4
#define NSS_CORE_STATUS_SUCCESS 0
#define NSS_NBUF_PAYLOAD_SIZE 2048
#define U32_MAX UINT32_MAX
#define GFP_ATOMIC 0
#define GFP_KERNEL 1
#define READ_ONCE(x) (x)
#define unlikely(x) (x)
#define NSS_VERIFY_CTX_MAGIC(x) assert(x)
#define nss_warning(...) ((void)0)
#define nss_info(...) ((void)0)
#define nss_core_log_msg_failures(...) ((void)0)
#define module_param_array(...)
#define MODULE_PARM_DESC(...)
#define LINUX_VERSION_CODE 396288
#define KERNEL_VERSION(a,b,c) (((a)<<16)+((b)<<8)+(c))
#define NSS_STATS_MAX_STR_LENGTH 96
#define NSS_STATS_SINGLE_CORE -1
#define NSS_STATS_BANNER_MAX_LENGTH 80
#define NSS_STATS_BANNER_SPACES 12
#define NSS_STATS_NODE_NAME_MAX 24
enum nss_cmn_response { NSS_CMN_RESPONSE_ACK=0, NSS_CMN_RESPONSE_EMSG=1, NSS_CMN_RESPONSE_NOTIFY=5 };
struct nss_cmn_msg { uint32_t version,interface,type,len,response,error; nss_ptr_t cb,app_data; };
struct nss_ctx_instance;
struct list_head { struct list_head *next,*prev; };
#define LIST_HEAD(n) struct list_head n={&n,&n}
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_entry(p,t,m) container_of(p,t,m)
#define list_for_each_entry(p,h,m) for(p=list_entry((h)->next,__typeof__(*p),m);&(p)->m!=(h);p=list_entry((p)->m.next,__typeof__(*p),m))
#define list_for_each_entry_safe(p,n,h,m) for(p=list_entry((h)->next,__typeof__(*p),m),n=list_entry((p)->m.next,__typeof__(*p),m);&(p)->m!=(h);p=n,n=list_entry((n)->m.next,__typeof__(*n),m))
static void list_add_tail(struct list_head *n,struct list_head *h) { n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n; }
static void list_del(struct list_head *n) { n->prev->next=n->next;n->next->prev=n->prev; }
typedef struct { _Atomic uint64_t value; } atomic64_t;
#define ATOMIC64_INIT(x) {.value=x}
static uint64_t atomic64_inc_return(atomic64_t *v) { return atomic_fetch_add(&v->value,1)+1; }
#define DEFINE_SPINLOCK(n) pthread_mutex_t n=PTHREAD_MUTEX_INITIALIZER
#define DEFINE_MUTEX(n) pthread_mutex_t n=PTHREAD_MUTEX_INITIALIZER
#define spin_lock_bh(p) assert(pthread_mutex_lock(p)==0)
#define spin_unlock_bh(p) assert(pthread_mutex_unlock(p)==0)
#define mutex_lock(p) spin_lock_bh(p)
#define mutex_unlock(p) spin_unlock_bh(p)
static void rcu_read_lock_bh(void) {}
static void rcu_read_unlock_bh(void) {}
static void synchronize_net(void) {}
struct completion { unsigned done; };
static void init_completion(struct completion *c) { c->done=0; }
static void complete(struct completion *c) { c->done++; }
static bool completion_done(struct completion *c) { return c->done!=0; }
static unsigned msecs_to_jiffies(unsigned v) { return v; }
static void reply_to_last(void);
static bool boundary_ack;
static unsigned long wait_for_completion_timeout(struct completion *c,unsigned timeout) {
 (void)timeout;reply_to_last();if(boundary_ack)return 0;
 if(!c->done)return 0;c->done--;return 1; /* Kernel wait consumes completion. */
}
static unsigned live_allocations,allocations,zero_allocations;
static int fail_irq_slot=-1;
static bool fail_table;
static void (*allocation_hook)(void);
static void *kzalloc(size_t size,int flags) {
 (void)flags;allocations++;
 if(allocation_hook){void(*hook)(void)=allocation_hook;allocation_hook=NULL;hook();}
 if(!size){zero_allocations++;return (void *)16;} /* Linux ZERO_SIZE_PTR. */
 if(fail_table&&size==12*sizeof(void *)){fail_table=false;return NULL;}
 if(size==128*40&&fail_irq_slot>=0){if(!fail_irq_slot--){fail_irq_slot=-1;return NULL;}}
 void *p=calloc(1,size);assert(p);live_allocations++;return p;
}
static void *kcalloc(size_t n,size_t size,int flags) { assert(!size||n<=SIZE_MAX/size);return kzalloc(n*size,flags); }
#define kvcalloc kcalloc
#define kvzalloc kzalloc
static void kfree(void *p) { if(p){assert(p!=(void *)16&&live_allocations);live_allocations--;free(p);} }
#define kvfree kfree
static unsigned nss_cmn_get_msg_len(struct nss_cmn_msg *cm) { return cm->len+sizeof(*cm); }
static void nss_cmn_msg_init(struct nss_cmn_msg *cm,uint32_t ifnum,uint32_t type,uint32_t len,void *cb,void *data) { cm->version=1;cm->interface=ifnum;cm->type=type;cm->len=len;cm->cb=(uintptr_t)cb;cm->app_data=(uintptr_t)data; }
struct ctl_table;
struct ctl_table_header { int unused; };
struct ctl_table { const char *procname;void *data;int maxlen;unsigned mode;int (*proc_handler)(const struct ctl_table *,int,void *,size_t *,loff_t *);void *extra1,*extra2; };
static int proc_dointvec(const struct ctl_table *ctl,int write,void *buf,size_t *len,loff_t *pos) { (void)pos;if(write){int value;if(sscanf(buf,"%d",&value)!=1)return -EINVAL;*(int *)ctl->data=value;}else{int n=snprintf(buf,*len,"%d\n",*(int *)ctl->data);*len=n;}return 0; }
static int proc_dointvec_minmax(const struct ctl_table *ctl,int write,void *buf,size_t *len,loff_t *pos) { int value;if(write&&(sscanf(buf,"%d",&value)!=1||value<*(int *)ctl->extra1||value>*(int *)ctl->extra2))return -EINVAL;return proc_dointvec(ctl,write,buf,len,pos); }
static struct ctl_table_header fake_header;
static struct ctl_table_header *register_sysctl(const char *path,struct ctl_table *table) { (void)path;(void)table;return &fake_header; }
static void unregister_sysctl_table(struct ctl_table_header *h) { (void)h; }
static int scnprintf(char *to,size_t size,const char *fmt,...) { va_list ap;va_start(ap,fmt);int n=vsnprintf(to,size,fmt,ap);va_end(ap);return size?(n<(int)size?n:(int)size-1):0; }
static size_t strscpy(char *to,const char *from,size_t size) { if(!size)return 0;snprintf(to,size,"%s",from);return strlen(to); }
static ssize_t simple_read_from_buffer(char *to,size_t count,loff_t *pos,const char *from,size_t size) { if((size_t)*pos>=size)return 0;size_t n=size-*pos;if(n>count)n=count;memcpy(to,from+*pos,n);*pos+=n;return n; }
static bool nss_core_is_mq_enabled(void) { return true; }
static unsigned nss_core_register_handler(struct nss_ctx_instance *ctx,unsigned ifnum,void (*cb)(struct nss_ctx_instance *,struct nss_cmn_msg *,void *),void *data) { (void)ctx;(void)ifnum;(void)cb;(void)data;return 0; }
static unsigned nss_core_unregister_handler(struct nss_ctx_instance *ctx,unsigned ifnum) { (void)ctx;(void)ifnum;return 0; }
'''

STRUCTURES = r'''
struct nss_worker_thread_stats { struct nss_project_irq_stats *irq_stats; };
struct nss_ctx_instance { unsigned id;uint32_t worker_thread_count,irq_count;struct nss_worker_thread_stats *wt_stats; };
static struct { unsigned num_nss;pthread_mutex_t stats_lock;struct nss_ctx_instance nss[NSS_CORE_MAX]; } nss_top_main={.num_nss=2,.stats_lock=PTHREAD_MUTEX_INITIALIZER};
struct nss_stats_data { struct nss_ctx_instance *nss_ctx; };
struct file { void *private_data; };
enum plan { ACK,TXFAIL,TIMEOUT,NACK,SHORT_ACK,BAD_COUNT,BAD_ECHO };
static enum plan plan[128];
static struct nss_project_msg wire[128];
static struct nss_ctx_instance *wire_ctx[128];
static unsigned submissions;
static nss_tx_status_t nss_core_send_cmd(struct nss_ctx_instance *ctx,void *msg,unsigned size,unsigned payload) {
 assert(size==sizeof(struct nss_project_msg)&&payload==NSS_NBUF_PAYLOAD_SIZE&&submissions<128);
 wire[submissions]=*(struct nss_project_msg *)msg;wire_ctx[submissions]=ctx;
 return plan[submissions++]==TXFAIL?NSS_TX_FAILURE:NSS_TX_SUCCESS;
}
'''

CASES = r'''
static void deliver(unsigned index,enum plan action) {
 struct nss_project_msg msg=wire[index];
 msg.cm.response=action==NACK?NSS_CMN_RESPONSE_EMSG:NSS_CMN_RESPONSE_ACK;
 msg.cm.error=action==NACK?2:0;
 msg.msg.wt_stats_enable.worker_thread_count=action==BAD_COUNT?13:12;
 msg.msg.wt_stats_enable.irq_count=128;
 if(action==SHORT_ACK)msg.cm.len=0;
 if(action==BAD_ECHO)msg.msg.wt_stats_enable.enable=!msg.msg.wt_stats_enable.enable;
 nss_project_msg_handler(wire_ctx[index],&msg.cm,NULL);
}
static void reply_to_last(void) { unsigned i=submissions-1;if(plan[i]!=TIMEOUT)deliver(i,plan[i]); }
static void fresh(void) {
 nss_project_unregister_sysctl();assert(!live_allocations);
 for(unsigned i=0;i<2;i++){nss_top_main.nss[i].id=i;nss_control_init_core(&nss_top_main.nss[i]);nss_project_register_handler(&nss_top_main.nss[i]);nss_project_wt_state[i]=0;}
 nss_project_wt_stats_enable=0;submissions=allocations=zero_allocations=0;memset(plan,0,sizeof(plan));allocation_hook=NULL;fail_table=boundary_ack=false;fail_irq_slot=-1;
}
static int write_value(int v) { char buf[32];snprintf(buf,sizeof(buf),"%d",v);size_t n=strlen(buf);loff_t pos=0;return nss_project_wt_stats_handler(nss_project_table,1,buf,&n,&pos); }
static int read_value(void) { char buf[32]={0};size_t n=sizeof(buf);loff_t pos=0;assert(!nss_project_wt_stats_handler(nss_project_table,0,buf,&n,&pos));return atoi(buf); }
static ssize_t snapshot(char *out,size_t size) { struct nss_stats_data data={.nss_ctx=&nss_top_main.nss[0]};struct file file={.private_data=&data};loff_t pos=0;return nss_wt_stats_read(&file,out,size,&pos); }
static void notify(unsigned thread,unsigned written,unsigned len,unsigned response,unsigned irq,uint64_t count) {
 struct nss_project_msg msg={.cm={.interface=NSS_PROJECT_INTERFACE,.type=NSS_PROJECT_MSG_WT_STATS_NOTIFY,.len=len,.response=response}};
 msg.msg.wt_stats_notify.threadno=thread;msg.msg.wt_stats_notify.stats_written=written;
 msg.msg.wt_stats_notify.stats[0]=(struct nss_project_irq_stats){.irq=irq,.count=count,.callback=0x3f0057e0,.ticks_min=1,.ticks_avg=2,.ticks_max=3,.insn_min=4,.insn_avg=5,.insn_max=6};
 nss_project_msg_handler(&nss_top_main.nss[0],&msg.cm,NULL);
}
static void publish_first(void) { assert(!nss_project_wt_stats_send_enable(&nss_top_main.nss[0],true)); }
static void clear_tables(void) { nss_project_unregister_sysctl(); }
int main(void) {
 _Static_assert(sizeof(struct nss_cmn_msg)==40,"PROJECT common header ABI");
 _Static_assert(sizeof(struct nss_project_msg_wt_stats_enable)==12,"PROJECT enable ABI");
 _Static_assert(sizeof(struct nss_project_irq_stats)==40,"PROJECT IRQ ABI");
 _Static_assert(sizeof(struct nss_project_msg_wt_stats_notify)==1288,"PROJECT notify ABI");
 char *out=calloc(1,1024*1024);assert(out);fresh();
#ifdef BASELINE_READER
 puts("Injecting the first valid ENABLE ACK during zero-sized reader allocation");fflush(stdout);
 allocation_hook=publish_first;snapshot(out,1024*1024);abort();
#else
 assert(snapshot(out,1024*1024)==0&&allocations==0&&zero_allocations==0);
 assert(write_value(-1)==-EINVAL&&write_value(2)==-EINVAL&&submissions==0);
 assert(!write_value(1)&&read_value()==1&&submissions==2);
 assert(nss_top_main.nss[0].worker_thread_count==12&&nss_top_main.nss[0].irq_count==128);
 assert(snapshot(out,1024*1024)>0&&strstr(out,"WORKER THREAD"));
 assert(!write_value(1)&&submissions==2); /* Repeated confirmed enable is idempotent. */
 for(unsigned len=0;len<48;len++)notify(0,1,len,NSS_CMN_RESPONSE_NOTIFY,7,11);
 assert(!nss_top_main.nss[0].wt_stats[0].irq_stats[7].count);
 notify(0,33,1288,NSS_CMN_RESPONSE_NOTIFY,7,11);
 notify(12,1,1288,NSS_CMN_RESPONSE_NOTIFY,7,11);
 notify(0,1,1288,NSS_CMN_RESPONSE_ACK,7,11);
 notify(0,1,1288,NSS_CMN_RESPONSE_NOTIFY,128,11);
 assert(!nss_top_main.nss[0].wt_stats[0].irq_stats[7].count);
 notify(0,1,48,NSS_CMN_RESPONSE_NOTIFY,7,11);
 assert(nss_top_main.nss[0].wt_stats[0].irq_stats[7].count==11);
 assert(snapshot(out,1024*1024)>0&&strstr(out,"t-0:irq-7 callback: 0x3f0057e0, count: 11"));
 for(unsigned t=0;t<12;t++)for(unsigned irq=0;irq<128;irq++)nss_top_main.nss[0].wt_stats[t].irq_stats[irq].count=UINT64_MAX;
 memset(out,0,1024*1024);assert(snapshot(out,1024*1024)>0&&strstr(out,"t-11:irq-127")&&zero_allocations==0);
 assert(!write_value(0)&&read_value()==0&&submissions==4);
 uint64_t old=nss_top_main.nss[0].wt_stats[0].irq_stats[7].count;
 notify(0,1,1288,NSS_CMN_RESPONSE_NOTIFY,7,22);assert(nss_top_main.nss[0].wt_stats[0].irq_stats[7].count==old);
 /* Revalidation after table removal must not dereference the saved pointer. */
 allocation_hook=clear_tables;assert(snapshot(out,1024*1024)==0&&!live_allocations);
 for(enum plan bad=TXFAIL;bad<=BAD_ECHO;bad++) {
  fresh();plan[0]=bad;int wanted=bad==TIMEOUT?-ETIMEDOUT:(bad>=SHORT_ACK?-EPROTO:-EIO);
  assert(write_value(1)==wanted&&read_value()==0&&submissions==3);
  /* A late ACK for the abandoned ENABLE cannot publish a table or invoke its dead stack request. */
  deliver(0,ACK);assert(!nss_top_main.nss[0].wt_stats&&read_value()==0);
 }
 fresh();plan[1]=TXFAIL;assert(write_value(1)==-EIO&&read_value()==0&&submissions==4);
 fresh();plan[0]=NACK;plan[2]=TIMEOUT;assert(write_value(1)==-EIO&&read_value()==-1);
 assert(!write_value(0)&&read_value()==0);deliver(0,ACK);assert(read_value()==0);
 fresh();assert(!write_value(1));plan[2]=NACK;assert(write_value(0)==-EIO&&read_value()==-1&&submissions==4);
 assert(!write_value(0)&&read_value()==0);
 fresh();boundary_ack=true;assert(!write_value(1)&&read_value()==1);boundary_ack=false;assert(!write_value(0));
 fresh();fail_table=true;assert(write_value(1)==-ENOMEM&&read_value()==0&&!live_allocations);
 for(int slot=0;slot<12;slot++){fresh();fail_irq_slot=slot;assert(write_value(1)==-ENOMEM&&read_value()==0&&!live_allocations);}
 fresh();assert(!write_value(1));nss_project_unregister_sysctl();assert(!live_allocations);
 free(out);puts("PROJECT: ACK/NACK, timeout identity, rollback, bounds, snapshot race and allocation cleanup passed");return 0;
#endif
}
'''


def strip_includes(source):
    return re.sub(r"(?m)^#include[^\n]*\n", "", source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drv", type=Path, required=True)
    parser.add_argument("--project-overrides", type=Path)
    parser.add_argument("--baseline-reader", type=Path)
    args = parser.parse_args()
    project = args.project_overrides or args.drv
    code = (SHIM + strip_includes((project / "exports/nss_project.h").read_text()) +
            strip_includes((project / "nss_control.h").read_text()) + STRUCTURES +
            strip_includes((args.drv / "nss_control.c").read_text()) +
            strip_includes((project / "nss_project.c").read_text()) +
            extract.function((args.drv / "nss_stats.c").read_text(), "nss_stats_banner"))
    reader = extract.function((project / "nss_drv_stats.c").read_text(), "nss_wt_stats_read")
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="detect_leaks=1")
    with tempfile.TemporaryDirectory(prefix="nss-project-test-") as directory:
        root = Path(directory)
        for name, body, baseline in [("fixed", reader, False)] + (
                [("old-reader", extract.function(args.baseline_reader.read_text(), "nss_wt_stats_read"), True)]
                if args.baseline_reader else []):
            source = root / (name + ".c")
            source.write_text(code + body + CASES)
            binary = root / name
            command = [os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g",
                       "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-pthread",
                       "-Wall", "-Werror", "-Wno-format", "-Wno-sign-compare",
                       "-Wno-unused-function", "-Wno-misleading-indentation", str(source), "-o", str(binary)]
            if baseline:
                command.insert(1, "-DBASELINE_READER")
            subprocess.run(command, check=True)
            result = subprocess.run([str(binary)], text=True, capture_output=True, env=env)
            if baseline:
                assert result.returncode != 0 and "first valid ENABLE ACK" in result.stdout, result.stderr
                assert "0x000000000010" in result.stderr or "address 0x10" in result.stderr, result.stderr
                print("Old reader: first-ACK ZERO_SIZE_PTR regression reproduced")
            else:
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                print(result.stdout.strip())


if __name__ == "__main__":
    main()
