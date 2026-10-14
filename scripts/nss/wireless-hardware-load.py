#!/usr/bin/env python3
"""Controlled RF WAN load and latency; external speed-test congestion excluded."""
from pathlib import Path
import concurrent.futures
import json
import ipaddress
import os
import re
import secrets
import select
import socket
import socketserver
import subprocess
import sys
import time

PORT = 18551
ADDRESS = os.environ.get('NSS_RF_PEER', '')

if sys.argv[1:] == ['server']:
    assert ADDRESS and ipaddress.ip_address(ADDRESS).version == 4
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            stream = self.request.makefile('rb')
            request = json.loads(stream.readline())
            self.request.settimeout(40)
            if request['direction'] == 'down':
                deadline = time.monotonic() + request['seconds']
                chunk = b'Q' * 16384
                try:
                    while time.monotonic() < deadline:
                        self.request.sendall(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                total = 0
                while chunk := stream.read(16384):
                    assert chunk.count(b'Q') == len(chunk)
                    total += len(chunk)
                self.request.sendall(json.dumps({'received': total}).encode())
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_MARK,666)
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,b'wlan0\0')
            super().server_bind()
    with Server((ADDRESS, PORT), Handler) as server:
        print('READY', flush=True)
        server.serve_forever()
elif sys.argv[1:2] == ['client']:
    assert ADDRESS and ipaddress.ip_address(ADDRESS).version == 4
    direction = sys.argv[2]
    seconds = int(sys.argv[3])
    started = time.monotonic()
    count = 0
    with socket.create_connection((ADDRESS, PORT), timeout=40) as conn:
        conn.sendall((json.dumps({'direction': direction, 'seconds': seconds}) + '\n').encode())
        if direction == 'down':
            while chunk := conn.recv(65536):
                assert chunk.count(b'Q') == len(chunk)
                count += len(chunk)
        else:
            block = b'Q' * 16384
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                conn.sendall(block)
                count += len(block)
            conn.shutdown(socket.SHUT_WR)
            reply = b''
            while chunk := conn.recv(4096):
                reply += chunk
            assert json.loads(reply)['received'] == count
    elapsed = time.monotonic() - started
    assert count >= 1024 * 1024
    print(json.dumps({'bytes': count, 'seconds': elapsed, 'mbps': count * 8 / elapsed / 1e6}))
