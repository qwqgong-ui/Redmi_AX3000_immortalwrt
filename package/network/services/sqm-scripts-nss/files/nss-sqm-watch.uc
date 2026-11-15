#!/usr/bin/ucode
// SPDX-License-Identifier: GPL-2.0-only
import * as fs from 'fs';
import * as ubus from 'ubus';
import * as uci from 'uci';
import * as rtnl from 'rtnl';
import * as uloop from 'uloop';
import { create } from './nss-sqm-state.uc';

const check_only = index(ARGV, '--check') >= 0;
let planned = [], observed_roots;
const lock = check_only ? null : fs.open('/var/run/nss-sqm-watch.lock', 'ae');
if (!check_only && (!lock || !lock.lock('xn')))
	exit(0);
// Preserve the existing sqm.conf shell interface once at startup, never per poll.
const config = fs.popen('. /etc/sqm/sqm.conf; printf "%s" "$SQM_STATE_DIR"', 'r');
const state_dir = config ? trim(config.read('all') ?? '') : '';
if (!config || config.close() != 0 || !match(state_dir, /^\/[^\r\n]+$/))
	die('Unable to read SQM_STATE_DIR\n');
if (!check_only) {
	fs.mkdir(state_dir, 0700);
	fs.mkdir(`${state_dir}/nss-bindings`, 0700);
}

uloop.init();
const cursor = uci.cursor();
let bus;
const boot_pattern = /^S[0-9][0-9]sqm$/;
function call(object, method) {
	bus ??= ubus.connect(null, 2);
	return bus ? bus.call(object, method, {}) : null;
}
const watcher = create({
	state_dir,
	read: path => fs.readfile(path),
	exists: path => fs.stat(path) != null,
	names: path => fs.lsdir(path),
	unlink: path => fs.unlink(path),
	ifindex: name => +(fs.readfile(`/sys/class/net/${name}/ifindex`) ?? 0),
	wireless: name => fs.stat(`/sys/class/net/${name}/phy80211`) != null,
	enabled: () => {
		for (let name in fs.lsdir('/etc/rc.d') ?? [])
			if (match(name, boot_pattern) && fs.readlink(`/etc/rc.d/${name}`) != null)
				return true;
		return false;
	},
	config: () => {
		cursor.unload('sqm');
		if (!cursor.load('sqm'))
			return null;
		let result = [];
		cursor.foreach('sqm', 'queue', section => push(result, section));
		return result;
	},
	set_interface: (section, iface) => {
		if (check_only) { push(planned, ['set-interface', section, iface]); return false; }
		return cursor.set('sqm', section, 'interface', iface) && cursor.save('sqm');
	},
	network: () => call('network.interface', 'dump'),
	wireless_status: () => call('network.wireless', 'status'),
	roots: () => {
		observed_roots = rtnl.request(rtnl.const.RTM_GETQDISC, rtnl.const.NLM_F_DUMP, {});
		return observed_roots;
	},
	run: (action, iface) => {
		if (check_only) { push(planned, [action, iface]); return 75; }
		return system(['/usr/lib/sqm/run.sh', action, iface]);
	},
	write_binding: (path, text) => {
		if (check_only) { push(planned, ['binding', path]); return false; }
		let tmp = `${path}.tmp`;
		if (fs.writefile(tmp, text) == length(text))
			return fs.rename(tmp, path);
		fs.unlink(tmp);
		return false;
	},
});
if (check_only) {
	let valid = watcher.pass();
	bus?.disconnect();
	printf('%J\n', { valid, roots: observed_roots, planned });
	exit(valid ? 0 : 1);
}
let stopping = false, stop_attempts = 0, warned = false;
let timer;
timer = uloop.timer(1, () => {
	try {
		if (stopping) {
			if (watcher.cleanup() || ++stop_attempts >= 30) {
				if (stop_attempts >= 30)
					warn('SQM owner remains busy; bindings preserved for the next owner\n');
				uloop.end();
				return;
			}
		} else {
			watcher.pass();
		}
		warned = false;
	} catch (e) {
		if (!warned)
			warn(`NSS SQM observation failed: ${e}\n`);
		warned = true;
	}
	bus?.disconnect();
	bus = null;
	timer.set(stopping ? 200 : 5000);
});
const signals = [
	uloop.signal('HUP', () => timer.set(1)),
	uloop.signal('TERM', () => { stopping = true; timer.set(1); }),
	uloop.signal('INT', () => { stopping = true; timer.set(1); }),
];
uloop.run();
