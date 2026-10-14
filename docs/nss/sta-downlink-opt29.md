# opt29：NSS 密钥授权前等待 REO PN 执行状态

继续在 opt28 基础上补齐 NSS 并排查 5 GHz 中继下行。当前已完成
源码修复、实际 C 故障测试、canonical 补丁还原及最终完整镜像
构建；已保留配置安装opt29并完成启动、重连、传输与联网验收。
原回程低速尚未解决，不将命令时序修复当作带宽已改善的证据。

## 源码缺口和实现

旧 `ath11k_dp_peer_rx_pn_replay_config()` 对每个活动 TID 提交带
NEED_STATUS 的 UPDATE_RX_QUEUE，但 callback 为 NULL；提交成功
即返回0。随后 MAC 会执行 NSS cipher/SEC_TYPE/AUTH 配置，没有
等硬件执行状态。原厂及 MP12.2 的 SEC/AUTH ACK 不提供 Wi-Fi
密钥或硬件 PN 安装凭据，见[反汇编记录](firmware-reverse-2026-10-10.md)。

`999-999` 为 PN UPDATE 新增独立 command kind 和私有 completion。
发布前分配 request/entry，pin 当前 PUBLISHED 且未 retiring 的
队列；callback 不保存 peer、rx_tid 或 key 裸指针。全部活动 TID
先提交，再在锁外使用一个1000ms截止时间等待。每个 TID 单独
复制命令，避免 HAL 原地编码影响后续字段。

只有全部 SUCCESS 且原 peer、完整活动 queue 集和 REO epoch
仍一致才返回0。BLOCKED/FAILED/RESOURCE_BLOCKED、软件DRAIN、
部分提交错误、超时、
队列替换或关闭均失败；MAC 沿既有失败隔离路径返回，不继续 NSS
key configure/authorize。未改变 PN/SSN、默认aging或旧key回滚策略。

密钥通道门禁复用 `ath11k_mac_key_install_available_locked()`。
首次 PN 发布、完成重验和 MAC 进入 NSS 前均检查；NSS key_check
与 tracked enqueue 同持 base_lock，覆盖关闭与各阶段 ACK 间的
竞态；最后AUTH ACK后再验证原实例和门禁。仅关闭 WMI/key 门
而 REO 仍开放时，硬件 SUCCESS 也不授权。

超时只释放 waiter；ID、command 引用与队列 DMA pin 留到匹配
状态到达。PN observation 不使用 generic RETIRE callback，不
将活动队列标成退休。PN outstanding 纳入 quarantine/reopen，
关闭后无法证明硬件完成的 owner 继续保留。status-ring 临界区
覆盖 claim 至 complete/put；短 common header 在领取 ID 前拒绝。

新0400 `reo_pn_stats`仅记录事务、命令状态、超时、epoch和等待
时长；不输出 key、MIC、nonce 或 PN 值。SUCCESS 是这些 descriptor
的命令执行证据，不是后续包选择该队列或当前 PN 值的读回证明。

## 源码验证

实际 C / HAL 的 ASan/UBSan 测试覆盖17个 TID 的全部完成、
BLOCKED/FAILED/RESOURCE_BLOCKED、软件DRAIN、短/错类型/重复状态、
一个等待预算、超时
后晚到状态、peer unmap/同身份替换、REO/key 关闭、部分提交、
发布前分配失败和 quarantine；队列引用、DMA owner与活动状态
均检查。MAC 原函数测试注入 PN 错误，验证 NSS 没有提交、key/PN
软件状态没有被当作成功提交。NSS ACK测试覆盖三个阶段的关门
及unmap，包括最后ACK后的失败返回；debugfs原C也在ASan下执行。
硬件状态3与软件DRAIN=255分开统计，不用DRAIN作为数组下标。

10份文件的 canonical root/build 补丁一致，零fuzz还原与草稿
逐字匹配。补丁 SHA256：
`2bb917ef930a84fa91652b9ae67516e047713ac0edb6fcf2b69cf0160a462b79`。

最终12组canonical C回归均通过（r2555），包含PN、REO submit /
UPDATE / query / aging，以及WMI/key、NSS ACK/TX/EAP、shared DMA
和REO通知。关联fixture补齐有效TLV长度和新的kind，不放宽源码
错误判断。prepared的10份源码与草稿逐字一致；受保护AHB文件
仅对该文件sudo读取到fixture并逐字复核，没有更改源文件权限。

