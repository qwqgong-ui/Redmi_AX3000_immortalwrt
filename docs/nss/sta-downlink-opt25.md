# opt25：NSS REO 绑定通知与 aging 读回

继续在opt24上补齐NSS，并追查5GHz STA下行波动。当前设备已保留
配置升级到opt25；源码、实际C测试、完整构建及首轮硬件读回/诊断
恢复通过，下行关联继续验证。本文
明确区分固件反汇编、源码契约、主机故障测试与尚待完成的真机验证。

## 反汇编闭合的 type18 通知

MP12.2的WBM release路径在解析REO code0时进入缺失descriptor
处理；host HAL enum把0命名为DESC_ADDR_ZERO。只有push_reason为
error_detected时该error code有效，此时它表示硬件绑定为零，仍
不等同于宿主尚未分配qdesc。后续反汇编发现routing fall-through也
可进入解析code0的路径，因此type18本身不能证明真实NULLQ。
找到peer并确认sequence-control-valid
后，固件生成type18、len8、NOTIFY5，payload+40为u32 TID，+44为
u16 peer_id。发送后继续release处理，不等待host response；反向
dispatcher的type18项返回unsupported/error99。stock11.4采用同一
通知布局和NOTIFY语义。

本地证据为`current-12.2-ver6.asm`的0x40044980/0x40044d0c接收路径、
0x40043f40构造器、0x4004c780公共header及0x400beab4 dispatcher项；
stock11.4构造器在0x40040600，公共header在0x40046c60。未找到原厂
host对既有PUBLISHED队列的完整实现，不能将本次实现推导写成原厂
源码事实。

## 实现的恢复动作

`999-995`替换原ath11k type18 TODO。NAPI callback只校验、复制
数值、在base_lock内定位并pin当前peer/PUBLISHED queue，进入32槽
有限job池；相同peer/queue/TID合并，满队列拒绝并计数。保存原实例
与epoch，不只保存可复用peer_id供worker重新选择。

worker使用workqueue_aux，持ar->conf_mutex与BA协商/普通peer cleanup
串行，随后核对原peer、queue、retiring及epoch。新DP助手只重发原
paddr和执行时的软件窗口的WMI绑定，不提交HAL UPDATE，不构造SSN
或新DMA。begin/finish沿用opt24的inflight和实例引用合同；发送返回
0只计为wmi_queued，不能写成目标FW已确认执行。

通知没有generation或MAC，因此无法证明一条到达前peer_id已复用的
消息来自哪个旧实例。当前策略对收到时查到并pin住的现有实例操作，
保留其descriptor及协商状态；排队后的替换被再次核对拒绝。

每次worker最多处理32条，持续通知不能无限占用aux工作队列。关闭
先在同一base_lock下禁用admission，再锁外cancel_work_sync，最后
释放未执行job；不依赖注销driver callback来排空已投递的工作。
core stop/pdev destroy/crash在REO关闭、IRQ停止或ar释放之前排空；
reset/teardown、mac注销/销毁及注册失败清理也有幂等关闭。

审查找到过早开门的初始化窗口：NSS START早于peer hash表注册稳定。
已将开门移到core_pdev_create全部成功之后，并在mac_unregister及
mac_register失败清理入口排空。INIT失败时只计数/拒绝通知。

## 接收边界与硬件读取

driver `0214`在nss_core持有实际contiguous/first-frag buf_len时验证
SOC type18：reported payload至少8字节且不超过实际buffer减common
header。检查先于wifili logger和client，不依赖共享rx_msg_buf_len
作为访问证明。只新增host软件拒绝计数，不改变common或通知wire ABI。

GET在成功HAL提交后的同一reo_cmd_lock保护内读取四项aging寄存器，
与原REO MMIO使用相同admission/epoch保护。QCN6122完整offset为
0xa38564/568/56c/570；使用硬件表的`hal_reo1_aging_thresh_ix_0…3`。
结果叫aging_threshold_raw_at_submit；有效标记只说明读动作执行，
不单独证明寄存器单位、目标后续写入或DMA停止。

新增nss_reoq_stats只读数值，以及0600的nss_reoq_rebind诊断写入
`peer_id tid`。注入仅增加injected，真实callback才增加received/
notify；last_job_source区分两者。不能将人工注入冒充真实固件事件。

