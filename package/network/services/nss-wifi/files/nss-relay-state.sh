#!/bin/sh
# Numerical control state only. No traffic shaping or bandwidth settings.
# Times are monotonic centiseconds; the caller persists per-netdev state.
nss_relay_decide() {
	nr_action=
	local nr_value
	for nr_value in "$nr_now" "$nr_since" "$nr_attempts" "$nr_window" "$nr_seen" "$nr_index" "$nr_last_index"; do
		case "$nr_value" in ''|*[!0-9]*) return 1 ;; esac
	done
	if [ "$nr_seen" = 0 ] || [ $((nr_now - nr_seen)) -gt 200 ] ||
	   [ "$nr_index" != "$nr_last_index" ]; then
		nr_since=0
	fi
	nr_seen=$nr_now
	nr_last_index=$nr_index
	if [ "$nr_window" = 0 ] || [ $((nr_now - nr_window)) -ge 12000 ]; then
		nr_window=$nr_now
		nr_attempts=0
	fi
	if [ "$nr_state" = COMPLETED ]; then
		nr_since=0
		nr_attempts=0
		return 0
	fi
	# EAP, SAE and FT exchanges can legitimately spend time in ASSOCIATED.
	if [ "$nr_state" != ASSOCIATED ] || [ "$nr_key" != WPA2-PSK ] ||
	   [ "$nr_mode" != station ]; then
		nr_since=0
		return 0
	fi
	case "$nr_freq" in [0-9][0-9][0-9][0-9]) ;; *) nr_since=0; return 0 ;; esac
	case "$nr_id" in ''|*[!0-9]*) nr_since=0; return 0 ;; esac
	[ -n "$nr_bssid" ] || { nr_since=0; return 0; }
	if [ "$nr_freq" -lt 5000 ] || [ "$nr_freq" -ge 6000 ]; then
		nr_since=0
		return 0
	fi
	if [ "$nr_id" != "$nr_last_id" ] || [ "$nr_bssid" != "$nr_last_bssid" ]; then
		nr_since=0
		nr_last_id=$nr_id
		nr_last_bssid=$nr_bssid
	fi
	if [ "$nr_since" = 0 ]; then
		nr_since=$nr_now
	elif [ $((nr_now - nr_since)) -ge 100 ] && [ "$nr_attempts" -lt 3 ]; then
		nr_action=leave
		nr_attempts=$((nr_attempts + 1))
		nr_since=0
	fi
}
