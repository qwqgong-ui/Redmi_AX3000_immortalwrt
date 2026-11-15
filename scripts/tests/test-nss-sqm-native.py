#!/usr/bin/env python3
"""Run the deployed ucode SQM state engine with deterministic native-I/O fixtures."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--ucode', default=os.environ.get('UCODE', shutil.which('ucode')))
parser.add_argument('--module', type=Path, default=repo / 'package/network/services/sqm-scripts-nss/files/nss-sqm-state.uc')
args = parser.parse_args()
if not args.ucode:
    parser.error('Provide --ucode or UCODE after building package/utils/ucode/host/compile')
template = Path(__file__).with_name('nss-sqm-state.uc').read_text()
with tempfile.TemporaryDirectory(prefix='nss-sqm-native-') as directory:
    harness = Path(directory) / 'test.uc'
    harness.write_text(template.replace("'MODULE'", json.dumps(str(args.module.resolve()))))
    subprocess.run([args.ucode, str(harness)], check=True, timeout=20)
