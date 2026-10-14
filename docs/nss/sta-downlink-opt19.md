# opt19：STA 异常接收 TID 与中继下行继续验收

在已运行的 opt18 基础上继续制作，没有重新切换原厂 NSS BIN。原厂
11.4 和当前 12.2 的反汇编用于核对数据路径；当前镜像继续使用 Linux
6.12.108、AArch64、MP12.2、256 MiB Wi-Fi / LOW NSS 内存方案。

## 本轮源码修改

新增 `999-984-ath11k-set-exception-TID-before-QoS-reconstruction.patch`：

- NSS MCBC 异常绕过正常 REO 接收，原调用者只填写 descriptor、
  first/last、continuation 和 MCBC 分类，没有初始化 `rxcb->tid`。
  `ath11k_dp_rx_from_nss()` 现在先从当前硬件 descriptor 读取 TID，
  再进入 MPDU 解封装。普通 VDEV 与 mesh 的 MCBC 入口共用该函数。
- host NULL queue descriptor 分支原来在 MPDU 处理之后才读 TID；
  同一补丁把读取移到 QoS 头重建之前。
- QoS 重建、mac80211 的 `security_idx/seqno_idx` 和 CCMP PN 检查继续
  保留。没有关闭 MCBC exception、PN 检查或重复检查。

这是确定的初始化/顺序缺口。它可能影响具有非零 TID 的加密广播，
不能从源码发现直接认定为原上游 ARP 故障或普通单播带宽的根因。

同步修正了 `verify-reference.py` 的旧“三个启用项”假设。校验现在
核对当前 Config.in 的完整符号集合，并逐项比对当前配置片段的
y/n/未指定值；重新生成清单补上此前已启用的 VLAN 项。功能入口被选中
仍不等于该功能已经完成运行验收。

## 源码和构建证据

新增 `test-nss-mcbc-tid.py` 执行准备源码中的真实 NSS 接收函数、
802.11/QoS 头重建、mac80211 QoS 分类及 CCMP 检查：

- 旧代码在 descriptor TID 与接收 control block 的比较处失败（r2072）。
- 修补后遍历全部 16 个 QoS TID，以不同的旧 control block 值验证重建；
  TID0 和 TID6 的不同 PN 窗口不再混用，重复与倒退 PN 仍拒绝。
- 非 QoS 帧仍使用 security_idx=0、seqno_idx=16。
- 实际 host NULL queue 分支同样遍历 16 个 TID，在重建后核对选择的
  窗口。ASan/UBSan 通过（r2097）。测试不包含真实射频注入或硬件 AES。

原 MCBC、key ACK、key TX gate 回归通过（r2075/r2083）。canonical
clean/prepare 为 r2073，AArch64 模块 compile/modpost 为 r2074，
实际 `ath11k.ko` 确认为 AArch64 ELF。CI 已加入新测试，YAML 解析通过；
这次没有派发 GitHub CI。85 个参考文件哈希、2 个原厂 firmware checksum、
2 处脱敏和 44 项配置比对通过（r2084）。

完整 package/install、target/install 为 r2085，两个步骤退出码均为 0。
buildinfo 为 r2087；独立生成 profiles.json 首次缺少 TOPDIR 而失败，
随后显式设置当前构建根并清除递归 make 环境，元数据和 checksum 完成
（r2088）。没有改动现有 JSON 辅助脚本来扩展环境修复。

## 镜像和首次启动

版本 `r0-nsslan-opt19-fe7e690dcd`，mac80211 release 16。
factory UBI 为 17694720 字节，SHA256：

`04bc8d037667bb4b2975948c336935dc5e4d6ab47e80e8bb05bac312f33f33c4`

上传 SHA256 与本地相符，`sysupgrade -T` 接受镜像（r2090）；
factory UBI 提示没有嵌入 image metadata，不能把该提示当作含板型
metadata 的验收。镜像由当前 Redmi AX3000 profile 构建，另已核对
profiles.json 和 staging 版本。保留配置只发起一次升级（r2091）。

启动观察 r2092/r2093 确认新 revision、NSS core ready=1、有线
ready=1/error=0、原 5 GHz TP-LINK_3A 回程关联与 DHCP 默认路由。设备
ath11k SHA256 为：

`24213086943fc707dbd75c26ba725527e71c8ae37f5f6168ee54ce35287e0d4a`

与最终 root staging 相同。NSS driver、ECM 和 dnsmasq 延续 opt18
的相同二进制；wireless/network/dhcp/firewall/nss-wifi 配置逐字哈希
与刷入前相同。这是一轮软件升级启动证据，不能代替长期握手验收。

配置备份、opt19 镜像、opt18 回退镜像、哈希与状态在桌面
`Redmi_AX3000_NSS_opt19/`。配置归档包含用户网络设置，按 0600 保存，
没有将其加入仓库。

## 实际上游广播与定向 ARP 对照

