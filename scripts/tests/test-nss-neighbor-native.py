#!/usr/bin/env python3
"""Execute the real native neighbor scheduler against deterministic network snapshots."""
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
parser.add_argument('--module', type=Path, default=repo / 'package/network/services/nss-wifi/files/nss-neighbor-state.uc')
args = parser.parse_args()
if not args.ucode:
    parser.error('Provide --ucode or UCODE after building package/utils/ucode/host/compile')
with tempfile.TemporaryDirectory(prefix='nss-neighbor-native-') as directory:
    harness = Path(directory) / 'test.uc'
    harness.write_text(Path(__file__).with_name('nss-neighbor-state.uc').read_text().replace("'MODULE'", json.dumps(str(args.module.resolve()))))
    subprocess.run([args.ucode, str(harness)], check=True, timeout=20)
