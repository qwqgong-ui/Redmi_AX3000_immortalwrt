# 2026-10-10 opt6 刷入后的 5 GHz HE160↔有线对照

设备已刷入 `r0-nsslan20261010opt6-fe7e690dcd`，复用既有双端点 iperf3
测试完成四项 TCP 对照。Wi-Fi→LAN 单流为 787.09 Mbit/s，LAN→Wi-Fi 四流
为 930.68 Mbit/s；路由器两核平均 busy 为 3.94–4.66%。指定测速连接确认
进入 NSS bridge 加速，旧基准的 Ethernet host 通路与本次数据面不同。

factory UBI SHA256：
`bdd2ca4ed4feae322203f436b6d6247d8fa889ae439bc0a38eeff1d2ec2b15c4`。
设备的 qca-nss-dp、qca-dsa-nss、ath11k 模块 SHA256 与该构建目录一致。

电脑千兆有线端为 `192.168.1.127`；Wi-Fi 网卡移入独立网络命名空间，端点为
`192.168.1.254`，避免同机本地路由短路。两端分别运行客户端和服务器。
实际 5 GHz AP 为 AX、信道 36、160 MHz、中心频率 5250 MHz、24 dBm；
与 opt4 记录一致。每项传输 30 秒，另跳过 3 秒预热，采用接收端有效吞吐。
等待 hostapd `ENABLED`、60 秒 DFS CAC 完成后才建立无线端点。

旧记录中的电脑互联网经手机 USB。本轮 USB 未枚举手机，已保存的蓝牙共享
连接也未激活成功；测试期间电脑互联网经有线管理口和临时 2.4 GHz STA
回程保持连通。公网流量不作为本地吞吐端点。

单位为 Mbit/s。旧数据复用已有记录，没有重新刷旧版重测。

| 测试 | 10-08 opt2 基准 | 10-09 opt4 | 本次 opt6 | opt6 TCP 重传 |
|---|---:|---:|---:|---:|
| 单流 Wi-Fi→LAN | 544.15 | 533.85 | 787.09 | 0 |
| 单流 LAN→Wi-Fi | 912.94 | 895.67 | 902.34 | 933 |
| 四流 Wi-Fi→LAN | 563.08 | 638.27 | 771.99 | 0 |
| 四流 LAN→Wi-Fi | 909.41 | 917.13 | 930.68 | 3458 |

这是各一次测试窗口；无线环境与后台流量有变化，不把差值视为固定收益。
旧数据见 [10-08 实测](performance-2026-10-08.md) 和
[10-09 对照](performance-2026-10-09.md)。

CPU 按路由器 `/proc/stat` 约每秒采样，以 uptime 对齐 iperf 测量窗口，busy
包含 softirq。CPU 时钟为 1008 MHz。

| 测试 | opt2 CPU 0 / 1 busy | opt4 CPU 0 / 1 busy | opt6 CPU 0 / 1 busy | opt6 CPU 0 / 1 softirq |
|---|---:|---:|---:|---:|
| 单流 Wi-Fi→LAN | 98.20% / 40.70% | 98.44% / 46.10% | 5.72% / 2.21% | 1.93% / 0.14% |
| 单流 LAN→Wi-Fi | 96.91% / 83.30% | 94.47% / 83.35% | 5.92% / 2.51% | 3.46% / 0.20% |
| 四流 Wi-Fi→LAN | 99.34% / 44.81% | 82.39% / 89.52% | 4.93% / 3.49% | 1.62% / 0.17% |
| 四流 LAN→Wi-Fi | 97.32% / 90.60% | 94.23% / 83.84% | 7.16% / 2.28% | 3.49% / 0.20% |

本次每项 CPU 窗口覆盖 29.65–30.71 秒，最高温度 69°C，最小 MemAvailable
14532 KiB。CPU 降低不等于温度同比降低；未重新进行 UDP、600 秒持续负载
或满载 ICMP 丢包验证。

测前、测后有线控制器均为 `enabled=1 ready=1 error=0`。四流 LAN→Wi-Fi
期间的 ECM 快照中，connection 20759–20762 对应 `.127`→`.254:45202`，
原始和 NAT 地址相同，`is_routed=0`、`direction=3`、`accel_mode=2`。
接口层次为 eth1 physical 1、lan1 VLAN 32、phy1-ap0 35。四条连接各有约
201–204 MB 正向累计统计，`slow_path_packets=3`，NACK、driver fail、flush
和 no-action 均为 0。这与端点收到的吞吐及低 softirq 一起证明本次实际
使用 NSS 桥接数据面，而非仅确认控制器 READY。第二份快照已在连接结束、
配置恢复后取得，不作为同一连接的持续增量证据。

已恢复原 2.4 GHz HE40 AP＋5 GHz VHT80 STA，完整无线文件 SHA256 仍为
`7956835d0821810fda9dbd0345ab5612177aec62b8cf8702312690fd5136a6d1`。
默认回程为 phy1-sta0，路由器访问公网 3/3、电脑有线管理 ping 3/3，均无丢包。
电脑重新直连上游 Wi-Fi；测试命名空间、iperf 服务及临时 ECM 设备节点已清理。

原始 JSON、每秒 CPU、测前和测后统计保存在桌面
`Redmi_AX3000_刷机备份_20261008_062737/throughput/`，前缀为
`5g-he160-nss-lan-opt6`，CPU 汇总为 `cpu-5g-he160-nss-lan-opt6.json`。
完整配置备份和 live ECM 快照保存在
`Redmi_AX3000_NSS_继续开发_20261010/`。

