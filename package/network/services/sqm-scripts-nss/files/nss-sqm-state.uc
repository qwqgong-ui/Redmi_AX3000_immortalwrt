// SPDX-License-Identifier: GPL-2.0-only
// Observations can skip work. Repairs always recheck state under SQM's run lock.
export function create(io) {
	const dir = io.state_dir;
	const bindings = `${dir}/nss-bindings`;
	// ucode evaluates regexp literals with regcomp(), so compile once per daemon.
	const interface_pattern = /^[a-zA-Z0-9_.:@-]+$/;
	const section_pattern = /^[a-zA-Z0-9_]+$/;
	const binding_pattern = /^([a-zA-Z0-9_.:@-]+)[ \t]+([0-9]+)$/;
	const whitespace_pattern = /\s+/;
	const true_values = ['1', 'on', 'true', 'yes', 'enabled'];
	const scripts = ['nss-fq.qos', 'nss-edma.qos'];
	const enabled = value => index(true_values, `${value}`) >= 0;
	const interface_name = value => type(value) == 'string' && length(value) <= 15 && match(value, interface_pattern);
	const section_name = value => type(value) == 'string' && length(value) <= 64 && match(value, section_pattern);
	function read_binding(name) {
		let line = io.read(`${bindings}/${name}`);
		let fields = type(line) == 'string' ? match(trim(line), binding_pattern) : null;
		return fields && interface_name(fields[1]) && +fields[2] > 0 ? { iface: fields[1], index: +fields[2] } : null;
	}
	function stop(name) {
		let binding = read_binding(name);
		if (binding && io.run('nss-stop', binding.iface) != 0)
			return false;
		io.unlink(`${bindings}/${name}`);
		return true;
	}
	function cleanup() {
		let complete = true;
		for (let name in io.names(bindings) ?? [])
			if (section_name(name) && !stop(name))
				complete = false;
		return complete;
	}
	function pass() {
		if (io.exists(`${dir}/sqm-run.lock`))
			return true;
		let sections = io.config();
		let roots = io.roots();
		if (type(sections) != 'array' || type(roots) != 'array')
			return false;
		let seen = {}, indices = {}, wireless_devices = {};
		function ifindex(iface) {
			if (indices[iface] == null) indices[iface] = io.ifindex(iface);
			return indices[iface];
		}
		function is_wireless(iface) {
			if (wireless_devices[iface] == null) wireless_devices[iface] = io.wireless(iface);
			return wireless_devices[iface];
		}
		let network, wireless, network_loaded = false, wireless_loaded = false;
		let service_enabled = io.enabled();
		let core_ready = trim(io.read('/sys/module/qca_nss_drv/parameters/core0_ready') ?? '') == '1';
		let dsa_ready = trim(io.read('/sys/module/qca_dsa_nss/parameters/ready') ?? '') == 'Y';
		function root_present(iface, kind, handle) {
			let idx = ifindex(iface);
			for (let root in roots)
				if (idx > 0 && root.ifindex == idx && root.parent == 0xffffffff &&
				    root.kind == kind && (handle == null || root.handle == handle))
					return true;
			return false;
		}
		function healthy(section, iface) {
			if (!io.exists(`${dir}/${iface}.state`))
				return false;
			if (section.script == 'nss-fq.qos')
				return root_present(iface, 'nssfq_codel', 0x100000);
			if (!is_wireless(iface))
				return true; // EDMA's physical root belongs to its conduit.
			if (+section.upload > 0 && !root_present(iface, 'nsstbl'))
				return false;
			return !(+section.download > 0) || root_present(substr(`ifb@${iface}`, 0, 15), 'nsstbl');
		}
		for (let section in sections) {
			let name = section['.name'];
			if (!section_name(name) || index(scripts, section.script) < 0 ||
			    !(section.network || section.wireless_interface || enabled(section.nss_watch)))
				continue;
			seen[name] = true;
			if (io.exists(`${dir}/sqm-run.lock`))
				continue;
			if (!enabled(section.enabled) || !service_enabled) {
				stop(name);
				continue;
			}
			let iface = section.interface;
			if (section.network) {
				if (!network_loaded) {
					network = io.network();
					network_loaded = true;
				}
				if (type(network?.interface) != 'array')
					continue;
				iface = null;
				for (let row in network.interface)
					if (row.interface == section.network && row.up)
						iface = row.l3_device;
			} else if (section.wireless_interface) {
				if (!section_name(section.wireless_interface))
					continue;
				if (!wireless_loaded) {
					wireless = io.wireless_status();
					wireless_loaded = true;
				}
				if (type(wireless) != 'object')
					continue;
				iface = null;
				for (let key in keys(wireless))
					for (let row in wireless[key].interfaces ?? [])
						if (row.section == section.wireless_interface)
							iface = row.ifname;
			}
			if (!interface_name(iface) || !(ifindex(iface) > 0)) {
				stop(name);
				continue;
			}
			let idx = ifindex(iface);
			let old = read_binding(name);
			if (old && (old.iface != iface || old.index != idx) && !stop(name))
				continue;
			if (!core_ready || (!is_wireless(iface) && !dsa_ready))
				continue;
			if (section.interface != iface && !io.set_interface(name, iface))
				continue;
			let repair_denied = false;
			if (section.script == 'nss-edma.qos' && is_wireless(iface) && +section.download > 0) {
				let denied = io.read('/proc/sys/net/ecm/interface_denied_list');
				repair_denied = denied != null && index(split(trim(denied), whitespace_pattern), iface) < 0;
			}
			if (!old || old.iface != iface || old.index != idx || !healthy(section, iface) || repair_denied) {
				if (io.run('nss-reconcile', iface) != 0 || io.ifindex(iface) != idx)
					continue;
			}
			if (!io.exists(`${dir}/${iface}.state`))
				continue;
			if (!old || old.iface != iface || old.index != idx)
				io.write_binding(`${bindings}/${name}`, `${iface} ${idx}\n`);
		}
		for (let name in io.names(bindings) ?? [])
			if (section_name(name) && !seen[name])
				stop(name);
		return true;
	}
	return { pass, cleanup };
};
