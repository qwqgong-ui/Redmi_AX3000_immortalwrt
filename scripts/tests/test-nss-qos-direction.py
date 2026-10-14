#!/usr/bin/env python3
"""Compare actual ECM packet-priority code with actual NSS CREATE QoS fields."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

SHIM = r'''
#include <stdint.h>
#include <stdio.h>
#define ECM_CLASSIFIER_PROCESS_ACTION_QOS_TAG 1
#define NSS_IPV4_RULE_CREATE_QOS_VALID 1
#define NSS_IPV6_RULE_CREATE_QOS_VALID 1
enum sender_type { ECM_TRACKER_SENDER_TYPE_SRC, ECM_TRACKER_SENDER_TYPE_DEST };
struct packet { uint32_t priority; };
struct response { uint32_t process_actions, flow_qos_tag, return_qos_tag; };
struct message { struct { uint32_t flow_qos_tag, return_qos_tag; } qos_rule; uint32_t valid_flags; };
'''
TEST = r'''
int main(void) {
    const uint32_t pairs[][2]={{0,0},{2,0},{0,2},{1,7},{7,1},{0xffffffffU,0xdeadbeefU}};
    unsigned mismatches=0;
    for (unsigned i=0; i<sizeof(pairs)/sizeof(pairs[0]); i++) {
        struct response response={ECM_CLASSIFIER_PROCESS_ACTION_QOS_TAG,pairs[i][0],pairs[i][1]};
        struct message rule={0};
        create_qos(&response,&rule);
        if (!rule.valid_flags) return 2;
        for (int sender=ECM_TRACKER_SENDER_TYPE_SRC; sender<=ECM_TRACKER_SENDER_TYPE_DEST; sender++) {
            struct packet skb={0xaabbccddU};
            packet_qos(&skb,response,sender);
            uint32_t expected=sender==ECM_TRACKER_SENDER_TYPE_SRC ? rule.qos_rule.flow_qos_tag : rule.qos_rule.return_qos_tag;
            mismatches+=skb.priority!=expected;
        }
    }
    printf("native QoS packet/CREATE mismatches=%u\n",mismatches);
#ifdef EXPECT_ORIGINAL_BUG
    return mismatches==5 ? 0 : 1;
#else
    return mismatches ? 1 : 0;
#endif
}
'''

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('source',type=Path,help='prepared qca-nss-ecm source directory')
parser.add_argument('--expect-original-bug',action='store_true')
args=parser.parse_args()
for family in ('ipv4','ipv6'):
    common=(args.source/'frontends/cmn'/('ecm_ported_'+family+'.c')).read_text()
    nss=(args.source/'frontends/nss'/('ecm_nss_ported_'+family+'.c')).read_text()
    assignment=re.search(r'(skb->priority\s*=\s*[^;]+;)\s*\n\s*DEBUG_TRACE\("%px: skb priority:',common,re.S)
    create=re.search(r'if \(pr->process_actions & ECM_CLASSIFIER_PROCESS_ACTION_QOS_TAG\) \{([^}]+)\}',nss,re.S)
    if not assignment or not create:raise RuntimeError('Actual QoS blocks not found: '+family)
    code=SHIM+'\nstatic void packet_qos(struct packet *skb,struct response prevalent_pr,enum sender_type sender) {\n'+assignment[1]+'\n}\n'
    code+='static void create_qos(struct response *pr,struct message *nircm) {\n'+create[1]+'\n}\n'+TEST
    with tempfile.TemporaryDirectory(prefix='nss-qos-direction-') as tmp:
        source=Path(tmp)/'test.c';binary=Path(tmp)/'test';source.write_text(code)
        command=['cc','-std=c11','-O1','-g','-fno-omit-frame-pointer','-fsanitize=address,undefined','-Wall','-Wextra']
        if args.expect_original_bug:command+=['-DEXPECT_ORIGINAL_BUG']
        subprocess.run(command+[str(source),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    print('PASS '+family+(' original wrong return direction reproduced' if args.expect_original_bug else ' both packet directions match NSS CREATE'))