## opt9 同条件复测

复测设备已运行 `r0-nsslan20261010opt9-fe7e690dcd`。最终镜像 SHA256 为
`bf288c3d4f23a4c217bd4faf7f6a253056474b89a8590c4e836ea6f770639cae`；
设备 nss-lan init 文件与构建目录相同，NSS 为 `enabled=1 ready=1 error=0`，
ECM 已加载。复用上述同一电脑、千兆有线 `.127`、独立 Wi-Fi `.254`、AX
信道 36 / HE160 / 24 dBm 和 30 秒测量加 3 秒预热，直接使用既有旧数据对照。

| 测试 | opt2 旧基准 Mbit/s | opt6 Mbit/s | opt9 Mbit/s | opt2 / opt9 平均 CPU busy |
|---|---:|---:|---:|---:|
| 单流 Wi-Fi→LAN | 544.15 | 787.09 | 778.53 | 71.44% / 3.55% |
| 单流 LAN→Wi-Fi | 912.94 | 902.34 | 891.84 | 90.26% / 3.79% |
| 四流 Wi-Fi→LAN | 563.08 | 771.99 | 758.04 | 73.85% / 3.93% |
| 四流 LAN→Wi-Fi | 909.41 | 930.68 | 930.51 | 94.00% / 7.47% |

平均 CPU 是两核 `/proc/stat` 的整体 busy，包含 softirq。四项 opt9 的平均
softirq 分别为 0.83%、1.80%、1.24%、4.92%，CPU 仍为 1008 MHz。opt9 与
opt6 吞吐差异均在 2% 内；相对于 opt2 的 CPU 收益已在 opt6 接通有线 NSS
数据面时出现，不能归因于 opt9 的启动和 FDB 生命周期改动。各一轮测量也
不能消除无线环境、后台业务及统计读取的影响。

UDP 按四项 TCP 最低吞吐的 70% 取整，发送目标 530 Mbit/s、数据报长度
1200 字节；Wi-Fi→LAN 为 530.03 Mbit/s，LAN→Wi-Fi 为 529.99 Mbit/s，
两方向接收端均报告 0% 丢包。

600 秒、每方向两条 TCP 的同时双向负载也已完成，另跳过 3 秒预热：

| 指标 | opt2 旧基准 | opt9 |
|---|---:|---:|
| Wi-Fi→LAN | 272.33 Mbit/s | 327.97 Mbit/s |
| LAN→Wi-Fi | 529.57 Mbit/s | 847.39 Mbit/s |
| 两核整体平均 busy | 91.03% | 3.70% |
| CPU 0 / 1 平均 busy | 98.85% / 82.85% | 5.24% / 2.20% |
| 两核整体平均 softirq | 86.38% | 1.60% |
| 同时 ICMP 丢包 | 19.739%（590 / 2989） | 0.03328%（1 / 3005） |
| 满载 ICMP min / avg / max | 0.881 / 16.683 / 40.791 ms | 1.268 / 15.306 / 47.983 ms |
| 最高 thermal zone 温度 | 73°C | 83°C |

opt9 持续窗口的 CPU 样本覆盖 599.65 秒，最小 MemAvailable 为 12220 KiB，
CPU 始终 1008 MHz。低 Linux CPU 占用不能推断低温；温度取所有 thermal
zone 的最大读数，当前最高值高于旧记录。UDP 的目标码率随 TCP 实测值
自适应，旧记录为 380 Mbit/s、本次为 530 Mbit/s，不能将两者当作等码率
的 UDP 对照。

四流 LAN→Wi-Fi 的 live ECM connection 35–38 均为 `is_routed=0`、
`direction=3`、`accel_mode=2`，接口层次是 eth1 physical 1、lan1 VLAN 34
和 phy1-ap0 35。两份相隔约 2 秒的快照中，每条正向累计字节增加约
60–62 MB，slow_path_packets 保持 3，driver fail、NACK、flush 和 no-action
均为 0，证明测速数据实际通过 NSS。原始快照和筛选的连接字段存于桌面
`Redmi_AX3000_NSS_继续开发_20261010/opt9-he160-tcp-live-*`。

持续负载中 connection 48–51 的两份快照同样为 NSS ACCEL；上行两条数据
连接的累计字节分别增加 40.3 / 48.3 MB，下行增加 114.4 / 115.5 MB，
slow_path_packets 保持 3–4。原始证据为同目录的
`opt9-he160-soak-live-*`；该数据流与单向峰值分别验证。

本轮临时使用 2.4 GHz STA 保持电脑公网、5 GHz AP 提供本地测速；配置在
改动前已完整备份到桌面。新 iperf JSON、CPU 原始采样和状态记录使用
`5g-he160-nss-lan-opt9` 前缀，保留旧测试数据。

测试完成后逐字恢复原无线配置，SHA256 仍为
`7956835d0821810fda9dbd0345ab5612177aec62b8cf8702312690fd5136a6d1`，
恢复 2.4 GHz HE40 AP＋5 GHz VHT80 STA 和无线优先默认回程。电脑重新连接
上游 Wi-Fi，默认路由恢复 wlan0；路由器公网 ping 2/2。最终 NSS 仍为
`enabled=1 ready=1 error=0`，测试 namespace、两端 iperf 服务及 ECM 设备
节点全部移除。配置归档为桌面
`Redmi_AX3000_NSS_继续开发_20261010/config-before-5g-he160-nss-lan-opt9.tar.gz`。

