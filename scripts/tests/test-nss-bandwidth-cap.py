#!/usr/bin/env python3
"""Execute real HE MCS maps and peer NSS overrides for firmware bandwidth ratios."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "nss_cap_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((0xffffffffU >> (31-(h))) & (0xffffffffU << (l)))
#define FIELD_PREP(m,v) (((v) << __builtin_ctz(m)) & (m))
#define FIELD_GET(m,v) (((v) & (m)) >> __builtin_ctz(m))
#define min(a,b) ((a)<(b)?(a):(b))
#define cpu_to_le16(v) (v)
#define IEEE80211_HE_MCS_SUPPORT_0_11 2
#define IEEE80211_HE_MCS_NOT_SUPPORTED 3
#define IEEE80211_HE_PHY_CAP0_CHANNEL_WIDTH_SET_160MHZ_IN_5G 8
#define IEEE80211_HE_PHY_CAP0_CHANNEL_WIDTH_SET_80PLUS80_MHZ_IN_5G 16
#define IEEE80211_VHT_CAP_EXT_NSS_BW_MASK GENMASK(31,30)
enum { MODE_11AC_VHT80,MODE_11AC_VHT160,MODE_11AC_VHT80_80,
 MODE_11AX_HE80,MODE_11AX_HE160,MODE_11AX_HE80_80 };
struct ath11k_pdev_cap { bool nss_ratio_enabled;u8 nss_ratio_info;
 u32 tx_chain_mask_shift,rx_chain_mask_shift; };
struct ath11k_pdev { struct ath11k_pdev_cap cap; };
struct ath11k { struct ath11k_pdev *pdev;void *ab;
 u32 num_tx_chains,num_rx_chains,cfg_tx_chainmask,cfg_rx_chainmask; };
struct ieee80211_sta_he_cap { struct { u8 phy_cap_info[11]; } he_cap_elem;
 struct { u16 rx_mcs_80,tx_mcs_80,rx_mcs_160,tx_mcs_160,
 rx_mcs_80p80,tx_mcs_80p80; } he_mcs_nss_supp; };
struct peer_assoc_params { u8 peer_nss;unsigned peer_phymode,peer_bw_rxnss_override; };
#define ath11k_warn(...) ((void)0)
'''

TEST = r'''
static unsigned count(u16 map) {
 unsigned n=0;for(unsigned i=0;i<8;i++)if(((map>>(i*2))&3)!=3)n++;return n;
}
int main(void) {
 struct ath11k_pdev pdev={0};struct ath11k ar={.pdev=&pdev};
 struct ath11k_pdev_cap *cap=&pdev.cap;
 const unsigned widths=8|16;
 for(unsigned ratio=0;ratio<16;ratio++)for(unsigned enabled=0;enabled<2;enabled++){
  cap->nss_ratio_enabled=enabled;cap->nss_ratio_info=ratio;
  cap->tx_chain_mask_shift=4;cap->rx_chain_mask_shift=12;
  ar.num_tx_chains=4;ar.num_rx_chains=2;
  ar.cfg_tx_chainmask=15<<4;ar.cfg_rx_chainmask=3<<12;
  struct ieee80211_sta_he_cap he={0};he.he_cap_elem.phy_cap_info[0]=widths|1;
  ath11k_mac_set_hemcsmap(&ar,cap,&he,1);
  assert(count(he.he_mcs_nss_supp.tx_mcs_80)==4);
  assert(count(he.he_mcs_nss_supp.rx_mcs_80)==2);
  unsigned tx=!enabled||ratio==WMI_NSS_RATIO_1_NSS?4:
   ratio==WMI_NSS_RATIO_1BY2_NSS?2:0;
  unsigned rx=!enabled||ratio==WMI_NSS_RATIO_1_NSS?2:
   ratio==WMI_NSS_RATIO_1BY2_NSS?1:0;
  assert(count(he.he_mcs_nss_supp.tx_mcs_160)==tx);
  assert(count(he.he_mcs_nss_supp.rx_mcs_160)==rx);
  assert(he.he_mcs_nss_supp.tx_mcs_160==he.he_mcs_nss_supp.tx_mcs_80p80);
  assert(he.he_mcs_nss_supp.rx_mcs_160==he.he_mcs_nss_supp.rx_mcs_80p80);
  assert(he.he_cap_elem.phy_cap_info[0]==((tx&&rx?widths:0)|1));
  unsigned vht=correct_vht(&ar,0xc0000100);
  assert(vht==((enabled&&ratio==WMI_NSS_RATIO_1_NSS)?0x100:0xc0000100));
 }
 /* Asymmetric masks and separate per-radio shifts must not leak TX into RX. */
 cap->nss_ratio_enabled=true;cap->nss_ratio_info=WMI_NSS_RATIO_1_NSS;
 ar.cfg_tx_chainmask=5<<4;ar.cfg_rx_chainmask=2<<12;
 struct ieee80211_sta_he_cap he={0};
 ath11k_mac_set_hemcsmap(&ar,cap,&he,1);
 assert(he.he_mcs_nss_supp.tx_mcs_160==0xffee);
 assert(he.he_mcs_nss_supp.rx_mcs_160==0xfffb);
 cap->nss_ratio_info=WMI_NSS_RATIO_1BY2_NSS;ar.num_tx_chains=4;
 for(unsigned mode=0;mode<6;mode++)for(unsigned peer=1;peer<=4;peer++){
  struct peer_assoc_params arg={.peer_nss=peer,.peer_phymode=mode};
  if(mode<=MODE_11AC_VHT80_80)assoc_vht(&ar,&arg,peer);
  else assoc_he(&ar,&arg,peer);
  if(mode==MODE_11AC_VHT80||mode==MODE_11AX_HE80)assert(!arg.peer_bw_rxnss_override);
  else {
   unsigned mask=(mode==MODE_11AC_VHT160||mode==MODE_11AX_HE160)?
    ATH11K_PEER_RX_NSS_160MHZ:ATH11K_PEER_RX_NSS_80_80MHZ;
   assert(arg.peer_bw_rxnss_override&ATH11K_BW_NSS_MAP_ENABLE);
   assert(FIELD_GET(mask,arg.peer_bw_rxnss_override)==min(peer,2)-1);
  }
 }
 cap->nss_ratio_info=15;
 struct peer_assoc_params arg={.peer_nss=1,.peer_phymode=MODE_11AX_HE160};
 assoc_he(&ar,&arg,1);assert(!arg.peer_bw_rxnss_override);
 puts("PASS actual HE/VHT bandwidth capability: 1:1, 1:2, disabled/invalid ratio, asymmetric RX/TX shifts, peer 1SS and local radio limits");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backports", type=Path, required=True)
    args = parser.parse_args()
    ath = args.backports / "drivers/net/wireless/ath/ath11k"
    mac = (ath / "mac.c").read_text()
    wmi = (ath / "wmi.h").read_text()
    header = (ath / "mac.h").read_text()
    ratio = re.search(r"enum wmi_nss_ratio\s*\{.*?\};", wmi, re.S).group()
    definitions = "\n".join(line for line in header.splitlines() if re.match(
        r"#define (ATH11K_BW_NSS_MAP_ENABLE|ATH11K_PEER_RX_NSS_160MHZ|ATH11K_PEER_RX_NSS_80_80MHZ)\b", line))
    program = SHIM + ratio + "\n" + definitions + "\n"
    program += extract.function(mac, "ath11k_get_nss_160mhz")
    program += extract.function(mac, "ath11k_mac_set_hemcsmap")
    for kind, mode in [("vht", "11AC_VHT160"), ("he", "11AX_HE160")]:
        source = extract.function(mac, "ath11k_peer_assoc_h_" + kind)
        start = source.index("\tif (arg->peer_phymode == MODE_" + mode)
        stop = source.index("\n\tath11k_dbg(", start)
        program += ("static void assoc_" + kind +
                    "(struct ath11k *ar,struct peer_assoc_params *arg,unsigned max_nss) {\n"
                    "u8 tx_nss,rx_nss;u32 nss_160=0;\n" + source[start:stop] + "\n}\n")
    vht = extract.functions.function(mac, "ath11k_create_vht_cap")
    start = vht.find("\tif (ar->pdev->cap.nss_ratio_enabled &&")
    correction = "" if start < 0 else vht[start:vht.index("\n\treturn vht_cap;", start)]
    program += ("static u32 correct_vht(struct ath11k *ar,u32 cap) {\n"
                "struct { u32 cap; } vht_cap={cap};\n" + correction + "\nreturn vht_cap.cap;\n}\n")
    with tempfile.TemporaryDirectory(prefix="nss-bandwidth-cap-") as directory:
        source = Path(directory) / "cap.c"
        binary = source.with_suffix("")
        source.write_text(program + TEST)
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Werror=implicit-function-declaration",
                        "-Wno-unused-parameter", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                        str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15,
                       env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})


if __name__ == "__main__":
    main()