else:
    os.umask(0o077)
    namespace = 'nss-rf51'
    interface = 'nssrf51'
    label = sys.argv[1] if len(sys.argv) > 1 else 'baseline'
    local_ap = '--ap' in sys.argv[1:]
    if local_ap:
        namespace,interface = 'nss-ap51','nssap51'
    output = Path('/home/wudd/桌面/Redmi_AX3000_NSS_opt51') / (label + '-' + secrets.token_hex(4))
    output.mkdir(mode=0o700, parents=True)
    print('EVIDENCE ' + str(output), flush=True)
    here = str(Path(__file__).resolve())
    def run(argv, timeout=30):
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        with (output/'commands.log').open('a') as evidence:
            evidence.write(repr(argv)+'\n'+result.stdout+result.stderr+'\n')
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout
    assert namespace not in run(['ip', 'netns', 'list'])
    server = None
    created = False
    neighbor_changes = []
    link_created = False
    ssh = ['sudo','-n','-u','wudd','ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-o','BindInterface=eno1','-o','ControlMaster=no','-o','ControlPath=none','root@192.168.1.1']
    wan = json.loads(run(ssh+['ubus call network.interface.'+('lan' if local_ap else 'wwan')+' status']))
    assert wan.get('up') and wan.get('ipv4-address')
    router_device = wan['l3_device']
    if local_ap:
        router_device = run(ssh+['ubus call network.wireless status | jsonfilter -e \'@.*.interfaces[@.section="default_radio0"].ifname\'']).strip()
    assert re.fullmatch(r'[a-zA-Z0-9_.:@-]{1,15}', router_device)
    router_address = str(ipaddress.ip_address(wan['ipv4-address'][0]['address']))
    host_addresses = json.loads(run(['ip','-j','-4','addr','show','dev','wlan0']))
    peers = [a['local'] for item in host_addresses for a in item.get('addr_info',[]) if a.get('family')=='inet']
    ADDRESS = peers[0] if peers else None
    if label == '--check':
        print(json.dumps({'router_device':router_device,'router_address':router_address,
                          'peer_address':ADDRESS,'network_mutated':False}))
        raise SystemExit()
    assert ADDRESS, 'Connect the controlled upstream RF peer before a load test'
    assert ipaddress.ip_address(ADDRESS) in ipaddress.ip_network(router_address+'/'+str(wan['ipv4-address'][0]['mask']),strict=False)
    assert ipaddress.ip_address(ADDRESS) != ipaddress.ip_address(router_address)
    os.environ['NSS_RF_PEER'] = ADDRESS
    def replace_neighbor(prefix, address, device, mac):
        saved = json.loads(run(prefix+['ip','-j','neigh','show','to',address,'dev',device]))
        assert len(saved) <= 1
        neighbor_changes.append((prefix,address,device,saved))
        run(prefix+['ip','neigh','replace',address,'lladdr',mac,'nud','permanent','dev',device])
    def restore_neighbor(change):
        prefix,address,device,saved = change
        if not saved:
            result=subprocess.run(prefix+['ip','neigh','del',address,'dev',device],capture_output=True,text=True)
            assert result.returncode==0 or 'No such file' in result.stderr
            return
        old=saved[0]
        state=old.get('state',['STALE'])[0].lower()
        assert state in ('permanent','noarp','reachable','stale','delay','probe','failed','incomplete')
        command=prefix+['ip','neigh','replace',address,'dev',device,'nud',state]
        if old.get('lladdr'): command+=['lladdr',old['lladdr']]
        run(command)
    measurements = {'path':('wired client → router AP → laptop Wi-Fi' if local_ap else 'wired client → router STA → upstream AP → laptop Wi-Fi'),
                    'router_device':router_device,'router_address':router_address,'peer_address':ADDRESS}
    try:
        # The upstream AP does not deliver peer ARP broadcasts; use owned test neighbors.
        router_mac = run(ssh+['cat /sys/class/net/'+router_device+'/address']).strip()
        host_mac = json.loads(run(['ip','-j','link','show','dev','wlan0']))[0]['address']
        assert re.fullmatch(r'[0-9a-fA-F:]{17}',router_mac) and re.fullmatch(r'[0-9a-fA-F:]{17}',host_mac)
        if not local_ap:
            replace_neighbor([],router_address,'wlan0',router_mac)
            replace_neighbor(ssh,ADDRESS,router_device,host_mac)
        (output/'neighbors-before.json').write_text(json.dumps([{'address':a,'device':d,'saved':old} for _,a,d,old in neighbor_changes],indent=2)+'\n')
        run(['ip', 'netns', 'add', namespace]); created = True
        run(['ip', 'link', 'add', interface, 'link', 'eno1', 'type', 'macvlan', 'mode', 'private']); link_created = True
        run(['ip', 'link', 'set', interface, 'netns', namespace]); link_created = False
        run(['ip','netns','exec',namespace,'ip','link','set',interface,'up'])
        run(['ip','netns','exec',namespace,'arping','-D','-c','2','-I',interface,'192.168.1.251'],8)
        for argv in [['ip','link','set','lo','up'], ['ip','link','set',interface,'up'], ['ip','addr','add','192.168.1.251/24','dev',interface], ['ip','route','add','default','via','192.168.1.1'], ['sysctl','-qw','net.ipv4.conf.all.accept_redirects=0','net.ipv4.conf.default.accept_redirects=0']]:
            run(['ip','netns','exec',namespace] + argv)
        server = subprocess.Popen(['python3',here,'server'], stdout=subprocess.PIPE, stderr=(output/'server.stderr').open('w'), text=True)
        assert select.select([server.stdout],[],[],5)[0], 'RF server readiness timeout'
        assert server.stdout.readline().strip() == 'READY'
        if local_ap:
            # The PC owns wired and AP addresses on the same subnet. Pin this
            # test endpoint to its Wi-Fi MAC so ARP flux cannot bypass the AP.
            run(['ip','netns','exec',namespace,'ip','neigh','replace',ADDRESS,
                 'lladdr',host_mac,'nud','permanent','dev',interface])
            namespace_mac = json.loads(run(['ip','netns','exec',namespace,'ip','-j','link','show','dev',interface]))[0]['address']
            replace_neighbor([],'192.168.1.251','wlan0',namespace_mac)
        run(['ip','netns','exec',namespace,'ping','-n','-c','3','-W','3',ADDRESS], 15)
        def latency(target, seconds, name):
            result = subprocess.run(['ip','netns','exec',namespace,'ping','-n','-i','0.1','-w',str(seconds),target], text=True, capture_output=True, timeout=seconds+8)
            (output/name).write_text(result.stdout + result.stderr)
            samples = sorted(float(value) for value in re.findall(r'time[=<]([0-9.]+)',result.stdout))
            loss = re.search(r'([0-9.]+)% packet loss', result.stdout)
            assert samples, result.stderr
            return {'samples':len(samples), 'p50_ms':samples[len(samples)//2], 'p95_ms':samples[min(len(samples)-1,int(len(samples)*.95))], 'max_ms':max(samples), 'loss_percent':float(loss[1]) if loss else None}
        measurements['idle'] = latency(ADDRESS, 4, 'idle-ping.log')
        print('IDLE ' + json.dumps(measurements['idle']), flush=True)
        for direction in ('down','up'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                ping = pool.submit(latency, ADDRESS, 16, direction+'-ping.log')
                transfer = json.loads(run(['ip','netns','exec',namespace,'python3',here,'client',direction,'12'], 65))
                transfer['latency'] = ping.result()
            measurements[direction] = transfer
            print(direction.upper() + ' ' + json.dumps(transfer), flush=True)
        (output/'summary.json').write_text(json.dumps(measurements, indent=2)+'\n')
    finally:
        cleanup_errors=[]
        if server is not None:
            try:
                server.terminate()
                try: server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill(); server.wait(timeout=5)
            except Exception as error: cleanup_errors.append(str(error))
        if created:
            try: run(['ip','netns','del',namespace])
            except Exception as error: cleanup_errors.append(str(error))
        if link_created:
            try: run(['ip','link','del',interface])
            except Exception as error: cleanup_errors.append(str(error))
        for change in reversed(neighbor_changes):
            try: restore_neighbor(change)
            except Exception as error: cleanup_errors.append(str(error))
        assert not cleanup_errors, 'RF cleanup failed: '+repr(cleanup_errors)
    print('PASS controlled RF load and RTT; endpoints removed and previous neighbors restored')
