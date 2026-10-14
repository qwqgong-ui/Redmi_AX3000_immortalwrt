# 无带宽上限的 NSS 硬件队列

本次用户要求只做硬件 NSS 支持的队列整形，不设置固定带宽上限，只以
延迟、抖动和丢包作为调优验收重点。没有硬件能力的项目不启用。部署配置使用
`nss-fq.qos`，无线 WAN、AP 和 LAN 物理 conduit 的根队列均为
`nssfq_codel`，`accel_mode 0`。上下行 UCI rate 字段为 0；该脚本仍创建
硬件队列，且不创建 `nsstbl`、HTB、TBF 或其他 rate limiter。

当前参数：CoDel target 5 ms、interval 100 ms、packet limit 128、128 flows、
quantum 1514。packet limit 是排队深度，不是固定带宽上限。保留 WMM、
NSS 无线卸载和 ECM 加速；最终配置的 ECM interface denied list 为空。
无线 WAN 跟随逻辑接口 `wwan`，AP 跟随 `default_radio0`，LAN conduit
`eth1` 使用 `nss_watch 1`。监护服务会等待 NSS 就绪并追踪 netdev 重建。

## opt56 当前候选与已知问题

设备当前运行 opt56（`r0-nsslan-opt56-fe7e690dcd`），clients release8；
ath11k、NSS driver、ECM、硬件队列参数沿用 opt55。完整构建的四种镜像、
实际 factory/sysupgrade 内部版本和十一运行模块哈希均核对一致。
保留设置升级、一次清理测试状态的完整重启后，有线千兆全双工、UDP/TCP
DNS、20 次网关 ping 零丢包和 16 MiB 证书校验 HTTPS 下载均通过；七份
配置哈希保持一致。升级与该次重启期间笔记本关联上游提供备用出口，
因此这两次启动不作为“笔记本未关联时的独立启动”证据。

`0061-qdisc-retain-flow-DMA-until-node-FREE-is-confirmed.patch` 修复确定的
退出所有权缺口：VAP 注册已撤销时，FREE 发送返回 BAD_PARAM=7；原流程
即使失败仍等待 10 秒，且提前 unmap/free FQ 内存。新流程识别负值终态，
独立撤销 host bounce，仅在足够长的 FREE ACK/SUCCESS 后释放已发布 DMA。
不确定的映射保留原 device 和模块引用至重启，不保留 qdisc/netdev/callback
指针；代价是异常退出占用内存、阻止模块卸载。普通退出正常释放。

实际构建源码的 ASan/UBSan 测试覆盖分配/map 失败、configure/default 失败、
root/child FREE、短 ACK/NACK/无回复、FREE 成功但 UNASSIGN 失败、重复销毁。
真实 STA/AP/LAN 队列删除重建没有发生 quarantine；随后直接删除重建 STA
VIF 复现 FREE 发送失败，新版本保留一个 9216-byte 映射及 16 KiB 物理页，模块引用 3→4，负值
收尾约 0.000146 秒，接口及硬件队列恢复，持久配置不变。随后完整重启
清除了该测试保留状态。

opt55 运行约 14 小时后，用户报告设备网页间歇卡住而管理界面正常。
当时 STA 仍关联，上游 DHCP/GTK 更新正常；已复现 UDP DNS 超时，以及
有线和 AP 的小 HTTPS 请求等待 3–5 秒。分阶段测试将主要等待定位到 TCP
建连；暂停新 ECM 加速连接仍出现延迟，直连同一上游的笔记本也出现 1–3 秒
等待。这些对照不能证明唯一根因在上游，也不能把 DMA 缺口认作卡顿原因。
已备份运行配置并把 dnsmasq cache-size 从 0 恢复为 1000。

opt56 最后一次有线/AP 真实网页请求各三次，全部返回证书校验的 HTTP 200；
有线 TCP 建连 19–29 ms、首字节 92–105 ms，AP TCP 建连 27–60 ms、首字节
141–210 ms。请求直接绑定接口、读取真实网页前 4096 bytes，绕过本机代理；
这些是短期观测，不能证明间歇性卡顿或历史首次握手异常永久消失。
最终实际 LAN/WAN 四元组均确认 `nss_v4.ported.accel_mode=2`，各完成
16 MiB 数据校验；LAN 约 576.58 Mbit/s，WAN 暂停正文接收的验证约
5.13 Mbit/s，仅作当前可用性/加速证据，不作为峰值吞吐。临时对象已清理。
临时 Wi-Fi profile/源地址路由已清理，本机返回原有线出口，Wi-Fi 关闭。
当前应保存为测试发行，不按稳定版推广。

