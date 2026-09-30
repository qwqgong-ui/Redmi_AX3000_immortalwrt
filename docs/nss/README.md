# Redmi AX3000 / IPQ5018 NSS 开发交接

本目录用于在没有原厂路由器的工作地点继续开发。资料来自原厂 AP-MP02.1 的只读采集；路由器配置、服务和固件没有被修改。

## 随仓库带走的资料

| 内容 | 路径 |
|---|---|
| 原厂设备树，含寄存器、IRQ、时钟、内存和功能属性 | [DTS](stock-ap-mp02.1/device-tree/device-tree.dts)、[设备树归档](stock-ap-mp02.1/device-tree/device-tree.tar) |
| 原厂内核、内存、模块、实际时钟、中断 | [system](stock-ap-mp02.1/system/) |
| NSS 统计、字段定义、固件内存布局、参数和启动模块配置 | [nss](stock-ap-mp02.1/nss/) |
| 原厂 ECM 加速连接计数 | [ecm](stock-ap-mp02.1/ecm/) |
| 逐文件 SHA256、来源命令和未取得的项目 | [manifest.json](stock-ap-mp02.1/manifest.json) |
| 原厂 NSS 核心固件 BIN | [firmware/stock-nss/ipq5018](../../firmware/stock-nss/ipq5018/) |
| 全部 44 个 NSS_DRV 配置项 | [配置表](feature-options.md)、[机器可读清单](features.json) |
| 当前实现与未补齐功能 | 下方功能状态表 |

本次快照采集时间为 **2026-09-30 09:28:28～09:28:37 UTC**，包含 85 个文件。设备树的 2 个 MAC/序列号属性已置零，具体属性见 [redactions.json](stock-ap-mp02.1/device-tree/redactions.json)。没有采集账户、Wi-Fi 密码、VPN 密钥或网络配置文件；Telnet 密码仅用于登录，不写入文件。

当前内核日志缓冲区中没有匹配 NSS 的启动消息，采集结果在 manifest 的 `unavailable` 中记录；不能从这份快照还原完整启动时序。部分时钟 sysctl 读取不向标准输出返回数值，实际频率使用 `system/clocks.txt` 核对。

## 原厂硬件和固件基准

| 项目 | 原厂证据 |
|---|---|
| 型号 | `Qualcomm Technologies, Inc. IPQ5018/AP-MP02.1`，board `ap-mp02.1` |
| 主机环境 | Linux `4.4.60`、`armv7l`，CPU `0-1` |
| 物理内存 | 设备树：起始 `0x40000000`、大小 `0x10000000`，即 256 MiB |
| NSS 保留区 | 原厂设备树 `reserved-memory/nss@40000000`：8 MiB；固件 meminfo 的 `heap_ddr_size` 同为 8 MiB |
| NSS 核心寄存器 | `0x07a00000`，长度 `0x100` |
| QGIC 寄存器 | `0x0b111000`，长度 `0x1000` |
| 公共复位寄存器 | `0x01868010`；原厂 DT 长度为 1，当前移植按 32 位访问使用长度 4 |
| NSS IRQ | SPI `402,401,400,399,398,397,396,395`，上升沿；原厂 GIC 硬件编号为 `SPI+32` |
| 队列、IRQ、优先级数 | `4 / 8 / 4` |
| 固件加载地址 | `0x40000000` |
| 原厂频率表 | LOW=850 MHz、MID=850 MHz、HIGH=1 GHz |
| 采集时实际 NSS 核心频率 | `gcc_ubi0_core_clk=1000000000`；`auto_scale=1` |
| 总线和辅助时钟 | AXI/SNOC=400 MHz，UTCM/NC AXI≈266.67 MHz，CFG=100 MHz，DBG=600 MHz |
| 固件内嵌版本字符串 | `NSS.MP.11.4-7-R` |
| 原厂转发证据 | `qca_nss_drv`、`qca_nss_dp`、ECM 和专有 Wi-Fi 驱动加载；快照 ECM IPv4/IPv6 加速计数为 `43 / 11` |

原厂只定义 NSS core0。原厂 DT 的功能属性还包括 IPv4/IPv6、重组、PPPoE、GRE/redirect、PPTP、L2TP、6RD、IPIP6、MAP-T、VXLAN/PVXLAN、crypto/IPsec、shaping、mirror、match、CLMAP、portid、UDP speedtest、RMNET 和 Wi-Fi。这些是原厂声明的入口；不代表每项都已创建会话或实际工作。

