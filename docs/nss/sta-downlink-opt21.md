# opt21：可靠的 NSS 逐线程统计与下行定位

继续使用opt20的2048-byte NSS RX buffer、384-byte TLV、原ring/pool深度
与MCBC TID、host RX/TX修复。本轮qca-nss-drv release29，mac80211
release18，尚未据统计结果调整worker映射或时钟。

## 驱动修复与源代码验证

新增0213修复首次ENABLE ACK与debugfs读取的竞态：旧reader先在锁外
取到0几何尺寸，随后ACK发布table，可能对ZERO_SIZE_PTR执行strlen。
新reader在同一锁内取得pointer/count，再分配和复核；复制完成后只
格式化私有shadow。文本按活动IRQ数量分配，零活动IRQ也保留banner空间。

PROJECT控制复用nss_control的独立cookie、core/interface/type匹配和
callback排空。启停等待真实ACK，核对12-byte payload、echo enable和
12 context/128 IRQ编号域的边界；只接受0/1写入。开启失败后显式关闭
所有core，关闭仍尝试每个core。读值0/1表示全部已确认，-1表示混合
或未确认状态。禁用后丢弃旧N2H通知，保留末次宿主快照；注销摘除并
释放table，与reader/NOTIFY共用stats锁。

ACK callback仅保存结果；GFP_KERNEL分配在writer进程上下文完成。
等待返回值保留，因为正常等待消费completion；超时撤销后仍接纳在
边界到达的已完成ACK。长度检查使用cm.len，避免把包含40-byte公共
header的nss_cmn_get_msg_len当成payload长度。

实际C函数测试覆盖ACK/NACK、提交失败、超时/迟到/边界ACK、多core
回滚及未知状态、短NOTIFY、thread/IRQ/count上限、snapshot摘表竞态、
1536编号槽输出和每一步分配失败清理。旧reader的首次ACK崩溃在
ASan/UBSan下复现，新reader通过；现有控制身份/排空回归也通过。
canonical clean/compile/modpost成功。编译器仍报告原有其他文件的
missing-prototypes和nss_rps enum-compare告警，未扩展修复这些既有项。

