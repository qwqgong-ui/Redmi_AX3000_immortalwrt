#!/usr/bin/env python3
"""Run the real DSA NSS topology collector across carrier and STP changes."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
helpers = runpy.run_path(str(ROOT / 'scripts/tests/test-nss-relay.py'))
source = (ROOT / 'package/kernel/qca-dsa-nss/src/qca_dsa_nss.c').read_text()
SHIM = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef uint16_t u16;
#define DSA_NSS_MAX_NODES 4
#define IFF_UP 1
#define ASSERT_RTNL() ((void)0)
struct list_head { int unused; };
struct net_device;
struct dsa_bridge { bool tx_fwd_offload, vlan; unsigned vbid; };
struct dsa_port { struct dsa_port *cpu_dp; struct net_device *conduit; struct dsa_bridge *bridge; unsigned index, stp_forwarding; };
struct net_device { struct dsa_port *dp; unsigned flags; bool running, vlan_upper; };
struct dsa_nss_want { struct net_device *dev, *conduit; u16 vid; };
static struct net_device *devs[4];
static int ndevs;
#define for_each_netdev(net, d) for (int _i = 0; _i < ndevs && ((d) = devs[_i]); _i++)
#define netdev_for_each_upper_dev_rcu(dev, upper, iter) \
	for ((upper) = (dev), (void)(iter); (upper) && (upper)->vlan_upper; (upper) = NULL)
static bool is_vlan_dev(struct net_device *d) { return d->vlan_upper; }
static struct dsa_port *port_of(struct net_device *dev) { return dev->dp; }
static struct dsa_bridge *dsa_port_bridge_dev_get(struct dsa_port *dp) { return dp->bridge; }
static bool br_vlan_enabled(struct dsa_bridge *br) { return br->vlan; }
static bool netif_running(struct net_device *d) { return d->running; }
static unsigned dsa_port_bridge_num_get(struct dsa_port *dp) { return dp->bridge->vbid; }
static u16 dsa_tag_8021q_bridge_vid(unsigned vbid) { return 1000 + vbid; }
static u16 dsa_tag_8021q_standalone_vid(struct dsa_port *dp) { return 3000 + dp->index; }
/* Kernel semantics: only LEARNING/FORWARDING members are designated. */
static struct net_device *dsa_tag_8021q_find_user(struct net_device *c, int p, int s, int vid, int vbid)
{
	for (int i = 0; i < ndevs; i++)
		if (devs[i]->dp->bridge && devs[i]->dp->stp_forwarding &&
		    devs[i]->dp->bridge->vbid == (unsigned)vbid)
			return devs[i];
	return NULL;
}
'''
TEST = r'''
int main(void) {
	struct net_device conduit = { .running = true };
	struct dsa_bridge br = { .tx_fwd_offload = true, .vbid = 1 };
	struct dsa_port cpu = { .conduit = &conduit };
	struct dsa_port p1 = { &cpu, NULL, &br, 1, 0 }, p2 = { &cpu, NULL, &br, 2, 0 }, p3 = { &cpu, NULL, NULL, 3, 0 };
	struct net_device lan1 = { &p1, IFF_UP }, lan2 = { &p2, IFF_UP }, wan = { &p3, IFF_UP };
	struct dsa_nss_want want[DSA_NSS_MAX_NODES];
	devs[0] = &lan1; devs[1] = &lan2; devs[2] = &wan; ndevs = 3;

	p1.stp_forwarding = 1;
	assert(collect(want) == 2);
	assert(want[0].dev == &lan1 && want[0].vid == 1001 && want[0].conduit == &conduit);
	assert(want[1].dev == &wan && want[1].vid == 3003);

	p1.stp_forwarding = 0;
	assert(collect(want) == 2 && want[0].dev == &lan1);

	p2.stp_forwarding = 1;
	assert(collect(want) == 2 && want[0].dev == &lan1);

	lan1.flags = 0;
	assert(collect(want) == 2 && want[0].dev == &lan2);

	conduit.running = false;
	assert(collect(want) == -EAGAIN);
	conduit.running = true;
	br.vlan = true;
	assert(collect(want) == -EOPNOTSUPP);
	return 0;
}
'''
helpers['c_test']('actual DSA NSS collect: bridge node anchor survives carrier loss and STP changes',
                  SHIM + helpers['function'](source, 'collect') + TEST)
