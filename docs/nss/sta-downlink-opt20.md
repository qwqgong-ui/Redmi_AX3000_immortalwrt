# opt20：标准 MTU 的 NSS 接收缓冲区与主机路径修复

在 opt19 上继续制作，mac80211 release 18。当前原厂参考 BIN、MP12.2
运行固件和各 RX/TX ring 深度不变。

## 源码修改

- `999-991` 把小内存 profile 的 NSS buffer bytes 从1816改为2048。
  HTT仍提交384-byte packet offset，SOC_INIT仍提交相同TLV size；
  两者共用2048-byte buffer。原单buffer容量1432不足标准MTU，修正后
  为1664。ring深度、RX descriptor pool数量和NSS时钟没有修改。
- `999-985` 将host HTT完成状态从错误的`desc+128`改为`desc+8`。
  原算法把byte offset加到16-byte结构指针上，可能越过当前32-byte
  descriptor，并误把MEC通知计为TX完成、扣减预算。
- `999-986` 用`skb_reserve()`对齐新分配的零长度host/monitor skb，
  替代不能移动这种skb的`skb_pull()`。两个monitor入口按硬件descriptor
  大小定位payload，fragment容量同时扣除实际descriptor与L2 padding。
- 保留opt19的MCBC TID修复及PN/duplicate检查；没有改变STA三地址模式。

