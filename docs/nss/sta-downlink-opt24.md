# opt24：队列实例引用与硬件 REO 读回

在已运行的 opt23 上继续补齐5GHz下行观测。mac80211 release21，
NSS driver 保持 release29。2048/384 buffer/TLV、ring深度、BA窗口
和PN/重复帧验证未调整。代码、编译和主机测试已完成，已保留配置
刷入并取得真实硬件 GET；负载归因仍待验证，不能认定带宽问题已解决。

## 队列生命周期

999-994 为每次 qdesc 分配增加独立 refcounted owner、不可复用
generation、device引用和原始/对齐DMA元数据。peer、待删除节点、
命令和cache-flush各自持有引用；clone显式复制DMA元数据，不复制
timer、skb队列或fragment对象。query另持一份DMA pin，不进入旧的
活动rx_tid释放路径。引用计数不充当硬件停止证明。

初建队列在WMI提交前保持PREPARED/SUBMITTING且active=false；WMI
期间pin原peer和原queue、使用锁内捕获的paddr，返回后核对原实例。
初建的负返回在WMI/HTC/CE publication之前，可以回滚原未发布owner；
不能重新按可复用MAC/vdev/TID释放新实例。既有UPDATE及AMPDU_STOP
已发布HAL操作，随后WMI失败不撤销硬件副作用，也不free旧owner。
既有队列更新时保持PUBLISHED，避免新增同实例fragment丢弃。

WMI in-flight登记在提交门/epoch下，关闭时纳入保留判断，直到最后
使用ab/ar结束才撤销登记。SUBMITTING期间的删除先转移owner，WMI
结果驱动待删除队列继续处理，不依赖尚未产生的DELETE callback。
WMI成功但实例失效、删除/flush失败或cache节点分配失败时保留页；
软件DRAIN、IRQ排空与NSS RESET ACK都不作为WLAN DMA fence。

REO引起的不确定状态另有sticky标志。NSS teardown/reset在此状态
拒绝继续，不能用一次NSS RESET成功清除WLAN的未决owner；现有
DP/HAL/ab/ar保留策略继续生效，正常复位仍保留原路径。

peer_setup从frag初始化到逐TID设置和失败清理绑定原peer。frag timer
解锁等待期间pin原peer/queue并重核实例；reinject核对原始queue
地址与当前PUBLISHED owner。cleanup_all跨timer等待后重新取列表
节点，不保留可能被unmap释放的tmp，也不重复摘除旧实例。

## 私有硬件查询

新增只读reo_queue_targets列出vdev/TID/MAC、peer、descriptor
generation、paddr与软件请求窗口。reo_queue_query写入格式为
`vdev_id tid mac`，在base_lock内选择当前PUBLISHED且未retiring的
owner、pin DMA，并保持实例检查直到HAL publication。请求只设置
NEED_STATUS，未设置STATS_CLEAR。

QUERY是独立entry kind；waiter和command引用共享私有heap request。
每SOC只允许一条未回复query。1秒超时仅撤销waiter，不回收ID、
command引用或DMA pin；后来回复仍能完成。超时不读取正在写入的
结果，错ID/tag不释放reservation。关闭时未回复query进入quarantine。

GET parser复制完整header以及100-byte payload的各已定义字段。
非SUCCESS或短payload不发布SSN/PN/bitmap；短common header不领取
owner。结果标明header/payload有效性、提交epoch和descriptor
generation；current_instance_at_query_return仅表示该次返回时
仍匹配软件实例，之后读取缓存不重新查询。

SSN12、index8、PN四原始word、bitmap八原始word及各计数器原生
位宽保留。GET不提供硬件BA窗口、VLD、PN_VALID/PN_ERR；不把软件
requested_window写成硬件读回。timestamp保持raw，exec_time按
HAL注明的微秒。计数器回绕/饱和与bitmap旋转映射尚未证明，不以
普通32-bit减法解释差值。

## 已完成与待验证

实际C ASan/UBSan测试覆盖：分配失败、引用配平、真实DELETE→cache
→FLUSH退休、失败保留、WMI关闭/更新/删除交错、替换peer回滚、
cleanup/unmap移除当前和下一节点、字段最大值、失败清零、私有
completion、超时后迟到回复、错类型与畸形TLV。六组canonical
回归已通过，恢复测试另覆盖query/WMI未决时不释放共享资源。