最终 CPU 汇总为
`Redmi_AX3000_刷机备份_20261008_062737/throughput/cpu-5g-he160-nss-lan-opt9.json`。

## opt10 刷入与同条件对照

按用户要求复用已有数据，构建并保留配置刷入
`r0-nsslan20261010opt10-fe7e690dcd`。完整 Debian 构建通过，factory UBI
为 17694720 字节，SHA256 为
`110bdba4ca841ed4b3c2f52b972eddf96ec40f335b5dfd969500906d2d74b3a4`。
上传后的 SHA256 和 `sysupgrade -T` 检查通过；重启后版本以及 NSS driver、
qca-dsa-nss、ath11k 三个模块的 SHA256 均与构建目录一致。

本镜像包含 0603/0604 的组播路由及桥接快照内核接口，重新应用补丁并完成
vmlinux 构建，实际导出符号已核对；两组 IPv4/IPv6 ASan/UBSan 源码测试通过。
ECM/ath11k 组播成员同步仍未接通，未开启未完成的组播卸载。以下为单播
桥接数据面的运行对照，不能用来证明完整 NSS 组播功能已经实现。

复用电脑有线 `.127` 与独立 Wi-Fi namespace `.254` 双端点，分别运行
iperf3 客户端和服务器，保持 AX、信道 36、HE160、24 dBm，等待 DFS CAC
完成。每项传输 30 秒，另跳过 3 秒预热；CPU 使用既有每秒 `/proc/stat`
采样方法，并按各自传输窗口计算，busy 包含 softirq。

| 测试 | opt9 Mbit/s | opt10 Mbit/s | 吞吐变化 | opt9 / opt10 整体平均 CPU busy |
|---|---:|---:|---:|---:|
| 单流 Wi-Fi→LAN | 778.53 | 762.53 | -2.06% | 3.55% / 4.25% |
| 单流 LAN→Wi-Fi | 891.84 | 896.99 | +0.58% | 3.79% / 4.31% |
| 四流 Wi-Fi→LAN | 758.04 | 770.10 | +1.59% | 3.93% / 4.50% |
| 四流 LAN→Wi-Fi | 930.51 | 931.05 | +0.06% | 7.47% / 6.11% |

四项 opt10 的整体平均 softirq 为 1.41%、2.38%、1.44%、2.70%，各 CPU
窗口覆盖 29.63–30.70 秒，频率保持 1008 MHz。TCP 重传分别为 0、867、0、
3531。本轮单次窗口的吞吐与 opt9 接近，CPU 继续保持较低占用；相对于
opt2 的明显 CPU 收益此前已在 opt6 出现，不归因于本轮组播内核接口。

UDP 按本轮 TCP 最低吞吐的 70% 取整，目标为 533 Mbit/s：Wi-Fi→LAN
接收 533.01 Mbit/s、丢包 0%；LAN→Wi-Fi 接收 532.81 Mbit/s、丢包
0.03176%。本轮最高 thermal zone 温度 71°C，最小 MemAvailable
13076 KiB，未重新运行 600 秒持续负载；不能将此温度与 opt9 长时间满载
的 83°C 作同条件对比。

两方向四流期间均保存两份 live ECM 快照。Wi-Fi→LAN connection 14–17
及 LAN→Wi-Fi connection 20–23 都为 `is_routed=0`、`direction=3`、
`accel_mode=2`。前者每条累计转发字节增加 70.7–82.0 MB，后者增加
60.2–61.8 MB；slow_path_packets 保持 3–4，driver fail、NACK 和 no-action
均为 0。结合吞吐和 CPU，确认本轮数据确实经 NSS 桥接加速。

测试期间临时使用 2.4 GHz STA 回程维持电脑联网，5 GHz AP 用于本地测试。
结束后逐字恢复 2.4 GHz HE40 AP＋5 GHz VHT80 STA，无线文件 SHA256 仍为
`7956835d0821810fda9dbd0345ab5612177aec62b8cf8702312690fd5136a6d1`；
路由器默认回程为 phy1-sta0，公网 ping 3/3，电脑有线管理 ping 3/3、公网
ping 2/2。电脑重新连接原上游 Wi-Fi，测试 namespace、两端 iperf 服务和
临时 ECM 节点已移除，NSS 最终为 `enabled=1 ready=1 error=0`。

配置备份和 opt9/opt10 两份镜像保存在桌面
`Redmi_AX3000_NSS_刷入对比_20261010/`。本轮原始 iperf JSON、CPU 采样、
测前测后状态仍在既有 `throughput/` 目录，前缀为
`5g-he160-nss-lan-opt10`；汇总为 `cpu-5g-he160-nss-lan-opt10.json`。
Live 快照在 `Redmi_AX3000_NSS_继续开发_20261010/`，文件前缀为
`opt10-he160-single-live`（实际捕获 Wi-Fi→LAN 四流）和
`opt10-he160-reverse-live`（LAN→Wi-Fi 四流）。

## opt11 刷入与同条件对照

opt11 为 `r0-nsslan20261010opt11-fe7e690dcd`，factory UBI SHA256 为
`d2166016ba6db31ac71d69035aa29e3c7efd6d0307fa602e867bbc3adf8e2059`。
设备 ECM 与 ath11k 哈希均与镜像匹配。保留当前无线文件 SHA256
`28a1e08fe2338f7b17a3e45eda14fe81ef0b9b78e69917f4f1f20fb41f959edc`；
该文件与先前 opt10 备份不同，本轮只逐字恢复本轮开始时的当前配置。