固件ABI、callback采集边界及EMA公式见
[反汇编记录](firmware-reverse-2026-10-10.md#mp122-project-逐线程统计-abi-与启停-ack)。
ticks继续标为raw ticks，不能据EMA或cpu_load_ubi推断单worker饱和。

## 最终镜像与运行验收

版本：`r0-nsslan-opt21-fe7e690dcd`。
factory UBI：17694720 bytes，SHA256：

`c5afd536c18f6337324e6392eda7e8dcf0f1bb4ad2973ec10aed827be0e5a1a7`

staging NSS driver SHA256：

`bed13e638104ebc23fdacd4297e6fbb6aa84481a6eaa600e81ad44488496660f`

ath11k SHA256与opt20相同：

`8f6e0484a9ab001cd5dde3e12a0bda846980f824264b891fddd1a6de45f7f0d7`

桌面`Redmi_AX3000_NSS_opt21/`保存镜像、profiles.json、权限0600的
配置归档和opt20回退镜像。上传哈希与sysupgrade -T通过；factory UBI
没有嵌入metadata的提示保留。保留配置升级的启动、ACK与实际流量
验收继续补录，不能把源码回归或编译成功当作运行验证。

首次启动在uptime74.80秒确认上述revision和两个模块哈希，有线
NSS READY/error=0、原5GHz回程及默认路由在线。无线、network、DHCP、
firewall、nss-wifi五份配置哈希与刷前相同。

首次PROJECT运行拒绝写入2；未分配时reader返回空。写1真实ACK后
读取到15个活动IRQ，thread为0/2/3/4/7/8/9/10/11、编号均在范围内；
写0 ACK后间隔1秒的两份快照完全相同。统计保持关闭，无线/network
文件未改。原始证据为桌面opt21的project-first-runtime/。

第一轮近距离AP＋电脑原上游STA并存，VHT80/信道149、自然ARP、
标准MSS，每项20秒加3秒预热，PROJECT全程开启：

| 项目 | 本机前 / 后 Mbit/s | LAN NAT Mbit/s | NAT CPU / softirq |
|---|---:|---:|---:|
| P1 | 371.61 / 336.75 | 331.98 | 5.00% / 1.64% |
| P4 | 342.56 / 304.85 | 313.16 | 3.77% / 0.93% |

LAN相对本机前后平均分别0.937/0.967。尚未隔离电脑同radio双角色，
不能据单轮差值认定带宽瓶颈全部解决。第一轮只保留负载前后callback
累计次数和epoch极值；结束后EMA可能已回到idle，不能当负载成本。
后续采集在iperf开始后6/13/20秒读取EMA，再与packet/count增量对照。
clock_summary实际记录core为1GHz，auto_scale配置没有改动。

第一轮结束收到关闭ACK读值0，原无线/网络逐字恢复、电脑上游Wi-Fi
和有线profile恢复，临时AP/NAT/namespace与测试服务清理。完整数据
保存在sta-controlled-opt21-profile-r1/，负载内统计和剩余边界继续补录。

第二轮取得每项三份负载内统计（6/13/20秒），同一空口条件：

| 项目 | 本机前 / 后 Mbit/s | LAN NAT Mbit/s | NAT CPU / softirq |
|---|---:|---:|---:|
| P1 | 338.85 / 350.83 | 326.58 | 5.91% / 1.50% |
| P4 | 323.81 / 315.98 | 285.74 | 4.82% / 1.17% |

GMAC RX/TX ring服务(t2/IRQ39)、Wi-Fi释放/completion/refill组合poll
(t10/IRQ35)和Ethernet RX(t3/IRQ11)在NAT窗口的相对指令成本估计
居前；本机收包时N2H输出的相对成本明显增加。这个估计使用窗口调用
增量乘负载内EMA中位数，只能粗略排序，不是总指令数或worker利用率。
timer固定重挂在空ring也计数，不把约30k calls/s解释为30k packets/s。
Wi-Fi RX实际活动为t7/IRQ5，不按radio名称猜测IRQ映射。

第一轮统计块按INTERNAL IPQ5018 PDEV0/1/2、ATTACH0 QCN6122 PDEV0
保留顺序。QCN6122的P1/P4 RX delivered分别+663616/+639769，REO
reaped分别+663621/+639780，SG send/fail都为0。常规reo_error、RX
deliver drop、descriptor alloc fail、hardware unavailable与TCL
full/no-desc没有增长；但WBM src_reo_code_inv分别**+3919/+4389**，
不能将常规reo_error=0扩展成“全部REO硬件错误为零”。需要继续查
catch-all分类、实际descriptor code及tuple归属，不将聚合计数直接
换算测速丢包率或认定带宽根因。N2H payload alloc fail维持既有8。

第一轮实际P4连接18–21在三份快照持续ACCEL=2、is_routed=1，
reverse bytes逐条增长，slow_path分别保持3/3/4/3；driver fail、
NACK、flush与no-action为0。P1未采集同tuple的活动ECM快照，不能把
P4的规则证明直接移用到P1。

两轮结束均关闭统计、清理临时AP/NAT/namespace和测试服务，并逐字
恢复原无线/network。最终五份配置哈希相同，wired READY/error=0，
原5GHz关联、默认路由及电脑直连上游Wi-Fi恢复；网关ping3/3，HTTPS
下载47612 bytes完成，日志未出现Oops/BUG/旧completion mismatch。
当前仍未证明5GHz中继全部带宽问题、原上游广播ARP或NSS完整IPv6/
组播/WDS/PPPoE功能完成。下一步追WBM分类增长与独立空口测量条件。

## WBM逐码差分与下一步边界

反汇编进一步闭合：inv是code0/5专门路径以外的catch-all，含合法的
越窗、重复、PN及其他exception；SOC_STATS的WBM/REO/RXDMA数组偏移
与MP12.2写入一致。宿主已有soc_dp_stats，可直接读取逐码数组，不需
加入逐包日志，也不放宽PN/重复校验。

受控空闲20秒的QCN6122 RX delivered与SG为0，REO只有2…3个NULL
queue事件。r3完整P1窗口为319.60 Mbit/s，delivered+644516，inv+5234
完全由Frame OOR+5181、BA dup+53组成，FCS+59254；PN类和descriptor
invalid没有增长。这里的WBM是SOC级计数，不能合并为每PDEV数组。

r3 P4的ECM观察因要求恰好四条旧/新记录而失败：原筛选未限制活跃
socket，紧接P1的旧TCP条目可能仍在。旧观察未保存等待期原始ECM，
因此不把具体条目数作为该次已证原因。修正后按LAN namespace的
ESTABLISHED源端口筛实际data tuple，并保存每次尝试的原始记录。
另外先落盘iperf输出、硬件末次快照与partial-tests，再判断观察器
完整性，避免诊断失败丢失其他结果。

r4已完整通过两个NAT窗口和四条活动ECM捕获，但吞吐比前两轮低，
仍如实保留：

| QCN6122增量 | P1（159.29 Mbit/s） | P4（213.44 Mbit/s） |
|---|---:|---:|
| RX delivered / REO reaped | 364311 / 364315 | 430106 / 430110 |
| SG send | 0 | 0 |
| WBM inv | 4479 | 5238 |
| Frame OOR / BA dup | 4426 / 53 | 5101 / 137 |
| FCS | 30017 | 40889 |

P4连接80–83持续ACCEL=2，bytes增长、slow_path保持3/4/4/4，fail/
NACK/flush/no-action为0。空闲QCN6122没有OOR/FCS，负载下增量与inv
分类一致；这将下一步收敛到BA/序号窗口及空口交付，不能直接证明是
NSS软件、射频晚重传或某个iperf tuple导致，也不能直接算丢包率。

源码审查未发现协商window/SSN的确定字段错配。VHT上限64、HE256，
HAL编码window−1、12-bit SSN，WMI提交原window。NSS开关共用HAL/
WMI链，host仍消费REO status。但是UPDATE请求NEED_STATUS、callback
为NULL，软件只确认入队并立即更新窗口；实际REO执行结果没有回到
BA调用者。尚未发现运行失败，需要实际completion及目标peer/TID
的GET_QUEUE_STATS或HTT RX-TID证据，不能仅由OOR增长认定更新失败。

r4原配置恢复后网关3/3，但首次HTTPS返回Operation not permitted。
重启dnsmasq后HTTPS下载47612 bytes完成，五份配置哈希不变。清理
流程现在在原STA拓扑恢复后重新启动resolver服务，不把配置恢复
直接当作网络服务已恢复；尚未证明具体是哪个缓存socket或路由状态。
该轮尝试使用的目标timeout工具不存在，nslookup命令未实际执行，
保留限制，不把它写成DNS查询成功。HTTPS成功包含正常域名解析。

r4保存的实际ECM尝试含旧P1连接76及新P4连接80–83；地址/累计byte
筛选五条，ESTABLISHED源端口筛选四条，验证观察器修正。r6独立
2.4GHz回程在fresh resolver下仍为网关1/3、HTTPS被拒绝，原配置及
5GHz回程已恢复；该回程尚不适合作为AP单独发送试验的Internet保障。

最终final-opt21-state-network.log确认opt21模块哈希、五份原配置哈希、
统计关闭、有线READY/error=0、原5GHz关联/路由和网关3/3。此次实际
执行nslookup，经127.0.0.1返回openwrt.org的64.226.122.113，HTTPS
下载47612 bytes完成；电脑默认路由仍为原上游wlan0，namespace为空。

## 独立回程测试的当前限制

电脑iwlwifi同时承担上游STA和近距离AP，可能影响受控测试的速率。
临时使用原上游2.4GHz BSSID能关联和取得DHCP，但HTTPS请求超时或
被拒绝，尚未证明其可维持电脑的独立Internet回程。

最初脚本误用不存在的UCI section，随后已改为default_radio0；live
proto切换后恢复一度留下netifd NO_DEVICE，完整network restart恢复
原5GHz回程、DHCP与HTTPS。所有测试结束均按原始字节恢复无线/网络
配置，五份配置哈希与opt20刷前一致。数值IP/DNS分离试验的一次30秒
命令观察超时未保留部分输出，已补充超时原始输出落盘。暂不把这些
失败归因于NSS、上游隔离或空口饱和，也不据此声称已完成AP单独发送
的性能比较。
