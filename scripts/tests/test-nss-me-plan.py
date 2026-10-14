#!/usr/bin/env python3
"""Compare the real ME planner with the prepared bridge's forwarding function."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('me_mdb_test', Path(__file__).with_name('test-nss-mdb.py'))
mdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mdb)
function = mdb.function

EXTRA = r'''
#define CONFIG_IPV6 1
#define ATH11K_NSS_ME_SOURCE_MAX 4
typedef unsigned refcount_t;
static bool ipv4_is_zeronet(__be32 a) { return !(ntohl(a)&0xff000000); }
static bool ipv6_addr_equal(const struct in6_addr *a,const struct in6_addr *b) { return !memcmp(a,b,16); }
static bool ipv6_addr_any(const struct in6_addr *a) { return !memcmp(a,(u8[16]){0},16); }
static bool ipv6_addr_is_multicast(const struct in6_addr *a) { return a->s6_addr[0]==255; }
static bool ipv6_addr_is_ll_all_nodes(const struct in6_addr *a) { return !memcmp(a,(u8[16]){255,2,0,0,0,0,0,0,0,0,0,0,0,0,0,1},16); }
'''

TEST = r'''
static struct br_mcast_offload_host hosts[32];
static struct br_ip keys[16];
static struct br_mcast_offload_lookup_snapshot info;
static struct ath11k_nss_me_member plan[32];
static const u8 mac[2][6]={{2,0,0,0,0,1},{2,0,0,0,0,2}};
static u32 count;
static void source(struct br_ip *key,unsigned int index) {
    memset(&key->src,0,sizeof(key->src));
    if(key->proto==htons(ETH_P_IP)) key->src.ip4=htonl(0xc000020a+index);
    else { key->src.ip6.s6_addr[0]=0x20;key->src.ip6.s6_addr[1]=1;key->src.ip6.s6_addr[2]=0xd;key->src.ip6.s6_addr[3]=0xb8;key->src.ip6.s6_addr[15]=10+index; }
}
static void fixture(bool v6,bool exclude) {
    memset(hosts,0,sizeof(hosts));memset(keys,0,sizeof(keys));memset(&info,0,sizeof(info));
    info=(struct br_mcast_offload_lookup_snapshot){.seq=9,.bridge_ifindex=1,.host_count=2,.key_count=1,.snooping=true,.forwarding=true,.multicast_to_unicast=true,.querier_ipv4=true,.querier_ipv6=true,.source_filter_ipv4=true,.source_filter_ipv6=true};
    keys[0].proto=htons(v6?ETH_P_IPV6:ETH_P_IP);
    if(v6) { keys[0].dst.ip6.s6_addr[0]=0xff;keys[0].dst.ip6.s6_addr[1]=0x3e;keys[0].dst.ip6.s6_addr[15]=0x35; }
    else keys[0].dst.ip4=htonl(0xef230001);
    for(int i=0;i<2;i++) hosts[i]=(struct br_mcast_offload_host){.addr=keys[0],.filter_mode=exclude?MCAST_EXCLUDE:MCAST_INCLUDE,.flags=BR_MCAST_OFFLOAD_HOST_SPECIFIC};
    memcpy(hosts[0].host_mac,mac[0],6);memcpy(hosts[1].host_mac,mac[1],6);
}
static void add_key(unsigned int index) { keys[info.key_count]=keys[0];source(&keys[info.key_count],index);info.key_count++; }
static void add_host(unsigned int key,unsigned int which,u8 flags) {
    struct br_mcast_offload_host *host=&hosts[info.host_count++];
    *host=(struct br_mcast_offload_host){.addr=keys[key],.filter_mode=MCAST_INCLUDE,.flags=BR_MCAST_OFFLOAD_HOST_SPECIFIC|flags};
    memcpy(host->host_mac,mac[which],6);
}
static int build(u32 capacity) { count=0xbad;return ath11k_nss_me_plan_build(hosts,keys,&info,plan,capacity,&count); }
static bool firmware_accepts(const struct br_ip *packet,unsigned int which) {
    for(u32 i=0;i<count;i++) if(ath11k_nss_me_same_group(&plan[i].group,packet)&&!memcmp(plan[i].mac,mac[which],6)) {
        bool matched=false;size_t len=packet->proto==htons(ETH_P_IP)?4:16;
        for(u32 j=0;j<plan[i].source_count;j++) matched|=!memcmp(plan[i].source[j],&packet->src,len);
        return plan[i].mode==1?matched:!matched;
    }
    return false;
}
/* Use the real br_multicast_flood body after selecting its real global key. */
static bool bridge_accepts(const struct br_ip *packet,unsigned int which) {
    struct net_bridge br={0};struct net_bridge_port port={.flags=BR_MULTICAST_TO_UNICAST};
    struct net_bridge_port_group groups[32]={0};struct net_bridge_mdb_entry entry={.br=&br};
    struct net_bridge_mcast ctx={.br=&br,.multicast_igmp_version=info.source_filter_ipv4?3:2,.multicast_mld_version=info.source_filter_ipv6?2:1};
    struct sk_buff skb={.protocol=packet->proto};u32 n=0;bool found=false;
    struct br_ip selected=*packet;
    if(!br_multicast_should_handle_mode(&ctx,packet->proto)) memset(&selected.src,0,sizeof(selected.src));
    for(u32 i=0;i<info.key_count;i++) if(ath11k_nss_me_same_key(&selected,&keys[i])) { found=true;break; }
    if(!found) memset(&selected.src,0,sizeof(selected.src));
    entry.addr=selected;
    for(u32 i=0;i<info.host_count;i++) if(ath11k_nss_me_same_key(&hosts[i].addr,&selected)&&!memcmp(hosts[i].host_mac,mac[which],6)) {
        groups[n].key.port=&port;groups[n].key.addr=selected;groups[n].host_specific=true;groups[n].rt_protocol=RTPROT_KERNEL;
        groups[n].filter_mode=hosts[i].filter_mode;groups[n].flags=(hosts[i].flags&BR_MCAST_OFFLOAD_BLOCKED)?MDB_PG_FLAGS_BLOCKED:0;
        memcpy(groups[n].eth_addr,hosts[i].host_mac,6);
        if(n) groups[n-1].next=&groups[n];else entry.ports=&groups[n];n++;
    }
    ordinary_count=unicast_count=free_count=0;
    rcu_read_lock();br_multicast_flood(&entry,&skb,&ctx,false,false);rcu_read_unlock();
    assert(!ordinary_count);return unicast_count>0;
}
static void compare(void) {
    for(unsigned int i=0;i<9;i++) {
        struct br_ip ip=keys[0];source(&ip,i);
        struct br_mcast_packet *packet=calloc(1,sizeof(*packet)+2*ETH_ALEN);
        struct ath11k_nss_me_policy policy={.snapshot=info,.members=plan,.count=count,.cookie=77};
        assert(packet);packet->action=BR_MCAST_PACKET_HOSTS;packet->seq=info.seq;
        packet->mcu_cookie=77;packet->proto=ip.proto;
        size_t len=ip.proto==htons(ETH_P_IP)?4:16;
        memcpy(packet->source_ip,&ip.src,len);memcpy(packet->group_ip,&ip.dst,len);
        for(unsigned int which=0;which<2;which++) {
            bool native=bridge_accepts(&ip,which);
            assert(firmware_accepts(&ip,which)==native);
            if(native) memcpy(packet->mac[packet->count++],mac[which],ETH_ALEN);
        }
        if(packet->count) {
            assert(ath11k_nss_me_targets_same(&policy,packet));
            packet->mcu_cookie++;assert(!ath11k_nss_me_targets_same(&policy,packet));packet->mcu_cookie--;
            packet->seq++;assert(!ath11k_nss_me_targets_same(&policy,packet));packet->seq--;
            packet->mac[0][5]^=0x80;assert(!ath11k_nss_me_targets_same(&policy,packet));packet->mac[0][5]^=0x80;
            packet->count--;assert(!ath11k_nss_me_targets_same(&policy,packet));packet->count++;
            memcpy(packet->source_mac,packet->mac[0],ETH_ALEN);
            assert(!ath11k_nss_me_targets_same(&policy,packet));
        }
        free(packet);
    }
}
int main(void) {
    fixture(false,true);keys[0].src.ip4=htonl(0x00010203);assert(ath11k_nss_me_star_g(&keys[0]));
    keys[0].src.ip4=htonl(0x01000000);assert(!ath11k_nss_me_star_g(&keys[0]));
    for(int v6=0;v6<2;v6++) {
        fixture(v6,true);assert(build(32)==0&&count==2&&plan[0].mode==2&&!plan[0].source_count);compare();
        fixture(v6,false);assert(build(32)==0&&!count);compare();
        add_key(1);add_key(2);add_host(1,0,0);add_host(2,1,0);
        assert(build(32)==0&&count==2&&plan[0].mode==1&&plan[0].source_count==1);compare();
        fixture(v6,true);for(int i=1;i<=4;i++)add_key(i);
        add_host(1,0,BR_MCAST_OFFLOAD_STAR_EXCL);add_host(2,0,BR_MCAST_OFFLOAD_BLOCKED);
        add_host(3,0,BR_MCAST_OFFLOAD_STAR_EXCL);
        assert(build(32)==0&&count==2&&plan[0].mode==2&&plan[0].source_count==2);compare();
        /* Foreign S,G with no local STAR_EXCL is excluded, not inherited. */
        fixture(v6,true);add_key(3);assert(build(32)==0&&plan[0].source_count==1);compare();
        info.source_filter_ipv4=info.source_filter_ipv6=false;
        assert(build(32)==0&&!plan[0].source_count);compare();
        fixture(v6,false);add_key(1);add_host(1,0,0);info.source_filter_ipv4=info.source_filter_ipv6=false;
        assert(build(32)==0&&count==2&&plan[0].mode==2);compare();
        fixture(v6,true);for(int i=1;i<=5;i++)add_key(i);assert(build(32)==-E2BIG&&!count);
        info.key_count=5;keys[5]=keys[4];info.key_count=6;assert(build(32)==0&&plan[0].source_count==4);compare();
        fixture(v6,true);assert(build(1)==-E2BIG&&!count);
        fixture(v6,false);add_key(1);add_host(1,0,0);hosts[info.host_count]=hosts[2];info.host_count++;
        assert(build(32)==0&&count==1);compare();
        hosts[3].flags|=BR_MCAST_OFFLOAD_BLOCKED;assert(build(32)==-EUCLEAN&&!count);
        fixture(v6,true);hosts[0].flags&=~BR_MCAST_OFFLOAD_HOST_SPECIFIC;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.querier_ipv4=info.querier_ipv6=false;assert(build(32)==0&&!count);
        /* A row for the other family without a querier cannot disable this
         * family's valid full-port policy. It is absent from the ME table.
         */
        fixture(v6,true);keys[1]=(struct br_ip){.proto=htons(v6?ETH_P_IP:ETH_P_IPV6)};
        if(v6) keys[1].dst.ip4=htonl(0xef230099);
        else {keys[1].dst.ip6.s6_addr[0]=255;keys[1].dst.ip6.s6_addr[1]=0x3e;keys[1].dst.ip6.s6_addr[15]=0x99;}
        hosts[2]=hosts[0];hosts[2].addr=keys[1];info.host_count=3;info.key_count=2;
        if(v6) info.querier_ipv4=false;else info.querier_ipv6=false;
        assert(!ath11k_nss_me_protocol_ready(&info,&keys[1]));
        assert(build(32)==0&&count==2);compare();
        for(u32 i=0;i<count;i++) assert(plan[i].group.proto==keys[0].proto);
        struct br_mcast_packet packet={.action=BR_MCAST_PACKET_ORDINARY,.proto=keys[1].proto};
        struct ath11k_nss_me_policy policy={.snapshot=info,.members=plan,.count=count,.cookie=77};
        assert(!ath11k_nss_me_targets_same(&policy,&packet));
        /* Enabling its querier admits both families; the full snapshot flags
         * also force the old committed policy to fail revalidation.
         */
        info.querier_ipv4=info.querier_ipv6=true;
        assert(build(32)==0&&count==3);compare();
        keys[1].proto=0;hosts[2].addr=keys[1];info.querier_ipv4=info.querier_ipv6=false;
        assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.router_ipv4=true;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.router_ipv6=true;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.forwarding=false;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.snooping=false;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.multicast_to_unicast=false;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.vlan_snooping=true;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);hosts[0].addr.vid=1;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);hosts[0].flags|=0x80;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);hosts[0].host_mac[0]=1;assert(build(32)==-EOPNOTSUPP&&!count);
        fixture(v6,true);info.key_count=0;assert(build(32)==-EUCLEAN&&!count);
        fixture(v6,true);add_key(1);hosts[0].addr=keys[1];hosts[1].addr=keys[1];keys[0]=keys[1];info.key_count=1;
        assert(build(32)==-EOPNOTSUPP&&!count);
        printf("IPv%d ME policy and production RAW target comparison: actual bridge forwarding, INCLUDE/EXCLUDE, foreign S,G, legacy, stale cookies/epochs and source suppression passed\n",v6?6:4);
    }
    fixture(false,true);hosts[0].addr.dst.ip4=htonl(0xe00000fb);assert(build(32)==-EOPNOTSUPP&&!count);
    fixture(true,true);hosts[0].addr.dst.ip6=(struct in6_addr){.s6_addr={255,2,0,0,0,0,0,0,0,0,0,0,0,0,0,1}};assert(build(32)==-EOPNOTSUPP&&!count);
    assert(ath11k_nss_me_plan_build(NULL,keys,&info,plan,32,&count)==-EINVAL);
    assert(!rcu_depth&&!lock_depth);
    return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ath11k-source', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--bridge-header', type=Path)
    args = parser.parse_args()
    header = (args.bridge_header or args.kernel/'include/linux/if_bridge.h').read_text()
    plan_header = (args.ath11k_source/'nss_me_plan.h').read_text()
    packet_header = (args.kernel/'include/linux/br_mcast_packet.h').read_text()
    me_source = (args.ath11k_source/'nss_me.c').read_text()
    declarations = []
    for name,text in [('br_mcast_offload_host',header),('br_mcast_offload_lookup_snapshot',header),
                      ('ath11k_nss_me_member',plan_header),('br_mcast_packet',packet_header),
                      ('ath11k_nss_me_policy',me_source)]:
        match = re.search(r'struct '+name+r'\s*\{[^}]*\};',text)
        if not match:
            raise ValueError('Missing actual declaration: '+name)
        declarations.append(match.group())
    declarations.append(re.search(r'enum br_mcast_packet_action\s*\{[^}]*\};',packet_header).group())
    private = (args.kernel/'net/bridge/br_private.h').read_text()
    bodies = []
    for name in ('__br_multicast_querier_exists','br_multicast_querier_exists','br_multicast_should_handle_mode'):
        body = function(private,name)
        if body.lstrip().startswith(name+'('):
            body = 'static inline bool '+body
        bodies.append(body)
    for name in ('br_multicast_port_static_override','br_multicast_pg_allowed','br_multicast_port_has_aggregate','br_multicast_port_allowed'):
        body = function(private,name)
        if name != 'br_multicast_pg_allowed':
            body = ('static inline struct net_bridge_port_group *' if name=='br_multicast_port_static_override' else 'static inline bool ')+body
        bodies.append(body)
    bodies.append(function((args.kernel/'net/bridge/br_forward.c').read_text(),'br_multicast_flood'))
    planner = re.sub(r'^#include .*\n','',(args.ath11k_source/'nss_me_plan.c').read_text(),flags=re.M)
    targets = function(me_source,'ath11k_nss_me_member_accept') + function(me_source,'ath11k_nss_me_targets_same')
    with tempfile.TemporaryDirectory(prefix='nss-me-plan-') as directory:
        source = Path(directory)/'plan.c'
        source.write_text(mdb.SHIM+'\n'+EXTRA+'\n'+'\n'.join(declarations)+'\n'+'\n'.join(bodies)+'\n'+planner+'\n'+targets+'\n'+TEST)
        binary = source.with_suffix('')
        subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-O1','-g','-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer','-Wall','-Wextra','-Werror','-Wno-unused-function',str(source),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)

if __name__=='__main__':
    main()