电脑继续直接连接原上游 Wi-Fi，电脑与路由器分别运行只处理 ARP
包头的探针；按实时接口地址和 MAC 构造三次请求，没有设置永久邻居。
两端同窗口观察八秒，先广播请求，再直接发送到准确的对端 MAC。

| 镜像 / 方向 | 广播收到对端请求 / 回复 | 定向收到对端请求 / 回复 |
|---|---:|---:|
| opt18，路由器接收 | 0 / 0 | 3 / 3 |
| opt18，电脑接收 | 0 / 0 | 3 / 3 |
| opt19，路由器接收 | 0 / 0 | 3 / 4 |
| opt19，电脑接收 | 0 / 0 | 3 / 3 |

opt19 路由器窗口多收到一份回复，不能把它当作三次请求对应的额外
独立验收。两轮均确认同一上游的定向 ARP 可以双向交付，而广播不通。
没有把 TID 修补宣称为此故障已经解决。

r2080/r2094 为探针运行证据；完整包头与设备状态分别在桌面
opt18 的 `upstream-directed-arp-before-opt19/`、opt19 的
`upstream-directed-arp-opt19/`。临时 debug_mask 128 每轮结束恢复为
原值，探针二进制从设备 /tmp 删除。

普通非 IP/ARP 的 ETH_RX→N2H→host 出口已进一步与 stock11.4 对照，
见 [固件记录](firmware-reverse-2026-10-10.md#eth_rx-非-ip--arp-到主机的出口)。
STA MCBC 广播可能先走 type14，这个普通出口不能代替实际异常交付
证据；后续以关闭无线卸载的同上游对照及近距离受控 AP 继续分离条件。

## 关闭 NSS 的同上游对照

临时将无线和有线卸载设为 0 并重启，保留原无线/网络配置。实际参数
`nss_offload=0`，原 TP-LINK 5 GHz WPA 与 DHCP 默认路由在 uptime 56.9 秒
的观察点已成功。此前关闭 NSS 时的 `invalid msdu len`/WPA 认证失败在
这一窗口未复现；不将单次成功扩展为完整 host 回退已经稳定。

同样的三次广播/定向 ARP 测量中，两端广播仍为 0 请求/0 回复，定向
均为 3 请求/3 回复。这证伪了“只有 NSS offload 开启才发生广播故障”
的简单假设，仍不能单独区分上游 AP 与两模式共用的 WLAN 互操作条件。

host 窗口出现持续 `tx completion mismatch ... max_num -3/-1` 告警，
budget 处理需继续核对；没有用这轮作为吞吐对照。完整状态、包头和
日志在桌面 `host-path-startup.log`、`upstream-directed-arp-host-mode/`。
原 NSS 配置已从逐字备份恢复，哈希仍为
`1b09fc1bc66f7be1793b0e6376c427d11da3241082f6df7f5a408ca2fa8959d8`，
随后重启回正常 NSS 模式。

## 受控 AP 与 MSS 阈值

近距离电脑并发 AP 保持 VHT80、信道149，电脑原上游 Wi-Fi 继续联网；
路由器 STA 临时接入该 AP，有线 namespace 为独立 NAT 接收端。每项
20 秒加 3 秒预热，使用自然 ARP，未设置永久邻居。该 AP 的广播和定向
ARP 两端都收到 3 请求/3 回复（r2104），与原上游的条件不同。

| 项目 | 本机前 / 后 Mbit/s | 有线 NAT Mbit/s | NAT 平均 CPU / softirq |
|---|---:|---:|---:|
| P1 | 207.36 / 304.06 | 253.23 | 6.89% / 4.05% |
| P4 | 309.43 / 203.22 | 320.08 | 7.61% / 3.03% |

活动 P4 NAT 连接1246–1249的三份快照均为 ACCEL=2，reverse bytes
增长、slow_path_packets 按连接保持3/4/4/3，driver fail/NACK/flush/no-action为0。
发送AP的前后速率由866.7降至585.0 Mbit/s，不能把单次差值全部归因
本版源码。CPU为1008 MHz，最低MemAvailable16560 KiB，最高65°C。
原始数据在 `sta-controlled-opt19-r1/`，CPU分析为r2110。

随后在同一近距离 AP 会话做 P4 MSS1460→1300→1400→1460 对照
（r2117），吞吐分别为377.57/331.68/400.46/324.06 Mbit/s。
MSS1460首窗的 RX delivered/SG/REO 增量为
751329/751306/1502635；MSS1300为762231/0/762240。
这证明 buffer 阈值使标准包几乎全部跨两个buffer，小MSS转为一个；
没有证明小MSS提升吞吐或SG解释全部带宽波动。数据在
`sta-mss-threshold-opt19-r1/`。

两轮结束均恢复原无线/网络文件、原 5GHz 上联及电脑上游 Wi-Fi；
临时AP/NAT/namespace和测试服务清理。后续候选直接修正buffer容量，
不把小MSS作为产品配置交付。
