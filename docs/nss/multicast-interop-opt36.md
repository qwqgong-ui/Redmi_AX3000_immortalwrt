# opt36：完整MDB查找快照、关闭ME时双表建表和来源过滤

当前运行版本`r0-nsslan-opt36-fe7e690dcd`，ath11k release33、NSS driver
release32。本轮完整构建、保留配置刷入和受控收发已完成；自动MDB
worker、MCU发布、全范围数据回退及生命周期撤销尚未完成，完整NSS
补齐目标继续。前置ME模式/空表合同见[opt35](multicast-interop-opt35.md)。

## 本机有线实际验收

刷入后先前只核对了启动和有线NSS就绪；按用户提醒补做实际网络
验收，并把本机主出口切到`eno1`。链路1000Mb/s、全双工，地址
`192.168.1.127/24`，网关ARP为REACHABLE，5个网关ping全部返回。
路由查询明确经`192.168.1.1 dev eno1`。

DNS与直连TLS程序同时设置SO_BINDTODEVICE=eno1、SO_MARK=666，
排除本机透明代理：路由器UDP/TCP DNS均返回有效A响应，带证书校验
的Cloudflare HTTPS实收16384字节。将本机代理运行出口固定eno1并
刷新已有服务连接后，普通Arch和Cloudflare HTTPS均200。本机Wi-Fi
关闭时再次确认普通HTTPS200，不能仅用Wi-Fi备用网页代替有线验收。

组播测试期间有线HTTPS仍200。结束后明确绑定同一有线端点的16MiB
TLS通过：16777216字节、5.026秒、26.703Mbit/s；单一tuple
`192.168.1.127:45327 -> 162.159.140.220:443`为
`nss_v4.ported.accel_mode=2`。这证明有线经原无线回程的实际NSS转发，
不表示WAN达到千兆，也不宣称原回程带宽目标已经完成。

### 用户提醒后的有线复核与刷后门禁

再次确认当前主出口为`192.168.1.1 dev eno1`，链路1000Mb/s全双工，
现有NetworkManager DHCP租约的服务器、网关与DNS均为192.168.1.1；
这是现有租约核对，没有断开主接口或重新申请租约。网关20次ping无丢包，
普通Arch HTTPS返回200，来源192.168.1.127。复核16MiB实流量为
7.413秒、18.105Mbit/s，对应单一连接仍为`nss_v4.ported.accel_mode=2`，
六份配置在该复核前后相同，证据`flow-66495a4d`、Fastsh `r2826`。

新增仓库工具[scripts/nss-verify-wired.py](../../scripts/nss-verify-wired.py)：
强制SO_BINDTODEVICE与当前有线地址，显式采用既有代理绕过mark，校验
DNS问题、CNAME链与A记录，进行证书校验的16MiB HTTPS实收、20次网关
ping和网卡错误/丢包增量核对；可同时检查普通及相同source/mark的主路由。
不修改接口、无线电、路由或代理配置。不自动重试失败，也不覆盖已有证据。
当前candidate的刷后observe已接入必过检查；NSS ready不能单独作为联网验收。
不存在接口的负例返回非零并保留`passed=false`证据，源码只读复查完成。

带抓包的完整验收`r2835`、`wired-acceptance-final.json`：UDP/TCP DNS均通过，
20/20网关返回，HTTPS两次8MiB共16777216字节、6.887秒、19.489Mbit/s，
普通及mark666路由均经eno1；期间网卡RX/TX错误、丢包、carrier错误及碰撞
增量均0，另保留DNS pcap。本轮未改固件，运行版本仍为opt36。

诊断阶段的失败也保留：单次16MiB HTTP请求得到403/1字节，换为与既有
成功工具一致的两次8MiB请求后完整通过；另出现UDP DNS超时及一次TCP
DNS验证失败，之后相同有线检查通过，但早期超时根因尚未确认。
失败JSON和raw日志没有删除，不能据最终通过宣称长期DNS稳定性已完成。

后续`r2837`保留了匹配transaction ID的TCP DNS `flags=0x8185`
（RCODE=REFUSED）和一次HTTPS超时。已核对本机nft规则：mark666即0x29a，
在代理捕获前return，并由对应policy rule查main路由；绕过标记实际有效。
路由器dnsmasq当前cache-size=0，上游为223.5.5.5/223.6.6.6。
修正对照目标后，`r2840`的有线到路由器及到两台公共DNS均成功；电脑
直接经wlan0到223.6.6.6的UDP也超时，TCP成功。因此上游/无线侧也存在
超时，不能把所有异常归因为有线NSS，也不能证明各次失败同源；具体
REFUSED根因仍未确认。没有为此改写现有DNS或其他网络配置。

