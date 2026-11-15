#!/usr/bin/ucode
// SPDX-License-Identifier: GPL-2.0-only
import * as fs from 'fs';
import * as ubus from 'ubus';
import * as rtnl from 'rtnl';
import * as uloop from 'uloop';
import { create } from './nss-neighbor-state.uc';

const check_only = index(ARGV, '--check') >= 0;
const lock = check_only ? null : fs.open('/var/run/nss-neighbor.lock', 'ae');
if (!check_only && (!lock || !lock.lock('xn'))) exit(0);
uloop.init();
let bus, planned = [];
function connect() { bus ??= ubus.connect(null, 2); return bus; }
function dump(cmd) { return rtnl.request(cmd, rtnl.const.NLM_F_DUMP, { family: 2 }); }
const watcher = create({
	ready: () => trim(fs.readfile('/sys/module/ath11k/parameters/nss_offload') ?? '') == '1' &&
		trim(fs.readfile('/sys/module/qca_nss_drv/parameters/core0_ready') ?? '') == '1',
	objects: () => connect()?.list(),
	status: object => connect()?.call(object, 'control', { command: 'STATUS' })?.result,
	tables: () => ({ routes: dump(rtnl.const.RTM_GETROUTE),
		addresses: dump(rtnl.const.RTM_GETADDR), neighbors: dump(rtnl.const.RTM_GETNEIGH) }),
	link: iface => ({ index: +(fs.readfile(`/sys/class/net/${iface}/ifindex`) ?? 0),
		up: trim(fs.readfile(`/sys/class/net/${iface}/carrier`) ?? '') == '1',
		mac: trim(fs.readfile(`/sys/class/net/${iface}/address`) ?? '') }),
	now: () => int(fs.readfile('/proc/uptime')),
	refresh: iface => {
		if (check_only) { push(planned, iface); return 0; }
		return system(['/usr/lib/nss-relay-neighbor', iface]);
	},
});
if (check_only) {
	let valid = watcher.pass();
	bus?.disconnect();
	printf('%J\n', { valid, planned });
	exit(valid ? 0 : 1);
}
let warned = false, timer;
timer = uloop.timer(1, () => {
	try {
		if (!watcher.pass()) die('incomplete ubus or rtnetlink snapshot');
		warned = false;
	} catch (e) {
		if (!warned) warn(`NSS neighbor observation failed: ${e}\n`);
		warned = true;
	}
	bus?.disconnect(); bus = null;
	timer.set(5000);
});
// A short disconnect/reconnect can otherwise fit entirely between two polls.
const listener = rtnl.listener(event => {
	let msg = event.msg;
	if (msg?.dev)
		watcher.link_event(msg.dev, msg.flags, event.cmd == rtnl.const.RTM_DELLINK);
}, [rtnl.const.RTM_NEWLINK, rtnl.const.RTM_DELLINK], [rtnl.const.RTNLGRP_LINK]);
if (!listener) die('Unable to observe link transitions\n');
const signals = [uloop.signal('TERM', () => uloop.end()), uloop.signal('INT', () => uloop.end())];
uloop.run();
