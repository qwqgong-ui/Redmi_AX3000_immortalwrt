#!/usr/bin/env python3
"""Compatibility entry point for the expanded actual peer-lifetime tests."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('nss_peer_lifetime', Path(__file__).with_name('test-nss-peer-lifetime.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

if __name__ == '__main__':
    module.main()