仍使用千兆有线 `.127`、隔离 Wi-Fi `.254`，AX/36/HE160/24 dBm，30 秒
测量加 3 秒预热。opt10 直接复用已有记录，不重新刷旧版制造重复数据。

| 测试 | opt10 Mbit/s | opt11-r2 Mbit/s | opt10 / opt11 平均 CPU busy |
|---|---:|---:|---:|
| 单流 Wi-Fi→LAN | 762.53 | 674.95 | 4.25% / 4.10% |
| 单流 LAN→Wi-Fi | 896.99 | 906.72 | 4.31% / 4.32% |
| 四流 Wi-Fi→LAN | 770.10 | 665.78 | 4.50% / 5.15% |
| 四流 LAN→Wi-Fi | 931.05 | 930.54 | 6.11% / 3.49% |

上行本轮低约 11–14%，尚未区分无线环境与版本影响；Linux CPU 不是这轮
吞吐的满载瓶颈。四项 TCP 重传为 0、768、0、3404。UDP 按最低 TCP 的
70% 取 466 Mbit/s，接收 465.99/465.98 Mbit/s，丢包 0%/0.000412%。
两核平均 softirq 为 1.11%、2.27%、1.58%、1.75%，CPU 1008 MHz，最高
温度 68°C，最小 MemAvailable 14460 KiB。未重做 600 秒持续负载。

首次尝试在正式测速前因旧脚本要求公网 ICMP 成功而退出；其配置已恢复。
opt11-r1 的 Wi-Fi→LAN 为 636.96 Mbit/s、CPU 5.85%，随后 LAN→Wi-Fi
由约 900 Mbit/s 停流至 60 秒超时，同期有线 SSH CPU 采样停止，不能视为
通过。保存配置并重刷同一 opt11 镜像后，r2 六项均完成，未复现此次停流；
因此停流仍未定位，不能声称已经修复。r2 手动 live ECM 快照取得过晚，没有
选中测试 tuple，不把这份空快照作为该轮特定连接 NSS ACCEL 的证据。

原始 JSON、CPU、两端容量受限 pcap 在既有 `throughput/` 目录，前缀
`5g-he160-nss-lan-opt11-r1` 和 `5g-he160-nss-lan-opt11-r2`。汇总为
`cpu-5g-he160-nss-lan-opt11-r2.json`。配置备份在桌面
`Redmi_AX3000_NSS_刷入对比_20261010/config-before-opt11-clean.tar.gz`。
测试后恢复 2.4 GHz AP＋5 GHz STA，当前文件哈希逐字一致；电脑重新连接
上游 Wi-Fi，iperf 进程和 Wi-Fi namespace 已移除。

## opt13 刷入后的 HE160 与 DNS 验证

最终设备版本为 `r0-nsslan20261010opt13-fe7e690dcd`，factory UBI 为
17694720 字节，SHA256 为
`f8bb316ed0722a27fa0e7e8274a2cc64c4b11210c47f5a52ce772a9512a3e664`。
镜像包含 0607、ECM 0071–0073、ath11k 999-972 和 dnsmasq 的
`fast_dns_retry` UCI 配置转译，设备模块哈希与最终构建匹配。

本轮 HE160 尝试让电脑直接连接路由器 5 GHz AP 保持 Wi-Fi 联网，只将
有线网卡移到独立 namespace。2.4 GHz STA 回程、5 GHz AX/36/HE160 AP
及公网 TCP DNS 验证完成，但有线端到无线 `.254` 的初始连通检查失败，
第一次尝试尚未运行 iperf。随后改为等待实际两个端点的双向 TCP 确认，
opt13-r2 通过就绪检查并完成四项测试；没有改产品转发配置来迁就检查。
首次立即 ping 失败的原因尚未定位，不能据此声称固件数据面修复。

该尝试后已经逐字恢复本轮原无线文件；恢复 5 GHz STA 时一度持续
reason=15，约十五分钟自行连接。临时 2.4 GHz 回程救援随后也已撤销，
2026-10-11 00:07 再次恢复原 2.4 GHz AP＋5 GHz STA，约六秒连接。
电脑通过自己的上游 Wi-Fi 保持联网，没有要求手机提供测试端点。
新版 DNS 的有线/AP 运行验证见 [DNS 进展](README.md)，仍保留间歇超时
及握手故障记录，未把短时成功当成长期稳定性证明。

opt13-r2 仍为信道 36、AX/HE160、24 dBm、30 秒测量加 3 秒预热，分别
让有线和无线运行客户端/服务器。隔离端点改为有线 `.127`，电脑根命名
空间的 Wi-Fi 为 `.254`；测试期间公网经该 AP 和 2.4 GHz STA 保持在线。
这与 opt10/opt11 隔离 Wi-Fi 的主机布局不同，虽仍通过同一类真实桥接
链路，不能将单次差值全部归因于固件。

| 测试 | opt10 Mbit/s | opt11-r2 Mbit/s | opt13-r2 Mbit/s | opt13 CPU 平均 busy | opt13 CPU 0 / 1 busy |
|---|---:|---:|---:|---:|---:|
| 单流 Wi-Fi→LAN | 762.53 | 674.95 | 744.17 | 5.37% | 6.03% / 4.72% |
| 单流 LAN→Wi-Fi | 896.99 | 906.72 | 915.18 | 5.05% | 7.02% / 3.16% |
| 四流 Wi-Fi→LAN | 770.10 | 665.78 | 727.30 | 5.10% | 6.92% / 3.34% |
| 四流 LAN→Wi-Fi | 931.05 | 930.54 | 929.50 | 6.09% | 10.00% / 2.18% |