## 已有验证与待完成项

实际C ASan/UBSan通过：WMI-only操作保留DMA内容/SSN且不发HAL UPDATE，
使用最新窗口，重复/满job池、peer ID复用、epoch变化、send失败/busy、
worker等待conf_mutex时关闭，以及真实nss_setup/core_pdev_create/
mac_unregister初始化失败链。真实硬件寄存器表参与fixture，避免mock
成员名掩盖编译错误。两个canonical patch还原的12文件与审核草稿
逐字一致、无fuzz。新测试已接入CI。

干净AArch64 driver/mac80211构建通过（Fastsh r2366），mac80211
release22、driver release30。七组canonical实际C回归通过；12份
prepared源文件逐字等同草稿。完整镜像流水线r2369成功，SHA256为
`7e032fa5ce03cfd79efc9921e2221eb7a3854e53ebc5973d385a8cbafb2055db`。
stripped ath11k为`78631e90bd7dfe1a918f2c5c6cd87d388aee0441b1257cc8b1aa20b592aaf88d`，
NSS driver为`2a5172ea10c04938342bf6883143c65cddf3fcd369ee07825cf37073b571fc36`。
镜像、opt24回退镜像及升级前配置备份已保存，sysupgrade预检通过。

## 首轮真机结果

设备已升级为`r0-nsslan-opt25-fe7e690dcd`，module哈希与新镜像一致，
五份原配置哈希未变；NSS offload1、PROJECT统计0、有线ready1及
allocation_uncertain/error0，原TP-LINK_3A回程连接正常。两个SOC
admitting1，初始真实received/notify及driver拒绝计数均为0。

原回程TID0/16各做一次显式诊断重绑定。worker的source为injected，
WMI返回成功、pending/running回到0；两次均没有新增REO UPDATE。
前后4份GET均payload100、SUCCESS、当前实例匹配，generation分别
保持1/17、paddr不变。TID0 SSN1041→1611、processed MPDU5151→5721，
没有以输入缺失为由重置SSN或descriptor；这里包含背景流量，不把
SSN普通差值当作丢包率。真实received仍为0，不冒充真实通知触发。

四项实际读取的aging原始值均为40000，与host初始化写值一致。该
读数是在本次GET提交时取得，不证明之后永不改写，也不作为DMA
停止证据。下行/重连中的通知频率、阈值变化及长期稳定性仍待验证。
当前不认定5GHz带宽问题已修复，也没有新增SSR/DMA fence证明。

## 真实通知、负载与重连

Fastsh r2379的近距离AP测试暂停PC上游STA，只保留AP。P1/P4的
15秒有效窗口（2秒warmup）接收311.57/288.29 Mbit/s，CPU6.44%/
8.59%、softirq1.65%/2.02%，ECM四条连接保持ACCEL，SG0、PN失败
不增长。TID0 generation18贯穿本轮；late0→529→1089、hole0→
13185→31294，timeout0→27→63。所有原始窄计数按固定位宽保留，
没有用到达上限后的零差值判定无事件，也没有认定带宽改善。

本轮确实收到9条固件type18，独立于此前2次注入。before快照为
received7/wmi_queued9，之后为received9/wmi_queued11，注入始终2。
最后真实消息peer3/TID0、SOC接口215、response5/error0/len8；
last_job_source0、generation18/epoch1、result0。duplicate/full/
invalid/not_ready/stale/busy/failed均0，pending/running均0，driver
实际长度拒绝计数0。这证明真实通知经过新host恢复路径并成功排队
WMI，不补造不存在的FW执行ACK。真实通知多在临时AP接入初期出现，
不能因此归因所有Frame OOR或FCS；后者仍为SOC范围计数。

Fastsh r2380完成3轮原上游重连，submitted_delta366，越过256编号
边界；TID0 generation35→52→69→86，TID16 51→68→85→102。
8份GET有效、每轮pending0、NEED_STATUS完成及callback配平，原
配置哈希一致。人工恢复4份、负载7份、重连8份共19份GET均
payload100/SUCCESS/当前实例匹配，四项aging原始值始终40000。

