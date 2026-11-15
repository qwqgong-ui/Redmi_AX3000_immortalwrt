import { create } from 'MODULE';
function check(value, text) { if (!value) die(`FAIL: ${text}\n`); }
let env;
function reset() {
	env = {
		files: {
			'/sys/module/qca_nss_drv/parameters/core0_ready': '1\n',
			'/sys/module/qca_dsa_nss/parameters/ready': 'Y\n',
			'/state/phy1-sta0.state': 'state', '/state/phy0-ap0.state': 'state', '/state/eth1.state': 'state',
			'/proc/sys/net/ecm/interface_denied_list': 'phy1-sta0\n',
		},
		sections: [
			{ '.name': 'wan', enabled: '1', script: 'nss-fq.qos', interface: 'phy1-sta0', network: 'wwan' },
			{ '.name': 'ap', enabled: '1', script: 'nss-fq.qos', interface: 'phy0-ap0', wireless_interface: 'default_radio0' },
			{ '.name': 'lan', enabled: '1', script: 'nss-fq.qos', interface: 'eth1', nss_watch: '1' },
		],
		roots: [
			{ ifindex: 10, parent: 0xffffffff, handle: 0x100000, kind: 'nssfq_codel' },
			{ ifindex: 11, parent: 0xffffffff, handle: 0x100000, kind: 'nssfq_codel' },
			{ ifindex: 12, parent: 0xffffffff, handle: 0x100000, kind: 'nssfq_codel' },
		],
		indices: { 'phy1-sta0': 10, 'phy0-ap0': 11, eth1: 12, 'ifb@phy1-sta0': 13 },
		network: { interface: [{ interface: 'wwan', up: true, l3_device: 'phy1-sta0' }] },
		wireless: { radio0: { interfaces: [{ section: 'default_radio0', ifname: 'phy0-ap0' }] } },
		enabled: true, busy: false, writes: 0, queries: {}, calls: [],
	};
	return create({
		state_dir: '/state',
		read: path => env.files[path] ?? null,
		exists: path => env.files[path] != null,
		names: path => map(filter(keys(env.files), name => index(name, `${path}/`) == 0), name => substr(name, length(path) + 1)),
		unlink: path => delete env.files[path],
		ifindex: iface => env.indices[iface] ?? 0,
		wireless: iface => index(iface, 'phy') == 0,
		enabled: () => env.enabled,
		config: () => { env.queries.config = (env.queries.config ?? 0) + 1; return env.sections; },
		roots: () => { env.queries.roots = (env.queries.roots ?? 0) + 1; return env.roots; },
		network: () => { env.queries.network = (env.queries.network ?? 0) + 1; return env.network; },
		wireless_status: () => { env.queries.wireless = (env.queries.wireless ?? 0) + 1; return env.wireless; },
		set_interface: (section, iface) => { die('unexpected persistent interface change\n'); },
		write_binding: (path, text) => { env.files[path] = text; env.writes++; return true; },
		run: (action, iface) => {
			push(env.calls, [action, iface]);
			if (env.busy) return 75;
			check(index(['nss-stop', 'nss-reconcile'], action) >= 0, 'NSS-only runner actions');
			if (action == 'nss-stop') {
				delete env.files[`/state/${iface}.state`];
			} else {
				env.files[`/state/${iface}.state`] = 'state';
				push(env.roots, { ifindex: env.indices[iface], parent: 0xffffffff, handle: 0x100000, kind: 'nssfq_codel' });
				env.files['/proc/sys/net/ecm/interface_denied_list'] = 'phy1-sta0\n';
			}
			return 0;
		},
	});
}
let watch = reset();
check(watch.pass(), 'initial pass');
check(length(env.calls) == 3 && env.writes == 3, 'adopt existing owned roots once');
let before = length(env.calls), writes = env.writes;
env.queries = {};
for (let i = 0; i < 100; i++) check(watch.pass(), 'stable pass');
check(length(env.calls) == before && env.writes == writes, 'zero idle children and binding rewrites');
for (let key in ['config', 'roots', 'network', 'wireless'])
	check(env.queries[key] == 100, `one ${key} snapshot per pass`);
