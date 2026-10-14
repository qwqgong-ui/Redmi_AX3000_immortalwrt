#!/usr/bin/env python3
"""Test the real radio-buffer callback's ACK identity and payload contract."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
args = parser.parse_args()
source = args.source.read_text()
begin = source.index('struct ath11k_nss_radio_buf_request {')
end = source.index('static int ath11k_nss_radio_buf_cfg(', begin)
callback = source[begin:end]
sender_start = end
sender_end = source.index('static void ath11k_nss_fill_srng_info(', end)
sender = source[sender_start:sender_end]
assert 'sizeof(wlmsg->msg.radiocfgmsg)' in sender
assert 'nss_wifili_tx_msg_tracked(' in sender
assert sender.index('nss_wifili_cancel_msg(cookie)') < sender.index('kfree(request)')
assert 'keeping initialized radio' in source
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define NSS_WIFILI_RADIO_BUF_CFG 71
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_NOTIFY 2
struct completion { unsigned done; };
static void complete(struct completion *value) { value->done++; }
struct nss_wifili_radio_cfg_msg {
 u32 radio_if_num;
 union { struct { u32 buf_cnt,range; } radiobufcfgmsg; } radiomsg;
};
struct nss_wifili_msg {
 struct { uintptr_t app_data; u32 type,interface,response,error,len; } cm;
 union { struct nss_wifili_radio_cfg_msg radiocfgmsg; } msg;
};
''' + callback + r'''
static void reset(struct ath11k_nss_radio_buf_request *request,
                  struct nss_wifili_msg *msg) {
 memset(request,0,sizeof(*request)); memset(msg,0,sizeof(*msg));
 request->if_num=20; request->radio_if_num=28; request->buf_cnt=8192; request->range=2;
 msg->cm.app_data=(uintptr_t)request; msg->cm.type=NSS_WIFILI_RADIO_BUF_CFG;
 msg->cm.interface=20; msg->cm.response=NSS_CMN_RESPONSE_ACK;
 msg->msg.radiocfgmsg.radio_if_num=28;
 msg->msg.radiocfgmsg.radiomsg.radiobufcfgmsg.buf_cnt=8192;
 msg->msg.radiocfgmsg.radiomsg.radiobufcfgmsg.range=2;
}
int main(void) {
 struct ath11k_nss_radio_buf_request r;
 struct nss_wifili_msg m;
 assert(sizeof(m.msg.radiocfgmsg)==12);
 reset(&r,&m); ath11k_nss_radio_buf_response(NULL,&m);
 assert(r.complete.done==1 && r.result==0 && !r.echo_verified);
 reset(&r,&m); m.cm.len=12; ath11k_nss_radio_buf_response(NULL,&m);
 assert(r.result==0 && r.echo_verified);
 reset(&r,&m); m.cm.len=8; ath11k_nss_radio_buf_response(NULL,&m);
 assert(r.result==-EMSGSIZE);
 reset(&r,&m); m.cm.error=1; ath11k_nss_radio_buf_response(NULL,&m);
 assert(r.result==-EREMOTEIO);
 reset(&r,&m); m.cm.response=1; ath11k_nss_radio_buf_response(NULL,&m);
 assert(r.result==-EREMOTEIO);
 reset(&r,&m); m.cm.response=NSS_CMN_RESPONSE_NOTIFY; ath11k_nss_radio_buf_response(NULL,&m);
 assert(!r.complete.done);
 reset(&r,&m); m.cm.type++; ath11k_nss_radio_buf_response(NULL,&m); assert(!r.complete.done);
 reset(&r,&m); m.cm.interface++; ath11k_nss_radio_buf_response(NULL,&m); assert(!r.complete.done);
 reset(&r,&m); m.cm.len=12; m.msg.radiocfgmsg.radio_if_num++; ath11k_nss_radio_buf_response(NULL,&m); assert(r.result==-EPROTO);
 reset(&r,&m); m.cm.len=12; m.msg.radiocfgmsg.radiomsg.radiobufcfgmsg.buf_cnt++; ath11k_nss_radio_buf_response(NULL,&m); assert(r.result==-EPROTO);
 reset(&r,&m); m.cm.len=12; m.msg.radiocfgmsg.radiomsg.radiobufcfgmsg.range++; ath11k_nss_radio_buf_response(NULL,&m); assert(r.result==-EPROTO);
 puts("PASS full radio payload, empty/full ACK, identity/length/error checks, tracked cancellation contract");
}
'''
with tempfile.TemporaryDirectory(prefix='nss-radio-ack-') as temporary:
    work = Path(temporary)
    (work / 'test.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
                    '-fsanitize=address,undefined', str(work / 'test.c'),
                    '-o', str(work / 'test')], check=True)
    subprocess.run([str(work / 'test')], check=True, timeout=15)
