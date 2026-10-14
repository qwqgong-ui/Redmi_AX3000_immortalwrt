#!/usr/bin/env python3
"""Test the actual default-table predicate saved by native multicast input."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('ecm_mcast_test',
                            Path(__file__).with_name('test-nss-ecm-multicast.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint16_t u16;
typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define RT_TABLE_DEFAULT 253
#define RT6_TABLE_DFLT 254
struct net { int id; };
static struct net init_net, other_net;
static bool net_eq(struct net *a, struct net *b) { return a==b; }
struct cb { u16 flags; };
struct sk_buff { u32 mark; unsigned char cb[48]; };
#define IPCB(skb) ((struct cb *)(skb)->cb)
#define IP6CB(skb) ((struct cb *)(skb)->cb)
'''

TESTS = r'''
int main(void) {
 struct sk_buff skb={.mark=7}, copy={};
 @CB@(&skb)->flags=@FORWARDED@ | BIT(8);
 @MARK@(&init_net,&skb,@DEFAULT@);
 assert(@ELIGIBLE@(&init_net,&skb));
 assert(@CB@(&skb)->flags & BIT(8));
 skb.mark=0xffffffff; /* FORWARD may change mark; it must not reselect the table. */
 assert(@ELIGIBLE@(&init_net,&skb));
 struct sk_buff *new=&copy, *old=&skb;
 @CLONE_COPY@
 assert(@ELIGIBLE@(&init_net,&copy));
 @MARK@(&init_net,&skb,@DEFAULT@+1);
 assert(!@ELIGIBLE@(&init_net,&skb));
 assert(@CB@(&skb)->flags & BIT(8));
 @MARK@(&other_net,&skb,@DEFAULT@);
 assert(!@ELIGIBLE@(&init_net,&skb));
 @MARK@(&init_net,&skb,@DEFAULT@);
 assert(!@ELIGIBLE@(&other_net,&skb));
 @CB@(&skb)->flags &= ~@FORWARDED@;
 assert(!@ELIGIBLE@(&init_net,&skb));
 memset(skb.cb,0,sizeof(skb.cb)); /* Native input reinitializes its protocol cb. */
 assert(!@ELIGIBLE@(&init_net,&skb));
 assert(!@ELIGIBLE@(&init_net,NULL));
 puts("IPv@V@ mroute: default/nondefault table, namespace, FORWARD mark, cloned cb and missing/cleared input predicate passed");
 return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    args = parser.parse_args()
    skbuff = (args.kernel / 'net/core/skbuff.c').read_text()
    clone = re.search(r'memcpy\(new->cb, old->cb, sizeof\(old->cb\)\);', skbuff)
    if not clone:
        raise ValueError('Actual skb clone no longer copies cb as expected')
    with tempfile.TemporaryDirectory(prefix='nss-mroute-table-') as temporary:
        for version, relative, header, prefix, cb, default in [
            (4, 'net/ipv4/ipmr.c', 'include/net/ip.h', 'IPSKB', 'IPCB', 'RT_TABLE_DEFAULT'),
            (6, 'net/ipv6/ip6mr.c', 'include/linux/ipv6.h', 'IP6SKB', 'IP6CB', 'RT6_TABLE_DFLT')]:
            source = (args.kernel / relative).read_text()
            definitions = (args.kernel / header).read_text()
            flags = '\n'.join(line for line in definitions.splitlines()
                            if re.match(r'#define\s+' + prefix + r'_(FORWARDED|MROUTE_OFFLOAD_DEFAULT)\s', line))
            family = 'ipmr' if version == 4 else 'ip6mr'
            body = flags + '\n' + '\n\n'.join(module.function(source, family + suffix)
                                for suffix in ['_mfc_offload_mark', '_mfc_offload_eligible'])
            body = body.replace('EXPORT_SYMBOL_GPL', 'UNUSED_EXPORT')
            test = TESTS
            for key, value in {'@V@': str(version), '@CB@': cb, '@DEFAULT@': default,
                    '@FORWARDED@': prefix + '_FORWARDED', '@MARK@': family + '_mfc_offload_mark',
                    '@ELIGIBLE@': family + '_mfc_offload_eligible', '@CLONE_COPY@': clone.group(0)}.items():
                test = test.replace(key, value)
            path = Path(temporary) / f'ipv{version}.c'
            binary = path.with_suffix('')
            path.write_text(SHIM + body + test)
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
                str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
