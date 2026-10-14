#!/usr/bin/env python3
"""Exercise the real VDEV state callback, including header-only ACK bounds."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
args = parser.parse_args()
source = args.source.read_text()
start = source.index('struct ath11k_nss_vdev_request {')
base = source[start:source.index('};', start) + 2]
start = source.index('struct ath11k_nss_vdev_state_request {')
end = source.index('static int ath11k_nss_vdev_set_state(', start)
callback = source[start:end]
sender = source[end:source.index('static void ath11k_nss_vdev_event_receive(', end)]
assert 'nss_wifi_vdev_tx_msg_tracked(' in sender
assert sender.index('nss_wifi_vdev_cancel_msg(cookie)') < sender.rindex('kfree(state)')
assert 'up && (' in sender, 'DOWN must remain available with failed key/format gates'

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint8_t u8;
#define ETH_ALEN 6
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_NOTIFY 2
#define NSS_WIFI_VDEV_INTERFACE_UP_MSG 32
#define NSS_WIFI_VDEV_INTERFACE_DOWN_MSG 33
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct completion { unsigned done; };
static void complete(struct completion *p) { p->done++; }
static bool ether_addr_equal(const u8 *a, const u8 *b) { return !memcmp(a,b,6); }
struct nss_cmn_msg { u32 type,interface,response,error,len; };
struct nss_wifi_vdev_msg {
 struct nss_cmn_msg cm;
 union { struct { u8 mac_addr[6],reserved[2]; } vdev_enable; } msg;
};
''' + base + callback + r'''
static void reset(struct ath11k_nss_vdev_state_request *r,
                  struct nss_wifi_vdev_msg *m) {
 memset(r,0,sizeof(*r)); memset(m,0,sizeof(*m));
 r->request.type=NSS_WIFI_VDEV_INTERFACE_UP_MSG;
 r->request.if_num=32; r->request.result=-ETIMEDOUT;
 memset(r->mac_addr,0x42,6);
 m->cm.type=r->request.type; m->cm.interface=32;
}
int main(void) {
 struct ath11k_nss_vdev_state_request r;
 struct nss_wifi_vdev_msg m;
 struct nss_cmn_msg header;
 reset(&r,&m); header=m.cm;
 ath11k_nss_vdev_state_cb(&r,&header);
 assert(r.request.result==0 && r.request.complete.done==1 && !r.echo_match);
 reset(&r,&m); m.cm.len=8; memcpy(m.msg.vdev_enable.mac_addr,r.mac_addr,6);
 ath11k_nss_vdev_state_cb(&r,&m.cm);
 assert(r.request.result==0 && r.echo_match);
 reset(&r,&m); m.cm.len=8;
 ath11k_nss_vdev_state_cb(&r,&m.cm);
 assert(r.request.result==0 && !r.echo_match); /* ACK is not a readback. */
 reset(&r,&m); header=m.cm; header.len=4;
 ath11k_nss_vdev_state_cb(&r,&header);
 assert(r.request.result==0 && !r.echo_match); /* No speculative payload read. */
 reset(&r,&m); m.cm.error=1; ath11k_nss_vdev_state_cb(&r,&m.cm);
 assert(r.request.result==-EREMOTEIO && r.request.error==1);
 reset(&r,&m); m.cm.response=1; ath11k_nss_vdev_state_cb(&r,&m.cm);
 assert(r.request.result==-EREMOTEIO);
 reset(&r,&m); m.cm.response=NSS_CMN_RESPONSE_NOTIFY;
 ath11k_nss_vdev_state_cb(&r,&m.cm); assert(!r.request.complete.done);
 reset(&r,&m); m.cm.type++; ath11k_nss_vdev_state_cb(&r,&m.cm);
 assert(!r.request.complete.done && r.request.result==-ETIMEDOUT);
 reset(&r,&m); m.cm.interface++; ath11k_nss_vdev_state_cb(&r,&m.cm);
 assert(!r.request.complete.done);
 reset(&r,&m); r.request.type=NSS_WIFI_VDEV_INTERFACE_DOWN_MSG;
 m.cm.type=r.request.type; m.cm.len=4; ath11k_nss_vdev_state_cb(&r,&m.cm);
 assert(r.request.result==0 && !r.echo_match);
 ath11k_nss_vdev_state_cb(NULL,&m.cm);
 puts("PASS VDEV state ACK/NACK, identity, header-only bounds, acceptance/readback distinction and waiter cancellation contract");
}
'''
with tempfile.TemporaryDirectory(prefix='nss-vdev-state-') as temporary:
    work = Path(temporary)
    (work / 'test.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
                    '-fsanitize=address,undefined', str(work / 'test.c'),
                    '-o', str(work / 'test')], check=True)
    subprocess.run([str(work / 'test')], check=True, timeout=15)
