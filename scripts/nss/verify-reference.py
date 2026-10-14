#!/usr/bin/env python3
"""Verify the portable stock NSS snapshot, firmware and feature inventory."""

import hashlib
import json
from pathlib import Path
import re
import tarfile


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "docs/nss/stock-ap-mp02.1"


def main():
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text())
    firmware = 0
    for relative, expected in manifest["files"].items():
        path = (SNAPSHOT / relative).resolve()
        assert path.is_relative_to(ROOT), relative
        data = path.read_bytes()
        assert len(data) == expected["bytes"], relative
        assert hashlib.sha256(data).hexdigest() == expected["sha256"], relative
        if "router_checksum" in expected:
            checksum = expected["router_checksum"]
            assert hashlib.new(checksum["algorithm"], data).hexdigest() == checksum["value"], relative
            firmware += 1
    assert firmware == 2, firmware
    redactions = json.loads((SNAPSHOT / "device-tree/redactions.json").read_text())
    with tarfile.open(SNAPSHOT / "device-tree/device-tree.tar") as archive:
        for redaction in redactions:
            data = archive.extractfile(redaction["property"]).read()
            assert data == bytes(redaction["bytes"]), redaction["property"]
    inventory = json.loads((ROOT / "docs/nss/features.json").read_text())
    assert len(inventory["features"]) == 44
    source = (ROOT / "package/kernel/qca-nss-drv/Config.in").read_text()
    profile = (ROOT / "configs/redmi-ax3000-nss-wifi.config").read_text()
    definitions = re.findall(r"(?m)^config (NSS_DRV_\w+)$", source)
    symbols = {f["symbol"] for f in inventory["features"]}
    assert len(symbols) == len(definitions) == 44
    assert symbols == set(definitions), "feature definitions differ from Config.in"
    for feature in inventory["features"]:
        symbol = re.escape(feature["symbol"])
        selected = re.search(r"(?m)^CONFIG_" + symbol + r"=(.*)$", profile)
        disabled = re.search(r"(?m)^# CONFIG_" + symbol + r" is not set$", profile)
        expected = selected.group(1) if selected else "n" if disabled else None
        assert feature["profile_value"] == expected, feature["symbol"]
    print(f"PASS: {len(manifest['files'])} snapshot hashes; {firmware} router firmware checksums; "
          f"{len(redactions)} redactions; 44 feature definitions and profile selections")


if __name__ == "__main__":
    main()
