# opt30b：NSS 冷启动格式事务与 QCN6122 并发监听验证

继续使用当前 `redmi_ax3000-25.12` 分支及 fe7e690dcd 基础，保留原 TP-LINK_3A
回程。目标仍是补齐 NSS 并定位 5 GHz 中继下行低速；模式一致性修复及监听
候选能力不等于带宽问题已经解决。

## 已完成的源码与构建验证

新增 ath11k `999-999z` 补丁及 NSS driver `0215` 补丁。mac80211 release28、
qca-nss-drv release31、nss-wifi release10；候选 revision
`r0-nsslan-opt30b-fe7e690dcd`。两套补丁在主仓库与构建树一致，零 fuzz 还原
通过，重新 prepare 的六个 ath11k 文件及 NSS core 与草稿逐字节一致。
驱动及 mac80211 编译通过；NSS driver 中原有 missing-prototype 警告保留。

初始 TX encap 与 RX decap 分别按各自 offload flag 选择。WMI 提交失败会
终止 add_interface；NSS 使用 private tracked 请求，仅在对应 ACK、error0、
正确 type/interface、8 字节 cmd/value echo，以及生命周期复核通过后发布
该方向的缓存。NSS core 在持实际 receive buffer 长度时验证 VAP command
ACK 边界，不能仅相信固件提供的 cm.len。

两条 WMI 命令提交成功且两个 NSS 模式得到 ACK 前，format-ready 关闭；
WMI vdev parameter 接口没有提供对应固件 ACK，不能把提交当格式 fence。
以 release/acquire 发布完整缓存。失败、
超时及不确定的单侧配置保留关闭状态，发送、接收、密钥及 AP_VLAN parent
门共同阻止继续使用。private cancel 排空已领取 callback 后才释放 waiter。

已经运行的 VDEV 不进行格式切换：同值更新不重新发送，异值请求恢复
committed offload flags 并拒绝。普通 N2H 没有逐包格式/epoch，MP12.2 的
cmd2 ACK 未证明旧 RX 已排空，不能把两条控制命令当格式 fence。

Native/RAW 接收增加 FC、完整头和 crypto trailer 边界检查；Ethernet 接收
检查 ETH_HLEN。STA MEC 在成功验证/解封装之后按真实格式取源地址。
Native WDS_LEARN/4ADDR 等特殊路径的完整合同仍待补齐，未宣称全面支持。

## 并发监听候选的范围

新增只读 module parameter `nss_monitor_test`，默认 false；启动脚本从
`nss-wifi.main.monitor_test` 读取，默认0。只有 QCN6122、NSS enabled、
Ethernet frame_mode、独立 RXDMA1 和 monitor 硬件路径同时满足时，试验才
声明 SUPPORTS_CONC_MON_RX_DECAP。两种 monitor VDEV 创建路径都显式
提交自身 RX_DECAP=RAW。不能以源码具备独立环推断目标 Wi-Fi FW 必然支持。

新增只读 `phyN/ath11k/monitor_stats`：merge 首 MSDU 的实际 decap_type、
完整基本 data/control/management 头、短/非法头、完整 single-TID BA、
提交 mac80211 数、FCS 标记和 monitor 启动次数。计数以 radio lifetime 为
范围，逐项读取不是一致快照；不是 peer 丢包分母，也不代表 pcap 已收到。
monitor ring 配置失败会尝试恢复环并停 VDEV；停失败时保留真实 STARTED
状态及 errno，不伪装已停止。

## 验证及交付状态

7组检查通过：实际格式事务/receive buffer/Native与BA头/monitor启动回滚
ASan+UBSan、NSS control cookie与callback drain、key ACK、TX gates、
EAP route、host rings，以及启动/VDEV/RPS/VLAN检查。启动测试补齐独立
config_get_bool destination；既有 VLAN fixture 只抽取目标函数，避免把
随后新增的无关 key helper 带入。

电脑独立 Wi-Fi UDP/TCP DNS 与校验证书的 HTTPS16384字节通过。路由器端
限时 observer 已静态交叉编译，仅读取 radiotap 接口，snaplen256、最长60秒、
最大32MiB，过滤原 STA MAC，保存 socket drops。当前低速根因尚未关闭。

