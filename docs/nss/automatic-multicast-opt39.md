# opt39–opt42：普通 AP 自动组播与原生目标契约

最新成功验收轮次为opt42b（镜像内部版本仍是opt42，factory仍为
`81823e63528ceee556d2f3a40f67403e959e63ca2118969f5cd6b08e640ac89c`）。
该轮在明确回退并验证opt41后重新部署，使用独立记录和一次性marker，
不是重放未知结果的升级。`r3050`八模块/六配置及NSS开启的真实有线
验收通过；`r3052`真实IPv6成员存在、IPv6无querier时IPv4六阶段通过；
`r3053`AP重建后同样的混合协议六阶段和有线/AP单播NSS验收通过。
启动曾有间歇性握手失败，根因尚未确定；IPv6无线数据和更多拓扑的验证
仍不应由这次IPv6成员测试替代。

以下保留前轮失败、隔离和实现证据。

最新部署状态：opt42 已完整构建并刷入，但冷启动 STA 回程持续四次握手
超时，尚未完成整机有线/组播验收；只进行一次 STA 重建后仍失败，已保留
配置回退到 opt41。同一已审阅 opt41 八模块和六配置匹配，回程仍握手
超时，因此当前不能直接归因 opt42 planner。本机使用独立 TP-LINK 上游
Wi-Fi，普通 HTTPS 通过。后续关闭无线NSS的host-path隔离实验恢复原
回程，本机通过真实有线验收并返回有线主路由，原六配置已恢复；无线
NSS本身尚未修复，见[隔离记录](wan-cold-start-opt41.md)。

## 当前运行结果

opt39 已保留配置刷入 `192.168.1.1`，实际版本为
`r0-nsslan-opt39-fe7e690dcd`。ath11k release35、NSS driver release32、
clients release3、ECM release7；八个运行模块与整机镜像构建产物一致，
六份配置哈希保持不变，包括 packet steering=0。

factory SHA256：
`9a6a54aca307b01cec7139eff93089d297235b2ca9db48a59f93bcd60318a232`。
factory/sysupgrade 的实际 SquashFS 版本都经过提取核对。
已保存 opt38b 回退镜像，SHA256：
`3e45c64dfada8a71bd2b81baa2d08e23fcb562447f2d5c3b63543d97958c4748`。

Fastsh `r2945` 完成启动和强制有线验收：eno1 1 Gbps/全双工，
UDP/TCP DNS、20/20 gateway ping、绑定 eno1 且 SO_MARK=666 绕过本机
代理的 16 MiB TLS 下载通过；测试期间 NIC 错误/丢弃增量为零。
这是现有无线回程的功能测试，不是千兆吞吐结论。
`r2953` 对独立有线 TCP tuple `192.168.1.127:45327 → 162.159.140.220:443`
取得 `nss_v4.ported.accel_mode=2` 并完成 16 MiB 下载。
`r2960` 对 AP 客户端 `192.168.1.100:45328` 取得相同 ACCEL=2 状态并完成
16 MiB 下载，原 Wi-Fi 关闭状态和有线主路由已恢复。

刷机期间使用本机独立 TP-LINK 上游 Wi-Fi，绑定 wlan0 的 TLS 和普通网页
均通过。返回有线时，备份默认路由移除前建立的代理连接曾超时；在删除该
路由并恢复原 Wi-Fi 关闭状态后刷新代理，`r2949` 恢复普通 HTTPS。
此修正只处理本次网络切换产生的连接状态。

**opt39 的自动硬件组播尚未验收成功。** `r2951` 真正完成了 AP 关联和
SSM 加入，RESET/create/member/toggle 的私有 ACK 正常，但桥层发布返回
`-EOPNOTSUPP`；`raw=0`、`pending=0`、`contract_drop=0`、`copy_drop=0`。
默认加载的 `nf_conntrack_bridge` 注册 POST_ROUTING 钩子，被初版“任何
egress bridge hook 均不允许合并”的保护条件拦住。试验结束后所有桥 sysfs
值、六份配置、主机 Wi-Fi 状态和自建 namespace 均恢复。

## 已接通的生产代码