修正DNS标签比较边界后的当前源码完整验收`r2841`、
`wired-current-source-complete.json`再次全部通过：16MiB、7.367秒、
18.218Mbit/s，UDP/TCP DNS、20/20网关、两种主路由和网卡错误/丢包
增量均通过，普通应用HTTPS也为200。DNS压缩指针、环、截断及标签
身份的独立负例通过；不存在接口的失败JSON保留在`r2836`。

## 修正的控制面输入

[0608内核补丁](../../target/linux/qualcommax/patches-6.12/0608-bridge-export-complete-multicast-lookup-snapshots.patch)
新增`br_mcast_offload_snapshot_lookups()`。在同一multicast_lock内导出
本端口全部host行、全桥全部MDB keys、source-filter版本谓词、真实
querier谓词、router及端口条件、bridge身份与seq。包含其他端口才有
的(S,G)及L2/匿名项；容量不足先返回E2BIG，两个输出数组均不部分写入。

此前逐端口source timer列表不足以复刻转发：全桥一旦存在(S,G)，
内核选择该项；本端口缺少同host行时，不继承EXCLUDE的(*,G)。
新planner直接按全桥key及实际本地行判断允许/阻断，处理STAR_EXCL、
BLOCKED、legacy模式、INCLUDE空集、EXCLUDE空集、重复及四来源上限。
匿名/router/VLAN、无querier、缺少全桥(*,G)的SG-only及不可表达条件
整体拒绝，避免生成会改变普通flood语义的硬件表。

同时补了query delay到期和运行时IPv6地址可用状态变化的seq通知及
软件MCU撤销；初始化时未建立锁的路径保持原样。仅依赖seq仍不能
消除timer core先撤销pending、callback尚未取得锁的窗口，因此消费者
还需重新比较当前querier等实际谓词。现有MCU发布API和在途数据撤销
不能据此当作完整的数据平面屏障。

## ath11k建表事务

[ath11k补丁](../../package/kernel/mac80211/patches/nss/ath11k/999-999zzzzzz-ath11k-stage-complete-MDB-ME-policies.patch)
增加planner及显式`<vdev> mdbstage`。仅在明确mode4关闭、global5/6与
表选择已知时工作：完整快照/编译、pin全部peer/state并捕获实际peer_id，
逐项reset/group/member ACK建表，两次ACK toggle完成两表，最终归0。
IPv4来源连续4字节、IPv6连续16字节打包，RA MAC填实际成员MAC。
每次关键提交重查NSS/key/peer及snapshot seq、模式、querier等条件。
部分失败保留staged=false；callback取消排空后释放全部临时引用。

该命令始终保持ME关闭，不设置bridge MCU。`mdb_staged`仅记录这次
离线建表成功；后续变化不会使它成为实时有效或允许启用的凭证。
自动发布前必须重新完整验证，并补齐数据回退、生命周期及撤销。
模块`nss_me_test`仍默认N，不改变默认数据转发。

增加`rxmcbc 0|1`的私有ACK控制。固件静态取证显示cmd22 bit29在
普通WiFi RX入口中将DA被标记MCBC的包提前送type14主机异常入口，
不改变AP_BRIDGE的单播bit7；它不覆盖wired/ECM直接送VDEV的TX。
实机端到端结果见下方，不把它扩展为所有入口都已关闭旁路的证明。

新增只对自建`NSSME35`/IPv4 UDP tuple计数的TX入口观察；不修改或
保留skb，默认关闭。记录Ethernet组播DA与单播DA，以及已冻结的
encap/decap。这用于区分受控帧是否经过宿主TX，不能代表全部流量。

## 源码与构建验证

[实际MDB C测试](../../scripts/tests/test-nss-mdb.py)验证全桥lookup容量、
外国(S,G)复制、IPv4/IPv6独立模式/querier谓词，以及两种delay callback
递增seq并撤销MCU。[实际planner测试](../../scripts/tests/test-nss-me-plan.py)
与prepared `br_multicast_flood()`交叉比较，覆盖INCLUDE/EXCLUDE、
foreign SG、legacy、重复冲突、容量与拒绝边界，ASan/UBSan通过。
无querier和SG-only的完整入口/flood选择主要仍为源码核对及拒绝检查，
不能把flood函数对照扩大为整个入口路径的运行证明。

