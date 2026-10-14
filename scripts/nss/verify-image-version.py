#!/usr/bin/env python3
"""Check the actual SquashFS payload in both factory UBI and sysupgrade tar."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import tempfile


def squashfs_bytes(data):
    if len(data) < 96 or data[:4] != b'hsqs':
        raise ValueError('Missing SquashFS superblock')
    used = struct.unpack_from('<Q', data, 40)[0]
    if not 96 <= used <= len(data):
        raise ValueError('Invalid SquashFS length')
    return data[:used]


def factory_rootfs(path):
    data = path.read_bytes()
    # Accept only a complete UBI geometry. The AX3000 currently uses 128 KiB.
    geometry = [size for size in (65536, 131072, 262144, 524288)
                if len(data) % size == 0 and all(
                    data[offset:offset+4] == b'UBI#'
                    for offset in range(0, len(data), size))]
    if not geometry:
        raise ValueError('No complete factory UBI geometry')
    for size in geometry:
        volumes = {}
        try:
            for offset in range(0, len(data), size):
                block = data[offset:offset+size]
                vid, payload = struct.unpack_from('>II', block, 16)
                if not 64 <= vid < payload < size:
                    raise ValueError('Invalid UBI header offsets')
                header = block[vid:vid+64]
                if header[:4] != b'UBI!':
                    raise ValueError('Invalid UBI VID header')
                volume, logical = struct.unpack_from('>II', header, 8)
                if volume >= 0x7fffefff:
                    continue
                blocks = volumes.setdefault(volume, {})
                if logical in blocks:
                    raise ValueError('Duplicate logical UBI block')
                blocks[logical] = block[payload:]
            roots = []
            for blocks in volumes.values():
                if not blocks.get(0, b'').startswith(b'hsqs'):
                    continue
                if sorted(blocks) != list(range(len(blocks))):
                    raise ValueError('Incomplete rootfs UBI volume')
                roots.append(squashfs_bytes(b''.join(blocks[i] for i in range(len(blocks)))))
            if len(roots) == 1:
                return roots[0], size
        except ValueError:
            continue
    raise ValueError('Could not assemble one complete factory SquashFS volume')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--factory', type=Path, required=True)
    parser.add_argument('--sysupgrade', type=Path, required=True)
    parser.add_argument('--expected', required=True)
    parser.add_argument('--unsquashfs', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Keep the existing image-version evidence')
    factory, block_size = factory_rootfs(args.factory)
    with tarfile.open(args.sysupgrade) as archive:
        roots = [member for member in archive.getmembers()
                 if member.isfile() and member.name.endswith('/root')]
        if len(roots) != 1:
            raise ValueError('Expected exactly one sysupgrade rootfs')
        with archive.extractfile(roots[0]) as stream:
            upgrade = squashfs_bytes(stream.read())
    if factory != upgrade:
        raise ValueError('Factory and sysupgrade contain different root filesystems')
    with tempfile.TemporaryDirectory(prefix='nss-image-version-') as directory:
        rootfs = Path(directory)/'root.squashfs'
        rootfs.write_bytes(factory)
        release = subprocess.check_output([args.unsquashfs, '-cat', str(rootfs),
                                           'etc/openwrt_release'], text=True)
    revision = re.search(r"(?m)^DISTRIB_REVISION='([^']+)'$", release)
    if not revision:
        raise ValueError('No revision in actual image filesystem')
    report = dict(expected_revision=args.expected, actual_revision=revision[1],
                  passed=revision[1] == args.expected,
                  factory_and_sysupgrade_rootfs_identical=True,
                  rootfs_sha256=hashlib.sha256(factory).hexdigest(),
                  ubi_block_size=block_size, release=release)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if not report['passed']:
        raise SystemExit('FAIL actual image revision=' + revision[1] + ', expected=' + args.expected)
    print('PASS actual factory/sysupgrade payload revision=' + revision[1])


if __name__ == '__main__':
    main()
