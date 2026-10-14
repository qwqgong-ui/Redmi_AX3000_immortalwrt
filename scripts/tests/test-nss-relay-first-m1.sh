#!/bin/sh
set -eu
. "${1:?path to nss-relay-state.sh required}"
reset_case() {
	nr_now=10000 nr_since=0 nr_attempts=0 nr_window=0 nr_last_id=- nr_last_bssid=-
	nr_state=ASSOCIATED nr_key=WPA2-PSK nr_mode=station nr_freq=5745 nr_id=0
	nr_bssid=f4:2a:7d:ab:24:4c
	nr_seen=0 nr_index=11 nr_last_index=0
}
reset_case
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_since" = 10000 ]
for nr_now in 10025 10050 10075; do
	nss_relay_decide
	[ -z "$nr_action" ]
done
nr_now=10100
nss_relay_decide
[ "$nr_action" = leave ] && [ "$nr_attempts" = 1 ]

# Received M1, GTK exchange and completed sessions cannot trigger the policy.
for nr_test_state in 4WAY_HANDSHAKE GROUP_HANDSHAKE COMPLETED SCANNING AUTHENTICATING; do
	reset_case
	nr_since=9000 nr_state=$nr_test_state
	nss_relay_decide
	[ -z "$nr_action" ] && [ "$nr_since" = 0 ]
done
for nr_test_key in WPA2-EAP WPA2-PSK-SHA256 SAE FT-PSK; do
	reset_case
	nr_since=9000 nr_key=$nr_test_key
	nss_relay_decide
	[ -z "$nr_action" ]
done
reset_case
nr_since=9000 nr_freq=2462
nss_relay_decide
[ -z "$nr_action" ]
reset_case
nr_since=9000 nr_mode=AP
nss_relay_decide
[ -z "$nr_action" ]

# Interface recreation/network or BSSID change starts a fresh observation.
reset_case
nr_since=9000 nr_last_id=0 nr_last_bssid=$nr_bssid nr_id=1
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_since" = 10000 ]
reset_case
nr_since=9000 nr_last_id=0 nr_last_bssid=00:11:22:33:44:55
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_since" = 10000 ]

# At most three explicit retries in a 120-second window; success resets it.
reset_case
nr_last_id=0 nr_last_bssid=$nr_bssid nr_window=9500 nr_attempts=3 nr_since=9000
nr_seen=10000 nr_last_index=11
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_attempts" = 3 ]
nr_now=21500
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_since" = 21500 ]
nr_now=21600
nss_relay_decide
[ "$nr_action" = leave ] && [ "$nr_attempts" = 1 ]
nr_state=COMPLETED
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_attempts" = 0 ]

# Missed observations and same-name netdev recreation cannot reuse old age.
reset_case
nr_since=9000 nr_seen=9700 nr_last_id=0 nr_last_bssid=$nr_bssid nr_last_index=11
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_since" = 10000 ]
reset_case
nr_since=9000 nr_seen=9900 nr_last_id=0 nr_last_bssid=$nr_bssid nr_last_index=10
nss_relay_decide
[ -z "$nr_action" ] && [ "$nr_since" = 10000 ]

# Invalid externally parsed fields must not become control commands.
reset_case
nr_id='0;reboot' nr_since=9000
nss_relay_decide
[ -z "$nr_action" ]
reset_case
nr_now='100:1'
if nss_relay_decide; then exit 1; fi
printf '%s\n' 'PASS initial-M1 only, ongoing/enterprise/other-band protection, peer changes, retry budget and malformed fields'