`0609` 给实际 bridge forwarding 结果附加不可变 skb extension。HOSTS
只包含当前原生输出端口的完整、去重目标 MAC；容量、分配或条件失败时
执行原生 per-host M2U。ORDINARY 表示原生 group-DA 输出及已转换为
unicast DA 的 IP multicast 副本；后者在 TX 保持原生逐目标发送。端口 cookie
防止 ifindex 复用，独立 contract bit 发现 extension 被 scrub 丢失。
驱动还必须验证当前 Ethernet/IP 身份，不能只根据 extension 的存在选表。

extension storage 持有 packet/flight 引用；skb clone 共享 storage，COW
连 inactive slot 一并增加引用，最终 storage 释放才减少引用。flight 仅含
引用计数、pending 和 waitqueue，不回调驱动、VIF 或已卸载模块。

ath11k 的 worker/notifier 已在普通 Ethernet AP 上接通，与 debugfs 测试
开关无关。MDB、peer/key 和 VIF 生命周期变化先撤销 RAW 资格。worker
在 conf_mutex 下使用完整 bridge lookup 快照和独立 peer/state pins，
用 trylock 避免 cancel_work_sync 死锁；notifier 不重入 bridge 锁或等待 ACK。

ME 保持 mode5。MP12.2 的表命令写 `1-selector`，TOGGLE 切换数据表；
worker 在撤销 RAW 并等待 flight pending=0 后才复用旧表，建表完成、
ACK/epoch/peer 复核、bridge commit 成功之后才发布 RAW。普通未知组、
广播或不可用的硬件条件经 NSS 发送合资格 STA 的 unicast 副本；HOSTS
只使用原生给出的名单。ORDINARY 保留原生 hairpin 的全部接收者，不自行
排除源 STA。手动 ME 命令与运行中的自动控制互斥。

数据 TX 环已经由 NSS 接管，回退不调用 ath11k host DP TX。RAW 要求原生
目标集合与当前硬件表双向一致，拒绝硬件源 MAC 抑制会遗漏原生目标的情况。
其准入限定于当前 IPQ5018/QCN6122 的普通三地址 AP、确认的 Ethernet
格式、linear/non-GSO、偶数 data 地址、完整 checksum、MTU 内且非分片的
受支持 IP 帧。其它 shape 使用原生或精确软件副本。

按 MP12.2 已审查 H2N→VAP→ME 路径，这些条件排除了查表前复制/提前释放
host opaque 的分支；ME 在复制 RA、解锁之后释放原 packet。pending 归零
因此是旧表读取者屏障，**不表示已生成的无线副本已经发送完毕**。
同一普通 AP 的 DOWN/UP 只改 UP 状态，保留 ME、selector、表和 cmd22；
重新创建 VDEV 才建立新控制知识。不能在同实例 UP 时盲目重发 ENABLE5。

## opt40 的具体修正与验证范围

opt40 给 `nf_ct_bridge_post` 增加明确的 guarded hook 类型。其它
FORWARD/LOCAL_OUT/POST_ROUTING nft/BPF/未知 hook、TC、非 noqueue egress
仍不允许合并。在每包 collector 中进一步排除未确认 CT、helper、
SEQ_ADJUST 和 GSO，保留这些包的原生逐目标处理。capability 检查提前到
提交固件表之前，避免不兼容配置下反复重建、切换未发布的表。

这依据实际 `nf_confirm()` 的 helper/sequence-adjust 行为及 bridge
refragment 的 header restore 和 skb extension-copy 路径，不靠卸载连接跟踪。

实际 C 函数 ASan/UBSan 回归覆盖 storage COW/inactive slot/失败分配、
引用及 flight 生命周期、context 丢失、端口 ABA、身份重写、授权变更和
副本入队失败。planner 与真实 `br_multicast_flood()` 比较 IPv4/IPv6
INCLUDE/EXCLUDE、foreign S,G、完整目标集、cookie/seq 和源 MAC 抑制。
新增 guard 测试拒绝 helper、SEQ_ADJUST、未确认 CT、GSO、nft/BPF/未知
hook，只允许明确标记的 CT post hook。

