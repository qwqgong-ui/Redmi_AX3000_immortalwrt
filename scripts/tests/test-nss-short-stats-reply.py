#!/usr/bin/env python3
"""Execute the real compact shaper STATS_SYNC_MANY reply check and broker copy."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "nss_short_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define U32_MAX 0xffffffffu
#define NSS_CORE_MAX 2
#define NSS_MAX_NET_INTERFACES 64
#define NSS_CMN_RESPONSE_ACK 0
#define NSS_CMN_RESPONSE_EMSG 4
#define NSS_IF_ISHAPER_CONFIG 10
#define NSS_IF_BSHAPER_CONFIG 11
#define NSS_SHAPER_CONFIG_TYPE_SHAPER_NODE_STATS_SYNC_MANY 25
typedef uintptr_t nss_ptr_t;
struct nss_ctx_instance { int id; };
struct nss_cmn_msg {
	uint16_t version, len; uint32_t interface, response, type, error, reserved;
	nss_ptr_t cb, app_data;
};
struct nss_shaper_node_stats_response { uint32_t qos_tag; uint32_t counters[19]; };
struct nss_shaper_node_stats_sync_many {
	uint32_t last_qos_tag; uint16_t size, count;
	struct nss_shaper_node_stats_response stats_sync[];
};
struct nss_shaper_configure {
	uint32_t request_type, response_type;
	union { struct nss_shaper_node_stats_sync_many stats_get; uint32_t other[12]; } msg;
};
struct nss_if_msg {
	struct nss_cmn_msg cm;
	union { struct { struct nss_shaper_configure config; } shaper_configure; } msg;
};
enum nss_control_family { NSS_CONTROL_DYNAMIC, NSS_CONTROL_WIFI_VDEV, NSS_CONTROL_WIFI_EXT_VDEV,
	NSS_CONTROL_PROJECT, NSS_CONTROL_BASE_IF, NSS_CONTROL_MIRROR, NSS_CONTROL_RPS,
	NSS_CONTROL_FAMILY_MAX };
struct list_head { struct list_head *next, *prev; };
#define LIST_HEAD(n) struct list_head n = { &n, &n }
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define list_entry(p, t, m) container_of(p, t, m)
#define list_for_each_entry(p, h, m) for (p = list_entry((h)->next, __typeof__(*p), m); \
	&(p)->m != (h); p = list_entry((p)->m.next, __typeof__(*p), m))
static void list_add_tail(struct list_head *n, struct list_head *h)
{ n->prev = h->prev; n->next = h; h->prev->next = n; h->prev = n; }
static int lock_depth;
static void spin_lock_bh(int *l) { assert(!*l); *l = 1; lock_depth++; }
static void spin_unlock_bh(int *l) { assert(*l); *l = 0; lock_depth--; }
static LIST_HEAD(nss_control_requests);
static int nss_control_lock;
'''

TEST = r'''
#define HEAD offsetof(struct nss_if_msg, msg.shaper_configure.config.msg.stats_get.stats_sync)
static struct nss_ctx_instance ctx = { .id = 0 };
static union { struct nss_control_request r; unsigned char raw[sizeof(struct nss_control_request) + sizeof(struct nss_if_msg)]; } slot;
static unsigned char wire[HEAD + 2 * sizeof(struct nss_shaper_node_stats_response)] __attribute__((aligned(8)));

static void track(uint32_t family, uint32_t if_num, uint32_t type, uint32_t request_type)
{
	struct nss_if_msg sent = { .cm = { .version = 1, .len = 56, .interface = if_num, .type = type } };

	sent.msg.shaper_configure.config.request_type = request_type;
	memset(&slot, 0, sizeof(slot));
	slot.r.cookie = 17; slot.r.core_id = 0; slot.r.if_num = if_num; slot.r.type = type;
	slot.r.family = family; slot.r.size = sizeof(sent);
	memcpy(slot.r.original, &sent, sizeof(sent));
	nss_control_requests.next = nss_control_requests.prev = &nss_control_requests;
	list_add_tail(&slot.r.list, &nss_control_requests);
}

static struct nss_cmn_msg *reply(uint32_t response, uint32_t type, uint16_t len, uint16_t count)
{
	struct nss_if_msg *m = (struct nss_if_msg *)wire;

	memset(wire, 0, sizeof(wire));
	m->cm = (struct nss_cmn_msg){ .version = 1, .len = len, .interface = 31, .response = response,
		.type = type, .cb = (nss_ptr_t)nss_control_wire_callback, .app_data = 17 };
	m->msg.shaper_configure.config.request_type = 99;
	m->msg.shaper_configure.config.msg.stats_get.count = count;
	return &m->cm;
}

int main(void)
{
	const uint32_t one = HEAD + sizeof(struct nss_shaper_node_stats_response);
	struct nss_cmn_msg *cm;

	track(NSS_CONTROL_BASE_IF, 31, NSS_IF_ISHAPER_CONFIG, NSS_SHAPER_CONFIG_TYPE_SHAPER_NODE_STATS_SYNC_MANY);
	cm = reply(NSS_CMN_RESPONSE_ACK, NSS_IF_ISHAPER_CONFIG, 56, 0);
	assert(nss_if_short_stats_reply(&ctx, cm, HEAD));
	cm = reply(NSS_CMN_RESPONSE_ACK, NSS_IF_ISHAPER_CONFIG, 56, 1);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	assert(nss_if_short_stats_reply(&ctx, cm, one));
	cm = reply(NSS_CMN_RESPONSE_ACK, NSS_IF_ISHAPER_CONFIG, 57, 0);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	cm = reply(NSS_CMN_RESPONSE_EMSG, NSS_IF_ISHAPER_CONFIG, 56, 0);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	cm = reply(NSS_CMN_RESPONSE_ACK, NSS_IF_ISHAPER_CONFIG, 56, 0);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD - 1));
	cm->app_data = 18;
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	cm->app_data = 17; cm->cb = 0;
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	cm = reply(NSS_CMN_RESPONSE_ACK, 3, 56, 0);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));

	track(NSS_CONTROL_BASE_IF, 31, NSS_IF_ISHAPER_CONFIG, 1);
	cm = reply(NSS_CMN_RESPONSE_ACK, NSS_IF_ISHAPER_CONFIG, 56, 0);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	track(NSS_CONTROL_WIFI_VDEV, 31, NSS_IF_ISHAPER_CONFIG, NSS_SHAPER_CONFIG_TYPE_SHAPER_NODE_STATS_SYNC_MANY);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	track(NSS_CONTROL_BASE_IF, 32, NSS_IF_ISHAPER_CONFIG, NSS_SHAPER_CONFIG_TYPE_SHAPER_NODE_STATS_SYNC_MANY);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	track(NSS_CONTROL_BASE_IF, 31, NSS_IF_BSHAPER_CONFIG, NSS_SHAPER_CONFIG_TYPE_SHAPER_NODE_STATS_SYNC_MANY);
	assert(!nss_if_short_stats_reply(&ctx, cm, HEAD));
	cm = reply(NSS_CMN_RESPONSE_ACK, NSS_IF_BSHAPER_CONFIG, 56, 0);
	assert(nss_if_short_stats_reply(&ctx, cm, HEAD));
	assert(!lock_depth && !nss_control_lock);
	return 0;
}
'''


def build(drv):
    control = (drv / 'nss_control.c').read_text()
    nss_if = (drv / 'nss_if.c').read_text()
    request = re.search(r'struct nss_control_request \{.*?\n\};\n', control, re.S).group(0)
    code = SHIM + request
    for name in ('nss_control_wire_callback', 'nss_control_valid', 'nss_control_request_copy'):
        code += extract.function(control, name)
    code += extract.function(nss_if, 'nss_if_short_stats_reply')
    return code + TEST


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--drv', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nss-short-stats-') as tmp:
        src, exe = Path(tmp) / 'test.c', Path(tmp) / 'test'
        src.write_text(build(args.drv))
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=20)
    print('PASS actual compact shaper stats reply: count-0 ACK accepted for its live '
          'STATS_SYNC_MANY request; short counts, rewritten len, NACK, other types, '
          'families, interfaces, cookies and request kinds rejected')


if __name__ == '__main__':
    main()