四项整体平均 softirq 为 2.02%、1.92%、1.26%、4.36%，CPU 保持 1008 MHz。
各 CPU 窗口覆盖 29.65–30.68 秒，最高温度 58°C，最小 MemAvailable
13592 KiB。TCP 重传为 0、1005、0、3597；本轮没有重新测 UDP 或 600 秒
负载。上行比 opt11 约高 9–10%，仍比 opt10 低约 2–6%；Linux CPU 没有
满载，尚不能声称无线→有线瓶颈已定位或彻底解决。

LAN→Wi-Fi 单流 live ECM connection 75，端口 45202，`is_routed=0`、
`direction=3`、`accel_mode=2`；两份快照中正向累计字节由 3200952141
增至 3561366141，slow_path_packets 保持 3，driver fail、NACK、flush 和
no-action 均为 0。这证明该连接实际使用 NSS，不将同窗口的控制连接
或单次 accelerated_count 当作数据流证据。没有同时取得上行的 live
快照，不能把这份下行统计直接移用于上行。

测速末段 AP 上的 10 次 A 查询全部响应，耗时 34.83–205.71 ms，原始
Fastsh 证据为 r1708；短窗口不代替手机长期 DNS 验收。完成后逐字恢复
原无线文件 SHA256 `28a1e08fe2338f7b17a3e45eda14fe81ef0b9b78e69917f4f1f20fb41f959edc`，
5 GHz 回程约六秒连接；电脑默认路由回到直连上游 Wi-Fi，测试 namespace
和 iperf 服务清理，NSS 仍为 `enabled=1 ready=1 error=0`。

原始 JSON、CPU 每秒日志及汇总在既有桌面 `throughput/`，前缀为
`5g-he160-nss-lan-opt13-r2`，汇总为 `cpu-5g-he160-nss-lan-opt13-r2.json`。
ECM 原始快照及字段摘要在桌面 `Redmi_AX3000_NSS_继续开发_20261010/`，
前缀为 `opt13-r2-he160-live`。配置副本为
`Redmi_AX3000_NSS_刷入对比_20261010/wireless-before-opt13-r2`。

## opt15 刷入后的 HE160 与上行 NSS 验证

版本 `r0-nsslan20261011opt15-fe7e690dcd` 已保留配置刷入。继续使用
opt13-r2 的实际端点布局：电脑 Wi-Fi `.254` 连接 5 GHz AP，独立有线
namespace `.127`；路由器临时以 2.4 GHz STA 提供公网。5 GHz 信道 36、
AX/HE160、24 dBm，TCP 每项 30 秒加 3 秒预热，双向轮换客户端/服务器。

| 测试 | opt13-r2 Mbit/s | opt15-r1 Mbit/s | opt15-r1 CPU 平均 busy |
|---|---:|---:|---:|
| 单流 Wi-Fi→LAN | 744.17 | 773.99 | 4.31% |
| 单流 LAN→Wi-Fi | 915.18 | 906.92 | 4.15% |
| 四流 Wi-Fi→LAN | 727.30 | 629.15 | 3.34% |
| 四流 LAN→Wi-Fi | 929.50 | 921.67 | 4.74% |

CPU 保持 1008 MHz，最高温度 58°C，最小 MemAvailable 18256 KiB。
整体平均 softirq 为 2.03%、1.85%、0.95%、2.05%；重传为 0、1082、677
及 3802（以对应原始 iperf JSON 为准）。这些单次差值不全归因于固件。
首次上行四流较低，故 opt15-r2 仅复测相同四流上行：706.55 Mbit/s，
重传 0，整体 CPU busy 3.16%、softirq 0.74%，CPU 0/1 为 4.01%/2.35%，
最高 58°C，最小 MemAvailable 24292 KiB。结果存在波动；CPU 没有满载，
无线→有线瓶颈仍未确定，没有把此次复测当作已解决带宽问题的证明。

复测传输期间，真实四条 TCP 数据连接 74–77 对应
`.254`→`.127:45201`，`is_routed=0`、`direction=3`、`accel_mode=2`。
连续三份快照的累计正向字节增加，slow_path_packets 分别保持 3、3、4、3，
driver_fail_total、ae_nack_total、flush_happened_total 和 no_action_seen_total
均为 0。这证实本轮四流上行实际通过 NSS，而非仅确认 READY。
首次手动快照在传输结束后没有选中测量 tuple，未用于此结论；ECM
字符设备在 /tmp 因 nodev 无法读取，改用临时 /dev 节点并在观察后删除。

原始吞吐 JSON、CPU 每秒样本和汇总仍在既有桌面 `throughput/`，前缀
`5g-he160-nss-lan-opt15-r1`、`5g-he160-nss-lan-opt15-r2`。ECM 快照和摘要
在桌面 `Redmi_AX3000_NSS_opt15_20261011/p4-repeat-ecm-*`，Fastsh 为
r1875/r1880/r1881。复测仅选择四流 TCP 上行，不重新解释为四项完整套件。

## opt16：peer key 生命周期修正后的 HE160 对照

`r0-nsslan20261011opt16-fe7e690dcd` 已保留配置刷入，设备 ath11k 模块
SHA256 为 `f4e9f5a876b8fd1ea9108f4bb7435d0d3c2e0dbbcf43d10c0ac9bf63eccc5cc7`，
与镜像 root staging 相同。此次更改为 key operation 宿主引用和删除
状态保护，未改 bulk 数据路径。继续使用 opt15-r1 的真实端点布局、
AX/36/HE160/24 dBm、TCP 每项 30 秒加 3 秒预热（r1962）。

