# opt22：REO 更新实际完成状态与内部 STA 对照

在opt21基础上继续制作，mac80211 release19、qca-nss-drv release29。
2048-byte NSS buffer、384-byte TLV、ring/pool深度、密钥/PN与重复帧
检查保持现有配置。当前新增观察不直接提高吞吐，也不把OOR增长
认定为驱动错误。

## 安全的 REO 执行观测

新增999-992，按SOC提供只读reo_update_stats：尝试、HAL接受/拒绝、
NEED_STATUS、BA/SSN/PN请求数，以及UPDATE实际success/blocked/failed/
resource-blocked/unknown。debugfs在独立锁内复制数值快照后格式化；
core_alloc初始化锁，因为SOC debugfs早于dp_alloc。每次dp_alloc重置
数值并增加epoch，不重新初始化已公开的锁。

HAL提交前复制请求参数，避免HAL将window=1和PN size原地规范化
后丢失原输入。last_hal_submit_errno明确表示HAL提交结果，不等于
整个带callback的发送函数最终返回值。最新提交与最新回复相互独立；
cmd_num是循环ring编号、epoch只是宿主统计重置边界，不能用它们
绑定当前peer或推算逐请求完成率。

没有新增callback或peer/queue引用。现有发送函数为callback对象复制
整个dp_rx_tid；cleanup会释放副本中的DMA地址，直接给活动UPDATE
挂一个统计callback会错误引入释放所有权，还会新增发送后分配失败
与早到回复窗口。观察器在已有status parser后记录数值，保留原
callback/返回值/释放行为。

原UPDATE parser只读取cmd_num/status，未填硬件timestamp和exec_time。
本次从原status header补齐这两项，避免观察器把初始化0当实际时间。
硬件timestamp保持raw值，不与NSS PROJECT raw ticks混用或换算。

实际C测试执行原发送函数、status parser和观察helper，覆盖原返回值、
HAL原地改写前的请求值、NULL-callback不分配/不取得queue所有权、
旧callback分配失败行为、四类状态/unknown与并发快照。ASan/UBSan
及canonical AArch64 clean/compile通过；共享DMA、恢复和IRQ生命周期
回归通过。IRQ fixture首次因prepared源文件权限失败，使用sudo -n
执行后通过，没有扩大修改目录权限。

## 镜像和运行边界

版本：r0-nsslan-opt22-fe7e690dcd。
factory UBI SHA256：

`b360c561d20658d1da0de99c25ddb81630b12e7fdbce904c5cec83e90176e738`

ath11k SHA256：

`a87091a2807e74ecd1d00bdb5248815a635b3a73b2ff58667449d39cff762a9d`

NSS driver保持opt21：

`bed13e638104ebc23fdacd4297e6fbb6aa84481a6eaa600e81ad44488496660f`

桌面Redmi_AX3000_NSS_opt22保存候选、opt21回退镜像、profiles.json
和权限0600的配置归档。上传哈希/sysupgrade -T通过，factory UBI
没有metadata的提示保留；一次保留配置升级已发起，运行验证补录。

首次启动uptime49.38秒确认新revision/ath11k哈希、有线READY/error=0、
原5GHz关联及默认路由。五份原配置哈希相同。QCN6122 UPDATE提交19、
硬件success19，BA2、PN17，最新BA请求window64/SSN4；IPQ5018提交17、
success17、PN17，所有失败分类为0，硬件timestamp实际为非0值。

近距离AP自然ARP、标准MSS、每项20秒+3秒预热的NAT窗口：

| 项目 | 下行Mbit/s | CPU / softirq | RX delivered / REO reaped | SG |
|---|---:|---:|---:|---:|
| P1 | 364.63 | 5.63% / 2.44% | 715023 / 715034 | 0 |
| P4 | 352.06 | 5.21% / 1.38% | 700817 / 700825 | 0 |

空闲/两个负载窗口的QCN6122累计UPDATE queued73/success73、IPQ5018
17/17，所有rejected/blocked/failed/resource-blocked/unknown为0；
负载期间没有新的UPDATE。QCN最新BA请求window64/SSN5。这证明已观察
命令完成没有失败，仍不能读取当前硬件SSN或将一条回复绑定某个peer。

空闲只有3个NULL queue事件。P1/P4 Frame OOR分别+651/+1020，FCS
分别+68429/+87451，PN类0；仍不能用FCS汇总直接换算iperf丢包率。
本轮速度比opt21数轮更高，但数据路径未调整，PC同radio STA/AP和
空口条件未隔离，不能认定为观察补丁带来的提升。原始数据在桌面
sta-controlled-opt22-reo-r1/，仍继续处理完整中继带宽波动。

## 2.4GHz 与连接日志的纠正

opt21的内部STA在同上游2.4GHz能关联/DHCP，但Internet保障未闭合。
r7实际数字IPv4 TCP探针连上网关192.168.15.1:80和公网223.5.5.5:53，
64.226.122.113:443等待3秒超时；网关ICMP0/3。因此不能只据ICMP失败
认定整个链路断开，也不能由混合端点结果认定NSS或防火墙根因。

uclient-http.c的uclient_do_connect失败统一返回UCLIENT_ERROR_CONNECT=1，
uclient-fetch.c对这个内部enum调用strerror，显示Operation not permitted。
这不是底层errno证据；前文“被拒绝”的日志描述不能证明权限/策略拒绝。
后续使用实际socket返回值、计数和host/NSS同一回程对照。

MP12.2 target29/IPQ5018与30/QCN6122安装同一RX HAL表；prepared均
使用qcn9074的384-byte descriptor，HTT/SOC_INIT均提交384/2048。
未找到IPQ5018专属STA不支持分支。已证target差异是RX context+101：
IPQ5018为1、QCN6122为0，直接读取点在WBM release处理，其完整硬件
语义尚未闭合，不能直接当错误配置。后续运行对照再决定追哪个丢弃点。

## host/NSS 内部 STA 对照和恢复

在同一opt22上把nss-wifi.main.enabled临时设0并重启，确认新boot_id
和ath11k.nss_offload=0。第一轮在网络重启后的SSH观测20秒超时即退出，
尚未获得内部STA数据，不能据此判定host失败；已修正为在同一就绪
转换中继续轮询，并禁用SSH连接复用。

第二轮host内部STA完成同BSSID关联/DHCP，source为192.168.15.15。
网关192.168.15.1:80 TCP connected，公网223.5.5.5:53和64.226.122.113:443
在3秒探针内超时，ICMP0/3、HTTPS连接失败。NSS模式r7同网关TCP
connected、公网DNS TCP connected、HTTPS TCP超时、ICMP0/3。
两种路径均未获得可靠2.4GHz Internet，不能将其归为NSS专属失败，
也不能将不同端点/空口条件下的数值当作固定条件性能比较。

第二轮恢复时过早的一次HTTPS检查失败；后续在同一恢复boot中确认
nss_offload=1、三份原配置字节/哈希相同、有线READY/error=0，原5GHz
关联/默认路由在线，网关3/3、127.0.0.1 DNS返回64.226.122.113、HTTPS
下载47612 bytes成功。恢复checker现在保留尝试并继续验证同一boot，
不因初次Internet观察失败重复重启。

目前仍需稳定空口来源、目标peer/TID硬件SSN读回及长期/IPv6/组播
验收；不能把UPDATE全部success或一轮365/352吞吐认定为全任务完成。