opt40 完整构建 `r2961` 成功，14 份 prepared 源码与已审阅源逐字节一致，
MDB/planner、packet/flight/CT guards 和实际 TX 回退五组验证通过。
factory/sysupgrade 内部实际版本为 `r0-nsslan-opt40-fe7e690dcd`；factory
SHA256 为 `a086370d89d4b09a785cc5621d60ca9001b6078a0d84e0748ddd009182a440dc`。
`r2966` 仅发送一次 opt40 升级；`r2967` 已确认实际启动、八模块哈希、
六份配置、NSS/DSA/MCBC边界和真实有线 DNS/TLS 下载验收通过。
刷机期间本机备份链路普通 HTTPS=200。`r2969` 已恢复有线主路由，但真实
SSM 加入后的自动策略仍返回 `-EAGAIN`，未进入硬件组播发送。
`r2973` 只读快照导出确认实际 IPv4 `(S,G)` 和 `(*,G)` host 两条，均为
本机 AP 客户端；当次导出 querier4=1、querier6=0、capable=0。该导出
不是失败 worker 的同次输入，不能据此断言 EAGAIN 来自 peer 或 querier。
后续必须完成实际 SSM 允许/禁止源、未知组回退、退组/rejoin 切表及
新镜像有线/AP 单播验收后再更新结论。源码回归不能代替无线运行验收。

扩展只读探针在 `r2975` 加载后导致路由器意外重启。探针将
`NF_BR_NUMHOOKS=6` 当作实际 `hooks_bridge[5]` 数组长度，存在越界读取；
没有取得 panic 栈，不将推断写为已证实堆栈结论。该探针已停用，未写入
持久配置。重启后核对 opt40、NSS/DSA ready、原无线回程和六份配置，
`r2978` 恢复有线优先级并通过绑定 eno1 的直接 TLS 及普通 HTTPS=200。

## opt41 的 ECM 边界与真机结果

ECM 两个 BR_POST_ROUTING handler 在任何 FDB 查询、跟踪、分类及硬件
操作之前，对 AP/AP_VLAN 的 bridge contract 直接 NF_ACCEPT。这个 no-op
分支仅在 NSS/Linux-snooper、bridge snooping 和无线头配置同时启用时
注册明确 hook 类型。普通有线、单播和其它 backend 保持原有入口。
原生 M2U 的 unicast DA/IP multicast 也取得 ORDINARY contract，因此
它与 HOSTS collapse 均不触发 ECM 的逐副本状态/QoS 副作用。损坏 contract
保持不变，交给 ath11k 的现有 fail-closed 校验。MCU capability 仅对 AP
和 AP_VLAN 开放，其它无线端口不使用这个 hook 约定。

新增回归执行真实 helper 和 IPv4/IPv6 检测函数，检查 nonzero network
offset、截断/错误版本、unicast IP、AP/STA/mesh/monitor、缺失 profile
以及 skb 不被修改；既有 packet guard 测试继续拒绝 nft/BPF/未知 hook。
ath11k 只读状态补充失败阶段、实际输入的 querier/host/key/seq 和 peer
pin 结果，供下一次真机失败定位使用。

本轮允许 MCU 的运行边界是上述固定 hook 配置。尚未证明在已有 HOSTS
skb 生成后，动态注册新的 MAC 过滤 hook 能立即恢复该包的原生逐 host
判决；不能把后续包的 capability 拒绝当作这一窗口已闭合。

opt41 整机构建 `r2987` 成功，21 份 prepared 源码逐字节一致，七组实际
C 函数回归通过；ath11k release37、ECM release8。实际镜像版本为
`r0-nsslan-opt41-fe7e690dcd`，factory SHA256 为
`0d35c71b423c70fda726f14ad4e983f81dd45ace1de90041464f113e7c949909`。
`r2993` 只发送一次升级，`r2996` 八模块/六配置/真实有线验收通过。
`r2999`、`r3003` 两轮 IPv4 六阶段试验成功：允许源 128/128 收件且
RAW=127，禁止源零收件；未注册非本地组按原生 router-only 规则零收件，
未知链路本地组按 ORDINARY NSS UC 回退 128/128；退组后回退仍有效，
rejoin RAW=128 且 128/128 收件，无重复、异常目标或 contract/copy drop。
`r3000` 有线 16 MiB TLS 与 ACCEL=2 通过。

AP down/up 期间 STA WAN、boot_id、绑定 eno1 的直接 TLS 和普通 HTTPS
保持正常，新 VDEV 的 MCBC RX ACK、automatic running 与 pending=0 正常。
这不等于全部后续硬件组播验收通过：

- `r3002` 复用旧 UDP tuple 时正确收件 128/128、RAW=0；随后独立 tuple
  的 `r3003` 六阶段全部通过，不能据此给旧 tuple 未命中的原因下定论。