| 测试 | opt15-r1 Mbit/s | opt16-r1 Mbit/s | opt16 CPU 平均 busy | opt16 softirq |
|---|---:|---:|---:|---:|
| Wi-Fi→LAN，P1 | 773.99 | 779.70 | 3.19% | 1.17% |
| LAN→Wi-Fi，P1 | 906.92 | 901.94 | 4.54% | 2.68% |
| Wi-Fi→LAN，P4 | 629.15 | 694.90 | 2.56% | 0.83% |
| LAN→Wi-Fi，P4 | 921.67 | 930.25 | 4.20% | 1.92% |

上行四流也需与 opt15-r2 的 706.55 Mbit/s 一并比较，不能仅选较低的
opt15-r1 宣称带宽修复。opt16 重传依次为 0、1076、0、3657，频率
始终 1008 MHz，最高 59°C、最低 MemAvailable 15384 KiB；平均 CPU
与最忙核心的样本均未达到饱和，吞吐波动不能归于 CPU 满载。

NSS IPv4 special RX bytes 从 148164 增至 14157103230，RX/TX packet
从 375 增至 9769906，四个 IPv4 RX queue drop 保持 0。该证据确认
窗口内有大量 NSS 转发；不从这些 SOC 总计推导每条连接的加速状态
或证明所有 Wi-Fi drop 计数为零。LAN→Wi-Fi P4 的同一时间窗口中，
20/20 UDP/TCP A/AAAA DNS 查询回应且 RCODE 全为 0（r1963），原始
JSON 保存于桌面 opt16 目录的 `he160-load-dns.jsonl`。

吞吐 JSON、每秒 CPU 和 NSS 前后快照仍在桌面既有 `throughput/`，
前缀 `5g-he160-nss-lan-opt16-r1`；CPU 汇总为
`cpu-5g-he160-nss-lan-opt16-r1.json`。测试完成后逐字恢复原无线配置，
2.4 GHz AP＋5 GHz STA 与电脑上游 Wi-Fi、临时 namespace/iperf 均已恢复
或清理。普通 STA 回程下与电脑上游 STA 的自然 ARP 仍不通（r1961），
本次没有用静态邻居掩盖该结果；不能宣称已解决广播或长期握手问题。

## 5 GHz STA 下行：同端点本机接收与有线 NAT 转发

按更新后的目标，验收转为实际 5 GHz STA 回程下行，不能用上节的
5 GHz AP 下行峰值替代。r1975 保留原 2.4 GHz AP＋5 GHz STA，电脑
上游 Wi-Fi 作为同一个 iperf3 发送端，分别测试路由器本机接收、有线
namespace .127 经 NAT 接收，再重复本机接收；P1/P4 各一组，每项
20 秒加 3 秒预热。为隔离已知 STA↔STA 自然 ARP 不通，仅此窗口使用
双侧准确临时邻居，测后删除，未将其当作产品修复。

| 同上游两段无线链路 | 本机前 / 后 Mbit/s | LAN 转发 Mbit/s | LAN CPU 平均 busy |
|---|---:|---:|---:|
| P1 | 15.31 / 11.95 | 14.42 | 4.77% |
| P4 | 15.47 / 12.64 | 9.23 | 8.61% |

电脑上游信号约 -80/-81 dBm，该发送端是限制之一，不能把绝对数值
当作路由器下行极限。r1976 捕获实际逆向 NAT 数据连接 2057–2060：
三次快照均 ACCEL=2、to_data_total 增长，slow_path_packets 保持
3/3/4/4，driver fail/NACK/flush/no_action 为 0；低速不是由“没有
启用 NSS”这一简单假设解释。

为排除该弱链路，r1980 验证电脑可在已关联的信道 149 并发一个
VHT80 AP，原 managed Wi-Fi 和公网默认路由仍保留。r1985 临时让
路由器 5 GHz STA 接入近距离电脑 AP（server 192.168.88.1，STA
.88.2），电脑上游 Wi-Fi 继续联网；有线 namespace .127 为独立
NAT 接收端。此窗口没有静态邻居，实际自然 ARP/TCP 连接成功。

| 近距离单无线跳，VHT80 | 本机前 / 后 Mbit/s | LAN 转发 Mbit/s | 本机 CPU 前 / 后 | LAN CPU |
|---|---:|---:|---:|---:|
| P1 | 324.73 / 347.87 | 374.71 | 56.23% / 64.95% | 4.14% |
| P4 | 359.09 / 365.73 | 317.36 | 68.28% / 68.24% | 5.89% |

P4 的实际 NAT 连接 2415–2418 再获三次硬件转发快照（r1986）：
均 ACCEL=2，slow_path_packets 保持 3，reverse to_data_total 持续
增长，无 driver fail/NACK/flush/no_action。P4 IPv4 sequence/ACK
异常及 RX queue drop 未增长，N2H payload alloc fail 保持 16；
这些特定计数不代表所有硬件内部丢包均为零。

P4 发送端 AP 的样本 TX rate 从 702 降至 585.1 Mbit/s、重试计数
增长，不能仅按本机平均值与 LAN 的 12.4% 差值归因固件。路由器
STA 省电已经 off，NSS core 实际 clk_summary 为 850 MHz（r1989），
没有低 NSS idle clock 或启用 STA 省电的现成证据可供盲调。

