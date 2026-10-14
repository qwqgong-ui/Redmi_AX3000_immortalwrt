#!/usr/bin/env python3
"""Post-flash wired acceptance: a link or NSS-ready flag alone is insufficient."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import struct
import subprocess
import time


def command(argv):
    return subprocess.check_output(argv, text=True, timeout=15)


def read_name(data, offset):
    labels, visited, end = [], set(), None
    for _ in range(128):
        assert offset not in visited and offset < len(data), 'Invalid DNS name pointer'
        visited.add(offset)
        length = data[offset]
        offset += 1
        if length & 0xc0 == 0xc0:
            assert offset < len(data), 'Truncated DNS pointer'
            if end is None:
                end = offset + 1
            offset = ((length & 0x3f) << 8) | data[offset]
            continue
        assert length <= 63, 'Invalid DNS label'
        if not length:
            return tuple(label.lower() for label in labels), end if end is not None else offset
        assert offset + length <= len(data), 'Truncated DNS label'
        labels.append(data[offset:offset + length].decode('ascii'))
        offset += length
    raise ValueError('Unterminated DNS name')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', required=True)
    parser.add_argument('--router', type=ipaddress.IPv4Address, default='192.168.1.1')
    parser.add_argument('--bypass-mark', type=int, default=0,
                        help='Existing local transparent-proxy bypass mark, if needed')
    parser.add_argument('--bytes', type=int, default=16 * 1024 * 1024)
    parser.add_argument('--https-address', type=ipaddress.IPv4Address,
                        help='Previously verified address for speed.cloudflare.com; TLS hostname verification remains enabled')
    parser.add_argument('--require-primary', action='store_true')
    parser.add_argument('--output', type=Path, help='New evidence file; existing files are preserved')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Run without Python optimisation; this probe requires its validation assertions')
    assert 16384 <= args.bytes <= 64 * 1024 * 1024
    assert 0 <= args.bypass_mark <= 0xffffffff
    os.umask(0o077)
    report = {'interface': args.interface, 'router': str(args.router), 'checks': {}}

    def checked(name, fn):
        try:
            value = fn()
            report['checks'][name] = {'passed': True, 'result': value}
            return value
        except Exception as error:
            report['checks'][name] = {'passed': False, 'error': str(error)}
            return None

    def link():
        entry, = json.loads(command(['ip', '-j', '-s', 'link', 'show', 'dev', args.interface]))
        assert 'LOWER_UP' in entry['flags'], 'Wired carrier is down'
        assert not Path('/sys/class/net', args.interface, 'wireless').exists(), 'Wireless interface selected'
        details = command(['ethtool', args.interface])
        speed = re.search(r'Speed: (\d+)Mb/s', details)
        duplex = re.search(r'Duplex: (\S+)', details)
        assert speed and duplex and 'Link detected: yes' in details, 'Link negotiation is incomplete'
        return {'speed_mbps': int(speed[1]), 'duplex': duplex[1], 'counters': entry['stats64']}

    before = checked('link', link)
    def address():
        entries = json.loads(command(['ip', '-j', '-4', 'address', 'show', 'dev', args.interface]))
        candidates = [row['local'] for entry in entries for row in entry['addr_info']
                      if row.get('scope') == 'global' and args.router in
                      ipaddress.IPv4Network(row['local'] + '/' + str(row['prefixlen']), strict=False)]
        assert len(candidates) == 1, 'Expected one wired address in the router subnet'
        return candidates[0]

    source = checked('address', address)
    report['source'] = source

    def wired(kind):
        assert source is not None, 'No verified wired address'
        sock = socket.socket(socket.AF_INET, kind)
        try:
            sock.settimeout(12)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, args.interface.encode() + b'\0')
            if args.bypass_mark:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, args.bypass_mark)
            sock.bind((source, 0))
            return sock
        except BaseException:
            sock.close()
            raise

    def exact(sock, size):
        data = b''
        while len(data) < size:
            part = sock.recv(size - len(data))
            assert part, 'Short DNS frame'
            data += part
        return data

    def dns(domain, tcp):
        ident = secrets.randbelow(65536)
        question = b''.join(bytes([len(label)]) + label.encode() for label in domain.split('.'))
        request = struct.pack('!6H', ident, 0x100, 1, 0, 0, 0) + question + b'\0' + struct.pack('!HH', 1, 1)
        with wired(socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
            sock.connect((str(args.router), 53))
            if tcp:
                sock.sendall(struct.pack('!H', len(request)) + request)
                reply = exact(sock, struct.unpack('!H', exact(sock, 2))[0])
            else:
                sock.send(request)
                reply = sock.recv(65535)
        xid, flags, questions, answers, _, _ = struct.unpack_from('!6H', reply)
        assert xid == ident and flags & 0x8000 and not flags & 0x7a0f, (
            'Invalid, truncated or failed DNS response: flags=' + hex(flags) +
            ', xid=' + str(xid) + ', expected=' + str(ident))
        assert questions == 1, 'Unexpected DNS question count'
        offset = 12
        name, offset = read_name(reply, offset)
        qtype, qclass = struct.unpack_from('!HH', reply, offset)
        offset += 4
        assert name == tuple(domain.split('.')) and qtype == 1 and qclass == 1, 'DNS question does not match the request'
        records, aliases = {}, {}
        for _ in range(answers):
            owner, offset = read_name(reply, offset)
            kind, klass, _, size = struct.unpack_from('!HHIH', reply, offset)
            offset += 10
            value = reply[offset:offset + size]
            assert len(value) == size, 'Truncated DNS answer'
            offset += size
            if kind == 1 and klass == 1 and size == 4:
                addr = ipaddress.IPv4Address(value)
                assert addr.is_global and addr not in ipaddress.IPv4Network('198.18.0.0/15'), 'Non-public/fake-IP DNS answer'
                records.setdefault(owner, []).append(str(addr))
            elif kind == 5 and klass == 1:
                target, end = read_name(reply, offset - size)
                assert end == offset, 'Invalid CNAME record length'
                assert owner not in aliases or aliases[owner] == target, 'Conflicting DNS aliases'
                aliases[owner] = target
        visited = set()
        while name in aliases:
            assert name not in visited, 'DNS CNAME loop'
            visited.add(name)
            name = aliases[name]
        addresses = records.get(name, [])
        assert addresses, 'No real IPv4 DNS answer'
        return {'domain': domain, 'transport': 'TCP' if tcp else 'UDP', 'answers': addresses}

    def download():
        host = 'speed.cloudflare.com'
        resolved = ({'answers': [str(args.https_address)]} if args.https_address else dns(host, False))

        class HTTPS(http.client.HTTPSConnection):
            def connect(self):
                last = None
                for address in resolved['answers']:
                    raw = wired(socket.SOCK_STREAM)
                    try:
                        raw.connect((address, 443))
                        self.sock = self._context.wrap_socket(raw, server_hostname=host)
                        self.local = self.sock.getsockname()[0]
                        self.remote = address
                        return
                    except Exception as error:
                        raw.close()
                        last = error
                raise last

        started = time.monotonic()
        conn = HTTPS(host, context=ssl.create_default_context(), timeout=12)
        try:
            received = 0
            requests = 0
            while received < args.bytes:
                size = min(8 * 1024 * 1024, args.bytes - received)
                conn.request('GET', '/__down?bytes=' + str(size), headers={'Connection': 'keep-alive'})
                response = conn.getresponse()
                actual = 0
                while chunk := response.read(65536):
                    actual += len(chunk)
                    assert actual <= size, 'Unexpectedly large HTTP body'
                    assert time.monotonic() - started < 90, 'HTTPS download deadline exceeded'
                assert response.status == 200 and actual == size, (
                    'HTTPS status=' + str(response.status) + ', bytes=' + str(actual) +
                    ', expected=' + str(size) + ', peer=' + conn.remote)
                received += actual
                requests += 1
            elapsed = time.monotonic() - started
            return {'status': response.status, 'bytes': received, 'requests': requests, 'seconds': elapsed,
                    'mbps': received * 8 / elapsed / 1000000, 'local': conn.local,
                    'remote': conn.remote, 'certificate_verified': True,
                    'bound_interface': args.interface, 'bypass_mark': args.bypass_mark}
        finally:
            conn.close()

    def ping():
        result = command(['ping', '-n', '-I', args.interface, '-c', '20', '-i', '0.2', '-W', '2', str(args.router)])
        assert re.search(r'20 packets transmitted, 20 received, 0% packet loss', result), result
        return {'transmitted': 20, 'received': 20, 'loss_percent': 0}

    def primary():
        routes = {}
        for name, extra in [('ordinary', []), ('bypass', ['from', source, 'mark', str(args.bypass_mark)])]:
            route, = json.loads(command(['ip', '-j', '-4', 'route', 'get', '1.1.1.1'] + extra))
            assert route.get('dev') == args.interface and route.get('gateway') == str(args.router), route
            routes[name] = {'device': route['dev'], 'gateway': route['gateway']}
        return routes

    jobs = [('dns_udp', lambda: dns('archlinux.org', False)),
            ('dns_tcp', lambda: dns('archlinux.org', True)), ('https', download), ('gateway_ping', ping)]
    if args.require_primary:
        jobs.append(('primary_route', primary))
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(checked, name, fn) for name, fn in jobs]
        for future in futures:
            future.result()

    def counters():
        assert before is not None, 'No initial link counters'
        entry, = json.loads(command(['ip', '-j', '-s', 'link', 'show', 'dev', args.interface]))
        assert 'LOWER_UP' in entry['flags'], 'Carrier lost during acceptance'
        delta = {direction: {key: entry['stats64'][direction][key] - value
                            for key, value in before['counters'][direction].items()}
                 for direction in ('rx', 'tx')}
        assert all(value >= 0 for row in delta.values() for value in row.values()), 'Link counters reset during acceptance'
        assert all(delta[direction]['errors'] == 0 for direction in delta), delta
        return delta

    checked('link_counter_delta', counters)
    report['passed'] = all(check['passed'] for check in report['checks'].values())
    encoded = json.dumps(report, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(encoded)
        if 'SUDO_UID' in os.environ:
            os.chown(args.output, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
    print(encoded, end='')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