首次 opt30（factory SHA256 a75024c3df0ad092bced58a60482d2c9d63c64b5d7e4801a2b7b3c623372f671）
启动时，格式 callback 错把 `nss_cmn_get_msg_len()` 的总长度与8字节 payload
相比，返回 -EMSGSIZE(-90)，AP/STA创建被关闭门拒绝。已回退原 opt29，
原回程、17/17 PN SUCCESS、有线NSS和DNS/HTTPS恢复，六个配置hash一致。
首次镜像、补丁、测试日志和完整 boot 证据保留在桌面 opt30 目录。

修正比较为 `cm.len`，实际 buffer 下界仍由 NSS core 校验；测试直接抽取
driver exports/nss_cmn.h 的真实 getter，并验证它包含 common header，
避免错误 shim 再次掩盖 ABI 语义。opt30b 的重新构建和7组检查通过，四种
镜像/profile hash一致；factory SHA256
c1a9bc08707784e6e6a768718d1d8b9de63db8f9bb75704bd3ee2a168fd8fb69。

## opt30b 实机与监听结果

修正后升级成功，实际两个 NSS 模式 ACK、模块hash、六份原配置hash、
STA/DHCP、密钥和 PN SUCCESS通过。20秒受控 monitor 使用独立VDEV
RX_RAW，原 STA 保持 encap2/decap2/ready1/failed0；同 TCP 两轮8MiB
完整校验证书并读到16MiB，整段35.590Mbit/s，两个body36.039/93.628。
不把时变链路与连接预热差异解释成修复增益。

监听实际首MSDU类型：RAW2847、NATIVE0、ETHERNET11953、8023=7；
merge_failed11960。control头2083、management625、data头92，但针对原
AP/STA地址的有效DATA均0。目标 WLAN.HK.2.7.0.1-01744 的匹配数据复制
仍随 STA Ethernet decap，现有monitor consumer拒绝该格式；独立环和
monitor自身RX_RAW不足以证明完整并发monitor能力。试验不转为默认支持。

router observer记录1563个样本，socket_drops0；LAN7149包、kernel drops0。
TCP接收unique16808012字节、重叠51840，RTT中位203.186ms，window
最大14217216、window_full/zero均0。1115次区间缺口填补，中位300.765ms、
最大643.056ms、结束无未填缺口。TID0保持generation1同paddr：processed
1401→13161、late1→33、hole0→588；TID16 generation17保持processed0。
这些是同队列累计变化，包含背景流量，不能作为空口丢包率或定位丢包段。

另外，RAW monitor输出按skb链节点交付，没有保证DMA continuation拥有
MAC头，也没有合成完整MPDU；NATIVE QoS会给多个MSDU复制同一头。
因此同Seq/Retry的输出节点不能当独立空口重传，短/非法头也可能来自合法
continuation，不能判为空口畸形帧。

已删除自建monitor，恢复六份配置；再从原配置重启，使
`nss_monitor_test=N`、`concurrent_decap=0`。默认运行的原STA/DHCP、
Ethernet NSS格式门、有线NSS、PN/密钥及有线UDP/TCP DNS、HTTPS复核通过；
电脑Wi-Fi恢复原来的关闭/managed状态。工作固件为opt30b，证据及四种
镜像在桌面 `Redmi_AX3000_NSS_opt30b`，回退opt29随同保存。
最终内部/QCN PN为34/34、17/17 SUCCESS，无失败、超时或遗留请求；
aging保持40000、ext_rx_stats0。独立原生过滤器复核AP/STA DATA均0，
client/server SYN各1，确认本组为同一TCP连接。

下一取证点为monitor专用的原始header TLV及MPDU_START有效字段。
QCN6122 compact descriptor为384字节，hdr_status_tag在256、PPDU在260、
hdr_status[120]在264；现有get_80211hdr返回的是msdu_payload，ETH2时不能
当原MAC头。低内存profile的通用header-status getter固定NULL，monitor
filter却单独要求PACKET_HEADER/PER_MSDU_HEADER，需验证实际tag/length及
FC/TA/Seq/QoS有效位，不能全局打开getter或从ETH payload制造原始空口pcap。
