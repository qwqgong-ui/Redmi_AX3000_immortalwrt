#!/usr/bin/env python3
"""Preview or apply three unbounded NSS hardware FQ queues."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=('preview', 'apply'), nargs='?', default='preview')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
os.umask(0o077)
args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=4', '-o', 'BindInterface=eno1',
       '-o', 'ControlMaster=no', '-o', 'ControlPath=none', 'root@192.168.1.1']
scp = ['scp', '-B', '-O', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
       '-o', 'BindInterface=eno1']

def remote(command, timeout=12):
    result = subprocess.run(ssh + [command], text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Router command failed: ' + result.stderr.strip())
    return result.stdout.strip()

def parse_uci(text):
    result = {}
    for line in text.splitlines():
        key, value = line.split('=', 1)
        result[key] = shlex.split(value)
    return result

def safe_device(name):
    assert re.fullmatch(r'[a-zA-Z0-9_.:@-]{1,15}', name), 'Invalid netdev name'
    return name

owned = ('nss_wwan', 'nss_ap', 'nss_lan')
before = remote('uci -q show sqm')
before_values = parse_uci(before)
for key, value in before_values.items():
    if key.endswith('.enabled') and value == ['1']:
        assert key.split('.')[1] in owned, 'Another enabled SQM queue needs reconciliation'
wan = json.loads(remote('ubus call network.interface.wwan status'))
assert wan.get('up'), 'Wireless WAN is not up'
wan_device = safe_device(wan['l3_device'])
wireless = json.loads(remote('ubus call network.wireless status'))
ap = next(interface for radio in wireless.values() for interface in radio.get('interfaces', [])
          if interface.get('section') == 'default_radio0')
ap_device = safe_device(ap['ifname'])
for parameter in ('/sys/module/qca_nss_drv/parameters/core0_ready',
                  '/sys/module/ath11k/parameters/nss_offload'):
    assert remote('cat ' + parameter) == '1', 'NSS hardware offload is not ready'
assert not remote('cat /proc/sys/net/ecm/interface_denied_list').split()
for parameter in ('/sys/kernel/debug/ecm/front_end_ipv4_stop',
                  '/sys/kernel/debug/ecm/front_end_ipv6_stop'):
    assert remote('cat ' + parameter) == '0', 'ECM acceleration must remain enabled'
remote('test -r /usr/lib/sqm/nss-fq.qos && test -x /etc/init.d/nss-sqm')

# Keep unrelated stanzas byte-for-byte. Replace only the three owned queues.
old = remote('cat /etc/config/sqm') + '\n'
retained = []
skip = False
for line in old.splitlines(keepends=True):
    tokens = shlex.split(line, comments=True)
    if tokens and tokens[0] == 'config':
        skip = len(tokens) >= 3 and tokens[2] in owned
    if not skip:
        retained.append(line)
common = {'enabled': '1', 'qdisc': 'nssfq_codel', 'script': 'nss-fq.qos',
          'upload': '0', 'download': '0', 'elimit': '128', 'etarget': '5ms',
          'linklayer': 'none', 'use_mq': '0', 'debug_logging': '0', 'verbosity': '5'}
bindings = {'nss_wwan': {'interface': wan_device, 'network': 'wwan'},
            'nss_ap': {'interface': ap_device, 'wireless_interface': 'default_radio0'},
            'nss_lan': {'interface': 'eth1', 'nss_watch': '1'}}
candidate = ''.join(retained).rstrip() + '\n\n'
for section in owned:
    candidate += "config queue '" + section + "'\n"
    for key, value in (common | bindings[section]).items():
        candidate += '\toption ' + key + ' ' + shlex.quote(value) + '\n'
    candidate += '\n'
delimiter = 'NSS_FQ_' + secrets.token_hex(16)
assert delimiter not in candidate.splitlines()
def write_candidate(destination):
    return 'cat > ' + destination + " <<'" + delimiter + "'\n" + candidate + delimiter + '\n'

preview = remote('''set -eu
umask 077
nss_preview_dir=$(mktemp -d /tmp/nss-fq-preview.XXXXXX)
trap 'rm -rf "$nss_preview_dir"' EXIT
mkdir "$nss_preview_dir/delta"
''' + write_candidate('"$nss_preview_dir/sqm"') + '''
uci -c "$nss_preview_dir" -P "$nss_preview_dir/delta" show sqm
''')
values = parse_uci(preview)
for section in owned:
    assert values['sqm.' + section] == ['queue']
    for key, value in (common | bindings[section]).items():
        assert values['sqm.' + section + '.' + key] == [value]
for key, value in before_values.items():
    if key.split('.')[1] not in owned:
        assert values[key] == value, 'Unrelated SQM options changed in preview'
(args.output / 'sqm-preview.conf').write_text(candidate)
(args.output / 'sqm-preview-uci.log').write_text(preview + '\n')
print('PASS router UCI preview: three hardware FQ queues, upload/download zero, owned bindings', flush=True)
if args.action == 'preview':
    assert remote('uci -q show sqm') == before, 'Live SQM changed during preview'
    print('PASS live SQM unchanged; no queue/service mutation performed', flush=True)
    raise SystemExit()

stamp = str(time.time_ns())
backup_name = '/tmp/nss-fq-before-' + stamp + '.tar.gz'
remote('sysupgrade -b ' + backup_name, 30)
subprocess.run(scp + ['root@192.168.1.1:' + backup_name,
                      str(args.output / ('config-before-fq-' + stamp + '.tar.gz'))],
               check=True, timeout=30)
old_wireless_hash = remote('sha256sum /etc/config/wireless')
program = '''set -eu
/etc/init.d/nss-sqm stop
/etc/init.d/sqm stop
umask 077
''' + write_candidate('/etc/config/sqm') + '''
uci set wireless.default_radio0.wmm='1'
uci set wireless.wifinet1.wmm='1'
uci commit wireless
uci commit sqm
/etc/init.d/sqm enable
/etc/init.d/nss-sqm enable
/etc/init.d/sqm start
/etc/init.d/nss-sqm start
'''
remote(program, 60)
report = {'queues': {}, 'bindings': bindings, 'wireless_hash_before': old_wireless_hash}
for name in (wan_device, ap_device, 'eth1'):
    queue = remote('tc -s qdisc show dev ' + shlex.quote(name))
    assert re.search(r'^qdisc nssfq_codel 10: root\b', queue, re.M), name
    assert 'accel_mode 0' in queue and 'rate ' not in queue and 'nsstbl' not in queue
    report['queues'][name] = queue
assert not remote('cat /proc/sys/net/ecm/interface_denied_list').split()
report['wireless_hash_after'] = remote('sha256sum /etc/config/wireless')
(args.output / ('hardware-fq-' + stamp + '.json')).write_text(json.dumps(report, indent=2) + '\n')
print('PASS active STA/AP/LAN hardware FQ, no rate limit or ECM interface exclusion', flush=True)
