# opt37：原生 ECM AP 组播转发门与空快照清理

当前已保留配置刷入 `r0-nsslan-opt37-fe7e690dcd`，ECM release7，
ath11k release33、NSS driver release32。完整 NSS 补齐目标继续；
自动 MDB 同步、ME 发布与完整数据回退尚未完成。

## 实际运行路径与本次改动

本 profile 固定 `ECM_MCAST_LINUX_SNOOPER_SUPPORT=y`。IPv4/IPv6 MFC
事件直接调用 `ecm_interface_multicast_invalidate()`，bridge 的旧 MCS
callback 不登记；旧增量 UPDATE 的调用者处于未编译的分支中。
之前把旧 UPDATE 的竞态当作本机构建阻塞的判断不准确。暂存区的旧
UPDATE worker/driver 改动已经撤回，没有进入本次源码补丁或镜像。
当前成员变化使用整体失效、撤销及重新 CREATE 的路径。

[0074 补丁](../../package/kernel/qca-nss-ecm/patches/0074-ecm-keep-complete-AP-multicast-fanout-on-host.patch)
在实际 IPv4/IPv6 CREATE 中增加两个检查：取得输出快照后扫描全部
层级；提交前重新取得当前输出快照。出现 AP/AP_VLAN 时拒绝整条硬件
fanout，保留主机策略处理，避免仅删除一个输出而建立不完整规则。
有线及 STATION 输出继续允许；失踪设备、缺失层级或空 fanout 拒绝。
拒绝分支释放快照、消息并通过原 `accel_abort()` 清理 pending owner。

每个设备由 `dev_get_by_index()`/`dev_put()` 持有引用，外层 RCU 覆盖
cfg80211 注销的同步。当前 mac80211 wdev 嵌在 netdev 私有区；Linux
6.12 与 backports6.18 的公开前缀均为 wiphy 指针、iftype，AArch64
iftype 偏移8，AP/AP_VLAN枚举均3/4。此次仅读取该前缀。
类型快照不能替代类型切换、硬件撤销与在途数据排空；这些仍需在
自动 ME 发布阶段完整处理。

审查另发现 DB 已设置但全部层级为空时，`get_and_ref_all()` 返回0
却仍返回两块已分配快照。本次 wrapper 和 IPv4/IPv6 CREATE 均初始化
输出指针，在此返回路径释放已取得的快照，避免泄漏。

## 源码及构建证据

[test-nss-ecm-ap-fanout.py](../../scripts/tests/test-nss-ecm-ap-fanout.py)
执行实际 guard 与原生 MFC callback，使用实际 DB 常量及 inline 布局
helper；覆盖全部16×9位置的 AP/AP_VLAN、普通有线/STA、设备消失、
中间层缺失、非法边界、无快照及返回0但仍拥有快照的情况。
引用平衡和输入不修改检查通过，ASan/UBSan及严格主机编译通过。
测试不执行完整 CREATE；pending 清理仍由既有实际 `accel_abort()`
回归及拒绝分支源码检查提供证据，不扩张为所有硬件路径的证明。

既有 IPv4/IPv6 ECM epoch、stats、CREATE/DESTROY、MFC 输出和入口 MAC
实际函数回归通过。CI 已接入新测试。clean prepare 后三个 ECM 文件与
编辑源逐字节一致。最终完整构建为 Fastsh `r2861`，新 ECM 模块含两份
`ecm_nss_common_multicast_fanout_allowed` 及 IPv4/IPv6 CREATE 符号；
其余七个验收模块与 opt36 哈希一致。早先构建产物不用于本次交付。

factory UBI SHA256：
`00adb7a264d0cba7c6567f9a467c8e4b29d8b54f8027e7593b87edd901aca125`。
ECM模块SHA256：
`2684ca800281167a82ec2623d306cb6b96c00abac722d17b3af7396a68c62fbb`。
四种镜像/profile和 opt36 回退镜像均校验通过。

## 保留配置刷入与本机联网

刷前本机 Wi-Fi 实际为关闭。保存此状态后临时启用已有上游连接，
使用自有 metric47 与代理运行出口 wlan0，普通 HTTPS200、来源
192.168.15.22，再备份配置、校验上传镜像及 `sysupgrade -T`。
只发送一次 sysupgrade（`r2868`），SSH246后观察启动，不重复刷入。

首轮 `r2869`：新版本、八模块、六配置hash、NSS READY及原STA/DHCP
均通过；绑定 eno1 的16MiB TLS成功，但UDP DNS超时，验收因此失败。
该失败JSON保留。稍后 `r2870` 同一验收全部通过：UDP/TCP DNS、
20/20网关、16MiB实收4.753秒、28.240Mbit/s，网卡错误、丢包、
carrier错误和碰撞增量均0。此速率是该次实际回程下载，不表示千兆WAN
或原回程带宽目标已完成。先前 opt36 的DNS间歇异常证据继续保留。

有线链路重启时 NetworkManager 清除了自有临时 metric48；删除备用
metric47后恢复主出口检查失败（`r2871`）。`r2872`只重新添加原自有
metric48，保留NM原配置及metric700；`r2873`恢复代理eno1、刷新连接，
普通 HTTPS200，再恢复刷前 Wi-Fi关闭，纯有线普通HTTPS仍200。

## 实际 NSS 连接证据与范围

首次 NSS 流量取证 `r2874` 已收到16MiB，但固定1秒采样未捕获目标
连接；该次TLS响应头在约2秒才到达。不能以此宣称没有加速，也不能
把下载成功单独当作加速证据。失败记录 `flow-8ab8e74e` 保留。

将取证改成子进程在证书校验及第一份HTTP响应头后通知父进程，暂停
body读取并限定接收缓冲，父进程仅取一次活跃连接快照，再继续传输。
`r2875`/`flow-d1c43054` 实收16777216字节，单一tuple
`192.168.1.127:45327 -> 162.159.140.220:443` 为
`nss_v4.ported.accel_mode=2`；六份配置前后相同，自建char节点已删除。
该验证包含暂停和接收窗口约束，其29.081秒/4.615Mbit/s不能用作性能
对照或原回程吞吐结论。

本轮实机证明新镜像加载、配置保留、有线联网及实际 IPv4 NSS NAT
没有被此改动破坏；AP guard 的所有层级语义主要为实际C函数及源码
证据，尚未完成每个AP/bridge固件入口的实机关闭证明。

## 未完成项

自动 MDB worker、完整当前谓词/seq 的 MCU发布、未知/控制/广播数据
回退、NSS bridge/AP_BRIDGE旁路、STA/key/VDEV生命周期及在途撤销、
多STA/IPv6组播实机过滤仍需完成。原回程性能与其他未接通NSS功能
继续保留，不以本轮组播转发门代替完整增强实现。

镜像、回退、源码、配置备份、失败与验收记录位于桌面
`Redmi_AX3000_NSS_opt37`。
