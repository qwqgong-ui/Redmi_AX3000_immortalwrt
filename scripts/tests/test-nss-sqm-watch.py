#!/usr/bin/env python3
"""Execute the deployed FQ queue's readiness gates without touching a real queue."""
from pathlib import Path
import subprocess
import tempfile

TEST = r'''
IFACE=eth1
TC=fq_tc
fq_mods=0
fq_creates=0
modprobe() { fq_mods=$((fq_mods + 1)); }
fq_tc() { fq_creates=$((fq_creates + 1)); }
tc() { echo 'qdisc nssfq_codel 10: root'; }
echo N > "$work/sys/module/qca_dsa_nss/parameters/ready"
if sqm_start; then exit 1; fi
[ "$fq_mods:$fq_creates" = 0:0 ] || exit 1
echo Y > "$work/sys/module/qca_dsa_nss/parameters/ready"
sqm_start || exit 1
[ "$fq_mods:$fq_creates" = 1:1 ] || exit 1
IFACE=phy0-ap0
echo N > "$work/sys/module/qca_dsa_nss/parameters/ready"
sqm_start || exit 1
[ "$fq_mods:$fq_creates" = 2:2 ] || exit 1
echo 0 > "$work/sys/module/qca_nss_drv/parameters/core0_ready"
if sqm_start; then exit 1; fi
[ "$fq_mods:$fq_creates" = 2:2 ] || exit 1
echo 'PASS NSS FQ readiness: DSA gating, wireless independent of DSA, NSS core gating'
'''

repo = Path(__file__).resolve().parents[2]
fq = (repo / 'package/network/services/sqm-scripts-nss/files/nss-fq.qos').read_text()
functions = fq[fq.index('sqm_start() {'):]
with tempfile.TemporaryDirectory(prefix='nss-fq-ready-') as directory:
    root = Path(directory)
    for device in ('phy0-ap0', 'eth1'):
        (root / 'sys/class/net' / device).mkdir(parents=True)
    (root / 'sys/class/net/phy0-ap0/phy80211').touch()
    for path, value in [('sys/module/qca_nss_drv/parameters/core0_ready', '1'),
                        ('sys/module/qca_dsa_nss/parameters/ready', 'Y')]:
        target = root / path
        target.parent.mkdir(parents=True)
        target.write_text(value)
    functions = functions.replace('/sys/', str(root) + '/sys/')
    script = f'work="{root}"\nsqm_debug() {{ :; }}\n' + functions + TEST
    subprocess.run(['bash', '-ec', script], check=True, timeout=10)
