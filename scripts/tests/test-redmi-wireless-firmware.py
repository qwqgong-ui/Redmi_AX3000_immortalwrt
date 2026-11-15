#!/usr/bin/env python3
"""Verify the Redmi AX3000 combo firmware and board data in a built rootfs."""
import argparse
from pathlib import Path
import struct


def tlvs(data):
    offset = 0
    while offset < len(data):
        assert len(data) - offset >= 8, 'Truncated board TLV header'
        kind, length = struct.unpack_from('<II', data, offset)
        start, end = offset + 8, offset + 8 + length
        assert end <= len(data), 'Truncated board TLV payload'
        yield kind, data[start:end]
        offset = (end + 3) & ~3
        assert offset <= len(data), 'Truncated board TLV alignment'


def board_ids(path):
    data = path.read_bytes()
    magic = b'QCA-ATH11K-BOARD\0'
    assert data.startswith(magic), 'Invalid ath11k board magic'
    entries = {}
    for kind, board in tlvs(data[(len(magic) + 3) & ~3:]):
        if kind != 0:
            continue
        names = []
        for item, payload in tlvs(board):
            if item == 0:
                names.append(payload.rstrip(b'\0').decode('ascii'))
            elif item == 1:
                assert names and len(payload) == 0x20000, 'Invalid board data size/name'
                for name in names:
                    fields = dict(part.split('=', 1) for part in name.split(','))
                    assert fields['bus'] == 'ahb' and fields['qmi-chip-id'] == '0'
                    board_id = int(fields['qmi-board-id'])
                    assert board_id not in entries, 'Duplicate board ID'
                    entries[board_id] = payload
                names.clear()
        assert not names, 'Board name has no payload'
    return set(entries)


def mdt_segments(path):
    data = path.read_bytes()
    assert data[:6] == b'\x7fELF\x01\x01', 'Expected little-endian ELF32 MDT'
    phoff = struct.unpack_from('<I', data, 28)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 42)
    assert phsize == 32 and phnum and phoff + phsize * phnum <= len(data)
    checked = 0
    for index in range(phnum):
        kind, offset, vaddr, paddr, size, memsize, flags, align = struct.unpack_from(
            '<8I', data, phoff + index * phsize)
        if kind != 1 or not size:
            continue
        assert size <= memsize, 'MDT file payload exceeds memory size'
        if offset + size <= len(data):
            continue
        segment = path.with_suffix('.b' + str(index).zfill(2))
        assert segment.is_file() and segment.stat().st_size == size, segment
        checked += 1
    return checked


def image_path(rootfs, relative):
    # Board overrides are installed through OpenWrt's rootfs overlay mechanism.
    override = rootfs / 'rootfs-overlay' / relative
    return override if override.is_file() else rootfs / relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-source', type=Path, required=True)
    parser.add_argument('--rootfs', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    assert args.firmware_source.name == 'WLAN.HK.2.7.0.1-01744-QCAHKSWPL_SILICONZ-1'
    assert 'IPQ5018_QCN6122_QCN6122' in args.firmware_source.parts
    components = (
        ('IPQ5018', args.firmware_source, 'ipq5018', {0x10, 0x24}),
        ('QCN6122', args.firmware_source / 'qcn6122', 'qcn6122', {0x60}),
    )
    payloads = segments = 0
    for chip, source, suffix, ids in components:
        relative = Path('lib/firmware/ath11k') / chip / 'hw1.0'
        expected = [p for p in source.glob('*.*') if p.is_file()]
        assert expected and (source / 'm3_fw.mdt').is_file()
        if chip == 'IPQ5018':
            assert (source / 'q6_fw.mdt').is_file()
        for path in expected:
            actual = image_path(args.rootfs, relative / path.name)
            assert actual.read_bytes() == path.read_bytes(), actual
            payloads += 1
            if path.suffix == '.mdt':
                segments += mdt_segments(actual)
        board = image_path(args.rootfs, relative / 'board-2.bin')
        original = repo / 'package/firmware/ipq-wifi/src' / ('board-redmi_ax3000.' + suffix)
        assert board.read_bytes() == original.read_bytes(), board
        assert board_ids(board) == ids, board
    print('PASS Redmi AX3000: 01744 combo payloads match source (' + str(payloads) +
          ' files), all ' + str(segments) + ' external MDT load segments complete, '
          'IPQ5018 PA board IDs 16/36 and QCN6122 board ID 96 preserved')


if __name__ == '__main__':
    main()
