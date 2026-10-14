#!/usr/bin/env python3
"""Exercise the actual bounded EAPOL trace parser under address/UB sanitizers."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
args = parser.parse_args()
source = args.source.read_text()
start = source.index('static bool ath11k_nss_eapol_header(')
opening = source.index('{', start)
depth = 1
end = opening + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
function = source[start:end]
assert 'skb_copy_bits(skb, 0, header, 31)' in function
assert 'skb->len < 31' in function
tx = source[source.index('static void ath11k_nss_trace_eapol_tx('):
            source.index('static void ath11k_nss_trace_eapol(', start)]
assert 'skb->' not in tx, 'TX result trace must use the saved header after NSS consumes skb'
assert 'get_unaligned_be64(header + 23)' in tx
assert 'header + 31' not in tx

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
#define ETH_P_PAE 0x888e
#define ETH_HLEN 14
struct sk_buff { unsigned int len; const u8 *data; bool fail_copy; };
static unsigned copies;
static u16 get_unaligned_be16(const void *v) {
    const u8 *p = v; return ((u16)p[0] << 8) | p[1];
}
static int skb_copy_bits(struct sk_buff *s, int off, void *dst, int len) {
    copies++;
    if (s->fail_copy) return -1;
    assert(off >= 0 && len >= 0 && (unsigned)(off + len) <= s->len);
    memcpy(dst, s->data + off, len); return 0;
}
''' + function + r'''
static void valid(u8 *frame, unsigned length) {
    memset(frame, 0xa5, length);
    frame[12]=0x88; frame[13]=0x8e; frame[14]=2; frame[15]=3;
    frame[16]=0; frame[17]=95; frame[18]=2;
}
int main(void) {
    u8 header[31], *frame;
    struct sk_buff skb = {0};
    for (unsigned length=0; length<31; length++) {
        frame=malloc(length ? length : 1); memset(frame, 0, length);
        skb=(struct sk_buff){length, frame, false}; copies=0;
        assert(!ath11k_nss_eapol_header(&skb, header)); assert(copies==0);
        free(frame);
    }
    frame=malloc(113); valid(frame, 113);
    skb=(struct sk_buff){113, frame, false};
    assert(ath11k_nss_eapol_header(&skb, header));
    skb.fail_copy=true; assert(!ath11k_nss_eapol_header(&skb, header));
    skb.fail_copy=false;
    frame[13]=0; assert(!ath11k_nss_eapol_header(&skb, header)); frame[13]=0x8e;
    frame[15]=0; assert(!ath11k_nss_eapol_header(&skb, header)); frame[15]=3;
    frame[17]=12; assert(!ath11k_nss_eapol_header(&skb, header));
    frame[17]=96; assert(!ath11k_nss_eapol_header(&skb, header));
    frame[16]=255; frame[17]=255; assert(!ath11k_nss_eapol_header(&skb, header));
    free(frame);
    for (unsigned length=31; length<=256; length++) {
        frame=malloc(length); valid(frame, length);
        skb=(struct sk_buff){length, frame, false};
        for (unsigned declared=0; declared<512; declared++) {
            frame[16]=declared>>8; frame[17]=declared;
            (void)ath11k_nss_eapol_header(&skb, header);
        }
        free(frame);
    }
    puts("PASS bounded headers, truncated/copy-failed frames, malformed lengths, TX ownership");
}
'''
with tempfile.TemporaryDirectory(prefix='nss-eapol-trace-') as temporary:
    work = Path(temporary)
    (work / 'test.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(work / 'test.c'), '-o', str(work / 'test')], check=True)
    subprocess.run([str(work / 'test')], check=True, timeout=15)