env.files['/state/sqm-run.lock'] = 'busy';
env.roots = [];
watch.pass();
check(length(env.calls) == before, 'partial owner publication untouched');
delete env.files['/state/sqm-run.lock'];
env.roots = null;
check(!watch.pass() && length(env.calls) == before, 'failed root observation is not a missing root');
env.roots = [{ ifindex: 10, parent: 0xffffffff, handle: 0x100000, kind: 'nssfq_codel' },
	{ ifindex: 12, parent: 0xffffffff, handle: 0x100000, kind: 'nssfq_codel' }];
watch.pass();
check(length(env.calls) == before + 1 && env.calls[-1][1] == 'phy0-ap0', 'only missing AP root repaired');
before = length(env.calls);
env.indices['phy1-sta0'] = 20;
watch.pass();
check(length(env.calls) == before + 2 && env.calls[before][0] == 'nss-stop', 'same-name ifindex replacement');
check(env.files['/state/nss-bindings/wan'] == 'phy1-sta0 20\n', 'new instance published');
before = length(env.calls);
env.network = null; env.wireless = null;
watch.pass();
check(length(env.calls) == before, 'failed ubus observation preserves bindings');
env.network = { interface: [{ interface: 'wwan', up: false }] };
watch.pass();
check(length(env.calls) == before + 1 && env.files['/state/nss-bindings/wan'] == null, 'confirmed disconnect cleans owned binding');
env.enabled = false; env.busy = true;
watch.pass();
check(env.files['/state/nss-bindings/ap'] != null && env.files['/state/nss-bindings/lan'] != null, 'busy disable retains bindings');
env.busy = false;
watch.pass();
check(env.files['/state/nss-bindings/ap'] == null && env.files['/state/nss-bindings/lan'] == null, 'disabled service cleanup');

watch = reset(); watch.pass();
before = length(env.calls);
env.sections = filter(env.sections, section => section['.name'] != 'ap');
watch.pass();
check(length(env.calls) == before + 1 && env.calls[-1][0] == 'nss-stop', 'removed section cleanup');
env.sections = null; before = length(env.calls);
check(!watch.pass() && length(env.calls) == before, 'unreadable config retains bindings');

watch = reset(); watch.pass();
env.sections[0].script = 'nss-edma.qos'; env.sections[0].upload = '0'; env.sections[0].download = '1000';
env.roots = filter(env.roots, root => root.ifindex != 10);
push(env.roots, { ifindex: 13, parent: 0xffffffff, handle: 0x10000, kind: 'nsstbl' });
before = length(env.calls); watch.pass();
check(length(env.calls) == before, 'ingress-only source VIF needs no egress root');
env.files['/proc/sys/net/ecm/interface_denied_list'] = '';
watch.pass();
check(length(env.calls) == before + 1, 'ECM reset repaired by locked runner');
env.sections[2].script = 'nss-edma.qos';
env.roots = filter(env.roots, root => root.ifindex != 12);
before = length(env.calls); watch.pass();
check(length(env.calls) == before, 'DSA root belongs to conduit');
env.files['/sys/module/qca_dsa_nss/parameters/ready'] = 'N';
delete env.files['/state/eth1.state'];
watch.pass();
check(length(env.calls) == before, 'DSA readiness gate');
env.files['/sys/module/qca_nss_drv/parameters/core0_ready'] = '0';
delete env.files['/state/phy0-ap0.state'];
watch.pass();
check(length(env.calls) == before, 'NSS readiness gate');
env.busy = true;
check(!watch.cleanup() && env.files['/state/nss-bindings/ap'] != null, 'TERM busy ownership retained');
env.busy = false;
check(watch.cleanup(), 'TERM owned cleanup');
print('PASS native SQM: 100 idle passes without runner/file writes; shared snapshots, ownership locks, transient failures, VIF identity, missing roots, ingress-only/DSA, disabled/deleted cleanup and ECM repair\n');
