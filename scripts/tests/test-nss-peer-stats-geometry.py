#!/usr/bin/env python3
"""Execute the real WIFILI guard with public records and multi-peer RX extents."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    'nss_peer_geometry', Path(__file__).with_name('test-nss-control.py'))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint32_t u32;typedef uint64_t nss_ptr_t;
enum nss_cmn_response { NSS_CMN_RESPONSE_ACK,NSS_CMN_RESPONSE_EMSG,NSS_CMN_RESPONSE_NOTIFY };
#define NSS_WIFILI_PEER_STATS_MSG 12
#define min(a,b) ((a)<(b)?(a):(b))
#define pr_warn_ratelimited(...) ((void)0)
struct nss_ctx_instance {};
static unsigned actual_length,accepted,total;
static u32 nss_core_rx_msg_buf_len(struct nss_ctx_instance *ctx) { (void)ctx;return actual_length; }
'''

TEST = r'''
static void receive(struct nss_ctx_instance *nss_ctx,struct nss_wifili_msg *ntm) {
 struct nss_cmn_msg *ncm=&ntm->cm;
 GUARD
 accepted++;
 for(unsigned i=0;i<ntm->msg.peer_stats.stats.npeers;i++)
  total+=ntm->msg.peer_stats.stats.wpcs[i].tx.tx_success_cnt;
}
static void check(unsigned count,unsigned truncation,bool valid) {
 unsigned header=offsetof(struct nss_wifili_msg,msg.peer_stats.stats.wpcs);
 unsigned size=header+count*sizeof(struct nss_wifili_peer_ctrl_stats)-truncation;
 struct nss_wifili_msg *msg=calloc(1,size);assert(msg);
 actual_length=size;msg->cm.type=NSS_WIFILI_PEER_STATS_MSG;
 /* Real MP156 notifications retain this fixed declared length. */
 msg->cm.len=sizeof(struct nss_wifili_peer_stats_msg);
 msg->msg.peer_stats.stats.npeers=count;
 if(!truncation)for(unsigned i=0;i<count;i++)msg->msg.peer_stats.stats.wpcs[i].tx.tx_success_cnt=i+1;
 accepted=total=0;receive(NULL,msg);
 assert(accepted==valid);
 assert(total==(valid?count*(count+1)/2:0));
 assert(msg->cm.len==sizeof(struct nss_wifili_peer_stats_msg));
 free(msg);
}
int main(void) {
 for(unsigned n=1;n<=16;n++){check(n,0,true);check(n,1,false);}
 unsigned header=offsetof(struct nss_wifili_msg,msg.peer_stats.stats.wpcs);
 for(unsigned bytes=sizeof(struct nss_cmn_msg);bytes<header;bytes++){
  struct nss_wifili_msg *msg=calloc(1,bytes);assert(msg);actual_length=bytes;
  msg->cm.type=NSS_WIFILI_PEER_STATS_MSG;accepted=0;receive(NULL,msg);assert(!accepted);free(msg);
 }
 struct nss_wifili_msg msg={0};msg.cm.type=NSS_WIFILI_PEER_STATS_MSG;
 msg.msg.peer_stats.stats.npeers=UINT32_MAX;actual_length=sizeof(msg);
 accepted=total=0;receive(NULL,&msg);assert(!accepted&&!total);
 puts("PASS actual WIFILI peer geometry: fixed cm.len with 1..16 records, actual-buffer truncation, absent count, overflow count, no partial stats or header rewrite");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--drv', type=Path, required=True)
    args = parser.parse_args()
    common = (args.drv / 'exports/nss_cmn.h').read_text()
    header = (args.drv / 'exports/nss_wifili_if.h').read_text()
    handler = extract.function((args.drv / 'nss_wifili.c').read_text(), 'nss_wifili_handler')
    start = handler.index('\tif (ncm->type == NSS_WIFILI_PEER_STATS_MSG)')
    stop = handler.index('\n\tnss_wifili_log_rx_msg', start)
    definitions = '\n'.join(line for line in header.splitlines() if re.match(
        r'#define (NSS_WIFILI_MAX_RESERVED_TYPE|NSS_WIFILI_TQM_RR_MAX)\b', line)) + '\n'
    definitions += extract.structures.structure(common, 'nss_cmn_msg')
    for name in ('nss_wifili_tx_dropped', 'nss_wifili_tx_ctrl_stats', 'nss_wifili_rx_err',
                 'nss_wifili_rx_ctrl_stats', 'nss_wifili_retry_ctrl_stats',
                 'nss_wifili_peer_ctrl_stats', 'nss_wifili_peer_stats', 'nss_wifili_peer_stats_msg'):
        definitions += extract.structures.structure(header, name) + '\n'
    definitions += 'struct nss_wifili_msg { struct nss_cmn_msg cm;union { struct nss_wifili_peer_stats_msg peer_stats; } msg; };\n'
    with tempfile.TemporaryDirectory(prefix='nss-peer-geometry-') as directory:
        source = Path(directory) / 'peer.c'
        source.write_text(SHIM + definitions + TEST.replace('GUARD', handler[start:stop]))
        for define in ('NSS_FIRMWARE_VERSION_11_4', 'NSS_FIRMWARE_VERSION_12_2', 'NSS_FIRMWARE_VERSION_DEFAULT'):
            binary = Path(directory) / define
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
                            '-D' + define, '-fsanitize=address,undefined',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                            '-Werror=implicit-function-declaration', str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True,
                           env={**os.environ, 'UBSAN_OPTIONS': 'halt_on_error=1'})


if __name__ == '__main__':
    main()
