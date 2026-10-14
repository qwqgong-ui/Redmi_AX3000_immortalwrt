# opt26：REO aging受控实验与失败断电门禁

继续补齐NSS并排查5GHz下行。当前设备已保留配置升级为
`r0-nsslan-opt26-fe7e690dcd`；本文区分已实现/构建/运行的证据和
尚未完成的性能结论。没有将增加诊断接口当作带宽已经修复。

## 当前配置与原厂证据边界

TID0/3映射BE、使用aging index0。Linux HAL四项初始化值为
`HAL_DEFAULT_REO_TIMEOUT_USEC=(40*1000)`，此前NSS0/1的真机GET均
读回raw40000。原厂采集没有REO寄存器/ADDBA或实际BA window快照，
反汇编尚未闭合NSS写这些寄存器的动态路径，也没有公开aging消息。
所以40000是当前驱动/实测值，不能写成原厂推荐参数。

## 实现与生命周期

`999-996`新增0600的`reo_aging_thresholds`，位于phy的ath11k debugfs。
读取返回epoch和四项raw值；写入九个数：epoch、四项预期旧值、
四项目标值。CAS拒绝过期epoch或已变化的原值，只写确实变化的AC，
读回不匹配返回EIO。目标值限定40000…200000，零值及关闭aging不
接受，开机默认值仍为40000。

持锁顺序为conf_mutex→base_lock→reo_cmd_lock；要求radio ON，
现有REO admission开放，没有crash/QMI fail/unregister/未知所有权。
整个MMIO期间保持cmd锁，关闭门会等待已进入操作完成。接口拒绝
支持suspend的硬件或启用CONFIG_SUSPEND的内核；当前两款硬件及
目标配置不支持该睡眠路径。软件门不是DMA停止证明，四寄存器也
不是硬件原子事务；阈值作用于整个SOC对应AC的所有队列。

审查还发现QMI_FAIL移除路径会先断电而绕过core_stop。现在AHB/PCI
先标记unregister，停止QMI/recovery/deferred工作；失败路径排空
NSS绑定worker并关闭REO门后才power_down。PCI shutdown以及AHB
未注册shutdown同样补闭门，避免与已经进入的MMIO交错。停止函数
为独立AHB/PCI模块导出；首轮modpost缺导出的失败已修复并干净重建。

## 构建与源码验证

新增实际C ASan/UBSan测试覆盖解析、溢出/NUL/额外字段、范围、CAS
冲突、读回失败、OFF/PM/crash/QMI/unregister/epoch/所有权门禁，
并执行实际AHB/PCI failed-remove/shutdown及并发操作关闭。八组
canonical C回归通过，CI已接入新测试。六份patch还原和干净prepared
源码与审核草稿逐字一致，没有fuzz。

mac80211 release23、NSS driver release30；干净AArch64构建及严格
modpost通过（r2444），完整image/package/install/buildinfo通过
（r2455）。factory UBI SHA256：
`e8dd2a6f70c8257cfb842ca19619ad7082939a68cbc8c0e972572a6f352a7beb`。
ath11k：`95d8604d6d3966f801b1bacc5120a78b9fd6c95f0227d0dc62d7dd6ecfc8a0ed`；
AHB：`a418e7514e760104eb8d0ec0a3e731d6bd0b990a2cdc71a1f79362c8a24979b8`；
PCI：`250b3f89029d51b27a7cab5227fa29289024300b7beaf61382bf243f04c991cf`。
NSS driver仍为`2a5172ea10c04938342bf6883143c65cddf3fcd369ee07825cf37073b571fc36`。

## 安装与实验状态

r2461只发送一次sysupgrade，已确认opt26启动。四个加载模块哈希
与镜像一致，五份网络配置加rc.local的六份原哈希一致。无线NSS1、
有线ready1/error0/uncertain0，原5GHz回程正常；新接口epoch1、
四项raw40000读回通过。配置备份、镜像和opt25回退镜像已保存在
桌面Redmi_AX3000_NSS_opt26目录。

实验保持原队列实例，以BE的40000→100000→40000作P1/P4对照，
所有硬件GET要求实际提交时观察到指定profile。controller结束后
按epoch/原值CAS恢复并读回；200秒设备侧guard仅恢复同epoch的
已知100000/40000/40000/40000，避免覆盖恢复后的新实例。近距离
六段测试r2463已完成，19份GET观察到对应profile且generation18
一致。三段P4均为四条ECM ACCEL连接、字节增长、slow_path不增长。

| 连接数 | baseline-before | extended-middle | baseline-after |
|---|---:|---:|---:|
| P1 | 277.25 | 327.92 | 346.68 |
| P4 | 405.94 | 247.66 | 264.58 |

单位Mbit/s。P1中段相对两侧平均1.051，P4为0.739；短时变化不支持
稳定吞吐改善，保留默认40000。late原始序列0/637/1270/1862/2368/
2871/3787，timeout0/6/8/18/19/21/35。hole16bit有跨界，按原始值
及modulo保留，不把差值当准确丢包数。FCS样本仍有7.502%…14.052%
的错误，不等同全部空口或TCP丢包率。CAS及结束读回证明恢复为四项
40000，AP/NAT/namespace和两份原网络配置恢复。

## 原回程实验与握手失败恢复

r2464在原上游重连阶段失败，没有进入aging负载，不能并入性能
数据。日志显示反复4WAY_HANDSHAKE_TIMEOUT。该次wrapper先等待
关联再恢复ext_rx_stats，失败时留下了统计1；已修正为先恢复统计
再等待关联，并在观察超时时保留全部原始输出。r2469关闭统计并
wifi reload后恢复原BSSID和DHCP。此恢复包含多个动作，不能证明
扩展统计单独导致握手失败；长期重连及角色切换根因仍未闭合。

保持恢复后的已有关联，r2470不再重连或开启扩展统计，完成原回程
本机接收的六段实验。generation324贯穿19份有效GET，profile均
与提交时读数一致：

| 连接数 | baseline-before | extended-middle | baseline-after |
|---|---:|---:|---:|
| P1 | 0.699 | 0.699 | 3.425 |
| P4 | 3.915 | 5.033 | 7.760 |

同一上游AP的两个STA路径含两次空口传输。中段相对两侧平均0.339/
0.862，仍不支持将100000设为新默认；原回程低速和波动没有修复。
两组共38份硬件GET有效、每组独立的原实例不变、四项阈值按profile
实际读回；结束均恢复40000。

## 收尾状态

opt26运行，NSS1、PROJECT0、ext_rx_stats0、原回程连接和DHCP恢复，
有线ready1/error0/uncertain0。六份原文件哈希一致。QCN NEED_STATUS
830/830、callback667/667、submitted1694；内部53/53、17/17。
pending/submit_failed/unexpected/tag_mismatch均0。真实type18共5，
注入0、WMI排队5，pending/running/failed均0。本轮交付是安全接口与
断电门禁修复及受控排查证据，未证明全部NSS功能或带宽目标完成。

电脑最终恢复本轮前Wi-Fi软关闭状态，经eno1/192.168.1.1联网；
mark666的LAN UDP/TCP DNS均rcode0、2个answer，HTTPS返回200。
临时AP/NAT/namespace/精确邻居及aging guard清除，四项仍为40000。
诊断脚本和sha256清单已随镜像、回退、配置及原始结果保存到桌面
opt26目录。Git分支与HEAD保持原值，未提交或推送。