factory UBI SHA256：
`dfa701760f8e07fdf151f8ad9b0c1910e555b50f52b93c7b0f48b82c343b5c89`。
镜像不含个人无线配置，保留设置升级沿用现有队列；清空配置后需先设置
网络，再按下方配置工具 preview/apply。私有备份与日志留在桌面
`Redmi_AX3000_NSS_opt56`，发行附件只包含镜像、公开校验信息和说明。

## opt55 运行记录

设备已刷入并验收 opt55（`r0-nsslan-opt55-fe7e690dcd`），Linux 6.12.108。
完整构建的四种镜像、实际 factory/sysupgrade 内部版本和十一模块 SHA256
均已核对，运行中的四个可选重试工具文件也与构建产物一致。七份持久配置
在升级、完整重启和无线 VIF 重建后哈希一致，原始 SSID、密码、MAC 和
拓扑保留；WMM 启用，STA power save 为 off。

笔记本未关联上游时，opt54 原 MAC 连续三次完整重启连接成功；opt55 的升级
首次启动、一次完整重启及一次真实 STA VIF 删除重建也连接成功。
opt55 的 STA、AP、LAN 三个 NSS FQ 根队列均自动恢复为 128 packets / 5 ms，
ECM IPv4/IPv6 stop=0、interface denied list 为空，上下行 rate 字段均为 0。
实验性的首次 M1 主动重试默认关闭，运行服务已禁用、没有进程；EAPOL trace
关闭，EAP CCE 路由恢复原规则。连接成功不依赖这些实验功能或笔记本关联。

独立连接的运行验收已通过，但此前首次握手故障的唯一根因尚未证明，不能
保证上游状态变化后永不复现。以下保留失败对照和证据范围。历史失败样本反复出现认证、关联
status=0，随后约 3.1 秒被上游以 reason 15（四次握手超时）断开；失败窗口
尚未在 NSS normal RX 看到该 STA 的 M1/M3。不能据此判断上游未发报文。

用户提供的 USB 备用网络已通过绑定接口的 HTTPS 验证，支持持续诊断；
笔记本关联上游的测试 profile 没有默认路由，不替换本机备用出口。
本次已实际复现：笔记本关联同一上游后，路由器原有失败重试随后完成握手，
额外发送 SELECT_NETWORK 控制命令之前，STATUS 已是 COMPLETED。
M1/M3 经 NSS normal VDEV RX、共用 netdev 提交到 supplicant；M2/M4 NSS
提交状态为 0，没有观测到 format/key gate 拒绝。

随后笔记本关联时的一次 warm reconnect 成功；断开笔记本、关闭其 managed
接口并保持 monitor 固定 149 / 80 MHz 后，紧接着重启路由器也在首轮关联中
成功。此结果不能推翻此前独立冷启动失败：上游近期关联留下的状态及间歇性
故障仍待排除。不得以一次成功宣称根因已修复。

空口证据有明确限制：此前 filtered pcap 只包含正常管理帧；另一次未筛选
捕获实际随扫描跳频道，仅有 beacon/probe response。二者均不能证明没有
发送 M1，也不能验证此前 TA 全零的解码输出。当前增加了固定频道、正常
握手正向对照捕获。抓包私有保存，只分析有界非秘密报头，不输出密钥材料。

NSS EAPOL ABI 定义 `dir=0` 为 TX、`dir=1` 为 RX；type19 的 TX exception
重发语义仍未经固件证据确认，当前没有依据修改包的丢弃或重发规则。观测
参数默认关闭，解析器及 TX skb 消费后的日志边界已通过 ASan/UBSan。

opt52 修复了 radio buffer config 的实际 payload：radio_if_num 与 buffer
配置合计 12 字节，旧声明 8 字节漏掉最后字段。请求使用 driver-owned
cookie、可取消等待和回调排空；完整回复校验 type/interface/length/echo。
运行中两个 radio、四个 range 共八个请求都得到完整 12 字节 echo ACK。
仍保留每 range 8192 的原 buffer 配置；该字段未被证明是排队深度或可在线
缩减的 credit，不能为了延迟盲目降低它。

