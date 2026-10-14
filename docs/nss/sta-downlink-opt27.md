# opt27：EAP 路由失败回滚与原回程握手取证

继续补齐 NSS 和排查 5 GHz STA 下行。设备已保留配置安装
`r0-nsslan-opt27-fe7e690dcd`；本轮修复一个确定的启动失败清理缺口，
尚未证明原回程带宽已修复。

## 源码修复与实际 C 验证

`999-997` 修复 `ath11k_mac_op_start()`：NSS EAP 路由 ADD 排队成功后，
monitor-status 或 idle-PS 配置仍可失败。mac80211 的 `iface.c` 在
`drv_start()` 失败后直接进入 `err_del_bss`，跳过 `drv_stop()`，因此不能
依赖正常 stop 中的 DEL 清理该次 ADD。

现在用本次调用的局部标志记录成功排队的 ADD，错误出口在 conf_mutex
持锁期间尝试 DEL，并保留最初的失败码。ADD 失败、ADD 之前的失败、
禁用 NSS、非法 state 和 factory 模式不会撤销其他调用的路由。正常
启动流程与原有默认参数相同。WMI 发送成功只证明排队，DEL 没有执行
ACK，不能据此声称硬件路由残留已被读回排除。

新增 `test-nss-eap-route.py` 执行实际 start 与 packet-filter C 函数，
覆盖全部失败点、DEL 再次失败、状态/锁/发布、恢复与 NSS-disabled
分支，启用 ASan/UBSan。opt26 原 C 在漏 DEL 断言失败（r2495），修复
草稿及干净 prepared C 通过（r2495/r2500）。key、key ACK、TX gate
三组相关 C 回归通过。key ACK 测试此前假定 `#else` 紧邻 TX stub，
新增 REO stubs 后该提取器失效；已改为定位实际 TX 定义，NSS-disabled
key stubs 的实际编译/运行重新通过（r2501）。CI 已接入新回归。

根仓库和构建树补丁逐字一致，`patch --fuzz=0` 还原与草稿逐字一致；
干净 prepared `mac.c` 同样一致。mac80211 release24、NSS driver
release30，干净 AArch64 编译/严格 modpost（r2498）与完整镜像构建
（r2502）通过。factory UBI SHA256：
`de81d6333603c060c022168de2c30a4c25d2cf8c9e79340dbe11dbe0a925000a`。
ath11k：`211c822e7946c77884a01a11bc1249829c32633e0520e21b6b9e0ef242c13114`；
AHB/PCI/NSS driver 与 opt26 相同。

## opt26 原回程握手捕获

这些观测发生在刷入 opt27 之前，没有将其记为 opt27 修复效果。
临时有界 AF_PACKET collector 同时捕获 STA 入站/出站 EAPOL，并跟随
日志；控制命令通过设备现有 ubus 接口。采集结束恢复日志等级和
ext_rx_stats，六份配置哈希一致，原 BSSID/DHCP 正常。

| 操作 | 统计设置 | 捕获 | M1→M2 | M3→M4 |
|---|---:|---|---:|---:|
| REASSOCIATE（r2486） | 0 | M1/M2/M3/M4 | 3.605 ms | 3.771 ms |
| radio1 down/up（r2488） | 1 | M1/M2/M3/M4 | 3.180 ms | 5.070 ms |

两次 supplicant 均报告 COMPLETED，没有重现旧 4WAY_HANDSHAKE_TIMEOUT。
这是 AF_PACKET 时戳和 key-info 分类，没有验证 MIC 密码学或空口 ACK。
第一份电脑并发 monitor 没有任何 packet，不能支持空口结论；增加
otherbss/control 后第二份只见上游 beacon/probe response，信号约
−81…−82 dBm，没有抓到目标握手，也不能用其缺失来推断 AP 没发送。

