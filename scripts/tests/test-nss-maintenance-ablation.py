#!/usr/bin/env python3
"""Withdraw individual guards and require real scheduler/runner tests to reject them."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--ucode', default=os.environ.get('UCODE', shutil.which('ucode')))
parser.add_argument('--sqm', type=Path, required=True)
args = parser.parse_args()
if not args.ucode:
    parser.error('Provide --ucode or UCODE')
sq = repo / 'package/network/services/sqm-scripts-nss/files/nss-sqm-state.uc'
ng = repo / 'package/network/services/nss-wifi/files/nss-neighbor-state.uc'
cases = [
    ('sqm-idle-skip', sq, 'test-nss-sqm-native.py',
     '|| repair_denied) {', '|| repair_denied || true) {'),
    ('sqm-instance-identity', sq, 'test-nss-sqm-native.py',
     'old.index != idx', 'false'),
    ('sqm-ECM-repair', sq, 'test-nss-sqm-native.py',
     '|| repair_denied) {', ') {'),
    ('neighbor-cadence', ng, 'test-nss-neighbor-native.py',
     'now - state.last >= 300', 'now - state.last >= 0'),
    ('neighbor-SKIP-backoff', ng, 'test-nss-neighbor-native.py',
     'state.attempt = now;', 'if (false) state.attempt = now;'),
    ('neighbor-address-identity', ng, 'test-nss-neighbor-native.py',
     'connection.bssid, address.local, prefix,', 'connection.bssid, "", prefix,'),
    ('neighbor-link-mask', ng, 'test-nss-neighbor-native.py',
     "if (type(flags) == 'array') flags = flags[0];", 'if (false) flags = flags[0];'),
    ('neighbor-base-address', ng, 'test-nss-neighbor-native.py',
     '(!a.label || a.label == iface)', 'true'),
]
runner = args.sqm / 'src/run-openwrt.sh'
runner_cases = [
    ('runner-skipped-section', '[ -z "$RUN_IFACE" -o "$RUN_IFACE" = "$IFACE" ] || return 0',
     '[ -z "$RUN_IFACE" -o "$RUN_IFACE" = "$IFACE" ] || return 1'),
    ('runner-error-aggregation', 'start_sqm_section "$@" || RUN_STATUS=$?', 'start_sqm_section "$@" || true'),
    ('runner-ECM-restore', 'nss_restore_denied "$script" "$section"', ':'),
    ('runner-idempotent-stop', '[ -f "$f" ] || return 0', '[ -f "$f" ] || return 1'),
]
with tempfile.TemporaryDirectory(prefix='nss-maint-ablation-') as temporary:
    root = Path(temporary)
    for name, source, test, before, after in cases:
        text = source.read_text()
        assert before in text, name
        module = root / (name + '.uc')
        module.write_text(text.replace(before, after))
        result = subprocess.run([sys.executable, str(repo / 'scripts/tests' / test),
                                 '--ucode', args.ucode, '--module', str(module)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode and 'FAIL:' in result.stderr and 'Syntax error' not in result.stderr, (name, result.stdout, result.stderr)
        print('PASS rejected ' + name)
    for name, before, after in runner_cases:
        candidate = root / name
        (candidate / 'src').mkdir(parents=True)
        (candidate / 'platform/openwrt').mkdir(parents=True)
        text = runner.read_text()
        assert before in text, name
        (candidate / 'src/run-openwrt.sh').write_text(text.replace(before, after))
        shutil.copyfile(args.sqm / 'platform/openwrt/sqm-hotplug', candidate / 'platform/openwrt/sqm-hotplug')
        result = subprocess.run([sys.executable, str(repo / 'scripts/tests/test-nss-sqm-reconcile.py'),
                                 '--sqm', str(candidate)], capture_output=True, text=True, timeout=30,
                                env=os.environ | {'LC_ALL': 'C'})
        assert result.returncode and 'AssertionError' in result.stderr, (name, result.stdout, result.stderr)
        print('PASS rejected ' + name)
print(json.dumps({'rejected_runtime_mutants': len(cases) + len(runner_cases)}))