opt53 增加 VDEV UP/DOWN 的私有 tracked request：匹配接口、消息
类型、ACK/error，等待有界，取消时先排空回调再释放 waiter。ACK 只代表
接受请求；UP 完整八字节回复的 MAC echo 仅记录，不作为未规定的 readback
契约。保留 WMI UP → NSS UP 的既有顺序，STA/AP 的失败回滚只有在 WMI
DOWN 提交成功时才清 `is_up`。这补齐了原先只看 TX submit 的确认缺口，
并不等于已定位握手超时的根因。

opt53 同时在 trace 开启时统计每 VDEV 的普通 RX callback、短包、可识别
EAPOL、解封装拒绝与交付拒绝。新 VDEV 在注册 callback 前清零，计数从
`monitor_stats` 只读展示，避免把 EAPOL 专用日志为空等同于 callback 未到。
原生测试执行真实 state callback 的 ACK/NACK、身份和 header-only 访问
边界；waiter 取消顺序只做结构检查，不能称为并发取消的运行验证。

opt53 的失败启动已确认每次 UP 为 ACK/error=0、payload=8、MAC echo=1，
DOWN 为 ACK/error=0、payload=4，提交至确认约 10–70 ms。失败窗口的已解析
VDEV 普通 RX 计数为 0，NSS 外部 SoC 的 delivered/REO reaped 也为 0；
确认 UP 并未使握手恢复。当前 peer 的 TID5 GET_QUEUE_STATS 返回有效完整
payload、实例匹配，BAR_received=1、processed MPDU/MSDU=1、约24 bytes，
TID0/16未处理数据。不能把正常 ADDBA/BA 控制交互当作 EAPOL 到达。

失败空口对照有五次该 DUT 的成功认证/关联、随后约3.1秒 reason15；没有
可解码的 M1或合法上游→DUT data。相同固定监听已抓到成功的 legacy 6 Mb/s
M1–M4，仍不能排除捕获前丢失。TA零/FC零/HE元数据记录仅出现在首次失败
窗口，未随其余四次重试重复，不等同于 M1。合法 DUT TX 的 PM位全0，
对应AID的TIM位全0，没有 Null/PS-Poll，不支持已公告的睡眠缓存解释。

定向探测但不关联的笔记本未使 opt53 恢复；随后实际关联、上游网关通信也
未必使其恢复。HT/VHT临时禁用、单独重建 STA VIF、真实临时 MAC、opt52
关闭两 SQM 服务的冷启动均未恢复。所有临时参数已还原，七份配置哈希不变，
SQM/NSS监护服务和硬件 FQ已重新启用；这些对照不作为最终配置。

opt54 增加仅 root 可写的 `nss_eap_route` 诊断控制，操作既有
EAP CCE→WBM规则；普通 NSS 卸载、硬件整形、rate字段不变。WMI返回只代表
提交结果。规则删除和重新添加时均仍出现无M1握手超时；已重新提交原规则。
这不证明固件确实执行了DEL，也不证明未经授权的EAP会被普通路线豁免。

上游公开管理页识别为 TL-WDR5620千兆版，硬件/软件版本尚未识别。新电脑
MAC的同一捕获先出现 AID2、无M1、reason15，再出现AID5和完整M1–M4。
另外路由器运行日志有AID6失败，故不得把AID5/6写成必成功，或根据AID
修改驱动字段。两张不同无线网卡都出现过首次握手超时，仍需区分上游状态、
空口条件和客户端路径；并行monitor是笔记本实验的额外条件。

一次受控试验在ASSOCIATED约1.4秒仍无M1时主动发送DEAUTH_LEAVING，下一次
关联AID5、WPA/DHCP成功，笔记本未关联上游。但其后的冷启动和多轮主动
leave未稳定复现恢复，因此不能宣称该策略修复独立启动。
`nss-relay-watch` 已实现受限的实验性策略：NSS硬件就绪、5GHz station、
WPA2-PSK且仍ASSOCIATED时才考虑重试，最多3次/120秒；正常/其它认证流程
不触发。数值状态保护、观测中断/同名netdev重建、原子状态保存已测试。
最后STATUS复查与DISCONNECT非原子，仍有M1恰好到达的小窗口；此功能默认
关闭，opt55 实际镜像保留该默认值，路由器的实验服务已停止并禁用。
控制器不改变NSS数据卸载和任何带宽/队列参数，也不作为当前连接成功的原因。