标准MTU错配的固件指令、实际HTT/SOC_INIT参数及MSS实验见
[反汇编记录](firmware-reverse-2026-10-10.md#384-byte-tlv-与-1816-byte-nss-buffer-的-sg-阈值)。
MSS1300使SG从几乎每包一次降为0，但吞吐没有同步提升，因此不把SG
认定为全部无线瓶颈。交付使用正常MTU，不把小MSS作为规避配置。

## 宿主容量和源代码验证

当前AArch64 NSS正常EMPTY的core0最小尺寸为1984，
`NET_SKB_PAD=64`，从skb head分配、DMA映射、广告长度均为2048。
MTU更新不低于这个下限；reuse要求head容量至少2048，广告/映射
`max(tail_offset,2048)`。当前paged_mode=0、jumbo_mru=0、
reuse max_size=4096，故候选没有额外扩大宿主pool或buffer分配。
刷前证据在桌面opt19的`buffer-capacity-before-opt20.log`。

正常NSS pool来自NSS driver自己的EMPTY队列，与新的ath11k host
对齐helper分开。当前IPQ5018/QCN6122在NSS开启时跳过普通host refill，
monitor使用独立ring，MCBC callback的descriptor-at-head合同不变。
map/unmap长度仍配平。该审查没有覆盖全部其他平台或reuse DMA方向。

旧TX函数的单descriptor ASan/UBSan用例检测到错误偏移越界；修正后
MEC过滤、真实完成预算通过。RX测试遍历128种初始对齐、384/392-byte
descriptor与0…3-byte padding，覆盖完整多片容量。MCBC真实QoS/CCMP、
共享DMA和完整relay回归通过。

relay的旧fixture只使用256-byte TLV并硬编码1816，不能发现本次问题；
现在从准备源码读取实际小内存buffer定义，同时执行256/384-byte
packet-offset与完整MTU容量用例。旧配置在384-byte容量断言失败，
2048配置通过。参考快照、44项配置清单和CI YAML核对通过，未派发CI。

最初buffer补丁排在ring-depth补丁之前，改变其context导致prepare失败；
已移到`999-991`在`999-990`之后，没有更改原ring-depth补丁。
最终canonical clean/compile和modpost通过。

## 最终镜像

版本：`r0-nsslan-opt20-fe7e690dcd`。
factory UBI：17694720 bytes，SHA256：

`8a94a785f727262d6671f78908bfd04b77029a26c175aab8e045f4fcdc0c6c4d`

最终staging的ath11k SHA256：

`8f6e0484a9ab001cd5dde3e12a0bda846980f824264b891fddd1a6de45f7f0d7`

镜像、profiles.json、配置归档和opt19回退镜像保存于桌面
`Redmi_AX3000_NSS_opt20/`，配置归档权限0600。
上传哈希和`sysupgrade -T`通过，factory UBI没有嵌入image metadata的
提示继续保留；仅发起一次保留配置升级。运行验收继续记录如下。

## 标准 MTU 的运行验收

首次启动观察在uptime42.98秒确认新revision、上述ath11k哈希、
原5GHz回程与有线NSS READY/error=0；五份配置文件哈希与刷前一致。

电脑Wi-Fi软关闭导致r1/r2在测试前退出；恢复radio并完成路由检查后，
r3使用原近距离并发AP方法，VHT80/信道149、每项20秒加3秒预热，
自然ARP与默认TCP MSS。受控AP广播/定向ARP两端均3请求/3回复。

| 项目 | 本机前 / 后 Mbit/s | LAN NAT Mbit/s | NAT CPU / softirq |
|---|---:|---:|---:|
| P1 | 383.94 / 321.45 | 318.93 | 4.42% / 2.02% |
| P4 | 284.62 / 275.11 | 309.85 | 6.12% / 2.39% |

第二活动radio的P1 RX delivered/SG/REO增量为643127/0/643131；
P4为599077/0/599084。默认MTU不再跨两个buffer，描述符处理约一包
一个。RX deliver drops、descriptor alloc fail、hardware unavailable
与REO error保持0。活动P4 NAT连接543–546连续三份快照均ACCEL=2，
reverse bytes增长、slow_path_packets按连接保持3/3/3/4，
driver fail/NACK/flush/no-action为0。

这证明容量错配和额外descriptor开销在真机消除，不能等同于峰值
吞吐已提升。opt19单流253.23/P4 320.08与本次318.93/309.85的方向
并不一致，本机前后及发送端也有波动；未在固定空口条件下证明全部
5GHz中继带宽问题已解决。CPU1008MHz、最低MemAvailable15644KiB、
最高66°C；未重复600秒负载。

原始数据、CPU分析与活动连接快照在桌面
`sta-controlled-opt20-r3/`。r3结束已逐字恢复原无线/网络文件、电脑
上游Wi-Fi、并清理临时AP/NAT/namespace和测试服务。

## 主机路径与最终恢复

关闭无线/有线NSS并重启的host对照完成原5GHz WPA/DHCP。
最初负载命令使用了本机BusyBox ping不支持的小数interval，该命令
未产生20次ping负载；随后用整数interval重新完成20/20网关ping。
TX计数从135增至159包，完整日志未出现此前的completion mismatch、
invalid MSDU、Oops或BUG。该短时对照不代替长期host吞吐/稳定性验收。

最终恢复原NSS配置并再次启动，nss_offload=1、wired READY/error=0。
五份配置哈希与刷前相同，ath11k哈希与最终镜像一致；paged_mode=0、
jumbo_mru=0、reuse max_size=4096、core0 min_sizes=1984保持不变。
原2.4GHz AP＋5GHz STA布局、默认phy1-sta0回程及电脑直连上游Wi-Fi
恢复，临时AP/NAT/namespace、测试进程和本轮root配置备份文件清理。

路由器与电脑到上游网关各3/3 ping；路由器本地DNS解析成功，HTTPS
下载openwrt.org的47612 bytes完成。223.5.5.5的公网ICMP为0/3，保留
该失败，不将其单独解释为无法联网。已有SSDK port0 notify告警仍在，
没有扩展本轮去改动该外部通知路径。最终证据在
`host-mode-load-corrected.log`、`final-state-and-network.log`。

剩余：原上游的广播ARP互操作、空口/回程带宽波动、长期握手、IPv6和
完整Wi-Fi组播成员同步仍未闭合。本轮只确认标准MTU双buffer错配、
MCBC TID与已验证的host错误路径修正，不宣称NSS全部功能完成。
