# NSS 驱动完整配置项清单

由 `scripts/nss/update-feature-inventory.py` 从仓库 `Config.in` 和配置片段生成，共 44 项。

“未指定”表示配置片段没有显式选择。它不等于最终 `.config` 为 `n`；Kconfig 的依赖、select、其他软件包及 Makefile 会影响实际构建。端到端功能状态见 [开发交接说明](README.md)。

| 配置项（省略 `NSS_DRV_`） | 配置片段 | Kconfig 默认 | 依赖 |
|---|---|---|---|
| `BRIDGE_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq60xx` |
| `CAPWAP_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq60xx` |
| `C2C_ENABLE` | 未指定 | `n` | `TARGET_ipq806x || TARGET_qualcommax_ipq807x` |
| `CLMAP_ENABLE` | 未指定 | `n` | `无平台限制` |
| `CRYPTO_ENABLE` | 未指定 | `n` | `无平台限制` |
| `DTLS_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq60xx` |
| `GRE_ENABLE` | 未指定 | `n` | `无平台限制` |
| `GRE_REDIR_ENABLE` | 未指定 | `n` | `NSS_DRV_GRE_ENABLE` |
| `GRE_TUNNEL_ENABLE` | 未指定 | `n` | `NSS_DRV_GRE_ENABLE` |
| `IGS_ENABLE` | 未指定 | `n` | `无平台限制` |
| `IPSEC_ENABLE` | 未指定 | `n` | `无平台限制` |
| `IPV4_REASM_ENABLE` | 未指定 | `n` | `无平台限制` |
| `IPV6_ENABLE` | 未指定 | `n` | `无平台限制` |
| `IPV6_REASM_ENABLE` | 未指定 | `n` | `NSS_DRV_IPV6_ENABLE` |
| `L2TP_ENABLE` | 未指定 | `n` | `无平台限制` |
| `LAG_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq60xx` |
| `MAPT_ENABLE` | 未指定 | `n` | `无平台限制` |
| `MATCH_ENABLE` | 未指定 | `n` | `无平台限制` |
| `MIRROR_ENABLE` | 未指定 | `n` | `无平台限制` |
| `OAM_ENABLE` | 未指定 | `n` | `TARGET_ipq806x` |
| `PORTID_ENABLE` | 未指定 | `n` | `TARGET_ipq806x` |
| `LSO_RX_ENABLE` | 未指定 | `n` | `无平台限制` |
| `PPPOE_ENABLE` | 未指定 | `n` | `无平台限制` |
| `PPTP_ENABLE` | 未指定 | `n` | `无平台限制` |
| `PVXLAN_ENABLE` | 未指定 | `n` | `无平台限制` |
| `QRFS_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x` |
| `QVPN_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq60xx` |
| `RMNET_ENABLE` | 显式关闭 | `y` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq50xx` |
| `SHAPER_ENABLE` | 未指定 | `n` | `无平台限制` |
| `SJACK_ENABLE` | 未指定 | `n` | `无平台限制` |
| `TLS_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq60xx` |
| `TRUSTSEC_ENABLE` | 未指定 | `n` | `无平台限制` |
| `UDP_ST_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq50xx` |
| `TRUSTSEC_RX_ENABLE` | 未指定 | `n` | `NSS_DRV_TRUSTSEC_ENABLE` |
| `TSTAMP_ENABLE` | 未指定 | `n` | `TARGET_ipq806x` |
| `TUN6RD_ENABLE` | 未指定 | `n` | `无平台限制` |
| `TUNIPIP6_ENABLE` | 未指定 | `n` | `无平台限制` |
| `VIRT_IF_ENABLE` | 显式启用 | `n` | `无平台限制` |
| `VLAN_ENABLE` | 未指定 | `n` | `TARGET_qualcommax_ipq807x || TARGET_qualcommax_ipq60xx || TARGET_qualcommax_ipq50xx` |
| `VXLAN_ENABLE` | 未指定 | `n` | `无平台限制` |
| `WIFIOFFLOAD_ENABLE` | 显式启用 | `n` | `无平台限制` |
| `WIFI_EXT_VDEV_ENABLE` | 显式启用 | `n` | `NSS_DRV_WIFIOFFLOAD_ENABLE` |
| `WIFI_MESH_ENABLE` | 未指定 | `n` | `NSS_DRV_WIFIOFFLOAD_ENABLE` |
| `WIFI_LEGACY_ENABLE` | 未指定 | `n` | `TARGET_ipq806x` |

固定驱动源码还包含 IPv4、ETH_RX、动态接口、N2H 等基础组件，不全部对应独立 NSS_DRV 配置项。
