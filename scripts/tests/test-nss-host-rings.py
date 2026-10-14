#!/usr/bin/env python3
"""Execute host TX completion parsing and RX DMA/monitor buffer helpers."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "nss_mcast", Path(__file__).with_name("test-nss-multicast.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define FIELD_GET(mask, value) (((value) & (mask)) >> __builtin_ctz(mask))
#define HAL_WBM_RELEASE_INFO0_REL_SRC_MODULE 7U
#define HAL_WBM_REL_SRC_MODULE_FW 3
#define HTT_TX_WBM_COMP_STATUS_OFFSET 8
#define HTT_TX_WBM_COMP_INFO0_STATUS (15U << 9)
#define HAL_WBM_REL_HTT_TX_COMP_STATUS_MEC_NOTIFY 5
#define DP_RX_BUFFER_SIZE 2048
#define DP_RX_BUFFER_ALIGN_SIZE 128
#define PTR_ALIGN(p, n) ((typeof(p))(((uintptr_t)(p) + (n) - 1) & ~((uintptr_t)(n) - 1)))
struct htt_tx_wbm_completion { u32 info0, info1, info2, info3; } __attribute__((packed));
struct hal_wbm_release_ring {
 u32 address[2], info0, info1, info2, rate[2], info3;
} __attribute__((packed));
struct sk_buff { u8 *data, *tail, *end; unsigned len; };
static __attribute__((unused)) void skb_reserve(struct sk_buff *skb, unsigned n)
{ assert(!skb->len && skb->tail + n <= skb->end); skb->data += n; skb->tail += n; }
static __attribute__((unused)) void *skb_pull(struct sk_buff *skb, unsigned n)
{ if (n > skb->len) return NULL; skb->len -= n; skb->data += n; return skb->data; }
'''

TX_CASES = r'''
static void check_tx(void)
{
 _Static_assert(sizeof(struct hal_wbm_release_ring) == 32, "WBM entry");
 _Static_assert(sizeof(struct htt_tx_wbm_completion) == 16, "HTT overlay");
 /* Allocate only one real entry: desc+128 is outside it, including at the
  * end of a ring. Status values in the same entry must decide its budget. */
 struct hal_wbm_release_ring *desc = calloc(1, sizeof(*desc));
 assert(desc);
 for (unsigned source = 0; source < 5; source++) {
  for (unsigned status = 0; status < 6; status++) {
   desc->info0 = source | (status << 9);
   bool valid = ath11k_dp_tx_completion_valid(desc);
   assert(valid == !(source == HAL_WBM_REL_SRC_MODULE_FW &&
                     status == HAL_WBM_REL_HTT_TX_COMP_STATUS_MEC_NOTIFY));
  }
 }
 int outstanding = 2;
 desc->info0 = HAL_WBM_REL_SRC_MODULE_FW | (HAL_WBM_REL_HTT_TX_COMP_STATUS_MEC_NOTIFY << 9);
 outstanding -= ath11k_dp_tx_completion_valid(desc);
 assert(outstanding == 2);
 desc->info0 = 0; outstanding -= ath11k_dp_tx_completion_valid(desc);
 desc->info0 = HAL_WBM_REL_SRC_MODULE_FW; outstanding -= ath11k_dp_tx_completion_valid(desc);
 assert(outstanding == 0);
 free(desc);
}
'''

RX_CASES = r'''
static void check_rx(void)
{
 void *memory = NULL;
 assert(!posix_memalign(&memory, DP_RX_BUFFER_ALIGN_SIZE, DP_RX_BUFFER_SIZE + 2 * DP_RX_BUFFER_ALIGN_SIZE));
 for (unsigned offset = 0; offset < DP_RX_BUFFER_ALIGN_SIZE; offset++) {
  struct sk_buff skb = { .data = (u8 *)memory + offset,
   .tail = (u8 *)memory + offset,
   .end = (u8 *)memory + offset + DP_RX_BUFFER_SIZE + DP_RX_BUFFER_ALIGN_SIZE };
  ath11k_dp_rx_align_skb(&skb);
  assert(!((uintptr_t)skb.data & (DP_RX_BUFFER_ALIGN_SIZE - 1)));
  assert(skb.data == skb.tail && !skb.len);
  assert(skb.end - skb.tail >= DP_RX_BUFFER_SIZE);
 }
 free(memory);
 for (unsigned size = 384; size <= 392; size += 8) {
  for (unsigned pad = 0; pad < 4; pad++) {
  unsigned capacity = DP_RX_BUFFER_SIZE - size - pad;
  u32 inputs[] = {0, 1, capacity-1, capacity, capacity+1, capacity*3+17};
  for (unsigned i = 0; i < sizeof(inputs)/sizeof(inputs[0]); i++) {
   u32 remaining = inputs[i], frag = 0, sum = 0, steps = 0;
   do {
    u32 before = remaining;
    ath11k_dp_mon_set_frag_len(size + pad, &remaining, &frag);
    assert(frag <= capacity && frag == (before > capacity ? capacity : before));
    assert(size + pad + frag <= DP_RX_BUFFER_SIZE);
    assert(before == remaining + frag);
    sum += frag; steps++;
   } while (remaining);
   assert(sum == inputs[i] && steps <= 4);
  }
  }
 }
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", type=Path, required=True)
    parser.add_argument("--tx-only", action="store_true")
    args = parser.parse_args()
    source = args.backports / "drivers/net/wireless/ath/ath11k"
    tx = (source / "dp_tx.c").read_text()
    program = SHIM + module.function(tx, "ath11k_dp_tx_completion_valid") + TX_CASES
    if not args.tx_only:
        rx = (source / "dp_rx.c").read_text()
        program += module.function(rx, "ath11k_dp_rx_align_skb")
        program += module.function(rx, "ath11k_dp_mon_set_frag_len") + RX_CASES
    program += "\nint main(void) { check_tx(); "
    if not args.tx_only:
        program += "check_rx(); "
    program += 'puts("Host rings: bounded HTT byte offset/MEC filtering, empty skb DMA alignment and hardware descriptor fragment sizes passed"); return 0; }\n'
    with tempfile.TemporaryDirectory(prefix="nss-host-rings-") as temp:
        path = Path(temp) / "host-rings.c"
        path.write_text(program)
        binary = path.with_suffix("")
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-g", "-O1",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie",
            "-Wall", "-Wextra", "-Werror", str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

if __name__ == "__main__":
    main()
