#!/usr/bin/env python3
"""Run the real SQM runner through concurrent root/state publication and repair."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sqm', type=Path, required=True)
    args = parser.parse_args()
    source = (args.sqm / 'src/run-openwrt.sh').read_text()
    with tempfile.TemporaryDirectory(prefix='nss-sqm-reconcile-') as directory:
        root = Path(directory)
        state, lib, binary = root / 'state', root / 'lib', root / 'bin'
        for folder in (state, lib, binary, root / 'qdisc'):
            folder.mkdir()
        (root / 'config.sh').write_text(r'''
config_get() {
 case "$2" in
 interface) if [ "$1" = queue ]; then echo eth1; else echo unrelated; fi ;; enabled) echo 1 ;;
 script) echo "${TEST_SCRIPT:-nss-fq.qos}" ;;
 upload|download) echo 1000 ;; debug_logging) echo 0 ;; verbosity) echo 5 ;;
 esac
}
config_load() { :; }
config_foreach() { "$1" before; "$1" queue; "$1" after; }
''')
        (root / 'sqm.conf').write_text(
            f'SQM_LIB_DIR="{lib}"\nSQM_STATE_DIR="{state}"\n'
            f'SQM_QDISC_STATE_DIR="{root / "qdisc"}"\n')
        (lib / 'functions.sh').write_text(r'''
check_state_dir() { :; }
sqm_trace() { :; }
sqm_warn() { echo "$*" >> "$test_root/warnings"; }
sqm_error() { echo "$*" >> "$test_root/errors"; }
''')
        (binary / 'tc').write_text(r'''#!/bin/sh
if [ -f "$test_root/healthy" ]; then
 if [ "${TEST_SCRIPT:-nss-fq.qos}" = nss-edma.qos ]; then
  echo 'qdisc nsstbl 10: root'
 else
  echo 'qdisc nssfq_codel 10: root'
 fi
else
 echo 'qdisc noqueue 0: root'
fi
''')
        (lib / 'start-sqm').write_text(r'''#!/bin/sh
. "$test_root/sqm.conf"
test -d "$SQM_STATE_DIR/sqm-run.lock" || exit 1
[ "${TEST_START_FAIL:-0}" = 0 ] || exit "$TEST_START_FAIL"
echo start >> "$test_root/mutations"
touch "$test_root/healthy"
if [ "${TEST_BLOCK:-0}" = 1 ]; then
 touch "$test_root/entered"
 while [ ! -f "$test_root/release" ]; do sleep 0.02; done
fi
printf 'IFACE=eth1\nSCRIPT=%s\n' "$SCRIPT" > "$SQM_STATE_DIR/eth1.state"
''')
        (lib / 'stop-sqm').write_text(r'''#!/bin/sh
. "$test_root/sqm.conf"
test -d "$SQM_STATE_DIR/sqm-run.lock" || exit 1
echo stop >> "$test_root/mutations"
rm -f "$test_root/healthy" "$SQM_STATE_DIR/eth1.state"
''')
        for file in (binary / 'tc', lib / 'start-sqm', lib / 'stop-sqm'):
            file.chmod(0o755)
        runner = root / 'run.sh'
        mapped = source.replace('/lib/functions.sh', str(root / 'config.sh')).replace('/etc/sqm/sqm.conf', str(root / 'sqm.conf'))
        for prefix in ('/sys/', '/proc/'):
            for boundary in ('"', ' '):
                mapped = mapped.replace(boundary + prefix, boundary + str(root / prefix.strip('/')) + '/')
        runner.write_text(mapped)
        env = os.environ | {'test_root': str(root), 'PATH': str(binary) + ':' + os.environ['PATH']}

        def run(action='nss-reconcile', **extra):
            try:
                return subprocess.run(['bash', str(runner), action, 'eth1'],
                                      env=env | extra, text=True, capture_output=True, timeout=3)
            except subprocess.TimeoutExpired as error:
                raise AssertionError('NSS reconciliation blocked on another SQM owner') from error

        def mutations():
            file = root / 'mutations'
            return file.read_text().splitlines() if file.exists() else []

        lock = state / 'sqm-run.lock'
        lock.mkdir()
        (lock / 'pid').write_text('999999\n')
        for action in ('nss-reconcile', 'nss-stop'):
            result = run(action)
            assert result.returncode == 75, result
        assert not mutations() and not (root / 'warnings').exists()
        (lock / 'pid').unlink()
        lock.rmdir()

        first = subprocess.Popen(['bash', str(runner), 'nss-reconcile', 'eth1'],
                                 env=env | {'TEST_BLOCK': '1'}, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 3
            while not (root / 'entered').exists() and time.monotonic() < deadline:
                assert first.poll() is None
                time.sleep(0.01)
            assert (root / 'entered').exists()
            assert (root / 'healthy').exists() and not (state / 'eth1.state').exists()
            result = run()
            assert result.returncode == 75 and mutations() == ['start'], result
        finally:
            (root / 'release').touch()
            stdout, stderr = first.communicate(timeout=3)
        assert first.returncode == 0, (stdout, stderr)
        assert not lock.exists()
        assert run().returncode == 0 and mutations() == ['start']
        (root / 'healthy').unlink()
        assert run().returncode == 0 and mutations() == ['start', 'stop', 'start']
        assert (state / 'eth1.state').exists() and (root / 'healthy').exists()
        assert run('nss-stop').returncode == 0
        assert mutations() == ['start', 'stop', 'start', 'stop']
        assert not (state / 'eth1.state').exists()
        assert run(TEST_SCRIPT='cake.qos').returncode == 0
        assert mutations() == ['start', 'stop', 'start', 'stop']
        assert not (root / 'warnings').exists() and not (root / 'errors').exists()
        phy = root / 'sys/class/net/eth1/phy80211'
        phy.parent.mkdir(parents=True)
        phy.touch()
        denied = root / 'proc/sys/net/ecm/interface_denied_list'
        denied.parent.mkdir(parents=True)
        denied.write_text('')
        (root / 'healthy').touch()
        (state / 'eth1.state').write_text('IFACE=eth1\nSCRIPT=nss-edma.qos\n')
        before = mutations()
        assert run(TEST_SCRIPT='nss-edma.qos').returncode == 0
        assert mutations() == before and denied.read_text() == 'add eth1\n'
        assert (state / 'eth1.nss-ecm-owned').exists()
        # An already denied interface may belong to another owner.
        (state / 'eth1.nss-ecm-owned').unlink()
        denied.write_text('eth1\n')
        assert run(TEST_SCRIPT='nss-edma.qos').returncode == 0
        assert not (state / 'eth1.nss-ecm-owned').exists()
        assert mutations() == before
        denied.write_text('')
        lock.mkdir()
        (lock / 'pid').write_text('999999\n')
        assert run(TEST_SCRIPT='nss-edma.qos').returncode == 75
        assert denied.read_text() == '' and not (state / 'eth1.nss-ecm-owned').exists()
        (lock / 'pid').unlink()
        lock.rmdir()
        assert run('nss-stop', TEST_SCRIPT='nss-edma.qos').returncode == 0
        # Native 11-sqm must use the same idempotent/nonblocking NSS actions;
        # its old unconditional stop/start races the repair watcher.
        hotplug_source = (args.sqm / 'platform/openwrt/sqm-hotplug').read_text()
        (binary / 'uci').write_text('#!/bin/sh\nexit 1\n')
        (binary / 'uci').chmod(0o755)
        init = root / 'sqm-init'
        init.write_text('#!/bin/sh\n[ "$1" = enabled ]\n')
        init.chmod(0o755)
        wrapper = root / 'runner'
        wrapper.write_text('#!/bin/sh\nexec bash "' + str(runner) + '" "$@"\n')
        wrapper.chmod(0o755)
        hotplug = root / 'hotplug'
        hotplug.write_text(hotplug_source.replace('/lib/functions.sh', str(root / 'config.sh'))
                          .replace('/usr/lib/sqm/run.sh', str(wrapper))
                          .replace('/etc/init.d/sqm', str(init)))

        def event(action, **extra):
            return subprocess.run(['bash', str(hotplug)], env=env | {
                'ACTION': action, 'DEVICE': 'eth1', 'INTERFACE': 'wan'} | extra,
                capture_output=True, text=True, timeout=3)

        before = mutations()
        assert event('ifup').returncode == 0 and mutations() == before + ['start']
        assert event('ifup').returncode == 0 and mutations() == before + ['start']
        assert event('ifdown').returncode == 0 and mutations() == before + ['start', 'stop']
        lock.mkdir()
        (lock / 'pid').write_text('999999\n')
        for action in ('ifup', 'ifdown'):
            event(action)
        assert mutations() == before + ['start', 'stop'] and not (root / 'warnings').exists()
        (lock / 'pid').unlink()
        lock.rmdir()
        before = mutations()
        assert event('ifup', TEST_SCRIPT='cake.qos').returncode == 0
        assert event('ifup', TEST_SCRIPT='cake.qos').returncode == 0
        assert mutations() == before + ['start', 'stop', 'start']
        assert event('ifdown', TEST_SCRIPT='cake.qos').returncode == 0
        assert not (root / 'warnings').exists() and not (root / 'errors').exists()
        # Skipped trailing sections cannot turn success into failure or hide
        # a genuine selected-section error. Repeated owned stop is a no-op.
        assert run(TEST_START_FAIL='7').returncode == 7
        assert not (state / 'eth1.state').exists()
        assert run().returncode == 0 and (state / 'eth1.state').exists()
        assert run('nss-stop').returncode == 0
        assert run('nss-stop').returncode == 0
        print('PASS actual SQM runner: quiet busy lock, concurrent partial root publication, atomic repair, healthy reuse, owned stop and ordinary-script isolation')


if __name__ == '__main__':
    main()
