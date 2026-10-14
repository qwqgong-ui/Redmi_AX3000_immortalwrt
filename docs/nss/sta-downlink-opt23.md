# opt23：REO 命令登记、编号回压和恢复提交门

在 opt22 的实际 REO UPDATE 完成观测基础上继续制作。mac80211
release20，NSS driver 保持 release29；NSS buffer/TLV 为2048/384，
ring/pool 深度、BA 窗口、PN 和重复帧验证未调整。

## 已定位的源码问题和修复

原 `ath11k_dp_tx_send_reo_cmd()` 先发布 HAL 命令，再 GFP_ATOMIC
分配和登记 callback。早到 status 可越过登记；ENOMEM 返回时硬件
命令仍可能已执行。删除 UPDATE 和最终 cache-flush 都取得 DMA owner，
这类失败不能当作无副作用的提交失败。

新增 `999-993` 先分配 callback entry，在同一 reo_cmd_lock 内检查
提交门、调用 HAL、保留编号并登记 entry。NULL callback 不分配、不
复制 rx_tid，不增加活动队列的释放所有权。有 callback 而未请求
status 或缺少 rx_tid 的调用在发布前拒绝。

保留硬件的固定 ring 编号1…实际 entries。所有 NEED_STATUS 请求均
保留编号，包括普通 BA/PN 的 NULL callback 请求。HAL 先 peek 槽，
检查编号范围与 reservation，再编码；只有成功才移动 HP。旧 status
未消费时，该槽返回 EBUSY，不覆写、不发布；不靠超时回收，不引入
65535 次后永久耗尽的 token。此方案仍依赖每条命令最多回复一次的
硬件合同，不能区分一个已消费回复之后再次出现的同 ID/类型重复回复。

接收先解析公共 header，在 reo_cmd_lock 内核对 ID 和 status tag，
接受后才运行会修改 HAL resource 的 parser，再解锁、调用 owner。
错编号、错类型不会调用 owner，也不改变 HAL resource，
错类型保留 reservation 等待匹配回复。无 callback 的正确回复也
释放 reservation。threshold 是 unsolicited event，不能作为某条
命令的完成。状态失败可以结束编号等待，不把状态码改成 success。

cache-flush 在任意 extension 提交失败时保留完整未提交范围并退出。
旧循环只在 ENOBUFS 退出，会被新增 EBUSY 路径触发，随后 base flush
还会覆盖 pending_desc_size。测试覆盖首段和中间段失败后的重试。

reo_cmd_lock、update_queue_lock 和三个 list 提前在 core_alloc
初始化。关闭提交门增加软件 epoch；发送在预分配前取得 epoch，
发布时重核 epoch，旧请求不能跨关闭/重开提交。dp_alloc 只在旧
list/pending 已清理且门关闭时重开，按 update_queue_lock→reo_cmd_lock
检查待重试 owner；拒绝重开前不重置 UPDATE 统计或 monitor list，
不重新初始化已公开的锁。
关闭门保持已有 owner 和 reservation；原 ownership_uncertain
保留策略继续生效。

core_stop、启动失败和 recovery 清理前关闭提交并排空 DP NAPI/IRQ；
正常 pdev_destroy 在 mac_unregister 后关闭，dp_free/common cleanup
再作兜底。此门仅序列化发布，IRQ drain 仅排空宿主 callback，不是
硬件 DMA fence。现有 QMI OFF 丢弃失败/服务断开、外部 SSR 停止证明
和 remoteproc 返回值缺口仍在；本轮没有把这些路径宣称为全部 DMA
停止，也没有为只读 GET_QUEUE_STATS 增加活动 queue owner。

只读 reo_cmd_stats 提供 epoch、提交门、pending、请求/完成数、
callback 登记/领取数及分配失败、HAL 失败、busy、错类型和意外回复。
reo_update_stats 的 last_submit_errno 现在覆盖发布前分配/门控失败，
不再沿用 opt22 的 last_hal_submit_errno 标签。最新提交、最新回复
仍是独立数值快照，不构成当前 peer/SSN 读回。

## 验证进展

`test-reo-command-lifetime.py` 提取并执行实际 HAL 三类编码/发送、
DP 提交、status 领取及 cache-flush 函数，ASan/UBSan 已通过。测试
覆盖发布前 ENOMEM、闭门/隔离、真实线程早到回复、ID busy 与错类型、
HAL 编码失败不推进 HP、缩小 ring 的非法 ID、跨恢复 epoch、关闭后
仍可退休的 callback、extension 重试和70000次编号复用。完整 status
接收路径的实际 HAL parser 已测试：被拒绝的 FLUSH 不改资源位，
合法 NULL-callback FLUSH 仍解析；真实 dp_alloc 的拒绝重开分支保留
旧 owner、统计和 monitor list，并正确释放两个锁。

同一 harness 使用 opt22 原函数，已复现 ENOMEM 返回时 HP 已推进、
没有 callback owner。原 UPDATE 观测的实际 C 测试已适配新失败语义
并通过；CI 加入生命周期测试。canonical clean/compile 和完整镜像
已完成，恢复、共享 DMA、deferred owner 与 IRQ 阶段回归通过。
旧 fixture 缺少新 helper/字段导致的编译失败已修复；测试继续执行
实际 close/status 代码，没有把新门控替换成空操作。

## 镜像与首次启动

版本 `r0-nsslan-opt23-fe7e690dcd`，factory UBI SHA256：

