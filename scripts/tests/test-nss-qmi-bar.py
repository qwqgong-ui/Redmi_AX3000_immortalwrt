#!/usr/bin/env python3
"""Run actual hybrid DEVICE_INFO mapping through repeated recovery and failures."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "extract_nss", Path(__file__).with_name("test-nss-control.py"))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define __iomem
#define QMI_RESULT_SUCCESS_V01 0
#define ATH11K_QMI_WLANFW_TIMEOUT_MS 1000
#define ATH11K_QMI_DEVICE_BAR_SIZE 0x200000
#define QMI_WLANFW_DEVICE_INFO_REQ_V01 0x4c
#define QMI_WLANFW_DEVICE_INFO_REQ_MSG_V01_MAX_LEN 0
#define ath11k_warn(...) ((void)0)
#define ath11k_info(...) ((void)0)
struct qmi_wlanfw_device_info_req_msg_v01 { int unused; };
struct qmi_wlanfw_device_info_resp_msg_v01 {
 struct { unsigned result,error; } resp;
 bool bar_addr_valid,bar_size_valid;uint64_t bar_addr;unsigned bar_size;
};
struct qmi_txn { int unused; };
static const int qmi_wlfw_device_info_resp_msg_v01_ei[1]={1};
static const int qmi_wlanfw_device_info_req_msg_v01_ei[1]={2};
struct ath11k_base {
 void *dev,*mem,*mem_ce;uint64_t mem_pa;unsigned long mem_len;
 struct { bool hybrid_bus_type,ce_remap; } hw_params;
 struct { int handle; } qmi;
};
static struct qmi_wlanfw_device_info_resp_msg_v01 response;
static int init_error,send_error,wait_error;
static unsigned txns,sends,cancels,maps,windows;
static bool map_failure;
static unsigned char mappings[8],separate_ce;
static unsigned msecs_to_jiffies(unsigned n) { return n; }
static int qmi_txn_init(int *h,struct qmi_txn *txn,const int *ei,void *out) {
 (void)h;(void)txn;assert(ei==qmi_wlfw_device_info_resp_msg_v01_ei);
 txns++;memcpy(out,&response,sizeof(response));return init_error;
}
static int qmi_send_request(int *h,void *addr,struct qmi_txn *txn,
 unsigned id,unsigned size,const int *ei,const void *req) {
 (void)h;(void)txn;assert(!addr&&req&&id==QMI_WLANFW_DEVICE_INFO_REQ_V01&&
 !size&&ei==qmi_wlanfw_device_info_req_msg_v01_ei);sends++;return send_error;
}
static void qmi_txn_cancel(struct qmi_txn *txn) { (void)txn;cancels++; }
static int qmi_txn_wait(struct qmi_txn *txn,unsigned ticks) {
 (void)txn;assert(ticks==1000);return wait_error;
}
static void *devm_ioremap(void *dev,uint64_t addr,unsigned size) {
 assert(dev&&addr==response.bar_addr&&size==response.bar_size&&maps<8);
 unsigned slot=maps++;return map_failure?NULL:&mappings[slot];
}
static void ath11k_hif_config_static_window(struct ath11k_base *ab) {
 assert(ab->mem&&ab->mem_pa==response.bar_addr&&ab->mem_len==response.bar_size);
 windows++;
}
'''

TEST = r'''
static void fresh(struct ath11k_base *ab,bool remap) {
 memset(ab,0,sizeof(*ab));ab->dev=ab;ab->hw_params.hybrid_bus_type=true;
 ab->hw_params.ce_remap=remap;if(remap)ab->mem_ce=&separate_ce;
 response=(struct qmi_wlanfw_device_info_resp_msg_v01){
  .bar_addr_valid=true,.bar_size_valid=true,.bar_addr=0x10000000,
  .bar_size=ATH11K_QMI_DEVICE_BAR_SIZE};
 txns=sends=cancels=maps=windows=0;init_error=send_error=wait_error=0;map_failure=false;
}
int main(void) {
 struct ath11k_base ab;
 for(unsigned remap=0;remap<2;remap++){
  fresh(&ab,remap);assert(!ath11k_qmi_request_device_info(&ab));
  void *original=ab.mem,*ce=ab.mem_ce;
  assert(maps==1&&windows==1&&ce==(remap?&separate_ce:original));
  /* Every FW_MEM_READY still needs the hardware window programmed. */
  for(unsigned i=0;i<100;i++){
   assert(!ath11k_qmi_request_device_info(&ab));
   assert(ab.mem==original&&ab.mem_ce==ce&&maps==1&&windows==i+2);
  }
  map_failure=true;assert(!ath11k_qmi_request_device_info(&ab)&&maps==1);
  unsigned before=windows;response.bar_addr+=0x200000;
  assert(ath11k_qmi_request_device_info(&ab)==-ESTALE);
  assert(ab.mem==original&&ab.mem_ce==ce&&ab.mem_pa==0x10000000&&
         ab.mem_len==ATH11K_QMI_DEVICE_BAR_SIZE&&maps==1&&windows==before);
 }
 for(unsigned failure=0;failure<8;failure++){
  fresh(&ab,false);int expected=-EINVAL;
  if(failure==0){init_error=-ENOMEM;expected=-ENOMEM;}
  if(failure==1){send_error=-ENOBUFS;expected=-ENOBUFS;}
  if(failure==2){wait_error=-ETIMEDOUT;expected=-ETIMEDOUT;}
  if(failure==3)response.resp.result=1;
  if(failure==4)response.bar_addr_valid=false;
  if(failure==5)response.bar_size_valid=false;
  if(failure==6)response.bar_addr=0;
  if(failure==7)response.bar_size--;
  assert(ath11k_qmi_request_device_info(&ab)==expected);
  assert(!maps&&!windows&&!ab.mem&&!ab.mem_pa&&!ab.mem_len);
  assert(cancels==(failure==1));
 }
 fresh(&ab,false);map_failure=true;
 assert(ath11k_qmi_request_device_info(&ab)==-EIO&&maps==1&&!ab.mem&&!windows);
 map_failure=false;assert(!ath11k_qmi_request_device_info(&ab)&&maps==2&&windows==1);
 fresh(&ab,false);ab.hw_params.hybrid_bus_type=false;
 assert(!ath11k_qmi_request_device_info(&ab)&&!txns&&!maps&&!windows);
 puts("PASS real hybrid BAR: repeated recovery reuse, window replay, unchanged CE aliases, changed tuple and QMI/mapping failures");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", type=Path, required=True)
    parser.add_argument("--qmi-source", type=Path)
    args = parser.parse_args()
    path = args.qmi_source or args.backports / "drivers/net/wireless/ath/ath11k/qmi.c"
    body = extractor.function(path.read_text(), "ath11k_qmi_request_device_info")
    with tempfile.TemporaryDirectory(prefix="nss-qmi-bar-") as directory:
        root = Path(directory)
        source, binary = root / "bar.c", root / "bar"
        source.write_text(SHIM + body + TEST)
        subprocess.run(["cc", "-std=gnu11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15)


if __name__ == "__main__":
    main()
