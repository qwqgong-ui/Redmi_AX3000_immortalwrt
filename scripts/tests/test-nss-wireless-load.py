#!/usr/bin/env python3
"""Run the actual load-result parser without invoking its network test entrypoint."""
import ast
from pathlib import Path
import re

source = Path(__file__).resolve().parents[1] / 'nss/wireless-hardware-load.py'
tree = ast.parse(source.read_text())
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'parse_latency')
namespace = {'re': re}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
parse = namespace['parse_latency']
result = parse('''64 bytes: icmp_seq=1 ttl=64 time=2.0 ms
64 bytes: icmp_seq=1 ttl=64 time=90.0 ms (DUP!)
64 bytes: icmp_seq=2 ttl=64 time=3.0 ms
3 packets transmitted, 2 received, +1 duplicates, 33.3333% packet loss, time 100ms
''')
assert result['samples'] == 2 and result['duplicates'] == 1 and result['transmitted'] == 3
assert result['max_ms'] == 3 and result['loss_percent'] > 0
try:
    parse('64 bytes: icmp_seq=1 ttl=64 time=1.0 ms\n')
except AssertionError:
    pass
else:
    raise AssertionError('Partial ping output accepted as completed test')
print('PASS wireless load parser preserves duplicates/loss and rejects incomplete observations')