`f2984f084be0b27a434dab08645997ddf93ba40e84f2a60b468380a8569fe384`

ath11k SHA256：

`5329b65fd86761fc32221304cc4dec603a56e54e8480455ff844674f97437e54`

NSS driver 保持 opt21/22：

`bed13e638104ebc23fdacd4297e6fbb6aa84481a6eaa600e81ad44488496660f`

桌面 Redmi_AX3000_NSS_opt23 保存镜像、opt22 回退镜像、profiles.json
和权限0600的刷前配置。初次 standalone metadata 指向旧目录，已改
用本次 target 根下 json_info_files，revision 和全部镜像哈希逐项
核对通过。上传哈希与 sysupgrade -T 通过；保留无 metadata 提示。
仅发起一次保留配置升级，关闭会话时 ubus Connection failed/exit246
不作为重复刷写依据。

首次新 boot uptime42.97秒确认新 revision/模块哈希，五份原配置
哈希不变，NSS offload=1、有线 READY=1/error=0，原5GHz上游已关联。
两个 SOC 均 accepting=1/epoch=1/pending=0。QCN6122 提交/完成19/19，
内部IPQ5018为17/17，allocation/submit/busy/错类型/意外回复均为0；
QCN UPDATE 的19条实际状态全 success。

## 原上游重连与编号复用

使用原5GHz上游，仅对radio1执行 down/up，没有修改配置。4轮累计
新增2/54/172/291条命令，已实际越过256槽的一圈；QCN累计submitted310，
NEED_STATUS请求/完成214/214、callback登记/领取85/85，pending0。
UPDATE queued/success180/180，所有提交/分配/busy/意外回复/错类型及
blocked/failed/resource-blocked/unknown增量为0。内部IPQ5018仍17/17。
原始结果在桌面opt23的reo-reconnect-r1/，Fastsh r2277。

两份config SHA256输出逐字相同，重连前后dmesg未匹配BUG/Oops/panic/
firmware crash或REO失败。恢复后网关3/3、localhost DNS和HTTPS下载
19137 bytes成功（r2278）。这验证了本次正常重连/编号复用，没有注入
真实错类型、丢失回复或Q6崩溃，不能替代前述SSR停止证据。

## 受控 STA→LAN NAT 下行

近距离 PC AP、自然 ARP、标准 MSS，空闲20秒，再分别测20秒并省略
前3秒预热。PC 上游 STA 与 AP 共用 radio，不能作为隔离空口的基准。

| 窗口 | 下行 Mbit/s | CPU / softirq | delivered / REO reaped | SG |
|---|---:|---:|---:|---:|
| P1 | 371.56 | 4.23% / 1.08% | 752509 / 752520 | 0 |
| P4 | 310.43 | 5.30% / 2.10% | 622615 / 622623 | 0 |

TCP retransmits为81/631，最高53°C，CPU保持1008MHz；最低可用内存
16968/21400KiB。P4三个活跃连接快照均为同4个socket的ECM ACCEL=2，
字节持续增长、slow path固定，driver fail/NACK为0。

P4后QCN总submitted511，NEED_STATUS319/319、callback153/153、pending0，
所有submission/slot/type错误为0。QCN UPDATE251/251、内部17/17；
负载期间没有新的UPDATE，仍不能读出当前硬件SSN或绑定peer实例。

空闲为3个NULL queue事件。QCN P1/P4的BA dup为50/28，Frame OOR为
1164/1424，FCS为81652/77857，PN类没有增长。FCS是SOC汇总，不能直接
换算这条iperf的丢包率。P1略高、P4低于opt22本轮值，原空口/PC
共用radio的限制未消除，不把这次修复宣称为吞吐提升。

原始数据在桌面sta-controlled-opt23-reo-r1/，r2279；CPU、REO原因、
完成及worker分析为r2281。PROJECT disable ACK=0确认，临时AP/NAT、
namespace和iperf/观察器已清理，五份原配置SHA256全部不变。最终
QCN submitted630，NEED_STATUS390/390、callback187/187、pending0，
错误仍0；原5GHz回程、电脑上游Wi-Fi、网关3/3、localhost DNS及HTTPS
19137 bytes均正常。最终网络检查为r2282。

## 后续观测的必要边界

peer refcount只保护peer对象，不能保护已移交到delete/cache-flush
链的qdesc。安全GET_QUEUE_STATS需要独立queue-instance DMA owner
引用、generation及query entry kind，并覆盖当前六处直接free和各
次owner复制/清零。WMI setup失败按可复用MAC/vdev/TID重新查找后free
也需绑定原实例。query超时不能释放ID或DMA pin；已领取callback的
取消必须排空status临界区。本轮没有增加这种query，也没有裸读活动
noncoherent DMA。

PROJECT的MMIO计数器0x3c000114同时用于公共32位回绕时基和timer
deadline；固件软件按CORE_FREQ的Hz标量构造每毫秒F/1000个tick，
默认F=850000000。官方toolchain的直接寄存器operand 0x114不能当作
这个MMIO寄存器名。实际clock source/divider及当前软件F与硬件一致性
尚未证明，worker ticks继续保持raw值，不能当作逐worker利用率。

带宽主目标尚未验收：已有 OOR/FCS 和空口波动不能据源码竞态直接
归因，本补丁不能在运行对照前声称提高吞吐。后续仍需稳定空口来源、
硬件当前 SSN/队列实例的安全读回，以及 IPv6、组播和长期稳定性。