原私有ME callback/admit/exchange回归通过；clean prepare后3个内核
文件、6个ath11k文件与编辑源逐字节一致。初次测试shim的常量htons及
atomic64_t声明问题已修复。初次模块构建遗漏`net/addrconf.h`导致IPv6
all-nodes helper声明错误，也已修复；最终完整构建及严格modpost通过。

factory UBI SHA256：
`14f3cfc583c2f25f7925f37eb6ea58504b807993c257f8b50c388c9acfab012a`。
四种镜像/profile、8个模块hash及opt35回退镜像均已核对。
只发送一次sysupgrade，首次启动8模块、6配置hash、原STA/DHCP和NSS
接管通过。默认monitor与ME试验开关均N。

## 真实成员快照与来源过滤

自建LAN namespace的两个地址192.168.1.250/249均先ARP DAD；电脑
临时连接原2.4GHz AP，IP192.168.1.100。保持订阅socket存活，用
IP_MSFILTER发真实IGMPv3 INCLUDE/EXCLUDE变化，开启临时bridge querier
及v3/v2版本，由完整MDB快照构建两表。建表时ME关闭。

为隔离固件源过滤，建表完成后临时关闭snooping/M2U再显式enable5，
使用已建表；这使历史快照不再是当前配置的发布凭证，本测试不声称
已经完成自动同步。每轮128个1024字节、35ms间隔的独立序号载荷，
同时验证UDP与AF_PACKET链路层pcap，避免由接收socket源过滤制造
“固件拒绝”的假阳性。

| 表与输入 | UDP/L2接收 | 宿主TX组播DA/单播DA增量 | 结果 |
|---|---:|---:|---|
| INCLUDE允许192.168.1.250 | 128/128 | 128/0 | STA单播DA，完整 |
| INCLUDE不允许192.168.1.249 | 0/0 | 未计该源 | 拒绝 |
| EXCLUDE允许192.168.1.250 | 128/128 | 128/0 | STA单播DA，完整 |
| EXCLUDE阻断192.168.1.249 | 0/0 | 未计该源 | 拒绝 |
| 空表组播DA，源250 | 0/0 | 128/0 | 仍吞包，无回退 |
| 空表STA单播DA，源250 | 128/128 | 0/128 | 正常绕过ME |

全部重复/异常0，encap=decap=2。正向与空表的受控源250全部经过
宿主TX，未观察到额外副本；源249不在该观察器的tuple范围。
此证据不排除其他未匹配流或同BSS/ECM入口的固件旁路。

路由器镜像缺少`bridge`命令，MDB CLI诊断127已单独记录，后续保留
控制与pcap验收。第一轮还因原Wi-Fi已关闭、工具假定原上游连接活跃
而在改动前停止；改为保存/还原实际radio/连接状态。全部自建namespace
及接口删除，sysfs/IPv6状态复核为原值，两个完整probe前后6配置一致。

## 普通AP MCBC RX对照

另建隔离LAN接收端192.168.1.251，电脑AP端发源192.168.1.100的
128帧组播。ME保持mode4，依次私有ACK设置rxmcbc 0、1、0；三轮
UDP及链路层均128/128、重复/异常0，DA均01:00:5e:23:00:01。
这验证本次AP→有线通路在启用主机异常和恢复后的端到端交付；没有
另设RX路径计数，不能单凭此结果声称所有包都经过type14或所有
STA→STA/单播路径已经验收。

## 当前状态与剩余工作

结束时ME mode4、rxmcbc0、试验N，snooping0、querier0、IGMP2/MLD1、
query12500/startup3125、M2U1、br-lan IPv6 disable1。电脑测试恢复各自
开始时的radio/连接状态；当前主出口及代理仍固定有线，普通HTTPS200。

首次刷入后的配置比较通过。之后发现`network.globals.packet_steering`
从1变0，其余5份配置不变；它已在两个完整probe开始前发生，各probe
和有线流量自身的前后hash都一致。本轮测试程序未写UCI，当前变更
保留。最终再与刷前旧hash比较会失败，该失败也保留，不隐去或改成
“全程6配置未变”。

仍需自动MDB/STA/key/VDEV失效与worker、全范围未知/控制/广播回退，
ECM MC直接规则及NSS bridge/AP_BRIDGE入口门、完整当前seq/谓词发布，
成员删除/ageing/在途包撤销、多STA与IPv6源过滤实机验收。原回程性能
及其他未接通NSS功能目标继续保留，不以本轮实验接口替代完整实现。

镜像、回退、配置备份、raw ACK、pcap、失败记录、清理结果及有线
验收在桌面`Redmi_AX3000_NSS_opt36`。
