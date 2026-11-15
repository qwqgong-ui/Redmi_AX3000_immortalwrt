// SPDX-License-Identifier: GPL-2.0-only
// Observe current owners; the one-shot sender independently rechecks the route.
export function create(io) {
	let states = {};
	const iface_pattern = /^[a-zA-Z0-9_.-]+$/;
	const mac_pattern = /^[0-9a-fA-F][02468aAcCeE](:[0-9a-fA-F]{2}){5}$/;
	const ip_pattern = /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/;
	function mac(value) {
		return type(value) == 'string' && length(value) == 17 &&
			value != '00:00:00:00:00:00' && match(value, mac_pattern) ? lc(value) : null;
	}
	function ip(value) {
		if (type(value) != 'string' || !match(value, ip_pattern)) return null;
		let bytes = split(value, '.');
		for (let byte in bytes) if (+byte > 255) return null;
		return ((+bytes[0] << 24) | (+bytes[1] << 16) | (+bytes[2] << 8) | +bytes[3]);
	}
	function status(text) {
		if (type(text) != 'string') return null;
		let values = {};
		for (let line in split(text, '\n')) {
			let at = index(line, '=');
			if (at > 0) {
				let key = substr(line, 0, at);
				values[key] ??= trim(substr(line, at + 1));
			}
		}
		return values;
	}
	function identity(iface, connection, tables) {
		let link = io.link(iface), route, address, neighbor;
		if (!link || !(link.index > 0) || !link.up || !mac(link.mac)) return null;
		for (let r in tables.routes)
			if (r.family == 2 && r.table == 254 && r.type == 1 && r.oif == iface &&
				(!r.dst || r.dst == '0.0.0.0/0') && r.gateway &&
				(!route || (r.priority ?? 0) <= (route.priority ?? 0))) route = r;
		if (!route) return null;
		for (let a in tables.addresses)
			if (a.family == 2 && a.dev == iface && !(a.flags & 1) &&
				(!a.label || a.label == iface)) { address = a; break; }
		if (!address) return null;
		let local_ip = ip(address.local), gateway = ip(route.gateway);
		let prefix = int(split(address.address ?? '', '/')[1]);
		if (local_ip == null || gateway == null || !local_ip || !gateway ||
			prefix == null || prefix < 1 || prefix > 32 || local_ip == gateway ||
			(local_ip >> (32 - prefix)) != (gateway >> (32 - prefix))) return null;
		for (let n in tables.neighbors)
			if (n.family == 2 && n.dev == iface && n.dst == route.gateway &&
				(n.state & 0xde) && mac(n.lladdr)) { neighbor = n; break; }
		if (!neighbor) return null;
		return join(' ', [link.index, connection.bssid, address.local, prefix,
			route.gateway, mac(neighbor.lladdr), mac(link.mac)]);
	}
	function pass() {
		if (!io.ready()) { states = {}; return true; }
		let objects = io.objects();
		if (type(objects) != 'array') return false;
		let seen = {}, candidates = [], valid = true;
		for (let object in objects) {
			if (index(object, 'wpa_supplicant.') != 0) continue;
			let iface = substr(object, 15);
			if (!length(iface) || length(iface) > 15 || !match(iface, iface_pattern)) continue;
			seen[iface] = true;
			let s = status(io.status(object));
			if (s == null) { valid = false; continue; }
			if (s.mode != 'station' || s.wpa_state != 'COMPLETED' ||
				!(+s.freq >= 5000 && +s.freq < 6000) || !mac(s.bssid)) {
				delete states[iface]; continue;
			}
			s.bssid = mac(s.bssid);
			push(candidates, { iface, connection: s });
		}
		for (let iface in keys(states)) if (!seen[iface]) delete states[iface];
		if (!length(candidates)) return valid;
		let tables = io.tables();
		if (type(tables?.routes) != 'array' || type(tables?.addresses) != 'array' ||
			type(tables?.neighbors) != 'array') return false;
		let now = io.now();
		for (let candidate in candidates) {
			let iface = candidate.iface, key = identity(iface, candidate.connection, tables);
			if (key == null) { delete states[iface]; continue; }
			let state = states[iface];
			if (!state || state.key != key) state = states[iface] = { key, last: -1, attempt: -30 };
			if ((state.last < 0 || now - state.last >= 300) && now - state.attempt >= 30) {
				state.attempt = now;
				if (io.refresh(iface) == 0) state.last = now;
			}
		}
		return valid;
	}
	function link_event(iface, flags, removed) {
		// rtnl DT_FLAGS returns [value, change-mask] when ifi_change is set.
		if (type(flags) == 'array') flags = flags[0];
		if (removed || !(flags & 0x10000)) delete states[iface];
	}
	return { pass, link_event };
};