干净AArch64构建通过。14个reviewed/prepared源码文件逐字一致，
CI YAML与diff空白检查通过，新测试已接入CI。首次统一diff分页
插入了额外换行，已改为base64无损传递并重新prepare核对；内核
current宏与结果字段重名也已修复。

完整镜像流水线已完成（Fastsh r2308），并已保留配置升级为
`r0-nsslan-opt24-fe7e690dcd`。镜像SHA256为
`fd503f34f769ca0ff74ce99ee8456711ac3103fb899d3bd3c14849101a53f372`；
真机ath11k为`53aabd5393c054199bd8d797461b3b46948f7fe37486ebbbedba9c054ab8c8de`，
NSS driver为`bed13e638104ebc23fdacd4297e6fbb6aa84481a6eaa600e81ad44488496660f`。
五份原配置哈希一致，有线NSS ready=1、allocation_uncertain=0，
原5GHz回程WPA/DHCP、DNS及HTTPS恢复（Fastsh r2325）。

首条QCN6122 TID0 GET真实返回100-byte payload，header/payload有效，
SUCCESS且当前queue实例仍匹配；提交/完成从19/19变为20/20，
callback1/1、pending0（原始证据保存在桌面opt24目录）。BusyBox
`printf '%s\n'`报告退出码1，但硬件已完成；改为不带尾部换行的
`printf '%s'`完整请求后，TID0和非QoS TID16均正常返回，退出码0。
两者generation分别为1/17，paddr分别为0x44185000/0x43b72000。

首份TID0读数SSN281、late126、hole1360；这些是原回程已有活动
流量的瞬时累计值，不是本轮受控负载的增量，也不能据此判定根因。
近距离AP的硬件GET与NAT负载关联已完成两轮，见下文。尚无吞吐
改善、SSR停止证明或长期稳定性结论。

## 硬件GET与实际下行

Fastsh r2330保留9份近距离AP TID0 GET。generation18/paddr0x49ab8000
在本轮保持一致，全部payload100、SUCCESS、current_instance=1。
单流/四流NAT下行94.21/160.86 Mbit/s，CPU7.92%/8.26%，softirq
3.08%/1.37%；ECM四条活跃流保持ACCEL、字节增长且slow_path_packets
不增长。SG为0，PN失败不增长。TID0 late端点217→943→1885，hole
1537→8013→21387，timeout17→59→63；没有把这些窄字段按普通32位
累计差值解释。所谓idle窗口仍有9616条QCN交付，不能当静默基线。

Fastsh r2334关闭PROJECT采样，在同一新peer上交叉测量本机接收与
LAN转发，保留21份GET。generation69保持一致；真正idle窗口TID0
processed_mpdu20→20、late/hole均为0。结果如下，速率是iperf接收端
20秒有效窗口，CPU由jiffies对该窗口加权：

| 并发 | 路径 | 接收 Mbit/s | CPU平均 | TCP重传 |
|---|---|---:|---:|---:|
| 1 | 本机，转发前 | 163.16 | 23.47% | 639 |
| 1 | LAN NAT | 210.39 | 5.19% | 805 |
| 1 | 本机，转发后 | 167.09 | 23.56% | 936 |
| 4 | 本机，转发前 | 146.41 | 27.33% | 2953 |
| 4 | LAN NAT | 89.39 | 5.66% | 1894 |
| 4 | 本机，转发后 | 177.57 | 36.86% | 1361 |

同一TID0同时记录到非空reorder queue：P1 LAN的负载快照为4 MPDU/
4 MSDU，P4最后一轮本机快照为26 MPDU/95 MSDU。SSN/index/bitmap
原始word已保留，未猜测bitmap旋转映射。late到4095后在processed
MPDU继续增长至477879期间保持4095；timeout也保持63。这与饱和
一致，后续零差值不能说明没有新事件。完整硬件饱和/回绕规格仍缺。