两次窗口均没有刷入另一个固件，也没有改 bulk 数据代码。自然 ARP
在受控 AP 成功而上游两 STA 不通，把排查范围收敛到上游互转或
特定互操作条件，但不能据此认定“上游隔离”或排除所有 NSS 条件。
当前已证明这条 VHT80 STA→有线 NAT 下行可以达到 317–375 Mbit/s、
低 CPU 并真实 NSS 加速；没有证明中继优化和间歇握手问题已全部完成。

原始 JSON、CPU、NSS/两端 Wi-Fi 样本在桌面 opt16 目录：
`sta-downlink-ab-a-opt16-r1/` 和 `sta-controlled-one-hop-opt16-r3/`。
受控窗口的网络/无线原文件在 `sta-controlled-one-hop-opt16-r3-setup/`
以 0600 保存；r1988 确认两份文件哈希逐字恢复、默认路由仍为电脑
wlan0，上游 STA 恢复、namespace、临时 AP/NAT 与邻居均已清理。
额外 DNS 观察启动时 AP 客户端已恢复，未取得满载重叠窗口，不声称完成
了满载 DNS 验证。两轮均恢复原无线文件、上游 Wi-Fi 默认路由及电脑
网络管理配置，wired NSS 最终 `enabled=1 ready=1 error=0`。

## opt17/opt18：密钥 ACK 事务与 VHT SU/STBC 速率解析

这轮源码修改仅针对 NSS 密钥控制路径与接收速率统计，未修改无线布局、
功率、ECM 加速策略或 bulk 数据转发参数。opt17 使用 mac80211 release 14；
修正运行发现的完成等待错误后的 opt18 候选为 release 15。

`999-982` 在 WMI key 操作期间保留原 NSS peer state 引用，每次 VDEV cipher、
peer security 与 authorize 提交都在 base_lock 内核对原 peer 实例，等待
私有 ACK 和 cancel 排空在锁外进行；三项按顺序确认成功后才允许最后的
宿主 key publication。NACK、超时、错误 peer payload、实例复用和分配失败
不会继续下一项。超时边界 cancel 排空期间到达的有效 ACK 仍会被采纳。

已经尝试 WMI 安装后的失败无法用一个 errno 撤销硬件状态，尤其同槽旧密钥
的硬件 TX/RX PN 无法从现有接口完整读取。失败路径因此只删除匹配的原
NSS peer，设置受影响 VDEV 的 key_failed gate，并异步请求 cfg80211_stop_iface；
没有引入全硬件 reset 后重装旧密钥的回滚。host payload、QoS-null/WMI 数据帧、
RX delivery/MCBC exception 和 AP VLAN parent/UP 都受该 gate 约束；断开所需
管理帧仍可发送。gate 只在新的 NSS VDEV 分配、注册、配置成功后解除。
already-created、BSS DOWN、重新关联或 VDEV UP 都不能把它清除。

这个停止请求本身不会关闭 netdev 或自动重建 VDEV，失败后需要重建无线接口。
也不能把 host gate 宣称为在置位瞬间撤销 NSS 内部已有加速流或在途包；接口
停止与 peer DELETE 有各自异步完成边界。无 NSS 编译 stub 和运行关闭 NSS
均保持原有路径，不触发该停止动作。