NSS 的 `wifili` 统计一次读取会输出多个实例，重复出现 `wifili[0]`。比较数据时必须保留实例/块顺序，不能仅以字段名称合并。`nss/stats-second/` 是随后读取的第二组 drv/n2h/wifili 计数；采样过程中只有自然流量，没有主动吞吐测试，各文件采样间隔也不完全相同。

## 当前 OpenWrt 实现和验证状态

当前分支使用 **Linux 6.12 / AArch64 / ath11k**；mac80211 backports 为 `6.18.39`，NSS 驱动固定源码提交为 `d7ef98b1d3d31346981d3a1abff5152a206374af`。配置片段为 [redmi-ax3000-nss-wifi.config](../../configs/redmi-ax3000-nss-wifi.config)，选择 NSS **12.2** 固件和 256 MiB/LOW 内存方案。

原厂是 32 位主机和 NSS 11.4 固件；它的设备树、时钟、资源和统计是移植参照，原厂模块不能直接装入新内核。当前 profile 使用 12.2 的 wifili peer-stats 布局；若切换到原厂 BIN，必须同时审查驱动、ath11k 和全部消息结构的固件 ABI。原厂的 8 MiB 保留区也不能直接代替当前 12.2 配置的 16 MiB 保留区。

| 功能 | 仓库实现/配置状态 | 验证和剩余工作 |
|---|---|---|
| NSS 核心加载、ready 等待 | `nss-wifi` 在 ath11k 之前装载 NSS；最多等待 30 次，未 ready 时选择主机 Wi-Fi 路径 | 启动正常/关闭/超时/已有 core/模块失败等 8 个主机测试通过；新固件启动待真机验证 |
| 禁用 Wi-Fi offload | 仍加载 NSS 驱动，提供 NSS-enabled ath11k 二进制需要的导出符号；`nss_offload=0` | 修复跳过依赖导致的无线加载失败；主机测试通过 |
| IPQ5018 + QCN6122 Wi-Fi RX/TX | ath11k 的 NSS radio/VDEV 接口和设备适配补丁存在，profile 选择 `WIFIOFFLOAD` | ath11k AArch64 编译和严格 modpost 通过；新固件的双频收发、吞吐待验证 |
| IPv4 / ETH_RX / generic redirect 基础接口 | DTS 开启 `ipv4-enabled`，为 Wi-Fi 默认 `NSS_ETH_RX_INTERFACE` 和 generic redirect 注册入口 | 这是 Wi-Fi 基础接口，不等于 Ethernet/NAT 加速 |
| VDEV 配置响应 | `999-966` 保留 ACK/NACK，拒绝的配置不再按成功处理 | 固定源码编译通过；真实 NACK/超时待验证 |
| VDEV 注册失败回滚 | `0202` 先注册两个 handler 再发布 datapath；失败仅撤销本次成功注册部分 | msg/core 失败、保留已有 handler/datapath、接口重试测试通过；并发真机故障注入待验证 |
| EAPOL/WPA 握手控制帧 | `999-959/964/965` 包含交付到 PAE 组地址、异常帧接收及 stop 时清除路由 | 编译通过；WPA2/WPA3、重连和重启恢复待真机验证 |
| STA WDS/MEC、AP 4-address | 现有 WDS 学习、4addr 通知和 AP_VLAN ext-vdev 处理 | STA/AP/WDS 桥接及隔离策略待真机验证 |
| Wi-Fi AP_VLAN / 动态 VLAN | profile 选择 `WIFI_EXT_VDEV`；现有 group-key、peer 绑定和恢复配置通路 | 与 Ethernet `NSS_DRV_VLAN_ENABLE` 无关；hostapd/RADIUS 实际接入待验证 |
| 高 VLAN ID | `999-967` 按 4096 个 `u16` 分配映射，拒绝 VID≥4095 和缺失映射 | VID 2048/4094 的 ASan/UBSan 测试通过 |
| VLAN group-key 槽 | `999-967` 使用完整 bitmap，锁内分配，保留索引 0 | 64 位 127 槽、耗尽、复用测试通过 |
| STA 多播/广播异常帧 | 现有 MCBC RX 分支交 mac80211 做接收/PN 处理 | 编译通过；PN、重放及成员间隔离待真机验证 |
| IGMP 控制帧异常接收 | `999-968` 将 NSS IGMP exception 交给现有解封装/host delivery | 编译通过；IGMPv2/v3、Linux bridge MDB 更新待真机验证 |
| 完整 NSS 组播成员同步/增强 | 尚无 NSS snooplist/control-plane 同步实现 | 不能将 IGMP 接收分支当作已完成 snooping；MLD/IPv6、复制成员、离组与 ageing 均待补齐 |
| AP client isolation | 已有 NSS isolation 命令联动 | 行为待真机验证 |
| NSS 802.11s Mesh | Mesh 补丁存在，`ATH11K_NSS_MESH_SUPPORT` 和 `WIFI_MESH` 当前未选 | 没有 mesh manager 包和端到端验证，当前不能标为可用 |
| NSS 850 MHz/1 GHz 档位 | 对照原厂修正 MID/HIGH；IPQ50xx HAL 不使用 LOW 档 | Linux 6.12 时钟表有这两个频率；实际调频/功耗待真机验证 |
| Ethernet NSS dataplane | 当前 `wifi_only=1` 跳过接管；qca-nss-dp 本身是实际驱动而非符号 shim | 尚未在新 OpenWrt 接通/验证 Ethernet 加速 |
| IPv4/IPv6 路由/NAT | 没有 ECM 包、conntrack/netfilter 规则建立、销毁和统计回灌接入 | 尚未实现端到端 NSS 路由/NAT 加速 |
| Ethernet bridge/VLAN | core driver 的 API 配置入口不等于 Linux 设备管理；缺 bridge/VLAN manager | BRIDGE 在当前 IPQ50xx Kconfig 还受平台依赖限制；功能待移植 |
| PPPoE | driver 可能随 `kmod-pppoe` 保留协议对象，但没有 PPPoE manager/ECM，DTS 也未启用入口 | 不能认定已有 PPPoE 加速 |
| QoS/IGS、隧道、安全和管理扩展 | 44 项入口完整列表见 [feature-options.md](feature-options.md) | 需要各自 manager、内核 hook、控制面及固件 ABI 验证；尚未接通 |