## 最终状态与剩余工作

最终opt25两份module及五份原配置哈希一致，NSS offload1、PROJECT
统计0、有线ready1/error0/allocation_uncertain0。QCN NEED_STATUS
379/379、callback172/172，内部36/36、callback0/0，pending均0；
通知仍9、注入2、WMI11，pending/running/failed均0。

原5GHz回程及网关ping3/3、HTTPS29506字节正常。首次收尾DNS查询
超时；同boot服务/53监听正常，随后127.0.0.1回答成功。电脑普通
dig也曾超时，采用已有mark666及eno1约束的LAN UDP/TCP DNS均得到
rcode0/1个answer，未改透明代理或系统环境。电脑恢复本轮前Wi-Fi
软关闭状态，经eno1/192.168.1.1联网，HTTPS200。临时AP、NAT、
namespace均已清理，镜像/回退/配置备份和诊断脚本保存在桌面opt25目录。

新增通知恢复已在真实通知和人工动作中运行，但5GHz下行仍有波动。
仍需对射频/重传/Frame OOR作更精确归因、验证原回程和长时间负载，
以及尚无证明的SSR/DMA停止边界。没有将本轮通过缩成整个目标完成。

## 同一实例的电脑射频对照

Fastsh r2394完成P1/P4各一次isolated→concurrent→isolated；只切换
电脑上游STA，临时AP和路由器连接一直保持。TID0的SOC/vdev/MAC/
peer/generation137/paddr在19份GET中一致，四项aging均40000。

| 连接数 | 暂停上游前段 | 上游并发中段 | 暂停上游后段 |
|---|---:|---:|---:|
| P1 | 282.22 | 280.11 | 290.60 |
| P4 | 258.44 | 259.14 | 280.11 |

单位Mbit/s；每项15秒有效窗口及2秒预热。中段相对两侧平均为
0.978/0.962，短时顺序测试没有支持电脑双角色导致明显吞吐下降，
也不能排除随时间变化的空口条件。CPU平均5.70%…11.39%。三段P4
各三份ECM快照均为四条ACCEL连接、字节增长、slow_path计数不变，
driver_fail/ae_nack均0。SG及PN仍没有增长。

六窗口真实type18增量分别1/8/1/0/8/0，WMI增量一致，pending/
running/failed均0；两次电脑上游恢复后的窗口各出现8条通知。
这只建立时序关联，结合routing fall-through不能把这些消息都
解释为真实硬件NULLQ。消息ABI没有同次WBM push_reason/质量/AST/
qaddr，现有HTT/WMI读回也不能补足目标FW当前绑定地址。

首轮r2393因新ECM输出目录未创建而在P4第一段后中止；四项测速
原始数据已保留，网络恢复成功。修正采集器自行创建目录后，r2394
完整通过，首轮不作为完整P4对照。

## 按peer读取已有monitor FCS统计

未改镜像。现有ext_rx_stats在station创建前启用，即可从当前
station rx_stats读取monitor PPDU/user FCS计数；NSS模式仍处理
monitor-status。r2399临时开启该开关，暂停电脑上游STA并做两个
15秒窗口，TID0 generation171保持一致：

| 窗口 | 下行Mbit/s | 已归属FCS ok | 已归属FCS error | 样本error占比 |
|---|---:|---:|---:|---:|
| P1 | 264.45 | 47392 | 3757 | 7.345% |
| P4 | 239.63 | 45332 | 5230 | 10.344% |

这证明当前peer/AST归属的样本有FCS错误，不能转换为全部空口或TCP
丢包率。无法解析/归属的PPDU没有进入这些计数，硬件peer/AST也
没有generation；坏帧的逐帧发送者、TID、SN和qaddr仍未证实。
GET processed MPDU增量为91679/102116，与monitor样本的来源及
采样时刻不同，不能将两者混作分子/分母。扩展统计会增加monitor
处理，不能将本轮速度差当固件回归。两份原网络配置逐字恢复，开关
恢复为原值0，临时AP/NAT/namespace清除。

电脑iwlwifi当前仅149…161的80MHz块允许发起AP；低频5GHz为
PASSIVE-SCAN。独立80MHz信道测试未执行，未改监管状态。

