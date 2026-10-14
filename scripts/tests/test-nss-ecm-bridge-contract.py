#!/usr/bin/env python3
"""Execute the production AP contract boundary and native-M2U IP detector."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('control', Path(__file__).with_name('test-nss-control.py'))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <arpa/inet.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#define IS_ENABLED(x) (x)
#define CONFIG_BRIDGE_IGMP_SNOOPING BRIDGE_PROFILE
#define CONFIG_CFG80211_HEADERS WIRELESS_PROFILE
#define CONFIG_IPV6 1
#define ETH_P_IP 0x800
#define ETH_P_IPV6 0x86dd
enum { NL80211_IFTYPE_STATION, NL80211_IFTYPE_AP, NL80211_IFTYPE_AP_VLAN,
       NL80211_IFTYPE_MESH_POINT, NL80211_IFTYPE_MONITOR };
struct wireless_dev { int iftype; };
struct net_device { unsigned dummy;
#if WIRELESS_PROFILE
 struct wireless_dev *ieee80211_ptr;
#endif
};
struct ethhdr { uint8_t h_dest[6],h_source[6];uint16_t h_proto; };
struct iphdr { uint8_t ihl:4,version:4;uint8_t tos;uint16_t len,id,frag;
 uint8_t ttl,protocol;uint16_t check;uint32_t saddr,daddr; };
struct ipv6hdr { uint8_t priority:4,version:4;uint8_t flow[3];uint16_t len;
 uint8_t nexthdr,hop_limit;struct in6_addr saddr,daddr; };
struct sk_buff { bool br_mcast_contract;unsigned offset,len;struct ethhdr eth;
 unsigned char data[128]; };
static const struct ethhdr *eth_hdr(const struct sk_buff *s) { return &s->eth; }
static int skb_network_offset(const struct sk_buff *s) { return s->offset; }
static void *skb_header_pointer(const struct sk_buff *s,int off,unsigned len,void *copy) {
 if(off<0 || (unsigned)off>s->len || len>s->len-(unsigned)off)return NULL;
 memcpy(copy,s->data+off,len);return copy;
}
static bool ipv4_is_multicast(uint32_t addr) { return (ntohl(addr)&0xf0000000)==0xe0000000; }
static bool ipv6_addr_is_multicast(const struct in6_addr *addr) { return addr->s6_addr[0]==0xff; }
'''

CASES = r'''
int main(void) {
 struct wireless_dev w={.iftype=NL80211_IFTYPE_AP};
 struct net_device ap={0},wired={0};
#if WIRELESS_PROFILE
 ap.ieee80211_ptr=&w;
#endif
 struct sk_buff s={.br_mcast_contract=true,.offset=17,.len=128},before=s;
 bool enabled=NSS_PROFILE && SNOOPER_PROFILE && BRIDGE_PROFILE && WIRELESS_PROFILE;
 assert(ecm_bridge_mcast_contract(&ap,&s)==enabled);
 assert(!memcmp(&s,&before,sizeof(s)));
 w.iftype=NL80211_IFTYPE_AP_VLAN;assert(ecm_bridge_mcast_contract(&ap,&s)==enabled);
 for(unsigned type=0;type<=NL80211_IFTYPE_MONITOR;type++) {
  w.iftype=type;assert(w.iftype==(int)type);assert(ecm_bridge_mcast_contract(&ap,&s)==
   (enabled&&(type==NL80211_IFTYPE_AP || type==NL80211_IFTYPE_AP_VLAN)));
 }
 assert(!ecm_bridge_mcast_contract(&wired,&s));assert(!ecm_bridge_mcast_contract(NULL,&s));
 w.iftype=NL80211_IFTYPE_AP;s.br_mcast_contract=false;
 assert(!ecm_bridge_mcast_contract(&ap,&s));
 /* UC Ethernet destination after M2U still has an IP multicast destination.
  * Nonzero network offset makes a data-at-Ethernet parse fail this test.
  */
 struct iphdr ip={.version=4,.ihl=5,.daddr=htonl(0xef270001)};
 s.eth.h_proto=htons(ETH_P_IP);memcpy(s.data+s.offset,&ip,sizeof(ip));
 assert(br_mcast_packet_ip_group(&s));
 ip.daddr=htonl(0xc0a80164);memcpy(s.data+s.offset,&ip,sizeof(ip));
 assert(!br_mcast_packet_ip_group(&s));
 ip.daddr=htonl(0xef270001);ip.ihl=4;memcpy(s.data+s.offset,&ip,sizeof(ip));
 assert(!br_mcast_packet_ip_group(&s));
 ip.ihl=5;ip.version=6;memcpy(s.data+s.offset,&ip,sizeof(ip));
 assert(!br_mcast_packet_ip_group(&s));
 s.len=s.offset+sizeof(ip)-1;assert(!br_mcast_packet_ip_group(&s));s.len=128;
 struct ipv6hdr ip6={.version=6};ip6.daddr.s6_addr[0]=0xff;ip6.daddr.s6_addr[15]=1;
 s.eth.h_proto=htons(ETH_P_IPV6);memcpy(s.data+s.offset,&ip6,sizeof(ip6));
 assert(br_mcast_packet_ip_group(&s));
 ip6.daddr.s6_addr[0]=0x20;memcpy(s.data+s.offset,&ip6,sizeof(ip6));
 assert(!br_mcast_packet_ip_group(&s));
 ip6.daddr.s6_addr[0]=0xff;ip6.version=4;memcpy(s.data+s.offset,&ip6,sizeof(ip6));
 assert(!br_mcast_packet_ip_group(&s));
 s.len=s.offset+sizeof(ip6)-1;assert(!br_mcast_packet_ip_group(&s));
 s.eth.h_proto=htons(0x806);assert(!br_mcast_packet_ip_group(&s));
 puts("PASS actual ECM AP contract no-op/profile boundary and native M2U IPv4/IPv6 detector");
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--ecm', type=Path, required=True)
    args = parser.parse_args()
    source = args.ecm/'frontends/cmn'
    header = (source/'ecm_bridge_mcast_contract.h').read_text()
    header = re.sub(r'^#include[^\n]*\n', '', header, flags=re.M)
    detector = extract.function((args.kernel/'net/bridge/br_forward.c').read_text(),
                                'br_mcast_packet_ip_group')
    for family in (4, 6):
        body = extract.function((source/f'ecm_ipv{family}.c').read_text(),
                                f'ecm_ipv{family}_bridge_post_routing_hook')
        first = body.index('if (ecm_bridge_mcast_contract(out, skb))')
        assert body[first:].startswith('if (ecm_bridge_mcast_contract(out, skb))\n\t\treturn NF_ACCEPT;')
        assert body.index('DEBUG_TRACE') > first
        assert body.index('spin_lock_bh') > first
        text = (source/f'ecm_ipv{family}.c').read_text()
        binding = text[text.index(f'static struct nf_hook_ops ecm_ipv{family}_netfilter_bridge_hooks'):]
        assert '#ifdef ECM_BRIDGE_AP_MCAST_CONTRACT\n\t\t.hook_ops_type\t= NF_HOOK_OP_BRIDGE_AP_MCAST_CONTRACT,' in binding
    with tempfile.TemporaryDirectory(prefix='nss-ecm-contract-') as directory:
        cfile = Path(directory)/'test.c'
        binary = Path(directory)/'test'
        cfile.write_text(SHIM+header+detector+CASES)
        for nss,snooper,bridge,wireless in ((1,1,1,1),(0,1,1,1),(1,0,1,1),(1,1,0,1),(1,1,1,0)):
            flags = [f'-DNSS_PROFILE={nss}',f'-DSNOOPER_PROFILE={snooper}',
                     f'-DBRIDGE_PROFILE={bridge}',f'-DWIRELESS_PROFILE={wireless}']
            if nss:
                flags.append('-DECM_FRONT_END_NSS_ENABLE')
            if snooper:
                flags.append('-DECM_MCAST_LINUX_SNOOPER_SUPPORT')
            subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Werror',
                            '-O1','-g','-fsanitize=address,undefined','-fno-pie','-no-pie',
                            *flags,str(cfile),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

if __name__ == '__main__':
    main()