`999-983` 修正 host monitor VHT SIG-A SU 解析：先从 NSTS/Partial AID 的
12 位复合字段取出 SU 低 3 位，再做 STBC 空间流换算。此前 Partial AID=1、
NSTS 编码=1、STBC=1 会算出 NSS=5；现在正确为 NSS=1。只改 group 0/63
的 SU 分支，保留现有 MU 分支。字段划分见
[Qualcomm fw-api VHT SIG-A 定义](https://android.googlesource.com/kernel/google-modules/wlan/qcom/wcn6740/wlan/+/d1efc457d0c4cebc1aef15c50994473cad1fa0cf/fw-api/hw/qca6750/v1/vht_sig_a_info.h)。
该问题影响速率统计发布，不能单凭异常 nss=5 日志推导实际硬件转发失效。

新的实际 C 函数测试覆盖三项 ACK/NACK/超时、deadline ACK drain、同 ID
实例复用、分配/CREATE 失败、gate 重建清除、编译关闭 NSS stub、QoS-null
绕行与 AP VLAN UP。VHT 测试执行实际 TLV 分支，遍历 512 个 Partial AID、
group 0/63、无 STBC NSS 1..8、STBC NSS 1..4。ASAN/UBSAN 及相关 peer/MCBC/
DMA/IRQ/control 回归通过（r2014；IRQ 读取受 root 文件权限限制，提权重跑
r2015 通过）。Debian AArch64 clean/compile 通过（r2013）。上述是源码及
编译证据，刷入与吞吐结果另记录，不能代替长期握手故障验收。

opt17 实际刷入后，两个 radio 的 VDEV CONFIGURE 均收到 ACK，但第一次
key_config 返回 -ETIMEDOUT，AP 停止、STA 安装 PTK 失败。该候选已经回退
到 opt16，2.4 GHz AP、5 GHz 上联与默认路由恢复；无线/网络/DHCP/防火墙
四份文件及 ath11k 模块哈希均与原 opt16 相同，没有重复刷入 opt17。

在 opt16 上加载一次临时 VDEV ACK 探针，仅重复当前 CCMP security 值 6，
不安装/删除密钥：if=32、type=10003、cmd=15、len=8、cookie=9 提交成功，
真实 callback 收到 response=0/error=0，私有 context 正确。wait 返回后
completion_done 为 0、result 为 0。探针随后卸载、临时模块删除，上联保留。
这揭示新 key helper 丢弃 wait_for_completion_timeout 返回值的错误：正常
成功等待会消费 complete() 的 done 计数，不能再只靠 completion_done 判断
成功。opt18 的两个 helper 保留等待返回值；只有等待确实超时，才用 cancel
排空后的完成标记接纳边界 ACK。回归 shim 也改为消费正常完成计数，并使用
实际 VDEV CONFIGURE/CMD type 10000/10003 和 NOTIFY=5；修正后 ACK/NACK、
超时、边界回复与无 NSS 编译测试通过。此问题属于本轮引入并修正的等待逻辑，
不能据此宣称此前普通版也发生的上游握手问题已经定位。

opt18 镜像 `32b3955e645d9880616a99edf26ee0d2da6d5a8d87fd0074c3c0c6272cf3821e`
已保留配置刷入（r2041），设备 ath11k SHA256
`a60526ce7fa03c4e217ae135fdaf116888a8300baea87f11eb9766ce329001e0`
与打包 root staging 相同。两 radio AP/STA key 安装及 5 GHz TP-LINK_3A
握手成功，NSS LAN ready/error=0。两轮受控 AP 切换及恢复原上游共五次
STA 连接均完成；日志仅有测试主动触发的 reason=3，没有 reason=15、
NSS key error、Oops 或 invalid NSS RX rate 告警。这个窗口不替代长期验收。

按 opt16 近距离单无线跳的方法复测 VHT80 STA 下行，电脑原上游 Wi-Fi
保持连接，P1/P4 每项 20 秒加 3 秒预热，使用自然 ARP，没有静态邻居。

| opt18 窗口 | 本机前 / 后 Mbit/s | LAN NAT Mbit/s | 本机 CPU 前 / 后 | LAN CPU / softirq |
|---|---:|---:|---:|---:|
| r1 P1 | 363.18 / 368.73 | 373.56 | 71.31% / 70.09% | 7.90% / 5.63% |
| r1 P4 | 533.14 / 475.47 | 437.62 | 92.90% / 85.80% | 4.91% / 1.69% |
| r2 P1 | 370.50 / 291.49 | 462.00 | 70.24% / 56.47% | 5.02% / 2.41% |
| r2 P4 | 357.35 / 421.00 | 250.04 | 64.86% / 74.11% | 5.59% / 2.10% |

r2 的同步 P4 观察在实际负载开始后约 2.3、4.4、6.6 秒取样：实际 NAT
数据连接 25–28 均 ACCEL=2，to_data_total 连续增长，slow_path_packets
保持 3/3/3/4，driver fail/NACK/flush/no_action 均为 0。r1 的独立观察
启动太晚，捕获的是结束后的 ACCEL=0 与已固定字节数，不能当作活动期间
未加速的证据。两轮原始 CPU/iperf/NSS/两端 Wi-Fi 与 r2 的活动连接快照
均保存在桌面 opt18 目录 `sta-controlled-one-hop-opt18-r1/`、
`sta-controlled-one-hop-opt18-r2/`，完整 CPU 计算为各自 `cpu-comparison.json`。

CPU 1008 MHz，最低 MemAvailable 14148 KiB，最高 65°C。本机接收的主要
CPU 时间在 softirq（r1 P4 52–59%）；iperf 接收端与本机 TCP 路径仍消耗
CPU。真正的无线到有线 NAT 转发保持约 5–8% 总 CPU，已实测走 NSS，不能
把本机 iperf 的高 CPU 当作 NAT 转发未卸载。

两轮及 opt16 之间没有足以证明单一固件带宽提升的固定空口条件：r1 P4
发送 AP 两次样本均 866.7 Mbit/s/NSS2；r2 P4 开始样本 433.3/NSS1、结束
866.7/NSS2，且本机前后结果也变化。保留 250–462 Mbit/s 的完整范围，
不择取峰值宣称中继带宽问题全已修复。

r2047 结束检查确认原无线/网络/DHCP/防火墙四份哈希逐字恢复，布局仍为
2.4 GHz AP＋5 GHz STA，STA 省电 off，PC 上游 wlan0 默认路由保留，临时
namespace/AP/ECM 设备与诊断模块清理。r2048 另按实时 WWAN 地址复查原
TP-LINK 上游两 STA 自然互通：双方仍 100% ping 丢失、ARP INCOMPLETE。
近距离受控 AP 的自然 ARP/转发通过不能代替这个互操作问题的修复，后续
应先用两侧 ARP/802.11 包头区分上游未转发与当前 RX 路径丢弃，避免盲改
NSS 时钟、PN 检查或添加永久邻居。

后续两侧 AF_PACKET ARP 观察在同一 12 秒窗口各看到三次本端发出的
who-has（PC .15.22、实时 router .15.11），双方均未收到对端请求或回复。
短时新增 PC software monitor，保留原 managed Wi-Fi、信道 149/80 MHz：
接收正对照中 PC 与 router ping 网关均成功，monitor 可看到 AP→PC 的数据
及 PC 本端 TX，但连已成功的 router↔网关单播也没有捕获。因此这个并发
monitor 缺少第三方客户端帧的可见性，不能用“没抓到广播”判定上游没有
转发、开启隔离，或判定 router 在空口未发送。没有改变上游配置、关闭
PN 校验或加入永久 ARP。证据在桌面 opt18 的 `upstream-arp-r1/`、
`upstream-arp-with-monitor-r3/`、`upstream-air-broadcast-r5/`。监控接口、
ARP 观察进程与临时二进制均已退出/移除，PC 原 Wi-Fi 保持连接。