源码表明 ext_rx_stats 改动独立 monitor-status 选表，不直接改 CCE
路由或数据 RX TLV offsets；它增加 PPDU 统计、NAPI/锁负担，尚无
运行证据证明这种负担造成旧握手超时。另有 WMI install-key 完成
事件未匹配当前 MAC/key_idx/key_flags 的迟到回复风险，尚未修复；
本次两次成功握手也没有证明不存在该交错。

## 一次空口的公网下行观察

关闭电脑自身上游 Wi-Fi，使数据路径仅为公网→上游 AP→路由器 STA，
再经有线交给电脑；避免此前同一上游 AP 两个 STA 的两次空口传输。
每段下载 4 MiB。第一次试验路由器与 LAN 解析到不同地址，第二次
发现地址仍变化并中止，保留全部原始证据，不混入固定地址结果。

r2505 只对 wget 进程的目标 hostname 做 DNS 地址固定，URL、TLS SNI
及证书校验仍正常，不改 resolver/hosts。三段均确认连接
`162.159.140.220:443`，结果如下：

| 端点 | 含建立连接的吞吐 | 整体 CPU busy |
|---|---:|---:|
| router-before | 4.571 Mbit/s | 7.845% |
| LAN-middle | 9.073 Mbit/s | 未采齐完整区间 |
| router-after | 2.903 Mbit/s | 5.660% |

LAN body 区间为 12.219 Mbit/s。TLS client、建立连接耗时及时间变化
仍不同，不将此表认定为 NSS/host 性能 A/B 或 NSS 带宽收益。该次
真实 NAT tuple 的 ECM 记录单独保留；固定地址组同样见 ACCEL=2、
下行313859字节和slow_path=4，单份有效snapshot不足以证明整个
下载期间始终加速。结果
没有显示 router 本机 CPU 饱和，仍不能区分上游/WAN/RF 全部限制。

## 交付与剩余项

镜像、opt26 回退、配置备份和哈希清单保存在桌面
`Redmi_AX3000_NSS_opt27`。归档时发现 opt26 的 sha256sums 是旧 build
快照，已保留为 `sha256sums.stale-build-snapshot` 并重新生成实际
文件名/哈希；当前 build 的九项和 opt26/27 交付清单均逐项校验。
四份 profiles image 的实际 hash/size 与元数据一致。

r2509 只发送一次 sysupgrade，新版本启动已确认；四个加载模块哈希
与交付镜像一致，六份原配置哈希逐字一致。有线 NSS ready=1、
allocation_uncertain=0，原 BSSID 和 DHCP 恢复，四项 aging 仍为40000。
升级前电脑独立 Wi-Fi 的 UDP/TCP DNS 和 HTTPS 200 已通过。

r2510 完成 opt27 的 radio1 down/up、ext统计1握手捕获：完整M1–M4，
M1→M2 3.939ms、M3→M4 6.304ms，supplicant COMPLETED，DHCP正常。
结束恢复 ext统计0、日志INFO/无timestamp，六份原配置仍一致。
最终有线 NSS ready1/error0/uncertain0，PROJECT0、aging四项40000，
QCN/内部REO UPDATE success分别74/74、53/53，type18无待处理任务。
启动日志包含 SSDK port0 netdev通知错误，原始日志保留；本轮未修改
SSDK，该告警没有阻止当前ready及收发，不以此宣称告警根因已解决。

电脑恢复本轮开始时Wi-Fi软关闭状态，默认经eno1/路由器联网；
最终LAN的UDP/TCP DNS均rcode0、2个answer，HTTPS200/16384字节通过。
临时observer/monitor已清除；本次及此前两组握手抓包、解析结果和
诊断源码保留，不能把这三次成功当作长期重连稳定性证明。

待完成：原回程间歇握手失败的完整失败
捕获与根因；WMI key 迟到完成匹配；稳定且能排除 RF/WAN 干扰的
原回程带宽结论。其他 NSS 功能缺口仍见 README 功能表，本轮没有
宣称全部 NSS 功能完成。
