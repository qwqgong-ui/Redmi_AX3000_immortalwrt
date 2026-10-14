# NSS qdisc、IGS 与 PPPoE 接入

本次按用户要求先补齐常用 NSS 组件，再构建和实机验证。工作继续在
`redmi_ax3000-25.12`，保留原有无线、DSA、组播和恢复补丁。

## 实现范围

- qdisc：FIFO、CoDel/FQ-CoDel、token bucket、HTB、BF、priority、WRR/WFQ、
  WRED、blackhole；IPQ5018 使用 NSS firmware 后端，独立于 PPE。
- IGS：`nssmirred`、IFB、conntrack ingress QoS 标签和 ECM DSCP/IGS 分类。
- 用户态：iproute2 NSS qdisc/action 解析器、`tc-full`、SQM 脚本及 LuCI SQM。
  安装不创建限速规则；共享 DSA conduit 可使用按 WAN 方向选择的独立队列。
- PPPoE：会话 manager、内核 channel/addressing hooks、ECM PPP/PPPoE 后端。
- IPv4/IPv6 重组：驱动开关及对应 DTS 入口。

内核接口以固定的 IPQ50xx 参考树为来源，重新定位到实际 Linux 6.12.108。
IFB firmware 统计采用单独锁和计数，避免与原生 RX/TX 队列统计写者竞争。
DSCP conntrack extension 保留 offset/size 上限检查，并更新 extension 数量上限。
新增 xt_DSCP 和 ECM PPP 符号的包依赖也已补齐。

IGS 控制 ACK 由驱动拥有的同步接口处理，cookie、接口和消息类型均需匹配。
超时及发送失败撤销当前请求；回包不携带客户端函数或裸 mapping 指针。
action ID 与 host record 在提交 firmware 配置前准备，失败只清理本次创建的
IFB；RESET/CLEAR 未确认则保留 quarantine，禁止复用。record 持模块/设备引用，
netdevice unregister 时撤销回调并释放设备引用，避免阻塞 Linux 注销。

PPPoE channel 事件以可睡眠 mutex 保证顺序，通知前持设备引用；channel holds
在 downl 保护下取得。PPPoE socket 的 channel ops/private 在重连中保持稳定，
addressing 在 BH/socket 锁下取得设备引用，manager 保留到 CREATE 事务结束。
DESTROY 失败也撤销 host registration 后再释放 context。

## 已完成的验证

- opt43 全镜像构建 `r3133`：退出 0。23 份 prepared 源码与审查版本逐字节相同。
- 实际 NSS IF C 代码 ASan/UBSan：ACK、NACK、发送失败、超时、迟到 ACK、
  interface/type 不匹配、cookie wrap 和客户端 callback 隔离通过。
- 启动控制错误路径、VDEV、RPS 和 127 个 VLAN slot 的现有回归通过。
- opt43 保留配置刷入：11 个模块文件 hash、6 份原配置、STA/DHCP、
  NSS/DSA ready、AP host policy 和实际有线 DNS/TLS/16 MiB HTTPS 通过。
- opt43 factory SHA256：
  `f8c0d43fec82ce3d77d9ffe11d73fa89874716004f408c4f47b5f6ac9dbea820`。

opt43 把 QoS pool 输入按 bytes 填写，但此驱动接口使用 MB。opt44 将默认输入
改为 `1`，并修正扁平的 `/proc/sys/net/ecm/igs_enabled` 路径。
opt44 完整构建 `r3146` 退出 0，实际 factory/sysupgrade payload 版本已核对。
factory SHA256 为
`358939c146a7696b505819b84ec612f3b8bc25e9018985464ce97d0fe67c6073`。

## opt44 实机结果

`r3148` 确认 opt44 版本、11 个模块文件 hash、6 份配置、原 STA/DHCP、
NSS/DSA ready 和实际有线上网。QoS pool 参数在分配后为 `1048577`，
输入 `1 MB` 转换后实际分配约 1 MiB；扁平 IGS sysctl 已置 `1`。

公网下载基线波动（一次 1.35 Mbit/s、另一次 19.52 Mbit/s），不能用它
单独证明 shaping。改用两组隔离 macvlan 端点的 L3 流量，经过路由器
转发，在共享 `eth1` conduit 上配置 8 Mbit/s token bucket＋FQ-CoDel。
16 MiB 实际传输结果：

| 测试 | 吞吐 |
|---|---:|
| 原队列、不限速 | 895.98 Mbit/s |
| NSS egress token bucket＋FQ-CoDel | 6.83 Mbit/s |
| IGS nssmirred→IFB token bucket＋FQ-CoDel | 6.75 Mbit/s |

原始记录：`r3155`，本机
`~/桌面/Redmi_AX3000_NSS_opt44/local-qdisc-cbd5a102/`。
创建、firmware 统计读取、正常 RESET/CLEAR、队列和 IFB 撤销均完成；
隔离端点、临时地址、原 qdisc 和六份配置已恢复。

最终验收 `r3156` 已回到 eno1 主路由、移除备用路由、恢复原 Wi-Fi 状态
和代理自动选网。千兆全双工、UDP/TCP DNS、网关 ICMP、TLS/16 MiB HTTPS
与普通 HTTPS 200 均通过；`r3158` 的独立 16 MiB 有线流实测
`nss_v4.ported.accel_mode=2`，配置再次核对不变。

PPPoE 尚未在真实会话中验收。GRE、PPTP、L2TP、6rd/IPIP6、安全及 mesh 等
独立扩展未纳入本次默认 profile，也未声称支持。

回退镜像仍使用已验证的 opt42b：
`81823e63528ceee556d2f3a40f67403e959e63ca2118969f5cd6b08e640ac89c`。
每次刷入前验证本机独立上游网络，刷入后必须检查实际有线上网。