随后增加客户端身份对照：笔记本完全断开，路由器临时使用其已工作MAC时
握手成功；另一个不同MAC也成功。两次试验后恢复原始MAC、配置文件和
NSS硬件队列，原MAC本身随后在AID2上也完成握手。因此不能把更换MAC或
AID作为已证明的永久修复。opt54原MAC、无笔记本关联条件下随后通过三次
独立完整重启（连接约38–40秒）及千兆全双工、UDP/TCP DNS、20次网关ping
零丢包、绑定eno1且SO_MARK=666的16MiB证书校验HTTPS下载。
恢复路径与上游客户端状态有关的假设仍未证明；opt55 的运行验收见上文。

## 最终配置与负载验收工具

`scripts/nss/configure-hardware-fq.py` 默认只执行 preview，使用路由器实际 UCI
解析临时配置，并核对实时 SQM 没有变化。它明确创建三个 owned queue，避免
恢复出厂配置后 `nss_wwan`/`nss_ap` 不存在而失败。临时 UCI 验证已在 opt51
通过，三个队列上下行字段均为 0，WAN/AP/物理 conduit 绑定正确。apply 模式
会先备份，再启用三个 NSS FQ 根；已实际应用并保留备份。

`scripts/nss/wireless-hardware-load.py` 从实际 ubus/IP 状态发现 WAN 和受控
对端地址，替换旧脚本固定 `192.168.15.25` 的假设。只读 check 已识别当前
WAN 为 `phy1-sta0` / `192.168.15.19`；笔记本 Wi-Fi 关闭时明确报告对端缺失。
负载模式先检查临时 LAN 地址重复，保存并恢复双方原邻居项，清理 owned
namespace/server。已实际运行双向 WAN/AP 负载，修正了双网卡同网段的源地址
路由和邻居绑定问题；成功轮次的数据校验及临时对象清理均完成。

早期负载结果不支持宣称 WAN bufferbloat 已改善。无 FQ 的 WAN 下行 p95
为 597 ms、上行为 346 ms；128 / 5 ms FQ 轮次分别为 1651 ms、346 ms。
对端笔记本信号约 −80 dBm、重试多，完整 RTT 混有空口及上游队列延迟。
本机 AP 的 128 / 5 ms 轮次下行 p95 76.7 ms、上行 122 ms，均零丢包；
32 / 2 ms 轮次延迟、吞吐及丢包更差，已恢复并持久化 128 / 5 ms。
这些测量只报告观测值；不以低负载或无线 PHY 速率推算带宽能力。

## opt55 阶段运行验收

下表方向以有线 LAN 测试端为准：接收表示 Wi-Fi 对端发送、有线端接收；
发送表示有线端发送、Wi-Fi 对端接收。每个方向持续约 12 秒，数据内容校验
通过，测试 namespace/server 已清理、原邻居项已恢复。WAN 测试包含路由器
STA 与笔记本经同一上游 AP 的两段无线传输；笔记本信号约 −82 dBm。

| 路径 | 有线测试端方向 | 实测吞吐 Mbit/s | RTT p50 ms | RTT p95 ms | 最大 RTT ms | ping 丢包 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 本机 AP | 接收 | 102.16 | 12.1 | 37.5 | 123.0 | 0% |
| 本机 AP | 发送 | 86.12 | 23.6 | 63.1 | 95.3 | 0% |
| 5 GHz 中继 | 接收 | 31.84 | 14.7 | 70.6 | 140.0 | 0% |
| 5 GHz 中继 | 发送 | 33.65 | 22.8 | 77.8 | 184.0 | 0% |

空闲 AP RTT p95 为 30.3 ms，中继路径为 5.0 ms。不同轮次的空口、上游
状态及对端信号没有受控一致，不把最终数值与早期数值的差异归因于某一补丁。
这些测试确认当前双向负载下可用，不能保证所有未来负载、空口条件的延迟。
最终 AP/LAN NSS 硬件队列包计数随实际数据传输增长，末次快照没有 backlog；
该快照不代表整个负载期间从未排队。