## 原回程与NSS冷启动对照

原TP-LINK回程的自然ARP双向失败，网关ping正常。r2406临时设置
双方精确邻居后，单播双向ping均2/2，随后删除条目；这只绕过邻居
发现用于取证，没有将静态邻居当成ARP修复。

r2407在同一generation222上完成五个有效窗口：P1本机前/后为
8.18/8.32、LAN为2.45 Mbit/s；P4本机前为6.15、LAN为4.82。最后
P4本机后段收取结果失败，整个数据集标为complete=false，不构成
完整P4前后对照。内核记录iperf3-sta-test申请4261416960 bytes，
并非普通低内存的证据。原始输出、有效partial及失败后GET均保留，
配置、邻居、namespace和扩展统计恢复正常。

r2411通过nss-wifi.enabled=0及重启进入真实NSS0，再恢复NSS1冷启动；
同时设了240秒路由器侧回退，六份原配置/rc.local逐字保存和恢复，
最终删除回退目录。分别核对boot_id变化及实际module参数，避免把
修改live参数误当成已切换接收路径。广播ARP在NSS1前、NSS0、NSS1
后三阶段均失败，因此没有证据将它归为无线NSS独有故障。

继续采用临时精确邻居，原回程本机接收的两个短窗口为：

| 模式/阶段 | P1 Mbit/s | P4 Mbit/s | CPU平均P1/P4 | 已归属FCS error占比P1/P4 |
|---|---:|---:|---:|---:|
| NSS0，r2411 | 6.43 | 8.46 | 12.25% / 15.30% | 8.939% / 5.551% |
| 恢复NSS1，r2413 | 12.37 | 19.01 | 12.02% / 14.05% | 5.213% / 8.673% |

每项15秒及2秒预热，两个阶段各7份有效GET，aging均40000。每阶段
内部保持同一peer/queue；跨boot的generation数值同为18，但paddr
和boot_id不同，不能冒称同一实例对照。电脑与路由器都是原AP的STA，
该路径含两次空口传输，不是独立Internet带宽基准。测试数据期信号
较弱且随帧/速率变化；顺序试验不能将NSS1较高数值当固件性能提升。
关闭无线NSS仍低速，且两种模式的已归属样本均有FCS错误，后续需
继续区分空口重传、REO aging/late和转发路径，不将SOC/样本计数
直接换算为TCP丢包率。

两种模式的控制连接均抓包，snaplen256，分别识别出两个成功控制
流。结果交换、客户端DONE之后，服务端均发出FE及203/errno；这些
尾部错误不把已完成的四个结果改为失败。本机客户端为iperf3.20，
电脑服务端实测为3.22。3.20的结果JSON_read没有长度上限；若在
错误阶段将`fe 00 00 00`当长度，值4261412864的分配按4KiB向上
取整恰为4261416960，与早先申请量吻合。失败轮没有抓包，所以这
仍是候选解释，未重现错位读取，也没有据此认定NSS数据损坏。

## checksum ABI补充与本次收尾

反汇编闭合N2H offset14/u16 bit1：serializer把内部packet+20的
transport状态bit3转为0x2，普通/EXT共用赋值段，FIRST/LAST另为
bits2/3；Wi-Fi入口依据RX attention的TCP/UDP checksum-fail位为0
设置内部状态。与host transport-valid定义及消费者一致，未发现
位错位。但尚未闭合unsupported/fragment/header-invalid时的硬件
充分性条件，不能扩大为所有packet均已验证的证明。

当前仍为opt25，两个module哈希与镜像一致，六份原文件哈希一致。
无线NSS1、PROJECT0、扩展RX0、有线ready1/error0/uncertain0。
QCN NEED_STATUS81/81、callback24/24；内部17/17，pending及失败
均0。冷启动后通知计数重新建立，当前两SOC received/injected均0，
不能与此前107条直接累加。原回程网关2/2、路由器HTTPS成功；电脑
恢复原Wi-Fi软关闭状态，经eno1的mark666 UDP/TCP DNS均rcode0、
2个answer，HTTPS200。临时AP/NAT/namespace/静态邻居/回退目录均
清理。未产生新镜像，源码判断和本次运行证据保存在桌面opt25目录。
