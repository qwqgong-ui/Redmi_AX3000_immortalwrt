#!/usr/bin/env python3
"""Run the actual VHT monitor TLV branch against SU/STBC Partial AID values."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", type=Path, required=True)
    args = parser.parse_args()
    ath = args.backports / "drivers/net/wireless/ath/ath11k"
    source = (ath / "hal_rx.c").read_text()
    header = (ath / "hal_rx.h").read_text()
    start = source.index("case HAL_PHYRX_VHT_SIG_A: {")
    stop = source.index("case HAL_PHYRX_HE_SIG_A_SU:", start)
    branch = source[start:stop]
    definitions = "\n".join(line for line in header.splitlines()
                            if line.startswith("#define HAL_RX_VHT_SIG_A_INFO_"))
    # GI values are the enum in the same real header; retain their values.
    gi_enum = re.search(r"enum hal_rx_vht_sig_a_gi_setting\s*\{.*?\};", header, re.S).group()
    nss_mask = next(line for line in (ath / "hal_rx.h").read_text().splitlines()
                    if line.startswith("#define VHT_SIG_SU_NSS_MASK"))
    shim = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
typedef uint32_t u32; typedef uint8_t u8;
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((0xffffffffU >> (31-(h))) & (0xffffffffU << (l)))
#define FIELD_GET(mask,v) (((v)&(mask)) >> __builtin_ctz(mask))
#define __le32_to_cpu(v) (v)
#define HAL_PHYRX_VHT_SIG_A 1
#define HAL_RX_GI_0_8_US 0
#define HAL_RX_GI_0_4_US 1
#define HAL_RX_RECEPTION_TYPE_SU 0
#define HAL_RX_RECEPTION_TYPE_MU_MIMO 1
struct hal_rx_vht_sig_a_info { u32 info0,info1; };
struct ppdu { u32 ldpc,mcs,gi,is_stbc,nss,bw,beamformed,reception_type;
 u32 vht_flag_values5,vht_flag_values3[4],vht_flag_values2,vht_flag_values4; };
'''
    harness = r'''
static unsigned decode(unsigned group,unsigned aid,unsigned encoded_nsts,bool stbc) {
 struct hal_rx_vht_sig_a_info sig={.info0=(group<<4)|(encoded_nsts<<10)|(aid<<13)|(stbc?BIT(3):0)|2,.info1=(7<<4)|1};
 struct ppdu value={0},*ppdu_info=&value;void *tlv_data=&sig;u32 info0,info1;
 switch(HAL_PHYRX_VHT_SIG_A) {
'''
    trailer = r'''
 }
 assert(value.bw==2&&value.mcs==7&&value.gi==HAL_RX_GI_0_4_US);
 assert(value.reception_type==((group==0||group==63)?HAL_RX_RECEPTION_TYPE_SU:HAL_RX_RECEPTION_TYPE_MU_MIMO));
 return value.nss;
}
int main(void) {
 for(unsigned group_index=0;group_index<2;group_index++) {
  unsigned group=group_index?63:0;
  for(unsigned aid=0;aid<512;aid++) {
   for(unsigned nsts=0;nsts<8;nsts++)assert(decode(group,aid,nsts,false)==nsts+1);
   for(unsigned streams=1;streams<=4;streams++)assert(decode(group,aid,streams*2-1,true)==streams);
  }
 }
 /* Explicit regression: Partial AID=1, NSTS encoding=1 previously gave 5. */
 assert(decode(0,1,1,true)==1);
 /* Preserve the existing MU branch, whose per-user decoding is separate. */
 assert(decode(1,0,1,false)==2);
 puts("PASS actual VHT SIG-A branch: all 512 SU Partial AIDs, groups 0/63, NSS 1..8 and STBC NSS 1..4");
}
'''
    with tempfile.TemporaryDirectory(prefix="nss-vht-rate-") as temp:
        test, binary = Path(temp) / "test.c", Path(temp) / "test"
        test.write_text(shim + definitions + "\n" + gi_enum + "\n" + nss_mask + "\n" + harness + branch + trailer)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                        str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