两轮均有QCN Frame OOR及FCS增长，SOC统计覆盖所有peer，不能把
每个FCS归给iperf。PC的上游STA与临时AP仍共用同一radio，PHY
速率在一个/两个spatial stream之间变化；本机接收也波动，结果
不能证明固定NSS转发上限，也不能与opt23跨时间数值作改善/回退
因果比较。原始日志及分析位于桌面`Redmi_AX3000_NSS_opt24`下的
`opt24-reo-get-lan`/`opt24-reo-get-full`；配置恢复后五份哈希一致。

## 源码继续核对的缺口

后续补充测速：Fastsh r2352暂停PC的上游STA，只保留临时AP，两组
15秒有效窗口/2秒warmup下，P1/P4为306.80/372.23 Mbit/s，CPU
6.45%/9.75%、softirq1.51%/2.28%，ECM仍加速，SG0。7份GET均有效，
generation222保持一致；late0→435→973、hole0→12244→25102。
这与STA/AP共用射频影响测量条件一致；跨时间、不同peer的结果不能
单独证明因果，也不能作为opt24固件改善的证据，原回程的弱信号与
波动仍需验证。
短测试后先恢复PC上游Wi-Fi，再恢复路由器原配置，临时资源已清理。

type18缺失处理和aging读取的后续实现见[opt25候选](sta-downlink-opt25.md)。

当前BA更新的HAL地址与三处WMI地址都来自同一rx_tid/queue owner；
BA更新不重新分配descriptor。NSS PEER_CREATE的peer-memory paddr
不是RX qdesc，未找到宿主缓存旧qdesc用于当前更新的确定错误。
WMI消息没有SSN字段；返回0只确认发送，不能作为FW执行ACK。

host初始化在NSS路径也给四个REO aging profile写入40000，HAL名义
单位为微秒。QCN6122完整HIF offset为0xa38564/568/56c/570；本轮
QMI报告BAR0x81e00000，静态窗口对应BAR内0xb8564/568/56c/570。
现有debugfs没有受控MMIO读取接口，未读取真机最终阈值，未证明
目标固件/NSS随后是否改写；没有调整timeout、BA窗口或PN检查。

`NSS_WIFILI_TID_REOQ_SETUP_MSG`（type18）的ath11k回调仍为TODO。
payload只给u32 TID/u16 peer_id，大小8字节，无地址/window/SSN。
所有17个TID已预建，但现有构建关闭driver/ath11k debug及kprobes，
没有该通知的独立计数，不能证明它本轮发生或造成OOR。后续诊断
应先在持有实际buffer长度的driver接收路径检查边界，再复制数值
计数；NAPI callback不能睡眠，也不能直接开始动态WMI setup。

## 原回程重连与最终状态

首版重连脚本将异步`wifi down/up`返回误当作新关联完成，第三轮
读取link时才看到本次测试的正常teardown。此时尚未提交GET，
不是GET失败或固件崩溃。日志已保留；脚本改为先观察Not connected/
No such device，再up并等待关联，随后查询并核对新generation。

修正后Fastsh r2342完成3轮原上游重连，submitted_delta365，超过
256个固定编号的一圈。TID0 generation137→154→171→188，TID16
153→170→187→204；8份GET均payload100、SUCCESS、当前实例匹配。
每轮pending0、status_requested/completed和callback注册/领取均
配平，提交/分配/类型/epoch错误不增长，五份配置哈希保持一致。

最终设备仍为opt24，NSS offload1、PROJECT统计0，有线ready1且
allocation_uncertain/error0。QCN NEED_STATUS908/908、callback
439/439，内部SOC197/197及85/85，均pending0。原TP-LINK_3A回程
恢复，网关ping3/3、DNS正常。首个uclient HTTPS请求失败并报告
Operation not permitted，同一boot的有界重试下载29506字节成功；
没有将该通用错误字符串判作系统权限故障。电脑恢复本轮前的
Wi-Fi软关闭状态，经eno1/192.168.1.1联网，HTTPS200。

网络reload期间仍有opt20已记录的SSDK port0 notify告警；本轮有线
NSS持续ready且完成实际转发，未扩展修改SSDK或系统环境。

桌面opt24目录保存新镜像、opt23回退镜像、升级前配置备份及原始
证据；临时AP、NAT、namespace和观察节点已清理。5GHz下行波动、
NSS type18通知是否发生、最终aging阈值及长期/SSR安全性仍未闭合。
