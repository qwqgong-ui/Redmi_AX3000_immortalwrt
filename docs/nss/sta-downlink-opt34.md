# opt34：修复 NSS N2H 首段替换后的悬空链

运行固件为 `r0-nsslan-opt34-fe7e690dcd`，NSS driver release32，
mac80211 release31、nss-wifi release10沿用opt33。本轮保留配置刷入，
原5GHz中继、公网带宽和完整NSS扩展功能的目标继续保持未完成。

## 源码与构建验证

新增 `0216-nss-retire-linear-receive-chain-before-replacing-head.patch`。
旧linear N2H handler在收到第二个FIRST时释放旧链；如果新skb已有
frag_list而被拒绝，ring的head/tail仍指向已释放的内存。实际handler
的ASan测试在下一middle进入`skb_has_frag_list(head)`时复现UAF。
这不是在路由器内核中触发异常输入的验证，也未证明是现场故障根因。

修复在geometry校验和当前DMA unmap之后，对FIRST共同退休旧链，
扣减旧head保留的一次NSS_SKB_COUNT统计并清空head/tail，再处理
完整帧、接受或拒绝新首段。坏geometry继续只释放当前skb、保留旧链。
linear转paged时也清tail。NSS_SKB_COUNT是统计，不能把它称为固件
缓冲额度。paged handler的其他既有统计遗漏未纳入此补丁。

`test-nss-n2h-sg.py`执行实际handler，ASan/UBSan覆盖拒绝和接受FIRST
替换、随后的middle/last、整包替换、链长度/所有权/统计、DMA及错误
geometry恢复。修复前的UAF复现与修复后回归均通过。WIFILI实际C的
请求实例、取消竞态、私有等待、DMA边界和隔离回归通过。

canonical补丁零fuzz应用并逐字节还原设计稿，clean prepare后的
`nss_core.c`逐字节一致。完整目标构建通过，driver严格modpost没有
未解析符号或强制放行；四份profile镜像的大小及SHA256全部匹配。
编译中的既有missing-prototype等警告保留在原始日志，没有扩展修复。

## opt34刷入及实际流量

刷前核验opt33回退、备份六份配置与sysupgrade完整配置包；上传后
核对SHA256并通过`sysupgrade -T`。刷写仅发送一次，SSH退出246后
观察新版本启动，没有重复刷写。设备8个模块SHA256与完整构建一致，
六份配置hash一致，NSS core ready、有线NSS ready、原STA及DHCP正常。
monitor试验仍关闭。

本机独立Wi-Fi出口在刷前通过固定公网IP、SO_MARK666、接口绑定及
证书校验的HTTPS。刷后复检出现DNS/TLS失败；先恢复有线默认出口，
再重连本机Wi-Fi，并用DHCP提供的ISP DNS完成UDP/TCP及HTTPS验证。
不能将上游地址192.168.15.1或公共DNS的超时单独归因于NSS。

有线电脑通过192.168.1.1的UDP/TCP DNS、带证书校验的16KiB HTTPS
和普通网页访问通过。另一次绑定eno1并绕过本机代理的同TCP两轮
8MiB共16MiB传输，用时6.22685秒、整段21.55468Mbit/s；对应
`.1.127:45327 → 162.159.140.220:443`在流量期间为NSS IPv4 ACCEL=2。
六份配置未变；RX MSDU error、deliver drops、SG fail及TX enqueue fail
前后均0。N2H RX frag_list和Wi-Fi SG观察计数均0，因此正常实机流量
没有覆盖异常首段路径，不能称为异常输入的真机复现或带宽收益。

## IPv6验证边界

原本机wlan0、路由器br-lan/phy1-sta0的IPv6运行开关均关闭。本轮用
独立macvlan namespace作为有线客户端，本机上游Wi-Fi作为另一端；
临时使用两个ULA网段，不移动原eno1或改写持久配置。原运行开关、
临时地址/路由及namespace在试验结束后恢复。

自动邻居发现下，LAN端能发现br-lan；路由器对Wi-Fi测试端的邻居为
FAILED，ping返回Address unreachable，TCP未连接且没有匹配ECM规则。
这一结果不能确定失败在NSS、上游AP还是电脑接收端；完整IPv6自动
邻居发现及公网IPv6验收仍未完成。

上游两端设置明确的临时静态邻居后，双向IPv6 TCP均成功，并分别在
实际数据tuple观察到`nss_v6.ported.accel_mode=2`：

| 方向 | 接收字节 | 接收Mbit/s |
|---|---:|---:|
| 隔离LAN客户端→上游Wi-Fi电脑 | 25034752 | 19.84962 |
| 上游Wi-Fi电脑→隔离LAN客户端 | 24641536 | 19.71222 |

NSS IPv6 special RX/TX byte计数从0增至57534174/58292946，CREATE
请求0→4；队列drop、invalid interface、destroy misses、frag fails和
by-rule drops保持0。数据面是真实LAN→STA→上游AP→电脑Wi-Fi通路，
不能与单跳公网测试比较吞吐，也不能用静态邻居掩盖自动ND的缺口。

设备BusyBox ip不支持邻居修改，试验使用临时AArch64静态netlink助手，
仅设置固定测试地址。成功对照的12项清理均返回0，六份配置hash不变，
三个IPv6运行开关恢复原值、namespace删除。成功原始数据在归档的
`ipv6-static-netlink/`；早先自动ND与工具不支持的失败证据也保留。

原始流量、配置备份、四镜像和回退在桌面`Redmi_AX3000_NSS_opt34`。
factory SHA256：`cb9c1d7cd53ae404c3697701ade2fdb88ef0b82610dc2b948a72470ea3210077`。
