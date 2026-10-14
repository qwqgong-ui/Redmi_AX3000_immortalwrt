#!/usr/bin/env python3
"""Execute actual REO submit/parse/observe code without acquiring queue ownership."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec=importlib.util.spec_from_file_location("reo_functions",Path(__file__).with_name("test-nss-control.py"))
extract=importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
typedef pthread_mutex_t spinlock_t;
#define BIT(n) (UINT32_C(1)<<(n))
#define GENMASK(h,l) ((UINT32_MAX>>(31-(h)))&~((UINT32_C(1)<<(l))-1))
#define FIELD_GET(mask,value) (((value)&(mask))>>__builtin_ctz(mask))
#define FIELD_PREP(mask,value) (((value)<<__builtin_ctz(mask))&(mask))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define spin_lock_bh(p) assert(!pthread_mutex_lock(p))
#define spin_unlock_bh(p) assert(!pthread_mutex_unlock(p))
#define GFP_ATOMIC 0
#define ATH11K_FLAG_CRASH_FLUSH 0
#define test_bit(bit,p) (!!(*(p)&(1ul<<(bit))))
#define READ_ONCE(x) (x)
#define lockdep_assert_held(p) assert(pthread_mutex_trylock(p)==EBUSY)
struct list_head {struct list_head *next,*prev;};
static void list_add_tail(struct list_head *n,struct list_head *h){n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n;}
enum hal_reo_cmd_type {HAL_REO_CMD_GET_QUEUE_STATS=0,HAL_REO_CMD_FLUSH_QUEUE=1,HAL_REO_CMD_FLUSH_CACHE=2,HAL_REO_CMD_UNBLOCK_CACHE=3,HAL_REO_CMD_FLUSH_TIMEOUT_LIST=4,HAL_REO_CMD_UPDATE_RX_QUEUE=5};
enum hal_reo_cmd_status {HAL_REO_CMD_SUCCESS=0,HAL_REO_CMD_BLOCKED=1,HAL_REO_CMD_FAILED=2,HAL_REO_CMD_RESOURCE_BLOCKED=3,HAL_REO_CMD_DRAIN=255};
struct hal_reo_status_header {u16 cmd_num;enum hal_reo_cmd_status cmd_status;u16 cmd_exe_time;u32 timestamp;};
struct hal_reo_status {struct hal_reo_status_header uniform_hdr;};
struct hal_tlv_hdr {u32 tl;u8 value[];};
struct hal_reo_status_hdr {u32 info0,timestamp;};
'''

STRUCTURES=r'''
struct ath11k_base;
struct ath11k_reo_queue;
struct dp_rx_tid {void *vaddr_unaligned;u8 tid;u64 paddr,paddr_unaligned;u32 size,pending_desc_size,ba_win_sz,unaligned_size;bool active;struct ath11k_reo_queue *reo_queue;};
enum ath11k_reo_cmd_kind {ATH11K_REO_CMD_RETIRE,ATH11K_REO_CMD_QUERY,ATH11K_REO_CMD_PN_UPDATE};
struct ath11k_reo_query {unsigned refs;u16 cmd_num;};
struct ath11k_reo_pn_update {unsigned refs;u16 cmd_num;};
static void refcount_inc(unsigned *refs){(void)refs;assert(!"QUERY is covered by the queue/query fixture");}
static void ath11k_dp_reo_queue_get(struct ath11k_reo_queue *q){assert(!q);}
static void ath11k_dp_reo_queue_put(struct ath11k_reo_queue *q){assert(!q);}
struct hal_srng {int unused;};
struct ath11k_dp {
 struct ath11k_base *ab;
 spinlock_t reo_stats_lock,reo_cmd_lock;
 bool reo_cmd_accepting;
 u64 reo_cmd_epoch;
 u16 reo_cmd_status_tag[257];
 struct ath11k_reo_cmd_stats reo_cmd_stats;
	 bool reo_query_outstanding;
	 unsigned reo_pn_outstanding;
	 struct {unsigned submitted;} reo_pn_stats;
 struct ath11k_reo_update_stats reo_update_stats;
 struct {unsigned ring_id;} reo_cmd_ring;
 struct list_head reo_cmd_list;
};
struct ath11k_base {unsigned long dev_flags;struct ath11k_dp dp;struct {struct hal_srng srng_list[1];} hal;struct {bool ownership_uncertain;} nss;};
struct dp_reo_cmd {struct list_head list;struct dp_rx_tid data;int cmd_num;u16 status_tag;enum ath11k_reo_cmd_kind kind;struct ath11k_reo_query *query;struct ath11k_reo_pn_update *pn_update;void (*handler)(struct ath11k_dp *,void *,enum hal_reo_cmd_status);};
static unsigned allocations,submissions;
static bool allocation_fail;
static int hal_result=1;
static void *kzalloc(size_t size,int flags){(void)flags;allocations++;return allocation_fail?NULL:calloc(1,size);}
static void kfree(void *p){free(p);}
static int ath11k_hal_reo_cmd_send(struct ath11k_base *ab,struct hal_srng *ring,enum hal_reo_cmd_type type,struct ath11k_hal_reo_cmd *cmd) {
 (void)ab;(void)ring;submissions++;
 if(type==HAL_REO_CMD_UPDATE_RX_QUEUE){if(cmd->ba_window_size<1)cmd->ba_window_size=1;if(cmd->ba_window_size==1)cmd->ba_window_size++;cmd->pn_size=2;}
 return hal_result;
}
'''

CASES=r'''
static void client_callback(struct ath11k_dp *dp,void *data,enum hal_reo_cmd_status status){(void)dp;(void)data;(void)status;}
static void *receive_many(void *arg){struct ath11k_dp *dp=arg;for(unsigned i=0;i<10000;i++){struct hal_reo_status_header h={.cmd_num=17,.cmd_status=i%4,.timestamp=i};ath11k_dp_reo_update_status(dp,&h);}return NULL;}
int main(void) {
 struct ath11k_base ab={0};struct ath11k_dp *dp=&ab.dp;struct ath11k_reo_update_stats out;
 pthread_mutex_init(&dp->reo_stats_lock,NULL);pthread_mutex_init(&dp->reo_cmd_lock,NULL);dp->ab=&ab;dp->reo_cmd_accepting=true;dp->reo_cmd_list=(struct list_head){&dp->reo_cmd_list,&dp->reo_cmd_list};
 ath11k_dp_reo_update_snapshot(dp,&out);assert(!out.epoch&&!out.requested);
 ath11k_dp_reo_update_reset(dp);assert(dp->reo_update_stats.epoch==1);
 struct ath11k_hal_reo_cmd cmd={.addr_lo=0xdeadbeef,.addr_hi=0x12,.flag=HAL_REO_CMD_FLG_NEED_STATUS,
  .upd0=HAL_REO_CMD_UPD0_BA_WINDOW_SIZE|HAL_REO_CMD_UPD0_SSN,.upd2=FIELD_PREP(HAL_REO_CMD_UPD2_SSN,4095),.ba_window_size=1,.pn_size=48};
 hal_result=25;
 /* NULL callback remains allocation-free, even with an invalid queue pointer. */
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,(void *)16,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL));
 assert(cmd.ba_window_size==2&&allocations==0&&submissions==1&&dp->reo_cmd_list.next==&dp->reo_cmd_list);
 ath11k_dp_reo_update_snapshot(dp,&out);
 assert(out.requested==1&&out.queued==1&&!out.rejected&&out.status_requested==1&&out.ba_queued==1&&out.ssn_queued==1);
 assert(out.last_window==1&&out.last_ssn==4095&&out.last_paddr==UINT64_C(0x12deadbeef)&&out.last_ba_window==1&&out.last_ba_cmd==25);
 struct {u32 tl;struct hal_reo_status_hdr header;} raw={.header={.info0=FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_STATUS_NUM,25)|FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_EXEC_STATUS,3)|FIELD_PREP(HAL_REO_STATUS_HDR_INFO0_EXEC_TIME,501),.timestamp=0xcafef00d}};
 struct hal_reo_status status={0};ath11k_hal_reo_update_rx_reo_queue_status(&ab,(u32 *)&raw,&status);
 assert(status.uniform_hdr.cmd_num==25&&status.uniform_hdr.cmd_status==3);
 assert(status.uniform_hdr.timestamp==0xcafef00d&&status.uniform_hdr.cmd_exe_time==501);
 ath11k_dp_reo_update_status(dp,&status.uniform_hdr);assert(dp->reo_update_stats.status[3]==1&&dp->reo_update_stats.last_timestamp==0xcafef00d);
 for(unsigned code=0;code<5;code++){status.uniform_hdr.cmd_status=code==4?255:code;ath11k_dp_reo_update_status(dp,&status.uniform_hdr);}
 assert(dp->reo_update_stats.status_unknown==1&&dp->reo_update_stats.status[0]==1&&dp->reo_update_stats.status[3]==2);
 hal_result=-EBUSY;assert(ath11k_dp_tx_send_reo_cmd(&ab,NULL,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL)==-EBUSY);
 hal_result=0;assert(ath11k_dp_tx_send_reo_cmd(&ab,NULL,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL)==-EINVAL);
 ab.dev_flags=1;assert(ath11k_dp_tx_send_reo_cmd(&ab,NULL,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL)==-ESHUTDOWN);ab.dev_flags=0;
 ath11k_dp_reo_update_snapshot(dp,&out);assert(out.requested==4&&out.queued==1&&out.rejected==3&&out.last_errno==-ESHUTDOWN&&allocations==0);
 hal_result=7;assert(ath11k_dp_tx_send_reo_cmd(&ab,NULL,HAL_REO_CMD_GET_QUEUE_STATS,&cmd,NULL)==-EOPNOTSUPP);assert(dp->reo_update_stats.requested==4);
 cmd.upd0=HAL_REO_CMD_UPD0_PN_CHECK;cmd.flag=0;cmd.ba_window_size=0;
 assert(!ath11k_dp_tx_send_reo_cmd(&ab,NULL,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,NULL));
 assert(dp->reo_update_stats.pn_queued==1&&dp->reo_update_stats.status_requested==1&&dp->reo_update_stats.last_window==0&&dp->reo_update_stats.last_ba_window==1);
 /* Callback allocation failure now precedes hardware publication. */
 cmd.flag=HAL_REO_CMD_FLG_NEED_STATUS;unsigned sent_before_failure=submissions;
 allocation_fail=true;struct dp_rx_tid tid={.tid=42};
 assert(ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback)==-ENOMEM);
 assert(submissions==sent_before_failure&&dp->reo_update_stats.last_errno==-ENOMEM&&dp->reo_update_stats.queued==2&&dp->reo_cmd_list.next==&dp->reo_cmd_list);
 allocation_fail=false;assert(!ath11k_dp_tx_send_reo_cmd(&ab,&tid,HAL_REO_CMD_UPDATE_RX_QUEUE,&cmd,client_callback));
 struct dp_reo_cmd *pending=(void *)((char *)dp->reo_cmd_list.next - offsetof(struct dp_reo_cmd, list));
 assert(pending->data.tid==42&&pending->cmd_num==7);free(pending);dp->reo_cmd_list=(struct list_head){&dp->reo_cmd_list,&dp->reo_cmd_list};
 ath11k_dp_reo_update_reset(dp);assert(dp->reo_update_stats.epoch==2&&!dp->reo_update_stats.requested&&!dp->reo_update_stats.status[0]);
 pthread_t workers[4];for(unsigned i=0;i<4;i++)assert(!pthread_create(&workers[i],NULL,receive_many,dp));
 for(unsigned i=0;i<10000;i++){ath11k_dp_reo_update_snapshot(dp,&out);assert(out.status[0]+out.status[1]+out.status[2]+out.status[3]<=40000);}
 for(unsigned i=0;i<4;i++)pthread_join(workers[i],NULL);
 ath11k_dp_reo_update_snapshot(dp,&out);for(unsigned i=0;i<4;i++)assert(out.status[i]==10000);
 puts("REO UPDATE: raw status fields, submit errors, prepublication ENOMEM, HAL mutation, NULL-callback ownership and concurrent snapshots passed");return 0;
}
'''

def structure(source,name):
    start=source.index("struct "+name+" {")
    return source[start:source.index("};",start)+2]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backports",type=Path,required=True)
    p.add_argument("--draft",type=Path)
    a=p.parse_args()
    source=a.backports/"drivers/net/wireless/ath/ath11k"
    draft=a.draft or source
    header=(draft/"dp.h").read_text()
    hal=(source/"hal.h").read_text()
    desc=(source/"hal_desc.h").read_text()
    macros=("HAL_REO_CMD_FLG_NEED_STATUS","HAL_REO_CMD_UPD0_BA_WINDOW_SIZE","HAL_REO_CMD_UPD0_SSN",
            "HAL_REO_CMD_UPD0_PN_CHECK","HAL_REO_CMD_UPD0_PN","HAL_REO_CMD_UPD2_SSN",
            "HAL_REO_STATUS_HDR_INFO0_STATUS_NUM","HAL_REO_STATUS_HDR_INFO0_EXEC_STATUS","HAL_REO_STATUS_HDR_INFO0_EXEC_TIME")
    definitions="\n".join(re.search(r"(?m)^#define[ \t]+"+name+r"[ \t]+[^\n]+",hal+"\n"+desc).group(0) for name in macros)
    for name in ("HAL_REO_GET_QUEUE_STATS_STATUS", "HAL_REO_FLUSH_CACHE_STATUS", "HAL_REO_UPDATE_RX_REO_QUEUE_STATUS"):
        value=re.search(r"(?m)^[ \t]+"+name+r"[ \t]*=[ \t]*([0-9]+)",desc).group(1)
        definitions+="\n#define "+name+" "+value
    structs=header[header.index("struct ath11k_reo_update_stats {"):header.index("struct ath11k_dp {")]
    helpers=header[header.index("static inline void ath11k_dp_reo_cmd_close"):header.index("/* HTT definitions */")]
    code=(SHIM+"\n#include <stddef.h>\n"+definitions+"\n"+structure(hal,"ath11k_hal_reo_cmd")+
          structs+STRUCTURES+helpers+
          extract.function((draft/"dp_rx.c").read_text(),"ath11k_dp_reo_tid_clone")+
          extract.function((draft/"dp_rx.c").read_text(),"ath11k_dp_reo_tid_drop")+
          extract.function((draft/"hal_rx.c").read_text(),"ath11k_hal_reo_update_rx_reo_queue_status")+
          extract.function((draft/"dp_tx.c").read_text(),"ath11k_dp_tx_reo_submit_locked")+
          extract.function((draft/"dp_tx.c").read_text(),"ath11k_dp_tx_send_reo_cmd")+CASES)
    with tempfile.TemporaryDirectory(prefix="reo-update-test-") as directory:
        root=Path(directory);c=root/"test.c";binary=root/"test";c.write_text(code)
        subprocess.run([os.environ.get("CC","cc"),"-std=gnu11","-O1","-g","-pthread","-Wall","-Werror",
                        "-Wno-unused-function","-fsanitize=address,undefined","-fno-omit-frame-pointer",str(c),"-o",str(binary)],check=True)
        subprocess.run([str(binary)],check=True,env=dict(os.environ,UBSAN_OPTIONS="halt_on_error=1",ASAN_OPTIONS="detect_leaks=1"))

if __name__=="__main__":main()