`IGS` 是 ingress shaping，与 IGMP snooping 不同。`VIRT_IF` 虽在 profile 显式选中，固定上游驱动对 generic dataplane 无条件构建 `nss_virt_if.o`，该开关并非一个已经实现独立裁剪的模块开关。PPPoE/GRE/IPsec 等部分对象还受对应内核软件包选择影响；不能仅依据 profile 中没有显式 `=y` 就认定编译产物必然不含该对象。

本轮测试从已打补丁源码中提取实际 C 函数做错误注入。SDK 是此仓库发布的 Linux `6.12.108` / GCC `14.3.0` / AArch64 SDK。ath11k 严格 modpost 通过，修改后的 `nss_wifi_vdev.o` 也交叉编译通过；NSS 全模块探索性构建没有提供 qca-nss-dp 的外部 symbol CRC，曾允许其依赖符号 unresolved。它不是完整 profile 固件构建或可加载固件的证明。设备树仅做 NSS 片段 dtc 验证，没有重新构建并刷入整机固件。

## 在另一个工作地点使用

复制或克隆整个当前分支，BIN 和快照已经位于仓库中，不需要连接原厂机器才能查阅。先验证文件完整性：

```sh
python3 scripts/nss/verify-reference.py
```

检查所有功能的配置定义，或在修改配置后重新生成清单：

```sh
python3 scripts/nss/update-feature-inventory.py
```

不连接路由器也可运行启动错误路径测试：

```sh
python3 scripts/tests/test-nss-wifi.py
```

要运行源码级注册和 VLAN 测试，先按仓库 Makefile 下载、校验、准备并应用补丁，然后传入两个源码目录：

```sh
python3 scripts/tests/test-nss-wifi.py /path/to/patched-qca-nss-drv /path/to/patched-backports
```

重新采集原厂机器时使用新的输出目录，脚本会提示输入密码，不接受含密码的命令行参数。所有 router 命令都是只读；生成归档、脱敏和 DTS 转换在本地完成。`dtc` 可选，有它时额外生成 DTS：

```sh
python3 scripts/nss/export-stock-reference.py \
  --host 192.168.10.1 --user root \
  --output /path/to/new-stock-snapshot \
  --firmware-output /path/to/new-stock-firmware
```

当前优先级仍是 Wi-Fi、动态 VLAN 和组播：先验证握手与 ext-vdev 生命周期，再补 NSS 组播成员同步及 IGMP/MLD 成员变化。Ethernet/ECM/PPPoE 属于后续独立接入任务。