## 编译、运行和待办

最终干净模块构建r2554和完整镜像r2555通过，mac80211 release26 /
`r0-nsslan-opt29-fe7e690dcd`，NSS driver保持release30。早期候选
未刷入，单独保留；最终镜像包含状态枚举和最后ACK门禁修复。

四份profiles image的实际size/hash与metadata一致；partial build
残留的bin sha256sums按原九个文件名重新计算并核对。factory SHA256：
`ce07ed71aba9f0000c0c0b36ab7dce2b4730c1200759c69d1ee5a391c8fad768`。
ath11k：`dc188086ec1b8942ae0b4116338477e0401cf745aed19ec7e05e83f41822e672`；
AHB：`adfedf707dcbedc41400f7c361dfa6e587fda05bdc369c2a239b984ba84419b0`；
PCI：`ad0f894b7cb2619166267f509fbe31f2fe3774411876f08d3d823296a1232961`；
NSS drv：`2a5172ea10c04938342bf6883143c65cddf3fcd369ee07825cf37073b571fc36`。

镜像、精确opt28回退、metadata、测试原日志和0600配置备份已保存
桌面opt29目录。升级前原六份配置SHA与opt28验收结果一致。

r2562仅发送一次保留配置升级，已启动opt29；初次验收脚本把
SOC统计当作per-PDEV路径而失败，修正到phy symlink的父目录后
以observe-only完成r2564验收，没有再次升级。设备四模块与六份
配置哈希一致，原STA/DHCP、有线NSS ready1/error0/uncertain0。
首次boot内部PN2个事务/34条、QCN1个事务/17条均全部SUCCESS，
failed/outstanding/各错误状态/timeout/stale为0。last_wait_ms=0
按jiffies记录，不能据此推断精确零延迟。

升级前独立Wi-Fi曾出现UDP/TCP DNS和HTTPS超时，保持上游关联、
网关邻居REACHABLE；重新关联并发送本站15.22的三个ARP公告后，
UDP/TCP DNS223.5.5.5均rcode0、2个answer，HTTPS200/16384字节
通过（r2561）。未修改上游配置，也未仅凭这组操作归因其故障。

同一公网端点162.159.140.220的opt28新基线为4MiB，完整请求
16.305Mbit/s、body28.169Mbit/s。电脑Wi-Fi关联原上游，同时下载
强制绑定eno1并使用mark666；信号/公网波动仍影响比较。

r2566原radio1 down/up抓到完整M1–M4（r2567分析），M1→M2
4.220ms、M3→M4 3.866ms，STA/DHCP恢复、四个消息均存在。首个
抓包调用因sudo切换SSH known_hosts上下文而在设备操作前失败；
改为正常用户运行、为升级后/tmp重新上传自己的EAPOL collector
后完成，未禁用host key校验，未额外重启/升级设备。INFO/时间戳0、
ext stats0、六份原配置恢复；自己的monitor与采集进程已清理。

重连与4MiB下载后内部PN仍34/34、QCN累计51/51 SUCCESS，合计
85条；两SOC failed/outstanding/错误状态/timeout/stale均0。
两phy的WMI sent/completed各5/5，expected/received tuple一致，
mismatch/unexpected/timeout/abort/send_failed/poison均0。

opt29同端点/接口/mark的4MiB完整请求14.282Mbit/s、body22.936Mbit/s。
没有观察到带宽提升；这是两个不同时段的单次公网样本，不能据此
认定稳定改善或回归。未排除WAN、RF和上游波动，也没有通过新
状态计数证明后续包实际绑定这些队列。

r2568最终电脑恢复开始时的Wi-Fi软关闭状态，经eno1/路由器原
Wi-Fi回程联网：UDP/TCP DNS223.5.5.5均rcode0、2个answer，
HTTPS200/16384字节。NSS1、有线ready1/error0/uncertain0、
四项aging40000、原STA/DHCP与六份配置哈希均正常。已保存最终
镜像、opt28回退、配置备份、握手/运行原证据和诊断源码。

原回程低速与间歇握手根因仍未定；完整 PN/fragment/replay 行为、
healthy DISABLE失败的NSS失效策略及VLAN key-owner合同仍有待办。