- `r3004` 重建后的 fresh flow RAW=127，但收件126/128，缺120/121；
  抓包确认发送端完整、最大发送间隔约35.5ms，接收最大延迟约2.21s。
  该无线瞬时丢包尚未定位，不归因为已证实源码错误或外部故障。
- `r3007` 延长接收窗口并记录 packet socket drops=0 后，数据128/128，
  但新增第三条 MDB host 使策略再次撤销。发送前后同次 worker 输入均为
  stage=2、hosts=3、keys=3、querier4=1、querier6=0、result=-EAGAIN。
  结合 planner 唯一的 querier EAGAIN 分支可判定新增无 querier 的 IPv6
  行阻塞了 IPv4；这是关联状态与源码的结论，未导出该行具体地址。

## opt42 的协议级准入修正

planner 两轮遍历只跳过明确的 IPv4/IPv6 且对应 querier 为 false 的
协议。未知/L2 协议仍严格拒绝；有 querier 的协议仍执行完整成员/键/源
过滤验证。所有 hosts/keys 继续保留在全 snapshot 和 seq 校验中。
实际 `br_input.c`、`br_device.c` 在无该协议 querier 时走 `br_flood()`，
其 AP 输出是 ORDINARY，不使用 HOSTS/RAW 或旧 ME 表，仍受原生端口
flood/hairpin 选择约束。querier/版本变化立即使旧 MCU 条件不匹配。

实际 planner 回归新增双向混合协议用例：IPv4 ready/IPv6 not-ready 和
IPv6 ready/IPv4 not-ready，ready 协议与原生目标比较一致；另一协议不在
ME 表且 ORDINARY 不能命中 RAW。启用另一 querier 后两种协议均建表；
全部无 querier 时不建表；未知协议仍拒绝。opt42 整机 `r3011` 已构建
成功，21 份 prepared 源码一致，实际 planner/TX 回归通过。

opt42 factory SHA256：
`81823e63528ceee556d2f3a40f67403e959e63ca2118969f5cd6b08e640ac89c`，
factory/sysupgrade实际版本均为 `r0-nsslan-opt42-fe7e690dcd`，保存 opt41
校验过的回退镜像。`r3015` 备用直连TLS/普通HTTPS成功后只升级一次。
`r3016/r3017` 新版八模块、六配置和 NSS ready 成功，但 STA/DHCP 未完成。
`r3018/r3019` 显示 reason=15 四次握手超时；`r3020` 一次 STA down/up
后仍未恢复。`r3021` 只发送一次 opt41 回退，`r3022/r3023` 证明同一
opt41仍存在该故障。路由器对目标上游的扫描信号约 -68dBm，PSK/CCMP
网络可见；未证明是射频、supplicant、上游或 NSS 数据路径中的哪一层。
最新失败不能写为有线正常或 opt42 已完成运行验收。

## opt42b 混合成员与生命周期实测

`r3052`由真实Linux客户端持有IPv6 UDP组成员 `ff3e::4242`，同时持有
IPv4 SSM成员。没有向另一个客户端伪造MLD，也没有修改主机持久配置。
当前客户端IPv6运行值原本为0，试验保留该值；先前测试工具误以为
该值应为1，已按实际运行状态修正。

joined/rejoined记录均为hosts=3、keys=3、querier4=1、querier6=0，
planner stage=0、result=0、members=1、groups=1、auto active=1。
这直接覆盖opt41曾经stage=2/EAGAIN的混合输入。允许源128/128、RAW=127；
禁止源和未注册非本地组零收件；未知链路本地组及退组后回退128/128；
rejoin128/128、RAW=128。所有阶段无重复、异常目标或packet socket drop，
contract/copy drop=0，pending=0。

`r3053`关闭并重新创建radio0 AP时，原radio1 STA回程、router boot_id、
绑定eno1的直接TLS及普通HTTPS保持正常。新VDEV MCBC RX ACK和automatic
worker恢复，随后真实IPv6成员保持时六阶段再次通过。六配置、桥sysfs
属性、本机IPv6运行值、原Wi-Fi关闭状态均恢复，自建namespace删除。
AP客户端 `.1.100:45328`和有线 `.1.127:45327`各完成16MiB TLS，
对应 `nss_v4.ported.accel_mode=2`。这些是运行验收，不能替代尚未完成的
IPv6无线UDP数据、多个真实成员不同源过滤或动态MAC过滤hook切换验证。
