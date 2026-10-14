#!/usr/bin/env python3
"""Check the actual LAN startup script against synchronous owner replies."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'package/network/services/nss-wifi/files/nss-lan.init'
CASES = {
    'disabled': (0, 0, 0), 'wired-off': (0, 0, 0),
    'core-not-ready': (0, 0, 0), 'host-wifi': (0, 0, 0),
    'module-failure': (1, 0, 0), 'success': (0, 1, 0),
    'link-settles': (0, 3, 2), 'uncertain': (1, 1, 0),
    'retained': (1, 1, 0), 'provider-held': (1, 1, 0),
    'no-status': (1, 1, 0), 'never-ready': (1, 5, 4),
    'active-ready': (0, 0, 0), 'active-settles': (0, 0, 2),
    'active-uncertain': (1, 0, 0),
}

for case, expected in CASES.items():
    with tempfile.TemporaryDirectory(prefix='nss-lan-init-') as tmp:
        base = Path(tmp)
        sys = base / 'sys'
        for mod, param, value in [('qca_nss_drv', 'core0_ready', '0' if case == 'core-not-ready' else '1'),
                                  ('ath11k', 'nss_offload', '0' if case == 'host-wifi' else '1'),
                                  ('qca_dsa_nss', 'enabled', 'Y' if case.startswith('active-') else 'N'),
                                  ('qca_dsa_nss', 'ready', 'Y' if case == 'active-ready' else 'N')]:
            path = sys / 'module' / mod / 'parameters' / param
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        status = sys / 'kernel/debug/qca-dsa-nss/status'
        status.parent.mkdir(parents=True)
        if case.startswith('active-'):
            status.write_text('enabled=1 ready=0 pinned=1 paused=0 provider_held=0 allocation_uncertain=' +
                              ('1' if case == 'active-uncertain' else '0') + ' error=0\n')
        calls = base / 'calls'
        functions = base / 'functions.sh'
        functions.write_text(f'''
config_load() {{ :; }}
config_get_bool() {{
 case "$3" in
 enabled) eval "$1={'0' if case == 'disabled' else '1'}";;
 wired_enabled) eval "$1={'0' if case == 'wired-off' else '1'}";;
 esac
}}
modprobe() {{ [ '{case}' != module-failure ]; }}
logger() {{ :; }}
sleep() {{
 echo sleep >> '{calls}'
 if [ '{case}' = active-settles ] && [ "$(grep -c '^sleep$' '{calls}')" -ge 2 ]; then
  echo Y > '{sys}/module/qca_dsa_nss/parameters/ready'
 fi
}}
printf() {{
 if [ "$1" != '%s' ] || [ "$2" != 1 ]; then command printf "$@"; return; fi
 echo write >> '{calls}'
 _writes=$(grep -c '^write$' '{calls}')
 if [ '{case}' = success ] || {{ [ '{case}' = link-settles ] && [ "$_writes" -ge 3 ]; }}; then
  echo Y > '{sys}/module/qca_dsa_nss/parameters/ready'
  command printf '%s' 1
  return 0
 fi
 _pinned=0 _provider=0 _uncertain=0
 case '{case}' in
 uncertain) _pinned=1 _uncertain=1;;
 retained) _pinned=1;;
 provider-held) _provider=1;;
 esac
 if [ '{case}' != no-status ]; then
  echo "enabled=0 ready=0 pinned=$_pinned paused=0 provider_held=$_provider allocation_uncertain=$_uncertain error=-11" > '{status}'
 fi
 return 1
}}
''')
        source = SCRIPT.read_text().replace('. /lib/functions.sh', '. ' + str(functions))
        source = source.replace('/sys/', str(sys) + '/')
        result = subprocess.run(['sh', '-c', source + '\nstart\n'], capture_output=True, text=True)
        lines = calls.read_text().splitlines() if calls.exists() else []
        observed = (result.returncode, lines.count('write'), lines.count('sleep'))
        assert observed == expected, (case, observed, expected, result.stderr)
        print('PASS NSS LAN startup: ' + case)
