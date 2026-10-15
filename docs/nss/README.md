# Redmi AX3000 / IPQ5018 NSS 开发交接

## 当前发行状态

当前真机为 **opt59 模块补齐预发行**，源码 `c27415c429`，保留完整 opt58 UBI 回退。
补齐按需加载的 MIRROR manager、驱动/DT 入口与条件编译的 ECM PCC 接口，
版本为 NSS driver release39、clients release10、ECM release12。
真实固件三轮镜像生命周期、指定 IPv4 TCP 流的双向宿主副本与 2 MiB TLS
传输通过；测试实例和规则已清理，默认不加载模块或创建复制规则。
完整 NSS、三路硬件队列、零带宽上限和八项配置已核对，验收及限制见发行附件。
此前报告的间歇性卡顿仍未确认根治，不能按稳定版结论发布。

此前完成队列验收的候选为 **opt56**，基于 Linux 6.12.108、NSS 12.2；ath11k release43、
NSS driver release38、clients release8、ECM release10、nss-wifi release12。
STA/AP/LAN 使用 NSS 硬件 `nssfq_codel`，128 packets / target 5 ms，
上下行 rate=0，没有固定带宽上限。配置工具默认 preview，运行设置及验收
范围见 [无线硬件队列记录](wireless-hardware-fq.md)。

opt56 修复节点 FREE 未确认时提前释放 FQ DMA 内存的问题，并使负值退出
状态及时结束等待；异常映射保留至重启，代价是保留内存与模块引用。
已刷入并完成十一模块、七配置、有线 DNS/HTTPS 与真实队列/VIF 退出验收；
实际构建源码的 DMA/退出 ASan、UBSan 测试及四种镜像校验已通过。
此前 opt55 的独立重启与重连测试成功，但随后仍收到间歇性网页卡顿报告；
该故障与首次握手异常的唯一根因都未确认，不能按稳定版结论发布。

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

opt41 已完成真实有线 DNS/TLS/20次ping、16MiB NSS ACCEL=2和 IPv4
自动硬件组播六阶段验收：允许/禁止源、未知组原生选择、普通 NSS UC
回退、退组和重入均已运行验证。AP 重建后发现无 querier 的 IPv6 MDB
行会撤销 IPv4 策略；当前源码 ath11k release38、NSS clients release3、
ECM release8、NSS driver release32，opt42 对两种协议分别准入，完整
镜像及实际C回归已通过。opt42 冷启动回程四次握手超时，已保留配置回退
**r0-nsslan-opt41-fe7e690dcd**，同一故障仍存在，尚未定位，不能认定仅由
opt42 planner 引起。隔离实验暂以无线NSS关闭的host path启动后，同一
回程WPA/DHCP成功，真实有线DNS/20次ping/16MiBTLS和普通网页恢复，
本机已返回有线主路由，原六配置已恢复。随后再次以无线NSS开启启动，
回程及真实有线验收、16MiB NSS ACCEL=2通过；启动故障呈间歇性，
根因未定，此状态不能认定NSS完成，见[回程记录](wan-cold-start-opt41.md)。
最新opt42b轮次（内部版本仍为opt42）已通过真实有线验收；IPv6成员
无querier时IPv4六阶段及AP重建后同样六阶段通过，有线/AP客户端各
16MiB NSS ACCEL=2通过。IPv6无线数据、更多成员拓扑及启动间歇故障
仍待进一步验证，详见
[opt39–42记录](automatic-multicast-opt39.md)。此前MCBC边界及AP单播实测
见[opt38b记录](multicast-host-boundary-opt38.md)。

opt37在原生CREATE中拒绝包含AP/AP_VLAN
的完整硬件fanout，修复空输出快照清理；完整构建、保留配置刷入、
八模块/六配置、实际有线DNS/TLS及16MiB NSS ACCEL=2连接通过。
自动同步、完整回退与发布仍未闭合，详见[opt37记录](multicast-host-fanout-opt37.md)。

opt36运行版本为r0-nsslan-opt36-fe7e690dcd。
opt36补齐全桥MDB lookup/模式/querier快照及失效通知，新增关闭ME时
双表建表和来源过滤planner。真实IGMPv3快照建表后，INCLUDE/EXCLUDE
允许源128/128、禁止源L2为0；受控源进入宿主TX、空表单播DA交付及
AP MCBC异常开/关的有线交付通过。纯有线DNS/TLS/普通HTTPS、16MiB
ACCEL=2实流量也已验收。自动worker、全范围回退和撤销仍未完成，
详见[opt36记录与剩余工作](multicast-interop-opt36.md)。

刷后验收必须完成实际有线联网检查，使用
[nss-verify-wired.py](../../scripts/nss-verify-wired.py)绑定eno1并绕过既有
本机代理，核对DNS、16MiB证书校验HTTPS、网关丢包及网卡错误增量。
最新完整有线验收通过；诊断阶段曾出现DNS超时，记录及未定根因保留在opt36文档。

opt35的ath11k/NSS driver均为release32。
opt35新增ordinary AP的私有ME ACK事务和默认关闭的显式测试接口，
完整构建并保留配置刷入后，真实mode/reset/group/member/toggle ACK、
模式5/6的单STA复制及ME开启时的单播DA交付通过；空/未知组仍被吞掉，
首轮普通组播125/128，自动MDB消费和完整回退尚未完成。
8个模块、6份配置、原STA/DHCP、有线NSS及16MiB ACCEL=2流量已复核。
详见[opt35 ME交付记录](multicast-interop-opt35.md)。

opt34修复N2H拒绝新FIRST后继续保留已释放head/tail的UAF，以及整包
替换的旧head统计与跨模式tail清理。实际handler的ASan复现/修复回归、
clean prepare和完整四镜像构建通过；保留配置刷入后8个模块hash、
6份配置、原STA/DHCP、有线NSS及16MiB真实ACCEL=2流量通过。
另以临时隔离端点/静态邻居完成双向IPv6单播ACCEL=2与统计增量验收。
异常首段尚未在真机诱发，IPv6自动邻居发现及原回程带宽目标仍未完成。
详见[opt34记录](sta-downlink-opt34.md)。

后续[opt35前置核对](multicast-interop-opt35.md)在原2.4GHz AP上验证
自动IPv6 ND双向5/5并抓到NS/NA；原5GHz上游段仍未闭合。桥组播
基线256帧收到229帧，NSS MC规则计数仍0，Wi-Fi MDB→ME成员同步链
尚未实现；新增ME启用5/6重置所选表及普通TX DA门的静态合同依据。

当前固件保留opt29的PN完成门禁
和opt30b的初始TX/RX独立选择、NSS格式private ACK、response buffer
边界、ACK后发布及运行中格式冻结；新增QCN6122 monitor首buffer只读
元数据取证。opt33修正PPDU高16位和已知截断MAC头前缀校验，完整
镜像、实际parser ASan/UBSan和格式回归通过；实机15886条元数据
无缺号，12292条AP→STA DATA全部完成独立MAC头/PPDU字段交叉验证。
默认已关闭试验且不分配记录环，原配置、5GHz STA/DHCP、NSS、PN/密钥
和联网复核正常。详见[opt33记录](sta-downlink-opt33.md)、
[opt32实机布局及交错对照](sta-downlink-opt32.md)、[opt31记录](sta-downlink-opt31.md)、
[opt30b记录](sta-downlink-opt30.md)、[opt29记录](sta-downlink-opt29.md)。
原回程带宽目标仍未完成，aging40000。

后续单空口取证见[opt29 airpath](sta-downlink-airpath-opt29.md)：原
回程同TCP长连接32MiB平均31.994Mbit/s，RTT约210ms，接收窗口
未耗尽，仍有等待重传修复的缺口；电脑observer没有捕获有效AP
下行，不能据此归因RF。新发现NSS并存monitor的RX decap不同步，
初始格式选择及NSS缓存发布已修复，在线改变格式仍拒绝，原带宽目标继续保持未完成。
opt30b实机监听的匹配DATA仍为Ethernet复制，RAW/NATIVE consumer丢弃。
opt32确认实际MAC偏移及PPDU高16位；opt33允许校验已存储MAC头，
但LEN132的未存储尾部仍标记截断且不获TRUSTED。完整加密帧、聚合
布局、硬件时间及TCP缺口对应关系仍待验证。交错对照中电脑直连上游
也只有9.3–21.7Mbit/s、LAN23.7–29.3Mbit/s，两端无线条件不同；不能
直接归因NSS固定上限，也不能据此宣称中继带宽或完整并发monitor已解决。

原厂是 32 位主机和 NSS 11.4 固件；它的设备树、时钟、资源和统计是移植参照，原厂模块不能直接装入新内核。当前 profile 使用 12.2 的 wifili peer-stats 布局；若切换到原厂 BIN，必须同时审查驱动、ath11k 和全部消息结构的固件 ABI。原厂的 8 MiB 保留区也不能直接代替当前 12.2 配置的 16 MiB 保留区。

