#!/usr/bin/env python3
"""Run real IPQ5018/QCN6122 REO setup against an instrumented register file."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "extract_nss", Path(__file__).with_name("test-nss-control.py"))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) ((~0U<<(l))&(~0U>>(31-(h))))
#define FIELD_PREP(m,v) (((u32)(v)<<__builtin_ctz(m))&(m))
#define HAL_SEQ_WCSS_UMAC_REO_REG 0x10000
#define HAL_REO1_GEN_ENABLE 0
#define HAL_REO1_GEN_ENABLE_FRAG_DST_RING GENMASK(25,23)
#define HAL_REO1_GEN_ENABLE_AGING_LIST_ENABLE BIT(2)
#define HAL_REO1_GEN_ENABLE_AGING_FLUSH_ENABLE BIT(3)
#define HAL_REO1_MISC_CTL(ab) ((ab)->hw_params.regs->misc)
#define HAL_REO1_AGING_THRESH_IX_0(ab) 0x564
#define HAL_REO1_AGING_THRESH_IX_1(ab) 0x568
#define HAL_REO1_AGING_THRESH_IX_2(ab) 0x56c
#define HAL_REO1_AGING_THRESH_IX_3(ab) 0x570
#define HAL_DEFAULT_REO_TIMEOUT_USEC 100000
#define HAL_REO1_DEST_RING_CTRL_IX_0 0x4
#define HAL_REO1_DEST_RING_CTRL_IX_1 0x8
#define HAL_REO1_DEST_RING_CTRL_IX_2 0xc
#define HAL_REO1_DEST_RING_CTRL_IX_3 0x10
#define HAL_HASH_ROUTING_RING_SW1 1
#define HAL_HASH_ROUTING_RING_SW2 2
#define HAL_HASH_ROUTING_RING_SW3 3
#define HAL_HASH_ROUTING_RING_SW4 4
#define HAL_SRNG_RING_ID_REO2SW1 0
#define HAL_SRNG_REO_ALTERNATE_SELECT 7
struct regs { unsigned misc; };
struct ath11k_base { struct { bool enabled; } nss;struct { const struct regs *regs; } hw_params; };
static u32 registers[0x800/4];
static unsigned writes[0x800/4];
static u32 ath11k_hif_read32(struct ath11k_base *ab,u32 addr) {
 (void)ab;assert(addr>=0x10000&&addr<0x10800&&!(addr&3));return registers[(addr-0x10000)/4];
}
static void ath11k_hif_write32(struct ath11k_base *ab,u32 addr,u32 value) {
 (void)ab;assert(addr>=0x10000&&addr<0x10800&&!(addr&3));
 registers[(addr-0x10000)/4]=value;writes[(addr-0x10000)/4]++;
}
'''

TEST = r'''
int main(void) {
 struct regs hw[]={ {.misc=IPQ_MISC},{.misc=QCN_MISC} };
 /* Independent values from fw-api qca5018/qcn6122 MISC register definitions. */
 assert(HAL_IPQ5018_REO1_MISC_CTL_FRAGMENT_DST_RING==0xe0000);
 for(unsigned chip=0;chip<2;chip++)for(unsigned enabled=0;enabled<2;enabled++){
  assert(hw[chip].misc==0x5d8);memset(writes,0,sizeof(writes));
  for(unsigned i=0;i<sizeof(registers)/sizeof(*registers);i++)registers[i]=0xd3fdf7a1;
  struct ath11k_base ab={.nss.enabled=enabled,.hw_params.regs=&hw[chip]};
  u32 general=registers[0],misc=registers[0x5d8/4];
  ath11k_hw_ipq5018_reo_setup(&ab);
  assert(registers[0]==((general&~GENMASK(25,23))|BIT(2)|BIT(3)));
  assert(registers[0x5d8/4]==((misc&~0xe0000)|(enabled?7U<<17:0)));
  assert(writes[0x5d8/4]==1&&writes[0]==1);
  /* Bit20 is outside this chip's three-bit destination field. */
  assert((registers[0x5d8/4]&BIT(20))==(misc&BIT(20)));
  for(unsigned offset=0x564;offset<=0x570;offset+=4)
   assert(registers[offset/4]==HAL_DEFAULT_REO_TIMEOUT_USEC&&writes[offset/4]==1);
  for(unsigned offset=4;offset<=16;offset+=4){
   assert(writes[offset/4]==!enabled);
   if(!enabled)assert(registers[offset/4]==0x43214321);
  }
 }
 puts("PASS actual IPQ5018/QCN6122 REO setup: official register/three-bit field, NSS/HOST routing, unrelated bits, aging and host hash maps");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", type=Path, required=True)
    args = parser.parse_args()
    ath = args.backports / "drivers/net/wireless/ath/ath11k"
    source, header = (ath / "hw.c").read_text(), (ath / "hal.h").read_text()
    mask = re.search(r"^#define HAL_IPQ5018_REO1_MISC_CTL_FRAGMENT_DST_RING[^\n]*",
                     header, re.M)
    # Keeps the old producer compilable for behavioral ablation.
    mask = mask.group() if mask else "#define HAL_IPQ5018_REO1_MISC_CTL_FRAGMENT_DST_RING 0xe0000"
    values = {}
    for chip in ("ipq5018", "qcn6122"):
        table = re.search(r"const struct ath11k_hw_regs "+chip+r"_regs = \{(.*?)\n\};",
                          source, re.S).group(1)
        member = re.search(r"\.hal_reo1_misc_ctl\s*=\s*(0x[0-9a-fA-F]+)", table)
        values[chip] = member.group(1) if member else "0"
    program = SHIM + mask + "\n" + extractor.function(source, "ath11k_hw_ipq5018_reo_setup")
    program += TEST.replace("IPQ_MISC", values["ipq5018"]).replace("QCN_MISC", values["qcn6122"])
    with tempfile.TemporaryDirectory(prefix="nss-fragment-route-") as directory:
        root = Path(directory)
        cfile, binary = root / "reo.c", root / "reo"
        cfile.write_text(program)
        subprocess.run(["cc", "-std=gnu11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-fno-pie", "-no-pie", str(cfile), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15)


if __name__ == "__main__":
    main()
