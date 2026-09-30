#!/usr/bin/env python3
"""Read-only Telnet export of stock IPQ5018 NSS references and firmware.

The password is prompted for and never written to the snapshot. Only
observational commands run on the router; all generated files are local.
"""

import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import uuid


class Telnet:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(1)
        self.pending = b""
        self.output = b""

    def receive(self):
        data = self.sock.recv(65536)
        if not data:
            raise EOFError("Router closed the Telnet connection")
        data = self.pending + data
        self.pending = b""
        clean = bytearray()
        i = 0
        while i < len(data):
            if data[i] != 255:
                clean.append(data[i])
                i += 1
                continue
            if i + 1 >= len(data):
                self.pending = data[i:]
                break
            command = data[i + 1]
            if command == 255:
                clean.append(255)
                i += 2
            elif command in (251, 252, 253, 254):
                if i + 2 >= len(data):
                    self.pending = data[i:]
                    break
                if command in (251, 253):
                    self.sock.sendall(bytes((255, 254 if command == 251 else 252, data[i + 2])))
                i += 3
            elif command == 250:
                end = data.find(b"\xff\xf0", i + 2)
                if end < 0:
                    self.pending = data[i:]
                    break
                i = end + 2
            else:
                i += 2
        self.output += bytes(clean).replace(b"\r", b"")

    def expect(self, pattern, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            match = re.search(pattern, self.output, re.MULTILINE)
            if match:
                result = self.output[:match.end()]
                self.output = self.output[match.end():]
                return result
            try:
                self.receive()
            except socket.timeout:
                pass
        raise TimeoutError("Timed out waiting for the router")

    def send(self, line):
        self.sock.sendall(line.encode() + b"\r\n")

    def login(self, username, password):
        self.expect(rb"login:\s*$")
        self.send(username)
        self.expect(rb"[Pp]assword:\s*$")
        self.send(password)
        self.expect(rb"root@[^\n]+#\s*$")

    def run(self, command, timeout=120):
        token = uuid.uuid4().hex.encode()
        begin, end = b"NSS_BEGIN_" + token, b"NSS_END_" + token
        self.send("printf '\\n%s\\n' " + begin.decode() + "; " + command +
                  "; printf '\\n" + end.decode() + ":%s\\n' \"$?\"")
        output = self.expect(rb"^" + end + rb":([0-9]+)\s*$", timeout)
        marker = re.search(rb"^" + begin + rb"\n", output, re.MULTILINE)
        finish = re.search(rb"^" + end + rb":([0-9]+)\s*$", output, re.MULTILINE)
        if not marker or not finish:
            raise RuntimeError("Invalid command framing")
        return int(finish.group(1)), output[marker.end():finish.start()].rstrip(b"\n")

    def close(self):
        try:
            self.send("exit")
        except OSError:
            pass
        finally:
            self.sock.close()


TEXT_READS = {
    "system/uname.txt": "uname -a",
    "system/board-name.txt": "cat /tmp/sysinfo/board_name",
    "system/model.txt": "cat /proc/device-tree/model",
    "system/cpu-online.txt": "cat /sys/devices/system/cpu/online",
    "system/memory.txt": "cat /proc/meminfo",
    "system/uptime.txt": "cat /proc/uptime",
    "system/modules.txt": "cat /proc/modules",
    "system/interrupts.txt": "cat /proc/interrupts",
    "system/clocks.txt": "cat /sys/kernel/debug/clk/clk_summary",
    "nss/sysctl-tree.txt": "find /proc/sys/dev/nss -type f",
    "nss/debugfs-tree.txt": "find /sys/kernel/debug/qca-nss-drv -type f",
    "nss/firmware-listing.txt": "ls -ln /lib/firmware/qca-nss*.bin",
    "nss/module-parameters.txt": (
        "for f in /sys/module/qca_nss_drv/parameters/*; do "
        "[ -r \"$f\" ] || continue; printf '%s\\n' \"$f\"; cat \"$f\"; done"
    ),
    "nss/clock-settings.txt": (
        "for f in /proc/sys/dev/nss/clock/*; do "
        "[ -f \"$f\" ] || continue; printf '%s\\n' \"$f\"; cat \"$f\"; done"
    ),
    "nss/boot-log.txt": "dmesg | grep -iE 'nss|ubi32|wifili|qcn6122'",
    "nss/module-load-files.txt": (
        "for f in /etc/modules.d/*nss*; do [ -f \"$f\" ] || continue; "
        "printf '%s\\n' \"$f\"; cat \"$f\"; done"
    ),
    "ecm/accelerated-counts.txt": (
        "for f in /sys/kernel/debug/ecm/ecm_nss_ipv4/accelerated_count "
        "/sys/kernel/debug/ecm/ecm_nss_ipv6/accelerated_count; do "
        "[ -r \"$f\" ] || continue; printf '%s\\n' \"$f\"; cat \"$f\"; done"
    ),
}


class Export:
    def __init__(self, connection, output, firmware):
        self.connection = connection
        self.output = output
        self.firmware = firmware
        self.manifest = {
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "access": "read-only Telnet; no router files or configuration written",
            "files": {}, "unavailable": [],
        }

    def save(self, relative, data, source, root=None, **extra):
        root = root or self.output
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        key = str(destination.resolve()) if root != self.output else relative
        self.manifest["files"][key] = {
            "source": source, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), **extra,
        }

    def text(self, relative, command):
        status, data = self.connection.run(command)
        if status:
            self.manifest["unavailable"].append({"source": command, "exit_status": status})
            return
        self.save(relative, data.replace(b"\x00", b"") + b"\n", command)

    def binary(self, remote):
        status, encoded = self.connection.run("base64 " + shlex.quote(remote))
        if status:
            raise RuntimeError("Unable to read " + remote)
        return base64.b64decode(b"".join(encoded.split()), validate=True)

    def firmware_files(self):
        status, listing = self.connection.run(
            "for f in /lib/firmware/qca-nss*.bin; do [ -f \"$f\" ] && printf '%s\\n' \"$f\"; done"
        )
        paths = listing.decode().splitlines()
        if status or not paths:
            raise RuntimeError("No stock NSS firmware found")
        for remote in paths:
            if not re.fullmatch(r"/lib/firmware/qca-nss[0-9][A-Za-z0-9_.-]*\.bin", remote):
                raise RuntimeError("Unexpected firmware path")
            data = self.binary(remote)
            status, checksum = self.connection.run("sha256sum " + shlex.quote(remote))
            algorithm = "sha256"
            if status:
                algorithm = "md5"
                status, checksum = self.connection.run("md5sum " + shlex.quote(remote))
            router_hash = checksum.decode().split()[0] if not status and checksum.split() else ""
            if router_hash != hashlib.new(algorithm, data).hexdigest():
                raise RuntimeError("Firmware checksum verification failed: " + remote)
            self.save(Path(remote).name, data, remote, root=self.firmware,
                      router_checksum={"algorithm": algorithm, "value": router_hash})
            print(f"Verified firmware: {Path(remote).name} ({len(data)} bytes; router {algorithm})", flush=True)

    def device_tree(self, dtc):
        status, encoded = self.connection.run("tar -C /proc/device-tree -cf - . | base64")
        if status:
            raise RuntimeError("Unable to export device tree")
        data = base64.b64decode(b"".join(encoded.split()), validate=True)
        archive = io.BytesIO()
        redactions = []
        with tarfile.open(fileobj=io.BytesIO(data)) as src, tarfile.open(fileobj=archive, mode="w") as dst:
            for entry in src.getmembers():
                if not (entry.isfile() or entry.isdir()):
                    raise RuntimeError("Unexpected device-tree archive entry")
                value = src.extractfile(entry).read() if entry.isfile() else b""
                if Path(entry.name).name in ("local-mac-address", "mac-address", "serial-number", "serialno"):
                    redactions.append({"property": entry.name, "bytes": len(value)})
                    value = bytes(len(value))
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ""
                dst.addfile(entry, io.BytesIO(value) if entry.isfile() else None)
        self.save("device-tree/device-tree.tar", archive.getvalue(), "/proc/device-tree",
                  identity_redacted=True, original_archive_sha256=hashlib.sha256(data).hexdigest())
        self.save("device-tree/redactions.json", (json.dumps(redactions, indent=2) + "\n").encode(),
                  "local identity-property redaction")
        if dtc:
            with tempfile.TemporaryDirectory(prefix="stock-nss-dt-") as temporary:
                with tarfile.open(fileobj=io.BytesIO(archive.getvalue())) as src:
                    src.extractall(temporary, filter="data")
                result = subprocess.run([dtc, "-I", "fs", "-O", "dts", temporary], capture_output=True)
                if result.returncode:
                    raise RuntimeError("Local DTS conversion failed")
                self.save("device-tree/device-tree.dts", result.stdout, "local dtc -I fs (identity-redacted)")
                self.save("device-tree/dtc-warnings.txt", result.stderr, "local dtc diagnostics")
        print(f"Saved device tree; redacted {len(redactions)} identity properties", flush=True)

    def debug_files(self):
        command = (
            "find /sys/kernel/debug/qca-nss-drv/stats "
            "/sys/kernel/debug/qca-nss-drv/strings "
            "/sys/kernel/debug/qca-nss-drv/meminfo -type f"
        )
        status, listing = self.connection.run(command)
        if status:
            raise RuntimeError("Unable to list NSS debug files")
        paths = sorted(listing.decode().splitlines())
        for index, remote in enumerate(paths, 1):
            prefix = "/sys/kernel/debug/qca-nss-drv/"
            if not remote.startswith(prefix):
                raise RuntimeError("Unexpected debug path")
            relative = remote[len(prefix):]
            if ".." in Path(relative).parts:
                raise RuntimeError("Unsafe debug path")
            self.text("nss/" + relative + ".txt", "cat " + shlex.quote(remote))
            if index % 10 == 0 or index == len(paths):
                print(f"Saved NSS debug files: {index}/{len(paths)}", flush=True)
        time.sleep(3)
        for name in ("drv", "n2h", "wifili"):
            self.text("nss/stats-second/" + name + ".txt",
                      "cat /sys/kernel/debug/qca-nss-drv/stats/" + name)

    def finish(self):
        # Manifest paths are portable across machines, with firmware rooted
        # relative to this snapshot directory rather than a workstation path.
        portable = {}
        import os
        for key, value in self.manifest["files"].items():
            portable[os.path.relpath(key, self.output) if Path(key).is_absolute() else key] = value
        self.manifest["files"] = portable
        self.manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "manifest.json").write_text(json.dumps(self.manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.10.1")
    parser.add_argument("--port", type=int, default=23)
    parser.add_argument("--user", default="root")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--firmware-output", type=Path, required=True)
    parser.add_argument("--dtc", default=shutil.which("dtc"))
    args = parser.parse_args()
    if args.output.exists() or args.firmware_output.exists():
        raise SystemExit("Use new output directories to preserve earlier snapshots")
    password = getpass.getpass("Router Telnet password: ")
    connection = Telnet(args.host, args.port)
    try:
        connection.login(args.user, password)
        del password
        print("Authenticated; collecting read-only NSS reference", flush=True)
        export = Export(connection, args.output.resolve(), args.firmware_output.resolve())
        for relative, command in TEXT_READS.items():
            export.text(relative, command)
        export.firmware_files()
        export.device_tree(args.dtc)
        export.debug_files()
        export.finish()
        print(f"Snapshot complete: {len(export.manifest['files'])} files", flush=True)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