| 功能 | 仓库实现/配置状态 | 验证和剩余工作 |
|---|---|---|
| NSS 核心加载、ready 等待 | `nss-wifi` 在 ath11k 之前装载 NSS；最多等待 30 次，ready 后配置双 host RX 队列并加载 Bridge Manager | 13 个启动错误路径测试通过；2026-10-08 新固件真机启动，core ready、双队列、Bridge Manager 和 ECM 加载正常 |
| NSS PROJECT逐线程统计 | `0213`校验消息边界、等待启停ACK，快照锁内取得几何并复制，复用控制cookie与排空 | opt21已刷入，真实启停/首份NOTIFY和关闭后快照稳定通过；ticks单位未闭合，不能当worker利用率，见[opt21记录](sta-downlink-opt21.md) |
| REO UPDATE 执行状态 | `999-992` 在既有 status parser 后记录数值，不新增 peer/queue owner | opt22 真机 QCN6122 73/73、内部 IPQ5018 17/17 success；不能读回硬件当前 SSN 或直接绑定 peer，见 [opt22 记录](sta-downlink-opt22.md) |
| REO 提交与 callback 登记 | `999-993` 发布前分配、锁内提交/登记、NEED_STATUS 编号回压及类型校验；关闭 epoch 阻止旧请求跨恢复提交 | opt23 已刷入，实际 C 故障/并发测试和干净模块/镜像构建通过；重连/负载验证见 [opt23 记录](sta-downlink-opt23.md) |
| REO 队列实例与硬件 GET | `999-994` pin原队列DMA owner，绑定WMI/fragment/cleanup实例，私有GET等待与返回校验 | opt24已刷入，实际C回归、完整构建和原回程TID0/16硬件GET通过；GET不提供硬件BA窗口，负载归因见[opt24记录](sta-downlink-opt24.md) |
| NSS TID REO 绑定通知 | `999-995` pin原实例、有限异步job、WMI-only重新绑定，`0214`先验证实际接收buffer | opt25已刷入，C故障/并发与初始化失败链、完整构建、9条真实通知/2次人工恢复、负载与重连通过；仍有带宽波动，见[opt25记录](sta-downlink-opt25.md) |
| REO aging受控调节及失败断电门 | `999-996` 仅ON/非suspend/开放门可按epoch与原值CAS，AHB/PCI失败及shutdown先关门排空 | opt26已刷入，C并发/拒绝/失败链及严格modpost通过，38份GET的两组对照与恢复通过；100000未显示稳定收益，保留40000，见[opt26记录](sta-downlink-opt26.md) |
| REO PN硬件完成与NSS授权门 | `999-999` pin原队列并等待各TID UPDATE执行、共同截止时间、完成后重验实例/epoch/key门，NSS最后ACK后重验 | opt29已刷入，12组实际C及完整构建通过；启动/重连/传输后内部34/34、QCN51/51 SUCCESS，无遗留/超时，完整M1–M4通过。不是PN值或后续包queue选择读回，见[opt29记录](sta-downlink-opt29.md) |
| 禁用 Wi-Fi offload | 仍加载 NSS 驱动，提供 NSS-enabled ath11k 二进制需要的导出符号；`nss_offload=0` | opt20 修正完成状态 byte offset、空 skb 对齐；host 对照完成 5 GHz WPA/DHCP、20/20 网关 ping，无旧 completion mismatch；长期回退吞吐/稳定性待验证 |
| IPQ5018 + QCN6122 Wi-Fi RX/TX | ath11k 的 NSS radio/VDEV 接口和设备适配补丁存在，profile 选择 `WIFIOFFLOAD` | 完整构建和真机双频收发通过；5 GHz HE160 下行约 913 Mbit/s，CPU 与满载丢包见[实测记录](performance-2026-10-08.md) |
| IPv4/IPv6 / ETH_RX / generic redirect 基础接口 | DTS 开启 IPv4、IPv6 和 bridge 入口；profile 选择对应 driver 功能 | Wi-Fi 与 Ethernet 接管已运行；opt34临时ULA/静态邻居的双向IPv6 TCP均为ACCEL=2，自动ND及公网IPv6仍待验收，见[记录](sta-downlink-opt34.md) |
| VDEV 配置响应 | `999-966` 保留 ACK/NACK，拒绝的配置不再按成功处理 | 固定源码编译通过；真实 NACK/超时待验证 |
| VDEV 注册失败回滚 | `0202` 先注册两个 handler 再发布 datapath；失败仅撤销本次成功注册部分 | msg/core 失败、保留已有 handler/datapath、接口重试测试通过；并发真机故障注入待验证 |
| EAPOL/WPA 握手控制帧 | `999-959/964/965/997` 包含 PAE 交付、异常帧接收、stop 清路由及 failed-start 回滚 | opt27 已刷入；实际错误路径 C 回归通过，opt26 两次 M1–M4 捕获成功，旧间歇超时根因未定，见[opt27记录](sta-downlink-opt27.md) |
| WMI密钥完成及关闭引用 | `999-998`匹配wire tuple、明确恢复失败、base生命周期poison、caller/RCU排空及原key宿主detach | opt28已刷入，实际C并发/失效与最终完整构建通过，真机12/12 tuple和重连成功；同tuple成功重复event及完整PN/VLAN合同未闭合，见[opt28记录](sta-downlink-opt28.md) |
| STA WDS/MEC、AP 4-address | 现有 WDS/4addr/ext-vdev 通路；`999-970` 修正 STA BSS peer 保留、释放及 MEC 锁内查找 | 同 MAC 不同 VDEV、legacy/v2 unmap、stale cleanup、接收/释放竞态的源码测试通过；四地址透明桥仍待实机验证 |
| Wi-Fi AP_VLAN / 动态 VLAN | profile 选择 `WIFI_EXT_VDEV`；现有 group-key、peer 绑定和恢复配置通路 | 与 Ethernet `NSS_DRV_VLAN_ENABLE` 无关；hostapd/RADIUS 实际接入待验证 |
| 高 VLAN ID | `999-967` 按 4096 个 `u16` 分配映射，拒绝 VID≥4095 和缺失映射 | VID 2048/4094 的 ASan/UBSan 测试通过 |
| VLAN group-key 槽 | `999-967` 使用完整 bitmap，锁内分配，保留索引 0 | 64 位 127 槽、耗尽、复用测试通过 |
| STA 多播/广播异常帧 | `999-972` 保留分类/PN 检查；`999-984` 从 descriptor 初始化 NSS exception TID，并修正 host NULL queue 的重建顺序 | 实际 QoS/CCMP 函数 ASan/UBSan 通过，opt19 已刷入；原上游广播 ARP 在 NSS 开/关均失败，仍待真实加密帧 replay 及广播交付验收 |
| IGMP 控制帧异常接收 | `999-968` 将 NSS IGMP exception 交给现有解封装/host delivery | 编译通过；IGMPv2/v3、Linux bridge MDB 更新待真机验证 |
| 完整 NSS 组播成员同步/增强 | 自动worker、原生目标契约、NSS UC回退、flight屏障及受限CT/ECM兼容已接通；opt42按协议判断querier | opt42b真实混合成员、IPv4六阶段及AP重建后回归通过；多个真实成员不同源过滤、IPv6无线数据和ageing仍待验收；固定hook配置限制见[记录](automatic-multicast-opt39.md) |
| AP client isolation | 已有 NSS isolation 命令联动 | 行为待真机验证 |
| NSS 802.11s Mesh | Mesh 补丁存在，`ATH11K_NSS_MESH_SUPPORT` 和 `WIFI_MESH` 当前未选 | 没有 mesh manager 包和端到端验证，当前不能标为可用 |
| NSS 850 MHz/1 GHz 档位 | 对照原厂修正 MID/HIGH；IPQ50xx HAL 不使用 LOW 档 | Linux 6.12 时钟表有这两个频率；实际调频/功耗待真机验证 |
| Ethernet NSS dataplane | `qca-dsa-nss` 管理 tagged physical/VLAN 接管；修正保留 live MAC 时的 CST/FCS 冲突 | 2026-10-10 修复镜像真机收发、三轮 host/NSS 切换及有线→5 GHz STA 的 NSS NAT 连接已验证，见[记录](firmware-reverse-2026-10-10.md) |
| NSS Bridge Manager | 已加入 IPQ5018 非 PPE manager，跟踪已确认的成员与待重试 leave，补齐现有/延迟登记成员同步和退出清理 | 源码 ASan/UBSan 测试通过；未知 DSA 端口不冒充 CPU conduit，混合桥广播/未知单播仍需真机验证 |
| IPv4 NAT / IPv6 路由 | 已加入 QSDK 14 ECM 的 NSS 前端、bridge/FDB/route 内核接口与 conntrack 事件观察接口 | IPv4 NAT自然流量及opt34双向IPv6静态邻居路由已实测ACCEL=2与统计增量；IPv6自动ND、公网/RA/DHCPv6、NACK故障及长期稳定性待验证 |
| Ethernet bridge/VLAN | qca8k 802.1Q tagger、VLAN manager、物理数据面与 Bridge Manager 已接入 | opt9 真机纯桥接 TCP 为 758–931 Mbit/s；600 秒双向 328 / 847 Mbit/s、整体平均 CPU 3.70%、ICMP 丢 1/3005，见[对照](performance-2026-10-10.md#opt9-同条件复测)；IPv6 待验证 |
| PPPoE | opt43 接入 manager、channel/addressing hooks、DTS 和 ECM PPP/PPPoE 后端，补齐引用及通知顺序 | 全模块/镜像构建通过；真实 PPPoE 会话加速尚未验收，见[qdisc 与常用组件记录](qdisc-opt43.md) |
| QoS/IGS | 接入全套 NSS qdisc、IGS/IFB、tc/SQM、DSCP/ingress QoS metadata；opt44 修正 QoS pool 的 MB 单位 | 控制 C 回归及完整构建通过；本地基线 896 Mbit/s，8 Mbit/s 配置下 egress/IGS 实测 6.83/6.75 Mbit/s，原配置恢复，有线 ACCEL=2，见[qdisc 记录](qdisc-opt43.md) |
| MIRROR / PCC 复制 | profile 选择 `kmod-qca-nss-drv-mirror`；接入 core/DT、6.12 manager 及 ECM PCC，无自动 registrant 或规则 | opt59 真机三轮生命周期与指定 IPv4 TCP 流双向复制通过，清理后完整 NSS/三路硬件队列及直接有线 TLS 通过。IPv6 复制未验收；整端口 ingress PMC 缺少跨客户端 next-hop 所有权恢复合同，当前不开放 |
| 隧道、安全和管理扩展 | 44 项入口完整列表见 [feature-options.md](feature-options.md) | 未纳入本次默认 profile；需要独立 manager、hook 和固件 ABI 验证 |

`IGS` 是 ingress shaping，与 IGMP snooping 不同。`VIRT_IF` 虽在 profile 显式选中，固定上游驱动对 generic dataplane 无条件构建 `nss_virt_if.o`，该开关并非一个已经实现独立裁剪的模块开关。PPPoE/GRE/IPsec 等部分对象还受对应内核软件包选择影响；不能仅依据 profile 中没有显式 `=y` 就认定编译产物必然不含该对象。

MIRROR manager 按需用 `modprobe qca-nss-mirror` 加载，控制入口为
`/proc/sys/dev/nss/mirror/config`。写入 `create` 后，以实际生成的
`mirror.N` 名称依次执行 `configure mirrordev=mirror.N mirror_size=128`、
`set_nexthop mirrordev=mirror.N mirror_next_hop=n2h` 和
`enable mirrordev=mirror.N`。这些命令只准备复制目标；选流需要另行注册
ECM PCC classifier。停止时先撤销 classifier 并排空其设备引用，再执行
`disable mirrordev=mirror.N`、`destroy mirrordev=mirror.N`，最后卸载模块。
仍有镜像实例时模块保留引用，固件释放未确认时保留实例供重试，避免悬空回调。

此前测试从已打补丁源码中提取实际 C 函数做错误注入。SDK 是此仓库发布的 Linux `6.12.108` / GCC `14.3.0` / AArch64 SDK。ath11k 严格 modpost 通过，修改后的 `nss_wifi_vdev.o` 也交叉编译通过；当时 NSS 全模块探索性构建没有提供 qca-nss-dp 的外部 symbol CRC，曾允许其依赖符号 unresolved。那一轮不构成完整 profile 固件构建或可加载固件的证明，设备树也仅做了 NSS 片段 dtc 验证。

2026-10-07 在 Redmi AX3000 上刷入提交 `7053455bcb` 对应的 CI squashfs factory UBI（`r0-7053455` / Linux `6.12.108` / 256 MiB profile），保留原配置。`nss_offload=1` 时，2.4 GHz AP 的两个客户端与 5 GHz WPA2 STA 中继均完成认证。将 `nss-wifi.main.enabled=0` 后重启，在 `nss_offload=0, frame_mode=2` 下出现 `invalid msdu len 11788/15426`、`Invalid EAPOL-Key MIC` 和 `4WAY_HANDSHAKE_TIMEOUT`；不更改 Wi-Fi 密钥，恢复 NSS 并重启后双频认证恢复。该对照确认 host 路径存在接收故障，尚未定位到具体 descriptor/offset；应先修复并验证 host RX，再使用关闭 NSS 作为性能对照或故障回退。

本轮针对现有 **AP＋STA 路由/NAT 中继**接入 ECM，没有强制开启 STA 四地址模式。
`999-969` 修正 host/monitor RX ring selection 的字节数：实际分配为 2048 字节，
原代码却在 256 MiB profile 下传入了 512 个 ring entries 的数量。NSS 的 1816
字节参数保持不变。源码回归通过不等于已修复上述真机握手故障，该失败记录继续保留。

ECM 在 NSS、Bridge Manager 和无线卸载就绪后加载，先以停止状态完成配置，再
启用 IPv4/IPv6 路由观察；有线 NSS READY 后装载 nf_conntrack_bridge 并注册
L2 bridge post-routing hook。已有
firewall flow offloading 时保持 ECM 停用。它只清理自身加速规则，不清空全部
conntrack；没有事件缓存的已有连接继续 host，后续新建连接才可进入 NSS。启停
期间保存/恢复 conntrack events 设置，不改写用户的 firewall、packet steering
或 bridge filtering 配置。conntrack observer 与 ctnetlink 主通知共存，主通知的
返回值及重发逻辑不被 ECM 覆盖。

这轮包含 Linux bridge/FDB/route 接口和可选的
`CONFIG_NF_CONNTRACK_EVENTS_OBSERVER`，需要成套重新构建内核和模块。主机侧可运行：

```sh
python3 scripts/tests/test-nss-relay.py \
  --clients /path/to/patched-qca-nss-clients \
  --backports /path/to/patched-backports \
  --kernel /path/to/patched-linux
```

测试包括 10 组 ECM 服务错误路径，以及实际 C 函数的 conntrack 通知、RX buffer、
MEC peer 和 bridge 成员生命周期回归；C 测试启用 ASan/UBSan。完整固件构建与实机
验证结果应另行记录，模块存在、`accelerated_count` 单次非零均不能代替流量前后对照。

2026-10-08，本次在 Debian 12.15 中使用 GCC 14.3.0 工具链完成整个目标固件构建，
包含 Linux 6.12.108、ath11k release 5、NSS driver release 23、Bridge Manager 与
ECM。新内核 ABI 为 `84e3bcac6c4c8f27fcf530e56c9b87d5`，observer 配置为 `y`。
两个新增模块均为 AArch64 ELF，实际编译日志没有缺失 modpost 符号或强制允许
unresolved 的标志。针对实际构建源码的 25 组主机回归通过；编译后的 DTB 含
IPv4/IPv6/bridge 入口，镜像内启动脚本与源码一致，S19/S95 启动链接存在。

该次本地 `immortalwrt-qualcommax-ipq50xx-redmi_ax3000-squashfs-factory.ubi` 的 SHA256
为 `4ed63e6aa7c5d2325730c812d55411861f06d822aa81b12d13b0dcc00729268f`。这只是当前
工作区构建产物的标识，不是未来 CI 镜像的哈希。

同日按用户要求保留配置刷入该镜像，真机版本为
`r0-nssrelay20261008-fe7e690dcd`。刷前配置和设置无线优先后的配置均另行备份到桌面。
真机 ath11k、ECM、Bridge Manager 模块与构建目录的 SHA256 一致，NSS core ready=1、
wifi_only=Y、nss_offload=1，ECM IPv4/IPv6 stop 均为 0。现有防火墙软件流量卸载
由 1 改为 0，以免与 ECM 并用；`wwan.metric=0`、`wan.metric=100`，路由查询确认
本机及 LAN 转发均经 `phy1-sta0`，有线 WAN 当前没有链路，未实测双上联切换。

2.4 GHz AP 的两台原有客户端和 5 GHz WPA2 STA 均完成认证，网关/公网各 3 次
ping 无丢包，DNS 解析成功。约 40 秒自然流量对照中，ECM IPv4 加速连接数由
29 增至 37；NSS IPv4 special RX/TX 转发包均由 562 增至 1982。按原始块顺序，
IPQ5018 PDEV0 的 RX delivered/TX sent 由 833/730 增至 1519/1368，QCN6122
PDEV0 由 4761/895 增至 5900/1555。两块的 RX MSDU error、RX deliver drops、
TX hardware enqueue fail 均为 0；WBM REO code invalid 计数仍有增长，尚未定位。
本次启动未见握手超时、invalid MSDU、固件崩溃或 Oops 日志。

这些是当前 NAT 拓扑下的启动、认证和实际加速流量证据，没有进行受控吞吐/CPU
对照、关闭 NSS 的 host RX 回退、IPv6 上联、反复 WPA 重连或长期稳定性测试。

随后完成的 2.4 GHz、5 GHz HE80、**5 GHz AX / 36 / HE160** 双向吞吐、
每核 CPU 和 600 秒负载结果，以及最新完整固件标识，见
[2026-10-08 性能实测](performance-2026-10-08.md)。最新源码回归为 32 组通过；
满载 ICMP 丢包仍存在，不能以峰值吞吐代替稳定性验收。

2026-10-09 已刷入有线 NSS 开发固件并复用既有 HE160 拓扑对比，见
[新旧固件吞吐与 CPU 对照](performance-2026-10-09.md)。新增有线数据面虽然
可以完成控制事务和 DMA 接管，普通 TX 仍未通过真机验证，已关闭并保留
Ethernet host 通路；本轮吞吐不作为有线 NSS 卸载成绩。恢复原无线布局后
再次出现既有 STA 握手超时，电脑继续经手机 USB 联网。

2026-10-10 当前状态已确认 5 GHz 回程连通，电脑另以直连上游 Wi-Fi 保持
开发期间联网。原厂与当前 NSS 镜像已用官方 UBI32 backend 实际反汇编，
定位到 GMAC 正常 RX 固定减 FCS 4 字节；保留 live MAC 时错误保留 host CST
造成 IP 包截短。仅清 CST 的真机对照恢复正确帧长和 ICMP，修复与边界见
[固件反汇编及 CRC 接管记录](firmware-reverse-2026-10-10.md)。

opt6 刷入后已复用既有信道 36 / HE160 双端点测试，完成有线↔5 GHz
单流、四流和每核 CPU 对照，并确认具体 bridge 连接已加速，见
[2026-10-10 刷入后的性能对照](performance-2026-10-10.md)。原无线配置及联网已恢复。

随后修复 FDB 通知格式、替换时的连接撤销和启动就绪等待，最终 opt9 已刷入，
首次启动及软件重启均自动启用有线 NSS、ECM 路由与桥接，见
[FDB 生命周期与启动验收](fdb-lifetime-2026-10-10.md)。

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

当前已验证 AP↔STA IPv4 路由/NAT、有线 NSS 接管、HE160 纯桥接 TCP/UDP 与
600 秒持续负载。下一阶段接通 IPv6 验收及完整组播成员同步；PPPoE 和四地址
透明 WDS 尚未验收。现有拓扑继续使用普通三地址 STA 路由/NAT 回程。

## 组播路由内核接口进展

`0603-mroute-export-ECM-multicast-cache-lifetime.patch` 为 Linux 6.12 增加 IPv4
和 IPv6 的实际 MFC 查询、增删/替换通知、VIF 失效通知及统计回灌。目的接口
列表先在私有数组中完整校验，再提交给调用者；缺失 VIF 或容量不足不会返回
部分可用列表。删除的 RCU 旧项不再参与查询。

查询返回 route cookie；新建、替换和引用 VIF 的删除/重用都会改变 cookie。
统计回灌要求匹配创建规则时的 cookie，拒绝旧代次；VIF 的 host 转发和 offload
更新都使用原子计数，避免并发增量互相覆盖。callback 注册/注销序列化，注销
在撤销发布后等待 RCU。相关锁的 process/softirq 访问已统一为 BH-safe。

这些接口目前对接的是 ECM 的 init_net 默认表 `(S,G)` 合同；同 key 多 parent
不合并，超出 NSS 规则能力的非 1 出口 TTL 阈值不冒充可卸载。后续 0605/0070
已加入实际输入选表谓词、ECM namespace/选表校验和规则绑定 cookie；统计
不再重新查询当前 cookie。MDB 快照、延后通知及 Linux snooper 消费者也已
接通，Wi-Fi 成员表和双表发布仍待实现。

本阶段验证：`ipmr.o`、`ipmr_base.o`、`ip6mr.o` AArch64 交叉编译通过；两个
地址族的实际 API 函数提取后分别通过 ASan/UBSan，包含 32 目的边界、短缓冲区
无部分写入、缺失接口、多 parent、TTL、cookie、host/offload 并发计数、事件
及正在执行 callback 时的注销等待。CI 已加入相同测试，但尚未派发此轮 CI。

```sh
UBSAN_OPTIONS=halt_on_error=1 python3 scripts/tests/test-nss-multicast.py \
  --kernel /path/to/patched-linux
```

0603/0604 内核接口已包含在 opt10，0605/0070 已随 opt11 刷入设备。单播
桥接实测见 [opt10 对照](performance-2026-10-10.md#opt10-刷入与同条件对照)
和 [opt11 对照](performance-2026-10-10.md#opt11-刷入与同条件对照)。内核
接口存在和单播吞吐不能作为组播硬件数据面验证。

## 桥接组播快照与多主机源过滤进展

`0604-bridge-export-multicast-snapshots-and-host-keys.patch` 提供 bridge dirty
通知、带序列的端口成员/源快照和完整目的端口查询。通知在 netlink 分配之前
发出，消费者只能在回调中失效状态/排工作，不得重新取得 multicast_lock。
成员、router-port、转换模式、snooping、querier 和协议版本改变会撤销硬件
转换标志；只有同 bridge、同序列的确认表才可再次抑制软件转换。

快照保留网络序 group/source、VID、host MAC、INCLUDE/EXCLUDE 和有效的
block 状态；EXCLUDE 中 timer pending 的 X 不当作排除源。容量不足时返回
所需数量，成员/源数组不部分写入。目的端口查询使用 RCU 的 VLAN context，
私有缓冲区和二轮检查；无 querier、本机接收或本机 router 所需副本不会被
冒充为只有外部端口的硬件转发。端口快照的 router bool 当前只描述全局
context，VLAN snooping 拒绝该快照，不能误用为各 VID 共用同一 router 集合。

修正了同 AP 多 STA 的 `(S,G)` hash 键：按条目创建时的 host-specific 类型
保留独立 MAC，派生项继承父项类型，EXCLUDE 复制使用目标 STA MAC。管理
add/replace 优先匿名项；delete 有匿名项时只删该项，否则删除该端口全部
学习主机，不再任意删除一个 STA。匿名管理项保持端口范围的覆盖语义。

软件转换现在先检查 INCLUDE/BLOCKED；router 与同端口多个 host 只交付
一次普通副本。MCUC 类型切换期间，旧 aggregate 与新 per-host 共存时按
端口普通交付，等待旧 aggregate 过期，避免丢主机或重复单播。

验证：`br_mdb.o`、`br_multicast.o`、`br_forward.o`、`br_if.o` AArch64 编译
通过；提取实际 API、键、过滤和 flood C 函数的 IPv4/IPv6 ASan/UBSan 用例
通过，覆盖容量、序列、source timers、blocked/include、混合 aggregate、
匿名管理项和 router 去重。CI 已加入同一测试，尚未派发。

```sh
UBSAN_OPTIONS=halt_on_error=1 python3 scripts/tests/test-nss-mdb.py \
  --kernel /path/to/patched-linux
```

ECM 的延后通知和公开查询已由 0070 接通；ath11k 仍需 ACK-ready peer、
逐项建表/表切换及未知组的软件交付。当前 opt11 已有新 ECM 消费者，但
组播路由仅验证了软件转发，NSS MC 规则尚未进入 ACCEL，完整组播卸载未完成。

## ECM 组播消费者与实际选表

`0070-ecm-use-kernel-multicast-lifetimes.patch` 删除 ECM 对 bridge 私有 MDB
结构的依赖，调用完整端口快照。MDB/MFC 通知递增拓扑代次并排工作，只撤销
旧代次的组播 CI，不在 bridge multicast_lock 内查询或发送 NSS 规则；所有
相关源/端口的旧连接都会处理，成员变化后按新快照销毁重建。退出先禁止新
工作并同步排空，再退出 frontend；注册失败和 init 回滚也覆盖同一清理。

CREATE 的分配、来源/目的 hierarchy 和 FROM_NAT 失败均释放引用并清 pending，
flush-before-ACK、defunct 竞态及迟到拓扑 ACK 也保持计数配平。UPDATE 失败
保留可 DESTROY 状态；DESTROY 正常 ACK 和已核对的 EMSG/error=5 均按规则
已移除处理，其余错误保留未知所有权。组播准入在 pending 计数的同一锁内
检查未知状态，不能把未知规则当作已释放。已有 FLUSH 后的过期 DESTROY
响应不会重复增加未知计数。

SYNC_MANY 使用固件回显的请求 token，对提交前已经 ACK 的规则保存 CREATE
代次和 MFC cookie。回复必须同时匹配请求、CI、规则及拓扑代次，才能更新
统计；新 CI 不能继承旧请求。过期批量回复与真实 NOTIFY 明确区分。单条
NOTIFY 没有规则代次，组播计数不按当前 tuple 回灌；真实 flush/evict 只走
保守的规则清理。这可能舍弃无法归属的最终增量，仍需运行统计对照，不能
声称所有最终计数均已无损同步。固件现场扫描、计数清零、token、CREATE
布局和 destroy-miss 证据见[反汇编记录](firmware-reverse-2026-10-10.md#mp122-批量连接统计与规则生命期)。

`0605-mroute-preserve-the-selected-table-for-offload.patch` 在原生 IPv4/IPv6
输入选表时记录 init_net 默认表谓词，用新增的协议 cb flag 保留它，无逐包
extension 分配。转发/clone 后即使 FORWARD 修改 mark，也不会误用新的 mark
重选默认表。公共 eligibility 仅供原生 INET/INET6 postrouting 使用，要求
实际选择及 FORWARDED 标志；ECM 不在 bridge cb 上解释 IP cb。非默认表、
其他 namespace、缺失记录继续软件转发，不能从默认表 tuple 命中推断资格。

实际重新应用两份补丁后，vmlinux 和包含 IPv4/IPv6 multicast 的 AArch64
ECM 模块构建及严格 modpost 通过，无旧 mc_bridge 依赖。MFC、MDB、ECM
生命周期、选表四组实际 C 函数 ASan/UBSan 回归均通过；CI 已加入新用例，
YAML 解析通过，尚未派发。上述为源码和构建证据，未替代新消费者的实机
MC CREATE、统计回灌、入退组、TTL 和 IPv6 收发验收。

包含 0605/0070 的完整 opt11 也已构建成功：
`r0-nsslan20261010opt11-fe7e690dcd`，factory UBI 17694720 字节，SHA256
`d2166016ba6db31ac71d69035aa29e3c7efd6d0307fa602e867bbc3adf8e2059`，
镜像已保存到桌面 `Redmi_AX3000_NSS_刷入对比_20261010/opt11-squashfs-factory.ubi`。
已保留配置刷入，镜像和设备 ECM/ath11k 模块一致。初次启动曾反复 WPA
reason=15，随后恢复；重刷后的启动在三分钟检查时已连接。不能据此声称
握手超时已修复；普通版此前也复现过。

IPv4 STA→MFC→br-lan 组播实验中，输入接口加入组后软件 MFC 统计为 2662
包，接收端 2552 个唯一序号、93 个重复包，TTL 从 32 减为 31。ECM 组播
ACCEL/pending 均为 0，live dump 没有测试 tuple。该结果证明软件路径
工作，不能认定硬件卸载、无丢包或无重复。测试后已恢复 bridge/nft 设置。

新增 0607/0071 修正真实 MFC 输出桥的快照：MFC VIF 自动设置 ALLMULTI，
而原输入/L2 getter 的 host-copy 保护误拒绝了输出桥。新 getter 对应
`br_dev_xmit()` 的 local-out 语义；ECM 重新核对 MFC cookie 和真实 OIF，
输入桥及合成成员项继续用原 getter。无 MDB、querier、MCU 所有权及容量
检查保持有效。IPv4/IPv6 实际函数的 ASan/UBSan 测试、原生内核和 ECM
modpost、完整 opt12 镜像构建通过；新模式的 MC CREATE/收发仍待真机验证。

opt12 运行仪表确认 native INET flags=0x401、MFC count=1/cookie=2，随后
source node 因源主机 ARP FAILED/INCOMPLETE 而无法建立。0072 仅在已证明
默认表 MFC、同一实际输入接口、完整未标记 Ethernet header 和有效单播
MAC 时使用收到帧的原始 source node，不替换成 AP BSSID。source node 和
目的层次随后成功建立。0073 修正 delay=1 的单播双向门槛阻止单向组播：
有效 UDP multicast hierarchy 收到两个慢路径包即可准入，单播保持原判定。

临时模块已获得 MC CREATE ACK/ACCEL，但软件包数仍增长，尚不能认定
STA multicast 的硬件转发通过。生产 MCBC exception 保持开启；999-972
修正 host 收到此异常时的分类、PN 和重复验证标记。详细依据及未闭合的
固件出口见 [反汇编记录](firmware-reverse-2026-10-10.md#sta-mcbc-exception-与组播接收边界)。
完整 opt13（0607、0071–0073、999-972）已构建，运行验收继续进行。

DNS 已发现 ISP 上游 TCP 查询超时，设备 wwan 设置 peerdns=0，使用已验证
UDP/TCP 的 223.5.5.5/223.6.6.6，默认回程仍为 5 GHz STA。此配置修正后
有线 UDP/TCP 和 10 次查询完成，但用户仍报告手机 DNS 超时；AP 接入测试
复现一次首个 UDP 超时，随后两轮各 10 次 UDP 及 TCP 均成功。因此手机
路径仍未验收，不能用有线或后续成功窗口声称所有 DNS 超时已经修复。

AP 追踪已命中首轮 UDP 超时：client .254:33573 的请求进入 br-lan/input，
dnsmasq 转发到两个上游；稍后收到回复，并最终向该 client port 返回响应。
因此这个窗口存在转发，但回复没有在 client 三秒期限内到达。加入 UCI
`fast_dns_retry` 到 dnsmasq init 的配置转译，设备设置为 `500,2000`，在
上游首轮丢包时由服务端主动重试。未设置该选项的配置保持原行为。

独立 DNS 实例的受控首包丢弃测试：默认模式 3002.73 ms 超时，开启自动
重试后 503.43 ms 收到答复。测试实例已退出，正常 DNS 不参与丢包注入。
之后 AP 首个 UDP/TCP 为 46.11/62.72 ms，另 10 次查询全部完成；手机
长期使用和回程反复启动仍需继续验证。原始证据在桌面
`ap-dns-opt12-r6/nftrace.log`、`ap-dns-opt12-fast-retry-r1/` 和
`dns-fast-retry-fault-test-r2.json`。dnsmasq 默认由 client 重试、该选项
提供自动指数退避的合同见[官方手册](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html)。

最终 opt13 已保留配置刷入，包含上述 DNS init 转译；factory UBI SHA256 为
`f8bb316ed0722a27fa0e7e8274a2cc64c4b11210c47f5a52ce772a9512a3e664`。
设备生成配置包含 `fast-dns-retry=500,2000`，wwan 上游为
`223.5.5.5`/`223.6.6.6`。电脑的 DHCP 实际获得 `192.168.1.1` 作为 DNS；
不能因为 UDP 公网目的地址查询成功就认定绕过了路由器：设备另有
`inet dnsmasq` 的 UDP/53 redirect。电脑本机代理也会拦截 DNS，因此以下
探针只给自己的 socket 设置 mark 666 并绑定真实接口，没有改全局代理。

2026-10-11 00:07 恢复本轮原始 2.4 GHz AP＋5 GHz STA 文件，SHA256 为
`28a1e08fe2338f7b17a3e45eda14fe81ef0b9b78e69917f4f1f20fb41f959edc`。
这次 STA 约六秒连接；此前软件重启后曾连续 reason=15，约十五分钟才
自行恢复。临时固定 STA MAC 没有解决该故障，已经撤销；不能宣称握手
超时已修复，也不能仅凭该现象归因于 NSS。

回程在线后的 opt13 复核：有线客户端到路由器 DNS，五个域名分别用新
UDP/TCP 连接查 A/AAAA，20/20 响应；独立电脑直连上游 Wi-Fi 的同组对照
也为 20/20。路由器 packet socket 观察到 LAN 请求及 5 GHz 上游回复；
首版观察器仅取得 RX，不能把缺失 TX 日志解释为 dnsmasq 没有发送。
随后电脑实际连接路由器 2.4 GHz AP，以 `.254` 为无线客户端，10 次 A
查询及 20 次新连接 A/AAAA 查询均响应，矩阵耗时 29.18–157.23 ms。
无地址的 AAAA 答案是有效 DNS 响应，用户原有 filter-AAAA 配置未修改。
这验证了新版有线和 AP 的 DNS 转发窗口，仍不能代替手机长期使用验收。
原始证据为桌面 `dns-opt13-5g-path-r1/` 和
`ap-dns-opt13-5g-backhaul-r1/`。测试后电脑回到上游 Wi-Fi，路由器仍使用
5 GHz 回程，NSS `enabled=1 ready=1 error=0`；没有保留测试 namespace。

随后 opt13-r2 完成 5 GHz AX/36/HE160 的单流/四流双向 TCP 和 CPU 对照：
Wi-Fi→LAN 744.17/727.30 Mbit/s，LAN→Wi-Fi 915.18/929.50 Mbit/s，
整体平均 CPU busy 5.05–6.09%；下行 live 连接确认 NSS 字节增长及慢路径
包数不变。测速末段 AP DNS 10/10 响应。完整方法、端点布局变化及限制
见 [opt13 对照](performance-2026-10-10.md#opt13-刷入后的-he160-与-dns-验证)。

## NSS peer 创建的本地失败处理

`999-973-ath11k-prepare-peer-resources-before-NSS-CREATE.patch` 将 stats、
peer DMA 和 STATIC AST 的准备移到 CREATE 入队之前。原路径在消息入队后
仍可能因 AST/stats 分配失败撤销 DMA；新路径成功提交后不再执行可能
失败的本地分配，未入队失败仅撤销本次 STATIC AST，清空失败分配字段。
peer DMA unmap 使用与原 map 相同的 DMA_TO_DEVICE 方向。

legacy HTT map 补齐 AST 链表初始化；legacy/v2 均在 base_lock 内记录
本地 `create_result` 后唤醒等待者。v2 不再在接收上下文取得 conf_mutex
并同步删除 peer，也不会重复解 base_lock。process-context peer create
在 rhash 插入之前检查本地错误，解开 base/tbl 锁后进入已有 WMI cleanup。
成功入队不是固件 ACK-ready，不能把本地错误字段当作 NSS ready 状态。

`test-nss-peer-create.py` 执行实际 CREATE 和两种 HTT map 函数，覆盖消息、
stats、peer/AST 分配失败，DMA map 失败、AST 资源耗尽、TX 未入队、重复
创建、仅撤销本次 AST、保留已提交 DMA、运行时禁用 NSS 和失败唤醒。
ASan/UBSan 回归通过；process 部分执行真实错误检查分支，没有执行完整
WMI cleanup 或真实异步响应。补丁已从干净 backports 重新应用成功；
AArch64 模块编译、原有 17 组 NSS 回归和完整镜像构建通过。CI 已加入
该测试，本轮尚未派发。

opt14 为 `r0-nsslan20261011opt14-fe7e690dcd`，factory UBI 17694720 字节，
SHA256 `8f8c8291395da8680ad2e2f640b609188528b87d530f3b31eaedd3f7f9ead8c7`。
镜像经 `sysupgrade -T` 校验后保留配置刷入；升级 SSH 退出码为 246，
未重复刷写，而是以新版本和设备模块验证结果。设备 ath11k SHA256 为
`434639abbe365d8f1b38c98a8122beea1815b55b909c3b892a7595b2df82eba0`，
与最终构建匹配；ECM 保持 opt13 的 `0dbaeb627a9c93a9b4652797626c2cbd76fd2cee19c70a141e0bcf456bdb86ff`。
原无线文件哈希仍为 `28a1e08fe2338f7b17a3e45eda14fe81ef0b9b78e69917f4f1f20fb41f959edc`。
有线 NSS READY，原 2.4 GHz AP 客户端已完成 WPA 认证；5 GHz STA 冷启动
仍出现 reason=15，冷启动等待窗口未通过，不能宣称该故障已修复。
本轮归档为桌面 `Redmi_AX3000_NSS_peer修复_20261011/`，包含完整配置备份、
最终镜像、校验结果及运行日志。电脑始终另以直连上游 Wi-Fi 保持联网。

此次等待到 uptime 1096 秒，STA 仍反复 reason=15。先调用的 `wifi reload`
只执行 netifd 配置 reload，对未变配置没有重建接口；随后 `wifi up radio1`
按 wifi-scripts 的 down/reload/up 路径实际重建 5 GHz 接口，ifindex 从 10
变为 11。无线文件和 STA MAC `44:df:65:b0:63:2e` 均未改变，数秒后完成
认证并取得 `192.168.15.23` 和 5 GHz 默认路由。这是一轮冷启动/接口重建
差异观察，不能排除外部变化，也不能作为自动重连已稳定的证明。

路由器 EAPOL 头部观察没有捕获握手帧。电脑增加同信道被动 monitor，并
保留 managed Wi-Fi 联网；第二窗口收到 5275 帧和 38 个上游信标，但没有
目标 STA 帧。抓取覆盖不足以证明 AP 没发送或 NSS 丢包，不据此归因。
临时 monitor 已删除，没有改变电脑原连接和信道。

接口重建后实际 AP 验收完成：电脑连接原 2.4 GHz AP，UDP/TCP、10 次 A
及 20 次新连接 A/AAAA 查询均响应；手机长期使用仍未验收。原始证据在
此前桌面 `Redmi_AX3000_NSS_刷入对比_20261010/ap-dns-opt14-after-warm-r1/`，
重建后的设备状态保存在本轮归档 `after-warm-state.log`。DNS 主动重试
配置保留，NSS `enabled=1 ready=1 error=0`，路由器维持原 5 GHz 回程。

迟到 CREATE/DELETE 响应的实例匹配、DELETE timeout/NACK 后的 DMA 所有权、
peer unmap 与 completion 生命周期仍需补齐。本补丁只修正确定的本地
错误路径，不能作为上述问题或 5 GHz reason=15 根因已经修复的证据。

## WIFILI 请求与 peer 实例生命周期进展

新增 0210 为 WIFILI 异步命令登记驱动持有的回调和不复用的 32 位请求 ID。
固件仅收到驱动分派入口；返回时核对 ID、接口及消息类型，恢复客户端
原始 app_data。重复、过期及 NOTIFY 不完成请求。登记到实际 enqueue
与注销入口串行；注销先关闭提交、撤销登记，再通过 synchronize_net
排空已分派回调。同步等待改为私有 completion，超时取消登记并等待
已执行回调结束，避免迟到响应复用旧全局等待对象。

999-974 为 peer 保存独立引用计数、CREATE/DELETE 等待对象及不可变身份。
进程上下文等待匹配 CREATE ACK 后才发布 peer；host unmap 只解绑host，
不释放固件内存。DELETE NACK/timeout 保留所有权，未退休的 peer ID 不可
再用；匹配 DELETE ACK 或确认 RESET 后才释放。复位前关闭peer提交入口，
回滚及销毁均补撤radio登记。peer lookup memory 可隔离到NSS驱动，直到
HAL halt与IRQ/NAPI排空；该API明确不涵盖硬件ring或packet buffer。

实际函数的ASan/UBSan测试通过：驱动请求匹配、取消回调竞态、私有同步
等待、DMA地址边界及隔离；peer分配/TX失败、匹配ACK、等待期间host被
删除、NACK/timeout保留、ID复用及迟到回复拒绝、复位提交门控。第一轮
干净prepare与AArch64模块构建通过；随后门控/串行化修订尚待重新构建。

**尚未交付新镜像。** 审查确认RESET失败后，上层core/DP/HAL清理仍可能
释放INIT/PDEV_INIT已提交的共享SRNG、rdp/wrp和buffer；保留peer内存、
撤销ctx及跳过NSS TX页释放不能作为完整DMA栅栏。下一步必须补齐这些
上层错误/恢复/卸载门控及确实的停止证明，才能进行新镜像运行验收。
当前设备仍为已验证的opt14，原5GHz回程及电脑Wi-Fi联网保持。

## 2026-10-11 DNS 转发复核

针对“路由器分配的 DNS 无法转发”的反馈，当前 opt14 的 DHCP 租约实际
下发 `192.168.1.1`。路由器的 5 GHz wwan 在线，dnsmasq 使用
`223.5.5.5`/`223.6.6.6`，生成配置保留 `fast-dns-retry=500,2000`。
有线客户端的 UDP/TCP A/AAAA 查询 20/20 响应；电脑实际连接原 2.4 GHz
AP 后，对路由器的首个 UDP/TCP、10 次 A 及 20 次新连接 A/AAAA 共
32/32 响应。独立电脑直连上游 Wi-Fi 的对照为 20/20 响应。
随后连续十轮新 UDP/TCP 连接查询，有线经路由器和电脑直连上游 Wi-Fi
两组均为 200/200 响应、0 timeout、0 error，原始 Fastsh 证据为 r1774。

路由器头部抓包记录了完整链路：LAN 收到查询、phy1-sta0 向上游发送、
收到上游回复、br-lan/lan1 向原客户端端口返回匹配 ID 的响应。原始证据
在桌面 `Redmi_AX3000_NSS_刷入对比_20261010/dns-forward-current-20261011-0305/`
及 `ap-dns-forward-20261011-0307/`，Fastsh 为 r1769/r1772。
这证明本轮在线窗口可以转发 DNS；没有覆盖手机实际请求、加密 DNS 或
回程启动期间，不能据此宣布间歇超时已修复。此轮没有修改设备 DNS 或
无线配置，测试后电脑恢复原上游 Wi-Fi，路由器无线文件 SHA256 未变。

## 2026-10-11 NSS 恢复时的共享 DMA 保护

新增 `999-975` 检查 crash recovery 的 NSS teardown 返回值：RESET
失败时，在 DP free、SRNG clear 和重新初始化之前退出，保留原共享环。
后续 QMI firmware-ready 事件也在启动固件和分配新 DP 前拒绝未解决的
所有权。关闭 offload 参数不能绕过这一状态；正常 RESET 成功的恢复
顺序保留。

`test-nss-recovery.py` 执行 prepare 后的实际 core/NSS 函数，注入 timeout、
NACK、分配失败和 I/O 失败，检查没有释放或覆盖共享环、不清除恢复标志、
mutex 已解锁，并拒绝后续 firmware-ready 和参数关闭后的恢复。正常复位
及复位成功后固件启动失败的既有清理路径也通过。该测试已加入 CI。

最新 0210、999-974 的 quiescing/提交串行化及 999-975 已从仓库干净
prepare，NSS 驱动和 ath11k AArch64 模块编译、modpost 均成功（r1780、
r1782）。WIFILI、peer、恢复测试通过（r1781），relay 回归及 CI YAML
检查通过（r1783）。第一次新增 patch 的 hunk 行数错误已修正，干净
prepare 复核通过；前一次未同步最新 patch 的构建不作本次验证依据。

**仍未交付新镜像。** 此保护尚未覆盖 setup-error 和 remove 的全部释放
路径。源码取证确认本板两个 radio 都经 AHB/WCSS remoteproc 管理；
QCN6122 的 PCIC/MSI 接口不能套用真正 PCI/MHI 的关机合同。hif_stop
排空主机 IRQ/tasklet 后会释放 CE buffer，没有可检查的 WLAN DMA 停止
结果。当前 AHB power_down 丢弃 rproc_shutdown 的返回值，pd2 的 user-PD
stop 也不能单独证明全部自主 DMA 停止。下一步需保留未解决的共享 DMA
及其宿主元数据，封闭初始化失败/卸载释放入口；不得把 NSS RESET_CTRL
读回或 WCSS OFFLINE 当作全部 DMA 已停的证据。

随后审查发现普通 AP/STA 控制事务的身份缺口：`nss_dynamic_interface.c`
ALLOC/DEALLOC 将调用者栈上的完成对象传给固件，超时返回后没有撤销；
迟到响应可写失效栈。ath11k VDEV CONFIG 使用每 VIF 共用的 completion，
`nss_wifi_vdev.c` 仍原样调用固件返回的 cb/app_data；旧配置超时、动态
接口复用后，旧响应可触及已销毁 VIF 或完成新请求。0210 仅覆盖 WIFILI，
不覆盖这两个消息族；对应修复及验证见下方 0211/999-976 记录。取消等待
不能当作取消固件已经执行的分配/配置副作用。普通 UP/DOWN 是异步入队合同，
authorize 部分调用在 base_lock 内，不能统一改成睡眠等待。这些是源码
风险，尚未证实为当前 5 GHz reason15 的真机根因。

## 2026-10-11 动态接口与 VDEV 私有事务

新增 0211 的 `nss_control` 保存客户端 callback/app_data。固件只接收
驱动内的无操作回调入口和不复用的 32 位 cookie；实际 handler 按 core、
接口、消息族、类型和 cookie 领取请求。重复、过期、NOTIFY 或投递到
其他消息族的响应不会调用旧客户端回调。登记至 enqueue 与关闭门控
共用锁；超时取消、VDEV 注销及 HAL remove 撤销未领取请求，并通过
网络 RCU 等待已领取回调结束。VDEV 注册/失败回滚/注销以 mutex 串行。

动态 ALLOC/DEALLOC 的等待对象改为独立 heap 对象。ACK 必须匹配原请求
的节点类型、合法接口编号及 payload 长度，才能更新宿主分配表。cookie
在 enqueue 锁内分配并作为代际；每 core/ifnum 的 shadow 只接受更高
代际，已领取的旧 DEALLOC/ALLOC 也不能覆盖后来状态或发旧删除通知。
更新和 atomic stats 通知共用 assignment 锁，getter 使用 READ_ONCE；
当前唯一找到的 netlink consumer 使用 GFP_ATOMIC，未调用等待接口。

999-976 让 CONFIG callback 只写独立请求对象，不访问 arvif，也不复用
每 VIF completion。取消排空后检查 completion_done，允许超时边界上
已领取并完成的有效 ACK 返回结果；未领取的旧 ACK 仍被拒绝。
UP/DOWN/authorize 的既有异步入队合同保留。

`test-nss-control.py` 的 ASan/UBSan 检查执行实际函数，覆盖身份校验、
重复/迟到响应、取消与已领取回调竞态、接口复用、门控与 enqueue 交错、
动态分配/释放 heap wait、错误长度/类型、分配与 TX 失败、旧/新 shadow
更新的双向交错，以及 wait 返回 0 后有效 ACK 已完成的边缘状态。
`test-nss-wifi.py` 另执行真实 register/unregister 函数，检查 gate 失败
回滚、mutex 解锁、撤销门控先于移除 datapath/handlers。CI 已接入新测试。

最终 canonical patch 的干净 prepare、NSS/ath11k AArch64 编译及 modpost
通过（r1806）；最终宿主控制、注册、WIFILI、peer、恢复检查全部通过。
最终测试及 CI YAML 检查分别为 r1808、r1807；干净 prepare 后的四个
driver 文件与 ath11k nss.c 均与已审查快照逐字相同，模块确认为 AArch64。
NSS driver release 为 27，mac80211 release 为 10。
**仍未交付新镜像，也未认定为 5 GHz 超时的真机根因。** 初始化失败/
卸载时的共享 DMA 保留尚未闭合；取消后固件已执行的未知分配/配置副作用
仍需明确处理。当前设备维持 opt14，5 GHz 回程和电脑 Wi-Fi 联网保持。

共享 DMA 保留的后续边界已核对：INIT 的 HAL rdp/wrp、TCL/REO 环及
link/scatter descriptors 的元数据在 ab，PDEV refill 环的元数据在 ar；
保留页而释放 ab/ar 会丢失这些记录。setup-error 仍经过 pdev free、
core stop、mac destroy、dp free；AHB QMI_FAIL/shutdown 的特殊分支也会
进入 HAL/CE/core free。保留 DMA 的同时仍需撤销 CPU 入口，尤其藏在
DP 清理里的 mon_reap/shadow timers 和 pdev debugfs；workqueue、QMI
events、IRQ/NAPI/tasklet 排空不能因跳过内存释放而一起省略。deferred
REO descriptor callbacks 也会直接释放 DMA，需覆盖这些底层入口。

## 2026-10-11 共享 DP/HAL 元数据保留第一阶段

新增 999-977：ownership_uncertain 时，SRNG、link/scatter banks、DP TX
对象和 REO command lists 的清理入口保留原内存和指针；HAL 不释放或
清空 rdp/wrp，也不覆盖 ring 元数据。DP 分配和 ring service 拒绝继续
处理被隔离的 datapath。该条件独立于 nss.enabled，关闭 offload 参数
不能绕过保留。

CPU 清理继续：pdev free 停止 mon_reap_timer 并撤销 pdev debugfs；
common/DP free 停止已初始化的 shadow timers。MAC destroy 保留含 PDEV
ring 元数据的 ar/hw。core free 排空并销毁 workqueues，持有 DMA device
引用并保留 ab；retained 标志防止顺序重复调用再次销毁队列或取得引用。
保留的 ab 只可视作元数据，已销毁的 workqueue 指针不可继续用于排队。

`test-nss-shared-dma.py` 执行实际 SRNG/common/scatter/bank/pdev、HAL、
MAC/core 清理函数，检查 RESET 失败时 DMA/heap 不释放、指针页不覆盖、
ar/ab/device 元数据保留，timer/debugfs 仍撤销，workqueue/device 引用
只处理一次；普通清理路径同样通过。ASan/UBSan 测试、控制及恢复回归
通过，CI 已接入该测试。干净 canonical prepare、AArch64 模块构建和
modpost 成功（r1818）。源码审查未发现该增量的新错误。

**仍未交付新镜像，整 SOC quarantine 尚未闭合。** CE、QMI、deferred
REO owner 和重新 probe 保护仍待实现。AHB 可在取得 hw_rev 后、ab 分配
和硬件操作前拒绝重新 probe；此状态必须由持续存在的所有者保存，不能
只放在可卸载的 ath11k 模块全局变量。CE cleanup 必须保留 DMA buffers
但停止 shadow timers；QMI deinit 应释放 handle、cancel event work 和
销毁 event workqueue，同时保留 M3/target memory。QMI 初始化需分别
记录 handle/work/wq 的有效阶段；setup 失败可能发生在 event work 本身，
不能从该线程取消自身或销毁自身队列。IRQ/tasklet/NAPI 是否已初始化
也需记录实际阶段，不能仅凭 ab 存在推断。以上保留不构成 DMA 已停证明。

## 2026-10-11 隔离所有者、CE 与 QMI 清理

0212 在 NSS provider 中保留 opaque SOC 元数据和硬件类型隔离位。同一
类型仅 pin provider 一次，重复发布不重复记录；这些状态没有 module_put
或清除路径，普通模块卸载/重载不能丢失“直到整机重启”的隔离状态。
IPQ5018/QCN6122 映射为 target 29/30。999-978 在 AHB 取得 hw_rev 后、
ab 分配/DMA mask/硬件访问前拒绝被隔离类型，即使运行参数关闭 offload
也不能绕过这一检查。

CE cleanup/free 继续停止已初始化的 shadow timers，保留 rings、SKB
映射和对应元数据；service/poll/send/post 在隔离状态拒绝继续处理。
QMI 新增 handle/worker/event queue 的初始化阶段标志：停止服务先在
event_lock 下关闭发表入口，再 release handle、cancel 已初始化 worker、
destroy 已存在 workqueue 并清残留事件。构造失败和重复 deinit 使用同一
收口，未初始化资源不会被取消/销毁。M3/target memory 在隔离后保留。
AHB free_resources 也调用可重复的 QMI deinit，覆盖未注册 shutdown 分支。

QMI mem_request callback 的 metadata 改写、fixed assign、dynamic alloc
和事件发表由 mem_lock 串行；锁在 core_alloc 初始化。NSS INIT 在同锁内
提交并发布 init_submitted，RESET 在同锁内发布结果和注销。NSS 已提交
且仍注册时，QMI 不替换内存；RESET 失败后永久拒绝替换，成功注销后才
允许新的请求。审查确认 INIT 失败先解锁再 RESET，且 NSS ACK callback
不取 QMI mem_lock，未发现该锁序的自等待或漏解锁。FW_READY 失败不再
误标 REGISTERED，非法 memory segment 长度也在改 metadata 前拒绝。

最终 canonical 干净 prepare、NSS/ath11k AArch64 编译与 modpost 成功
（r1835）。`test-nss-quarantine.py` 的实际函数测试覆盖 provider 重复发布、
初始化阶段失败、事件关闭/排空、内存请求门控、隔离时 DMA 保留及普通/
重复 deinit；source-order assertions 核对 mem_lock 和 probe 检查位置。
共享 DMA 测试扩展了真实 CE cleanup/free/service/poll 函数；控制、peer
与恢复回归通过。上述测试与锁序源码审查不能代替真机 DMA 停止验证。
最终隔离/控制/peer/恢复检查为 r1837；该批次的共享 CE 测试初稿因原有
int/u32 循环触发宿主 Werror，调整测试编译选项后单项复核通过，未修改
生产循环。所有最终源码与已审查快照逐字核对通过，模块确认为 AArch64。
NSS driver release 为 28，mac80211 release 为 11，CI 已接入隔离测试。

**仍未交付新镜像。** deferred REO descriptor 的宿主保留和 IRQ/tasklet/
NAPI 实际初始化阶段仍需闭合，不能用 ab 存在或 napi_enabled 推断资源
已经 add/初始化。当前设备仍为 opt14，原 5 GHz 回程继续在线。

```sh
UBSAN_OPTIONS=halt_on_error=1 python3 scripts/tests/test-nss-ecm-multicast.py \
  --ecm /path/to/patched-qca-nss-ecm
UBSAN_OPTIONS=halt_on_error=1 python3 scripts/tests/test-nss-mroute-table.py \
  --kernel /path/to/patched-linux
```

## 2026-10-11 实际无线 DHCP 与 DNS 转发

opt14 在线复核新增真实 DHCP 接入，而非手动设置测试 IP：电脑临时连接
2.4 GHz AP，获得 `192.168.1.100/24`；DHCP option 6 为 `192.168.1.1`，
option 3 同为 `192.168.1.1`。使用该 DNS，经真实 Wi-Fi 接口分别执行
50 次 UDP 和 50 次 TCP 查询，A/AAAA 各半，100/100 回应、RCODE 全为 0，
没有超时或传输错误。中位数 59.88 ms，P95 102.14 ms，最大 125.65 ms。
仅测试 socket 设置 mark 666 避开电脑代理；路由器的 DNS redirect 保留。

只记录包头的观察器同时确认 `phy0-ap0 → br-lan → dnsmasq → phy1-sta0`
上游请求与 `phy1-sta0 → dnsmasq → br-lan → phy0-ap0` 回包，返回的客户端
端口及 DNS ID 与请求匹配。有线经路由器和电脑直连上游两组各 20/20
回应。证据为桌面 `Redmi_AX3000_NSS_刷入对比_20261010/` 中
`ap-dhcp-dns-20261011-0512/`、`dns-live-20261011-0509/`，Fastsh
r1854/r1850。临时 NM profile 已删除，电脑恢复原上游 Wi-Fi，metric 50
优先，原有线 profile 保留为 metric 700。

当前在线窗口没有复现“DHCP 下发的 DNS 无法转发”。仍未覆盖手机特定
请求、加密 DNS 或冷启动期间；filter-AAAA 的空地址答案也不等于请求
超时。未因此修改 DNS、无线配置或关闭 NSS。

## 2026-10-11 deferred REO、host peer 与 IRQ 初始化阶段

`999-979` 在 REO status ring 锁、base_lock 的顺序下发布永久保留状态，
排空正在退休 descriptor 和 command owner 的回调；status handler 锁内
再次检查隔离状态。peer TID 的异步释放在 base_lock 内检查状态；五处
host peer 最终释放统一经过 finalizer。未确认 RESET 后使用嵌入 peer 的
list 保留 peer/TID metadata，不依赖失败路径的新内存分配。

`999-980` 分别跟踪成功 request 的 IRQ action、已初始化的 tasklet、
已 add 的 NAPI 与 dummy netdev，以及正常启停和 NAPI 临时 mask。
失败仅回滚成功前缀；多 action 共用 MSI 时按原 dev_id 逐个释放。
AHB/QCN6122 先完成 IRQ 配置再启动 core/QMI，避免 FW-ready work 与
尚未完成的 IRQ/NAPI 配置交错；AHB CE 在启动前使用 NOAUTOEN。

干净 AArch64 模块构建 r1847 通过。实际源码函数测试 r1858 验证在途
REO 回调阻止隔离发布、metadata 保留及正常释放；r1860 覆盖各 IRQ
request/lookup/NAPI 分配失败点、单 MSI 共享 action、重复 stop/free、
NAPI 临时 mask 配对与重复 completion。共享 DMA、peer、恢复、控制
回归通过，隔离测试的 source-order 检查已对应新的统一发布函数。
mac80211 release 为 12，CI 接入上述两项测试。此处是源码/宿主故障
注入与交叉编译结论，真机重启、吞吐和 DNS 验证待 opt15 镜像刷入。

## 2026-10-11 opt15 刷入和运行复核

完整 opt15 构建 r1862、buildinfo/校验和生成 r1866 成功；最终 relay
fixture 纳入真实 peer finalizer 后回归 r1868 通过，其余受影响的 Wi-Fi、
隔离、deferred owner 和 IRQ 检查通过。12 个 prepare 后的源码文件与
审查快照逐字相同。版本为 `r0-nsslan20261011opt15-fe7e690dcd`，factory
UBI 17694720 字节，SHA256 为
`e68a1d662f72acc688335240ea33eef5a120082368edd0454061da436e2e1933`。

r1869 在桌面 `Redmi_AX3000_NSS_opt15_20261011/` 保存配置备份，校验上传
哈希及 `sysupgrade -T` 后只发起一次升级。刷入后观察约 87.4 秒确认新
revision、5 GHz STA 关联及 DHCP 默认路由；这不是断电重启或多次启动
稳定性证明。设备 ath11k SHA256 为
`84240dbe22b5dea34c89e9292e5a7d6e8b14e93d7f350936a2d8279c7c238b39`，
NSS driver 为 `50c845a84aceebef77418f516889b590ba219183fe6f67d36557b66b4e3b1b40`，
ECM 为 `0dbaeb627a9c93a9b4652797626c2cbd76fd2cee19c70a141e0bcf456bdb86ff`，
均与镜像 staging 模块相同。四份 wireless/network/dhcp/firewall 配置
的哈希与刷机前一致，wired NSS 为 `ready=1 error=0 allocation_uncertain=0`。

刷后实际 AP DHCP 再获 `.100`、DNS `192.168.1.1`，100 次 UDP/TCP A/AAAA
查询全部回应、无超时（r1872）；有线连续 90 次 A 查询得到有效地址，
无超时（r1874）。后者开始时设备 uptime 约 181 秒：最初的自动观察器
因 root 用户的 SSH host-key 校验失败而没有取得最早启动阶段的 DNS
样本，修正观察器为原用户 SSH 身份后完成采样，不能用该文件名推断
它覆盖了最初的联网窗口。上述结果仍不能代替手机间歇超时验收。

恢复原拓扑后，r1883 再次完成有线经路由器 20/20、电脑直连上游 Wi-Fi
20/20 对照。刷后经路由器的实际无线和有线查询合计 210/210 回应，
其中 100 次来自真实 AP DHCP 客户端；直连上游对照不计入这 210 次。

5 GHz AX/36/HE160 双向单流/四流及 CPU 对照、上行 NSS 实际连接证据
见 [opt15 运行数据](performance-2026-10-10.md#opt15-刷入后的-he160-与上行-nss-验证)。
两轮测试后均逐字恢复原 2.4 GHz AP＋5 GHz STA，回程关联和默认路由
均恢复；电脑回到直连上游 Wi-Fi，测试 namespace、临时 profile、iperf
服务及 ECM 观察节点已清理。当前 DNS 转发正常，5 GHz 长期握手稳定性、
手机特定超时和无线→有线带宽波动仍没有根因结论。

## 2026-10-11 DNS 负载窗口与重试修正

在保留 2.4 GHz AP＋5 GHz STA 的现有布局下，将电脑有线端隔离到
namespace，以电脑自身的上游 Wi-Fi 地址作为 TCP 测量端点，同时经
DHCP 下发的 `192.168.1.1` 查询 DNS。此路径包含同一上游 AP 的两段
无线传输，电脑上游信号约 -81/-82 dBm，不能把它的 14–28 Mbit/s 结果
直接当作路由器 5 GHz 无线能力或与 HE160 AP 桥接峰值比较。

测试先发现两个上游 STA 的自动 ARP 相互不可达。双侧包头看到各自发出
广播 ARP，未见对方交付；仅为这两个测试地址临时设置准确邻居后，TCP
立即接通。空口头部观察看到 PC ToDS、addr3 广播以及部分 AP→PC 数据，
但缺少 payload/EtherType 确认且没有 beacon 覆盖，不能归因于 AP 或
NSS。静态邻居只用于受控负载测量，测后删除；并非广播故障的交付修复。

原 dnsmasq r2 在负载下出现 1/120、5/120 超时。一个 UDP 请求进入
LAN/dnsmasq 后于 500 ms 重试，此后停发，约 11.65 秒后才随另一查询
重发并获得答案；已超过客户端 3 秒等待。源码把 `fast-dns-retry` 总
预算从毫秒除以 1000，再用整秒 frec.time 判断：在小数 .8 秒发出的
请求，原 2000 ms 预算会在 +1.5 秒重试前跨过两个整秒而提前终止。
官方选项单位为毫秒，见 [dnsmasq 手册](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html)。

`201` 保留毫秒预算，以首发的毫秒时间测量总窗口，使用 monotonic
clock（平台不支持时保留原 fallback），在期限醒来并限制指数回退的
有符号溢出。实际函数测试涵盖整秒边界、1250 ms 窗口、32 位回绕、
时钟跳变、最大 backoff 和 DNSSEC 门控，CI 已接入。
私有 1054 端口实例丢弃前两个上游请求：旧 r2 四次均 3003 ms 超时；
修正二进制及实际安装的 r3 各四次均约 1504 ms 回答。正常 53 端口
没有参与丢包注入（r1905/r1911/r1915）。

r3 在线满载复测 UDP 全部回应，但有三次 TCP 超时。新的 TCP/UDP
包头观察器确认 TCP 请求已经到达路由器且转发给上游：有两条连接
上游 ACK 了查询却无 DNS 答案，约 10 秒才切换到另一上游并立即回答；
另一次 SYN 重传至约 3.2 秒才收到 SYN-ACK。不能把它们归为本地 DNS
监听失败或由 bulk TCP ACCEL 推断 DNS 无丢失。

`202` 增加明确的 opt-in `--dns-tcp-timeout-ms=发送/连接毫秒,接收毫秒`，
UCI 对应 `dns_tcp_timeout`。未设置时保留原 5/10 秒默认；配置超时时
避免 MSG_FASTOPEN 的 EAGAIN 被 datagram retry loop 再次延长。实际
函数测试验证默认、自定义及 INT_MAX 参数、Fast Open timeout/EINTR，
交叉编译及实际参数边界检查通过。私有 TCP 实例让首个上游接受查询
但保持静默，备用上游立即回应：旧默认超过 3 秒，500/1500 ms 配置
约 1576 ms 收到回答（r1923/r1924），正常 DNS 未参与故障注入。

dnsmasq-full r4 已按本地 APK 安装，只有该包升级，无外网依赖升级。
实际 binary SHA256 为
`0ca11ccf1628e6d99a76a9385f37c8f909911ae1a4e74ff284aeeeafb0293757`，
与已打包的 stripped binary 相同；配置和旧程序在桌面
`Redmi_AX3000_NSS_opt15_20261011/dns-retry-r4/` 备份。内核/NSS 驱动仍为
opt15，没有将此次单包更新误写为全镜像刷入。

最初 500/1500 ms 满载窗口虽然 240 次均回应，但有一次 REFUSED：首
个上游 SYN 在 500 ms 结束，备用服务器又无回答。因此将连接/发送
预算调为 1200 ms，接收预算调为 1000 ms，允许首次约 1 秒 SYN 重传。
最终两向满载各 120/120 回应、RCODE 全为 0、0 timeout、0 transport
error（r1930），均与 iperf 时间重叠。不能将“收到错误 DNS 响应”算作
查询成功；原始失败与 REFUSED 样本保留。

最终配置下，r1932 再次用真实 2.4 GHz AP DHCP 客户端取得 `.100` 和
DNS `192.168.1.1`，100/100 UDP/TCP A/AAAA 回应且 RCODE 全为 0。
这与满载 240 次共同验证了本轮两个修正的在线窗口。r1933 保存最终
binary、配置、回程和 NSS 状态，确认临时邻居已删除、namespace 已清理，
电脑默认路由仍经自己的上游 Wi-Fi；最终配置备份为桌面
`dns-retry-r4/config-after-dns-r4-final.tar.gz`。仍不替代手机长期验收。

原始包头、DNS JSON、CPU、NSS 全量统计在桌面 opt15 目录的
`sta-nat-load-dns-r4-20261011-0626/`、
`sta-nat-dns-r3-installed-20261011-0644/`、
`sta-nat-dns-r4-installed-20261011-0702/` 及
`sta-nat-dns-r4-budget1200-1000-20261011-0718/`。
当前配置保留原 DNS 上游和 fast retry，只新增上述 TCP 时限；仍需
手机具体路径和长期使用验证。广播 ARP、5 GHz 长期握手及上行带宽
波动没有被本次 DNS 修正证明解决。

源码审查还发现 key installation 的三个宿主缺口：
NSS 配置前再次查找 peer 后未检查 NULL；跨 base_lock 解锁/重锁继续
使用旧 peer 指针，WMI unmap 可导致 UAF；DISABLE_KEY 仍走恒置
auth_flag=1 的 NSS 授权分支。SECURITY 当前只确认提交，NACK 不影响
set_key 成功。修正需要独立 peer 实例引用、实例验证与 enqueue 原子
衔接、锁外私有 ACK 等待、发布时重新查找及实例核对，并明确 WMI
已经装 key 后 NSS 失败的处置。不能在 base_lock 下直接套用同步等待，
也不能由这些源码缺陷直接认定为本次广播 ARP 或旧握手超时根因。

`999-981` 已修正宿主 peer 生命周期和删除密钥状态：两处 peer map
分配初始化一个链表 owner 引用，key operation 获取额外引用，五处
release 不会在 key 等待期间回收宿主；PN helper 与最终发布均在
base_lock 下核对原实例。最终 put 也与隔离发布串行：unmap 先退休、
随后 RESET 发布 ownership_uncertain 时，最后一个 key 引用转交
retained_host_peers，仍需的 RX_TID 元数据不被释放，且不需要临时分配。
DISABLE 不再设置 NSS cipher/authorize；删除旧 GTK 不清除存活 GTK
选择或 PTK PN 状态，正数 NSS transport 错误转为 -EIO，不能误用
mac80211 软件加密 fallback。

`test-nss-key.py` 执行真实 set_key、fragment drain 循环、PN helper
与 peer 引用函数；在 timer drain/WMI 等待插入 unmap 和相同 peer ID
替换，并覆盖最后 put 前的隔离发布、GTK 换槽/同槽替换和各 NSS 提交
阶段错误。r1953 ASAN/UBSAN、deferred-owner、MEC/relay 回归通过；
r1955 从 canonical patch 干净 AArch64 重编译通过，mac80211 release
为 13。此层尚未把 SECURITY/AUTH/VDEV security 提交改为实例绑定的
ACK 事务，也未处理 WMI 已安装 key 后的 NSS NACK/timeout 硬件状态；
这些仍是下一层工作，不能把本层源代码测试当作无线超时根因结论。

收到“路由器分配的 DNS 无法转发”报告后再次核对（r1937–r1939）：
有线 DHCP 下发 `192.168.1.1`，60/60 UDP/TCP A/AAAA 查询回应且 RCODE
均为 0；直连两个上游各 20/20 成功。真实 2.4 GHz AP DHCP 客户端获得
`.100` 和同一 DNS，100/100 查询成功；包头记录包含 AP→br-lan→5 GHz
上游及反向回复。原始证据在桌面
`Redmi_AX3000_NSS_刷入对比_20261010/dns-user-report-ap-20261011/`。
路由器仍运行含重试修正的 dnsmasq-full r4；本次没有改变路由器配置。
检查时手机未关联 AP，不能把电脑测试代替手机故障复现。测后电脑
上游 Wi-Fi 默认路由恢复为 metric 50，临时 profile 和观察进程已清理。

## 2026-10-11 opt16 刷入与当前验证边界

最终干净 mac80211 构建通过（r1955），package/install、target/install、
buildinfo 完成（r1956）。递归 make 的 profiles 元数据步骤仍报
`too many values to unpack`；r1957 清除递归 make 环境变量后独立运行
原脚本完成 profiles.json，并生成 checksum，没有修改仓库辅助脚本。
r1958 验证镜像和 profile revision 均为
`r0-nsslan20261011opt16-fe7e690dcd`，UBI 17694720 字节、SHA256
`b1f24e11634d20f4f1fdc9f949cd53c947f45f8e5a219bf7e42aaef044d79327`。

r1959 在桌面 `Redmi_AX3000_NSS_opt16_20261011/` 保存原配置、镜像、
哈希和启动观察，上传哈希相符且 sysupgrade -T 通过后只刷入一次。
约 87.4 秒的观察点确认新 revision 和 5 GHz 回程。四份配置哈希均
与刷前相同；ath11k 实际 SHA256 为
`f4e9f5a876b8fd1ea9108f4bb7435d0d3c2e0dbbcf43d10c0ac9bf63eccc5cc7`，
NSS drv、ECM 和 dnsmasq 也与镜像 root staging 相同。DNS 仍为 r4，
保留 500/2000 ms UDP retry 与 1200/1000 ms TCP 时限。

早期 DNS 观察器在设备 uptime 约 41 秒取得首个样本，90/90 A 查询
获得有效地址（r1960）；它不覆盖设备启动前或全部初始化窗口。
HE160 LAN→Wi-Fi P4 满载时另有 20/20 UDP/TCP A/AAAA 正常回应
（r1963），最终恢复原布局后真实 2.4 GHz DHCP AP 客户端取得 .100、
DNS 192.168.1.1，100/100 查询回应且 RCODE 全为 0（r1964）。
本轮合计 210 次查询无超时或错误回应，仍不能替代手机具体路径验收。
吞吐、CPU 与 NSS 计数见 [opt16 对照](performance-2026-10-10.md#opt16peer-key-生命周期修正后的-he160-对照)。

原始无线配置逐字恢复、电脑默认路由为上游 wlan0/metric 50，临时
namespace、iperf、观察进程和 profile 清理；NSS 当前
`ready=1 allocation_uncertain=0 error=0`（r1965）。最终配置备份为
桌面 opt16 目录 `config-after-opt16.tar.gz`（r1966）。

不能宣称所有握手或广播问题已修复：自然上游 STA↔STA ARP 仍失败
（r1961，无静态邻居），HE160 对调时 2.4 GHz 回程第一次四次握手
等待约 12 秒失败，十秒等待后的同配置重试成功；恢复 5 GHz 回程
约六秒完成，初次启动和恢复时的 5 GHz Key negotiation 均成功。
这些是不同频段与时间窗口的证据，不是长期稳定性或 NSS 单一归因。
SECURITY/AUTH ACK 事务、WMI 部分状态处置及广播路径仍需继续处理。

## opt19：继续补齐 STA 异常接收与下行验收

当前候选已升级为 `r0-nsslan-opt19-fe7e690dcd`，在 opt18 的密钥 ACK
事务、VHT SU/STBC 统计修正基础上补齐 MCBC descriptor TID 和 host NULL
queue 的 QoS 重建顺序。新增测试执行真实接收、头部重建、mac80211 QoS
分类和 CCMP PN 检查，覆盖独立 TID 窗口、重复/倒退 PN 与非 QoS 帧。
干净 prepare、AArch64 模块及完整镜像构建、首次启动和模块哈希核对通过。
具体镜像、源码/运行证据和剩余边界见 [opt19 记录](sta-downlink-opt19.md)。

同原上游的包头对照确认广播 ARP 双向不交付、定向 ARP 双向通过；关闭
NSS 的 host 对照也得到相同结果。没有以 TID 修补或单次连通宣称上游广播
和中继带宽已经解决。完整 Wi-Fi 组播成员同步、IPv6 转发及长期握手仍待
验收；已有受控 STA→LAN NAT 下行的低 CPU/ACCEL 证据继续保留。

当前最终镜像已进一步升级为 `r0-nsslan-opt20-fe7e690dcd`，mac80211
release 18。原1816-byte NSS buffer配384-byte packet offset只剩1432
字节，标准MTU几乎全部跨两个buffer；结合实际固件和宿主DMA容量核对，
仅把buffer配置改为2048，ring深度与pool数量不变。真机标准MTU的P1/P4
SG增量均为0，REO约一包一个，NAT连接保持ACCEL。host TX完成偏移、
空RX skb对齐和monitor紧凑布局同时修正，原配置和电脑上游Wi-Fi恢复。
吞吐本轮约319/310 Mbit/s、CPU约4.42%/6.12%；空口仍波动，没有宣称
全部中继带宽问题解决。源码、镜像、条件与实测见 [opt20记录](sta-downlink-opt20.md)。

进一步升级为`r0-nsslan-opt21-fe7e690dcd`，qca-nss-drv release29。
修复PROJECT统计首次ACK读侧竞态并补齐可靠启停，原NSS数据路径、
ring/pool深度与ath11k二进制保持opt20配置。真实ACK/NOTIFY及负载
下启停已通过，第一轮STA→LAN下行约332/313 Mbit/s、CPU约5.0%/3.8%。
电脑上游STA＋AP共用radio的测量限制与剩余下行波动继续保留；运行
证据和下一步负载内统计见[opt21记录](sta-downlink-opt21.md)。

后续NAT窗口仍波动到159/213 Mbit/s，不能只引用前两轮较高值。
WBM catch-all已细分为越窗、BA重复等正常定义的exception，负载下还有
FCS增长；PN类没有增长。已有统计ABI与固件写入匹配，下一步核对
实际BA/REO完成与空口交付，仍未将某项计数认定为带宽根因。

opt22 已刷入 `r0-nsslan-opt22-fe7e690dcd`，mac80211 release19。
近距离 AP 下行本轮 365/352 Mbit/s，CPU 约 5.63%/5.21%，SG 为0；
REO UPDATE 的真实完成状态全部 success，PN 失败没有增长。PC 上游
STA/AP 仍共用 radio，结果不证明长期带宽波动已解决。内部 2.4GHz
host/NSS 对照都未获得可靠公网连接，不能归为 NSS 专属失败。原配置
和 5GHz 回程已恢复，详细证据见 [opt22 记录](sta-downlink-opt22.md)。

opt23 升级为 `r0-nsslan-opt23-fe7e690dcd`，mac80211 release20。
修复 REO 先发后登记竞态、固定编号回压及 cache-flush 失败范围，
首次启动模块/原配置哈希一致，两个 SOC 提交/完成均匹配且 pending=0。
原上游4轮重连越过一圈编号，callback85/85；近距离AP的NAT下行
371.56/310.43 Mbit/s，CPU4.23%/5.30%，SG0、ECM四条连接保持ACCEL。
最终原配置、回程、DNS/HTTPS和电脑上游Wi-Fi均恢复，带宽波动未宣称解决。
源码与后续运行验证见 [opt23 记录](sta-downlink-opt23.md)。

opt24补独立queue-instance DMA引用和私有GET_QUEUE_STATS。
初建/更新WMI、AMPDU_STOP、fragment与cleanup/unmap的实例窗口一并
处理；未回复query与WMI在途状态不能被NSS RESET ACK清除。实际C
故障/并发回归和AArch64编译通过，已保留配置刷入；原回程TID0/16
的硬件GET成功且pending0；3轮原回程重连/365条提交通过。NAT两轮
P1/P4约94/161及210/89 Mbit/s，ECM保持加速，但本机接收也波动；
late/timeout到4095/63后保持，不能用后续零差值认定无事件。原配置、
回程、DNS/HTTPS及电脑原联网状态已恢复，见 [opt24记录](sta-downlink-opt24.md)。