opt55 有线链路为千兆全双工，UDP/TCP DNS、网关 ping 和 16 MiB 证书校验
HTTPS 下载通过。最终重连后另外完成实际 LAN/WAN 连接的四元组匹配，
均观测到 `nss_v4.ported.accel_mode=2`；测试临时地址、ECM 状态设备已清理，
持久配置未变化。LAN 16 MiB 测试为 569.86 Mbit/s；WAN 16 MiB 测试包含
暂停正文接收和有界接收缓冲，仅作可用性/加速验证，不作为最大吞吐测量。

本机已恢复有线 `eno1` 经 192.168.1.1 的主要出口，用户提供的 USB 网络
保留为备用；绑定两接口的证书校验 HTTPS 均返回 200。测试用 AP/上游
Wi-Fi profile、monitor、namespace 和源地址路由 515/516 已清理；原始
Wi-Fi 配置保留，Wi-Fi 关闭、managed 模式和原物理 MAC 已恢复。
原有代理 fwmark 路由规则保留。

固件及私有验收证据归档于桌面 `Redmi_AX3000_NSS_opt55`。
`opt55-squashfs-factory.ubi` SHA256：
`d5b258c13c2ff45f5556d47a300713b87083d2bc26480b44a4cf5b6cb599c256`。
已验证的 opt54 回退 UBI 同目录保留；用户先前恢复成功的 opt46 UBI 也保留。

## 既有硬件队列运行证据

- opt48 已刷入；11 个模块 SHA256 与完整构建一致，原有六份配置在刷机时保留。
- opt48 初次启动通过真实有线千兆全双工、网关 ping、UDP/TCP DNS 和
  16 MiB 证书校验 HTTPS 下载。
- 三个硬件 FQ 根队列已实际创建，配置无 `rate`、无 `nsstbl`；ECM 全局
  stop 开关为 0，interface denied list 为空。
- 原始 Wi-Fi SSID、密码及拓扑已用私有备份和结构化比较核对；仅增加 WMM。

以上是早期运行证据；opt55 阶段负载和 opt56 新增退出验收见上文。

## 既有故障与验证范围

opt48 重启后曾出现有线物理链路未恢复、LAN 与无线 WAN SSH 均不可达。
用户使用 opt46 factory UBI 恢复后，已保留原网络配置升级到 opt49。
源码发现当前 **12.2** stats-many 在 ACK timeout 时不减少 retry，并在
退出等待超时后释放尚被 worker/callback 使用的对象；这是需要修复的
明确问题，但当前没有设备日志证明它就是本次失联的唯一原因。

opt49 已完成完整固件构建及 factory/sysupgrade 内部版本与 SHA256 核对，
已归档到本机桌面 `Redmi_AX3000_NSS_opt49`，已刷入并核对运行模块。
补丁修复该路径：统计请求使用 driver-owned cookie；重试有界；
root stop 关闭提交、唤醒本地 worker、排空回调与 timer 后才释放对象，
整树销毁在释放 children 前先停止 parent statistics。原生测试直接提取
12.2 分支函数，覆盖无 ACK 三次尝试、ACK drain、停止以及重复退出。
构建后实际源码上的统计退出、qdisc 生命周期、control cookie 和绑定恢复
原生测试均通过，`git diff --check` 通过。

opt52 已验证有线千兆全双工、20 次网关 ping 零丢包、UDP/TCP DNS、16 MiB
证书校验 HTTPS，并在实际 LAN/WAN 连接上观察到 ECM ACCEL=2。硬件 FQ
已完成无线 VIF 重建后的自动恢复、双向负载及计数验证。
opt55 已完成独立连接、重启、重连、负载及本机联网恢复的运行验收。
首次握手的历史失败仍没有唯一根因证据；上游型号已识别，硬件/软件版本
未知，未改上游配置或升级上游固件。今后若复现，需按当时上游状态和空口
证据继续定位，不能把此次连续成功等同于永久根因修复。

无固定 rate 的 AQM 管理本机/NSS 队列；实测可能仍存在上游 AP 或
无线空口拥塞。此前使用 20 Mbit/s 限速的延迟结果不作为当前配置的验收。
