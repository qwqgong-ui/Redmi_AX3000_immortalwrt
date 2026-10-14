#!/usr/bin/env python3
"""Run actual binding/watch functions against simulated OpenWrt link changes."""
from pathlib import Path
import subprocess
import tempfile

TEST = r'''
mock_iface=phy1-sta0
mock_up=1
mock_script=nss-edma.qos
mock_upload=20000
mock_download=20000
mock_root=1
mock_wireless=''
mock_logical=wwan
mock_config_iface=phy1-sta0
config_get() {
 if [ "$#" = 2 ]; then
  [ "$2" = download ] && echo "$mock_download"
  return
 fi
 local result
 case "$3" in
 enabled|nss_watch) result=1 ;; script) result=$mock_script ;; network) result=$mock_logical ;;
 wireless_interface) result=$mock_wireless ;; interface) result=$mock_config_iface ;;
 upload) result=$mock_upload ;; download) result=$mock_download ;;
 *) result=${4:-} ;;
 esac
 [ -z "$mock_wireless" ] || { [ "$3" != network ] || result=''; }
 printf -v "$1" %s "$result"
}
config_get_bool() { config_get "$@"; }
network_flush_cache() { :; }
network_is_up() { [ "$mock_up" = 1 ]; }
network_get_device() { printf -v "$1" %s "$mock_iface"; }
uci() { :; }
ubus() { echo '{}'; }
jsonfilter() { echo "$mock_iface"; }
tc() {
 local device=$4
 case "$device" in
 ifb@*) echo 'qdisc nsstbl 1: root' ;;
 *) [ "$mock_root" = 1 ] || { echo 'qdisc noqueue 0: root'; return; }
 if [ "$mock_script" = nss-fq.qos ]; then echo 'qdisc nssfq_codel 10: root';
 else echo 'qdisc nsstbl 1: root'; fi ;;
 esac
}
count() { [ "$(wc -l < "$work/calls")" = "$1" ] || { cat "$work/calls"; exit 1; }; }
: > "$work/calls"
seen=''
poll_queue wifi
count 1
poll_queue wifi
count 1
# A healthy ingress-only queue has no NSS root on its source VIF.
mock_upload=0
mock_root=0
poll_queue wifi
count 1
# A DSA port has its real root on the conduit, not on the bound port.
rm -f "$work/sys/class/net/phy1-sta0/phy80211"
mock_upload=20000
poll_queue wifi
count 1
touch "$work/sys/class/net/phy1-sta0/phy80211"
mock_root=1
# Recreated VIF, same name, new ifindex: stop the old instance and start anew.
echo 11 > "$work/sys/class/net/phy1-sta0/ifindex"
poll_queue wifi
count 3
poll_queue wifi
count 3
# Disconnect removes only the owned binding. Reconnect reinstalls once.
mock_up=0
poll_queue wifi
count 4
mock_up=1
poll_queue wifi
count 5
# The AP is resolved by wireless UCI section and its own FQ root.
mock_iface=phy0-ap0
mock_wireless=default_radio0
mock_script=nss-fq.qos
poll_queue ap
count 6
poll_queue ap
count 6
cleanup
count 8
mock_wireless=''
mock_logical=''
mock_config_iface=eth1
poll_queue wired
count 9
poll_queue wired
count 9
cleanup
count 10
echo 'PASS actual NSS SQM watcher: healthy STA, ingress-only/DSA topology, same-name VIF replacement, down/up and AP section binding'
'''


def main():
    repo = Path(__file__).resolve().parents[2]
    source = (repo / 'package/network/services/sqm-scripts-nss/files/nss-sqm-watch').read_text()
    functions = source[source.index('stop_binding() {'):source.index('\nwhile :;')]
    functions = '\n'.join(line for line in functions.splitlines() if not line.startswith('trap '))
    with tempfile.TemporaryDirectory(prefix='nss-sqm-watch-') as directory:
        root = Path(directory)
        state = root / 'state'
        (state / 'nss-bindings').mkdir(parents=True)
        for device in ('phy1-sta0', 'phy0-ap0', 'eth1'):
            dev = root / 'sys/class/net' / device
            dev.mkdir(parents=True)
            (dev / 'ifindex').write_text('10\n')
            if device != 'eth1':
                (dev / 'phy80211').touch()
        ready = root / 'sys/module/qca_nss_drv/parameters/core0_ready'
        ready.parent.mkdir(parents=True)
        ready.write_text('1\n')
        denied = root / 'proc/sys/net/ecm/interface_denied_list'
        denied.parent.mkdir(parents=True)
        denied.write_text('phy1-sta0\n')
        runner = root / 'run'
        runner.write_text('#!/bin/sh\necho "$*" >> "$work/calls"\n'
                          'if [ "$1" = stop ]; then rm -f "$SQM_STATE_DIR/$2.state"; '
                          'else touch "$SQM_STATE_DIR/$2.state"; fi\n')
        runner.chmod(0o755)
        service = root / 'enabled'
        service.write_text('#!/bin/sh\nexit 0\n')
        service.chmod(0o755)
        functions = functions.replace('/usr/lib/sqm/run.sh', str(runner)).replace('/etc/init.d/sqm', str(service))
        functions = functions.replace('/sys/', str(root) + '/sys/').replace('/proc/', str(root) + '/proc/')
        script = f'export work="{root}" SQM_STATE_DIR="{state}"\nruntime="$SQM_STATE_DIR/nss-bindings"\n' + functions + TEST
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=15)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-5000:])
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
