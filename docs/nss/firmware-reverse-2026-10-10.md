# 2026-10-10 NSS 固件反汇编与 GMAC 接收长度修复

## 输入与工具

沿用 [原厂采集资料](stock-ap-mp02.1/manifest.json)，没有改写 NSS BIN。

| 固件 | 大小 | SHA256 |
|---|---:|---|
| 仓库 `firmware/stock-nss/ipq5018/qca-nss0-retail.bin`，NSS.MP.11.4-7-R | 761612 | `d90f7dd2d12d48445765ba013ffcc9a4e7a4448cd1dc497dfffe3d0b726298cd` |
| 当前构建的 IPQ5018 `retail_router0.bin`，NSS.FW.12.2-156-MP.R | 789564 | `7f14b5a2e72ba0b016f0c4b2ac4ce74664de650f8e16b6d70e6f10d05f05edc0` |

两者均为直接加载到 `0x40000000` 的裸镜像，不是 ARM/AArch64 ELF。使用
[CodeLinaro QSDK UBI32 工具链](https://github.com/CodeLinaro-mirror/qsdk_oss_ubicom32-toolchain_repo/tree/236bff6653554ce3360dd94cc5291f54c8a550d0)，
固定提交 `236bff6653554ce3360dd94cc5291f54c8a550d0`，只取 binutils/BFD/opcodes
及其构建依赖，在 Debian 内实际编译出 GNU objdump 2.19。

最小构建命令（源码树省略 GCC、GDB、sim 和 libc）：

```sh
mkdir binutils-build
cd binutils-build
CFLAGS='-O2 -std=gnu89 -fcommon' ../toolchain-src/src/configure \
  --target=ubicom32-elf --disable-werror --disable-nls --disable-gdb \
  --disable-sim --disable-gcc --disable-gas --disable-ld --disable-shared
make -j4 MAKEINFO=true all-binutils
binutils/objdump -D -b binary -m ubicom32ver6 -EL \
  --adjust-vma=0x40000000 firmware.bin
```

完整反汇编输出在本机开发目录 `Redmi_AX3000_build/work/nss-ubi32-20261010/`，
分别为 `stock-11.4-ver6.asm`、`current-12.2-ver6.asm`。裸镜像的数据区也会
被 objdump 解码，不能把全部输出当作可执行代码或已恢复的 C 源码。

## 指令集与内存布局证据

两镜像入口都解码为 `nop`，随后 `jmpt.t 0x40000028` 跳过内存布局头。
原厂 `0x40001dec` 和当前 `0x4000200c` 的机器字 `09000468` 解码为
`moveio.4 d0,32(a3)`；固定源码 `src/cgen/cpu/ubicom32.cpu` 将此指令限定
为 ver6。实际换用 ver5 decoder 时该指令为 unknown，周围代码仍连续。
这支持使用 ver6 指令解码，不等于独立确认了芯片的硅版本编号。

原厂和当前均申请四个 GMAC RX/TX ring，每个大小 `0x1000`、对齐 `0x20`。
第二组放在 UTCM_SHARED；原厂记录 TX1=`0x3f02e000`、RX1=`0x3f02f000`，
与当前真机 NSS 接管时的 ring 地址相同。两 BIN 的 `heap_ddr_size` 均为
8 MiB；不要与当前 DTS 的 NSS 保留区大小混为一项。

## 固件正常 GMAC RX 分支确实减 4

当前镜像 `0x40013a64–0x40013a94` 将 `gmac_rx_desc_*` 请求的分配地址写入
端口上下文 `+260`，TX ring 为 `+256`。从 `0x40001f8c` 开始的处理函数
使用 RX ring 字段并以 32 字节步长读取 descriptor。

正常单 descriptor 分支的关键指令：

```text
40002374: and.4 d3,d2,d9       ; d9 = 0x3fff0000，取 frame length
40002378: lsr.4 d3,d3,#0x10
40002384: cmpi d0,#768        ; 检查 FS|LS == 0x300
40002388: jmpne.f 0x40002628  ; 非单 descriptor 另行处理
4000238c: add.4 d3,#-4,d3     ; 明确减去 4
400023bc: move.2 48(a3),d3
400023c0: move.2 46(a3),d3
```

原厂同类分支在 `0x40002154/0x40002158` 提取长度，`0x40002164` 检查
FS|LS，`0x4000216c` 减 4，`0x4000219c/0x400021a0` 保存结果。
两个 packet 字段的完整 C 类型未恢复，以上仅按实际偏移表示。

公开 SynGMAC descriptor 定义也使用 `0x3fff0000 >> 16`、FS=`0x200`、
LS=`0x100`。这里已找到闭源镜像中的减法，而不是仅依据抓包猜测。
特殊状态和 scatter 分支尚未完整还原，没有指令跟踪证明每个真机包的执行路径。

## 真机对照与源码修复

host SynGMAC RX 直接使用硬件 frame length，MAC CST=`0x02000000` 用于
硬件 CRC 剥离；NSS 的正常 RX 分支则在该长度上再减 4。ACS=`0x80` 是
另一配置位，ACS=0 不能证明没有剥 CRC。原 `syn_if.c` 的 TODO 明确指出
NSS 模式启用 CST 需要配套固件改变。

本轮仅改变 CST 位，保留 RE/TE、PHY、DMA ring 和 NSS 配置：

| NSS 控制器均 READY | MAC 配置 | eth1 收到的带标签 ICMP 长度 | lan1/br-lan 长度 | ping |
|---|---|---:|---:|---:|
| 原设置，CST=1 | `0x02700c0c` | 98，缺 4 | 94，IP total length 仍为 84 | 0/3 |
| 清 CST | `0x00700c0c` | 102，正确 | 98，正确 | 3/3 |

原设置下 tagged raw ARP 和 raw IPv4/ICMP 能发到电脑，普通 ICMP请求已到
br-lan，但因长度不足没有产生 kernel echo reply；不能再把故障笼统定为
普通 TX 不工作。有效关闭 SKB reuse 后仍失败，已排除该开关作为此次根因。

新增 `0006-nss-dp-switch-crc-stripping-before-firmware-open.patch`：在 DMA
已停止、固件 OPEN 之前清 CST，包括第一次保留活跃 MAC 的接管；MAC start
明确选择 host=CST 开、NSS=CST 关，回到 host 时恢复其正常处理方式。
没有通过补零或扩大收到的 skb 长度掩盖截短。

数据面 release 5 已构建；对实际准备源码执行 7 组 ASan/UBSan 回归通过，
新增覆盖 CRC 所有权转换、带标签 IPv4 长度和 host 恢复。短时真机对照是
临时寄存器验证，不替代下节的完整镜像验收。

## 完整修复镜像的运行验证

已构建并保留配置刷入 `r0-nsslan20261010opt5-fe7e690dcd`，factory UBI
SHA256 为 `89db8a4cb2e9afa54796b9310a2ae9bc5a056c80aa6eb3cb2bf10d3a77b6e6cb`。
真机版本核对一致，无线配置哈希仍为原始备份的
`7956835d0821810fda9dbd0345ab5612177aec62b8cf8702312690fd5136a6d1`。
此轮启动后 44 秒检查时，原 2.4 GHz AP＋5 GHz STA 布局中的回程已连接。
之前恢复配置后的短时 WPA 超时不代表回程一直断网。

没有加载临时改寄存器模块，启用有线 NSS 后真机状态为 READY：
physical=`1`、DSA VID=`3088`、VLAN interface=`33`。路由器→电脑 ping 3/3，
电脑→路由器 5/5，路由器经 5 GHz STA 访问公网 3/3。随后连续三轮
NSS→host→NSS 切换中，每次 host 状态均释放全部资源，双方 ping 均无丢包；
最后保留 NSS READY 并保存 `wired_enabled=1`。

电脑直连上游 Wi-Fi 保持开发联网。其透明代理会截取 root namespace 的
公网测试，故另外建立独立 macvlan 有线端点 `192.168.1.252`，该端点自身的
网络命名空间没有代理规则，主网络不变。5 MB 限速下载全部完成；测试期间
ECM connection 11 的快照确认：

- 源地址 `192.168.1.252`，NAT 地址 `192.168.15.13`，目标 `172.66.0.218`。
- 入接口层次为 physical eth1=`1`、VLAN lan1=`33`、bridge br-lan=`30`，
  VLAN tag=`0xc10`、TPID=`0x8100`。
- 出接口 `phy1-sta0`=`32`，即当前 5 GHz 无线回程。
- `is_routed=1`、`can_accel=1`、`accel_mode=2`；实际源码枚举确认 2 为
  ACCEL，而非 pending。该连接的接口统计已有约 1.74 MB 转发增量，且
  `no_action_seen=0`、`flush_happened_total=0`。

同一下载窗口 NSS IPv4 special RX/TX 字节分别增长 5264532 / 5342870，
invalid-interface 和 by-rule-drop 保持 0；累计计数可能包含原有客户端流量，
具体测试连接的加速证据以上述 connection 11 快照为准。

这证明此次有线→5 GHz STA 路由/NAT 连接实际进入 NSS 加速，不能拿限速
公网下载的速率作为硬件峰值。新的无线↔有线桥接峰值、长时间 CPU/丢包测试、
IPv6、透明四地址 WDS 和完整组播同步仍未在这一记录中验收。
已将源码缺省值恢复为启用、nss-wifi release 升至 7。最终已刷入
`r0-nsslan20261010opt6-fe7e690dcd`，factory UBI SHA256：
`bdd2ca4ed4feae322203f436b6d6247d8fa889ae439bc0a38eeff1d2ec2b15c4`。
增量构建首次保留了旧 base-files 版本标签，已清理重建 base-files 并重新
生成、校验和刷入正确标识的镜像；没有以手动修改设备版本字符串代替构建。

最终真机在启动后 40.58 秒自动达到 NSS READY，provider held=1、无错误，
未加载临时修改 MAC 的模块。实际安装的数据面为 release 5、nss-wifi 为 7。
原 2.4 GHz AP＋5 GHz STA 和无线文件哈希保持不变；回程已连接，
`wwan.metric=0`、`wan.metric=100`，路由确认经 phy1-sta0。路由器访问公网
3/3，电脑有线访问路由器 3/3，均无丢包；电脑默认互联网经自身 wlan0。
所有临时测速命名空间已删除，默认有线 NSS 保持启用。

最终镜像及 SHA256 文件、配置备份已保存到桌面
`Redmi_AX3000_NSS_继续开发_20261010/`。上述正常数据通路和开机接管已验收，
不将其扩展成新 HE160 峰值或长时间稳定性已经通过的结论。

原始抓包、描述符及配置备份保存在桌面
`Redmi_AX3000_NSS_继续开发_20261010/`，主要证据前缀为
`tx-h2n-trace-4096` 和 `tx-h2n-cst-clear-4096`。

## MP12.2 组播增强控制与过滤路径

继续使用已验证的 UBI32 v6 反汇编。以下为当前 MP12.2 BIN 的静态证据，
尚不代表 ath11k 已完成同步或通过成员增删真机验收。原始反汇编为开发目录
`Redmi_AX3000_build/work/nss-ubi32-20261010/current-12.2-ver6.asm`。

dispatcher 位于 `0x4009c0a0`；`0x4009c0e4–0x4009c0fc` 读取消息头偏移
12 的 type、减 10003，通过表 `0x400bf5f4` 分派。payload 起始偏移 40，
与当前驱动消息布局相同。

| 命令 | ID | 分支地址 |
|---|---:|---|
| group create / delete | 10004 / 10005 | `0x4009c1cc` / `0x4009c230` |
| member add / remove / update | 10006 / 10007 / 10008 | `0x4009c468` / `0x4009c30c` / `0x4009c498` |
| reset | 10013 | `0x4009c658` |
| toggle | 10018 | `0x4009c160` |
| ME_SYNC | 10020 | `0x4009c144`，此 dispatcher 的默认未处理返回 |

成员过滤的真实约束如下：

- add 在 `0x4009ca50–0x4009ca58` 保存 member mode 和 nsrcs。
  `0x4009d774–0x4009d830` 比较源地址：命中仅 mode=1 复制，全部未命中仅
  mode=2 复制，支持 INCLUDE=1 / EXCLUDE=2。
- **空源表例外：** `0x4009d6b4–0x4009d6b8` 在 nsrcs=0 时直接进入复制，
  不检查 mode。INCLUDE＋空源表不能发送为“拒绝全部”的成员规则，应不添加
  该成员。
- `0x4009c47c–0x4009c494` 拒绝 nsrcs>4，写 error=25，即
  `NSS_WIFI_VDEV_ME_INVALID_NSRCS`。`0x4009ca2c–0x4009ca38` 按
  nsrcs×16 复制源区，IPv4/IPv6 数据过滤分别按 4/16 字节推进。
- add 在 `0x4009c9f0–0x4009c9f8` 比较所选表的 member 计数与 **2048**；
  达上限后 `0x4009cba4` 写 error=11（SNOOPTABLE_FULL）。这只证明该
  member 计数上限，不代表所有资源都能分配至此数量。头文件的 32 是
  `ME_SYNC.grp_entry[]` 的单消息容量，不能当成成员总表容量。
- VDEV+491 的状态字节选择两套表，数据路径在 `0x4009d614` 读取它。
  global ME mode=5/6 时，group/member 操作指向另一套表；toggle 在
  `0x4009c8b8–0x4009c8d4` 切换选择，reset 调用 `0x4009b940` 释放选中
  表。这为逐项建表、确认 ACK 后 toggle 发布提供依据，不能用未处理的
  ME_SYNC 替代。
- RA 仅在 global mode=6 路径读取：`0x4009cb6c–0x4009cb88` 保存 ramac
  和 dup；`0x4009d7e8–0x4009d858` 跳过 dup 非零的成员并使用 RA MAC。
  其他 mode 使用 member MAC，不能声称 mode=5 会按 RA.dup 去重。
- UPDATE 在 `0x4009c4dc–0x4009c514` 通过 group、member MAC 和完整 64 字节
  source 区查找；`0x4009c532–0x4009c534` 只更新 mode。未见更新 nsrcs 或
  更换源表，源变化应走重建而非依赖 UPDATE。

当前布局中的 peer_id 对应消息偏移 60，但上述路径尚未找到它的读取和
有效性检查，不能以旧 QSDK 实现证明 MP12.2 的 peer_id 行为。完整同步仍需
绑定有效 STA 生命周期、实现 Linux MDB/MLD 逐主机快照，并验证 include /
exclude、离组、老化和表切换的实际收发。

### 未登记组与启停命令的追加核对

普通数据的 mode=2 和 mode=5 都经过 `0x4009d400`。组不存在、零成员或
所有成员被源过滤时，均不会自动恢复普通组播发送：组查找失败在
`0x4009d668–0x4009d66c` 跳 `0x4009da6c`，普通数据在 `0x4009da98` 消费
原件并返回 1；零成员及零复制最终走 `0x4009d750–0x4009d758` 的消费路径。
外层 `0x40036ac0` 只发送生成队列，空队列直接返回。因此不能省略不支持的
组后仍保持 ME 启用，未知组也必须保留软件交付。

发送 interface command 10003、cmd=3（ENABLE_ME）时，**关闭参数是 4**：
`0x4009c8a4–0x4009c8b4` 将 VDEV+489 置 4、+488 置 0；参数 0/1/2/3
进入 enable=1 / global mode=2 路径。value>6 在 `0x40099644–0x40099650`
被拒绝为 error=10。disable4 不改变 global mode+494 或所选表+491，不能
假定关闭后所有 group/member 命令都访问同一固定表。

mode2 没有额外的未知组回退；它另有 `0x4009dba0` 的活动成员通知路径，
`0x4009bf20–0x4009bf68` 构造 type=10020。这确认 **ME_SYNC 是该路径的
固件通知**，并不使同 ID 成为已实现的 host→firmware 发布命令。enable2 会
将表选择强制为 0；RESET 的清表分支仅在保留 global mode=5/6 时执行。
追加核对：`0x4009c190–0x4009c1b8`在value≠4时先将VDEV+491置0、
+488置1，再分派5/6路径并写global mode5/6。
因此enable5/6也会重置表选择，不能在每次toggle之后重复enable并
假定当前表保持。普通Ethernet调用者`0x40037c40–0x40037c5c`及
`0x40038508–0x40038538`有DA组播位门，支持进一步实测软件M2U回退；
ME内部及所有特殊/间接入口尚未闭合，不能据此认定全路径回退已可用。
这些结论尚未通过实际 ME 启停和收发测试。

## MP12.2 批量连接统计与规则生命期

当前二进制的 IPv4/IPv6 dispatcher 分别为 `0x40020c20` / `0x40017920`。
type=7 的分派表项为 `0x400be868` / `0x400be834`，进入 SYNC_MANY 分支
`0x40021084` / `0x40017d5c`，调用现场扫描器 `0x4004e700` /
`0x400508e0`。请求 index、size 位于完整消息 +40、+42；next、count
写回 +44、+46，记录从 +48 起，IPv4/IPv6 步长分别为 116 / 124 字节。

扫描器在 manager+4 锁内遍历当前连接 slot 表。slot 位于 manager+28
所指的表，IPv4/IPv6 步长为 84 / 92 字节；查找函数 `0x4004eb20` /
`0x40050d00` 只接受 +72 / +80 的有效 bit0。序列化函数为 `0x4004f520`
/ `0x40051860`。DESTROY 汇入移除函数 `0x4004ed00` / `0x40050ee0`，
在同一 manager 锁内清有效位（`0x4004ed98` / `0x40050f78`）。因此已完成
移除的旧 slot 不会被后续批量扫描选中；记录不是从以前的 NOTIFY 缓存复制。

SYNC_MANY 原位填充原请求后返回成功，进入公共处理器 `0x400738c0` 的
ACK 分支 `0x40073968`，只将公共头 response@+8 置 0。随后
`0x40073970–0x40073988 → 0x40073880 → 0x40072e80` 发送同一输入 pbuf
及其数据指针，没有重建消息头，也未改写 cb@+24/+28 或 app_data@+32/+36。
DRV ACK 路径仅替换 sync_many callback，保留 app_data。该链支持完整
64 位请求 token 回显；链上的 TCM 辅助调用 `0x3f0003c0` 未单独展开，
仍需实际非零 token 测试。

新 MC CREATE 的计数初始化也已定位：IPv4
`0x40023f60 → 0x400240d4 → 0x4004efe0 → 0x4004f1ac → 0x4004fc80`，
在 `0x4004fca8–0x4004fcb4` 清对象 +40/+44/+48/+52；IPv6
`0x4001a940 → 0x4001aa94 → 0x40051300 → 0x400514e0 → 0x40051f20`，
在 `0x40051f4c–0x40051f58` 清 +64/+68/+72/+76。复用空闲链中的对象也
经过这些初始化。SYNC_MANY 从 slot+32 / +36 取得该对象，再由
`0x4004fa20` / `0x40051cc0` 读取并清零同一组增量计数。

重复 CREATE 的成功 ACK 可能走现有规则路径（IPv4
`0x40024038–0x40024078`、IPv6 `0x4001aa10–0x4001aa54`），不代表新分配
或计数清零。因此 ECM 使用已 ACK 规则的请求快照、独立 CREATE 代次及
MFC cookie，并在成员/路由变化后销毁重建。未匹配请求、已改变的规则代次
或过期 MFC 不回灌统计。单条 NOTIFY 没有已证明的规则代次，不能按当前
tuple 把旧计数绑定到新 MFC；CREATE/DESTROY ACK 本身也不是全局统计屏障。
以上为固件指令与 DRV 源码判断，尚未完成新 ECM 组播通路的真机验收。

### MC CREATE 布局与 DESTROY miss

MP12.2 IPv4 `0x40023f60` 要求 payload 696 字节，IPv6 `0x4001a940` 要求
592 字节，加 40 字节公共头后为 736 / 632 字节。两者仅接受 protocol=17
（UDP），`if_count` 合法范围为 1–16，与当前 DRV 的 `NSS_MC_IF_MAX` 一致。
已对照当前 `exports/nss_ipv4.h` / `nss_ipv6.h`，未发现这些字段偏移不匹配：

| 完整消息字段 | IPv4 偏移 | IPv6 偏移 |
|---|---:|---:|
| source IP / ident | 40 / 44 | 40–55 / 56 |
| group IP / ident | 48 / 52 | 60–75 / 76 |
| protocol | 56 | 80 |
| rule flags / valid flags | 60 / 64 | 84 / 88 |
| source NSS interface | 68 | 92 |
| ingress VLAN[0/1] | 72 / 76 | 96 / 100 |
| multicast destination MAC | 84–89 | 108–113 |
| if_count | 90 | 114 |
| if_rule 数组起始 / 步长 | 96 / 40 | 120 / 32 |

if_rule 内的 output NSS interface、MTU、source MAC，IPv4 相对偏移为
24、28、32–37，IPv6 为 16、20、24–29；egress VLAN 为 IPv4 +12/+16、
IPv6 +4/+8，由 entry valid_flags bit0 控制。转换函数 `0x40023e20` /
`0x4001a820` 的 rule_flags bit0/bit1 对应 BRIDGE_FLOW=1 / ROUTED_FLOW=2。
结构没有每个 MFC 出口的 TTL 阈值字段；未在本轮证明每包 TTL 递减路径。

DESTROY 查找不到 tuple 的结果也已定位：IPv4
`0x40020fe8 → 0x4002116c`（组播汇入 `0x4002117c`），IPv6
`0x40017cc0 → 0x40017e44`（组播汇入 `0x40017e54`），均写 error@+16=5
并返回 1。公共响应处理器 `0x4007398c` 将其转为 response@+8=4，即
`NSS_CMN_RESPONSE_EMSG`。对应头文件枚举为
`NSS_IPV4_DR_NO_CONNECTION_ENTRY_ERROR` / `NSS_IPV6_DR_NO_CONNECTION_ENTRY_ERROR`。
匹配当前 DESTROY 的这个结果可证明处理时规则不存在，ECM 按已移除清理；
超时及其他错误仍保留未知所有权。迟到旧代次结果不能用于清理后来创建的规则。

## STA MCBC exception 与组播接收边界

ath11k STA 初始化发送 `NSS_WIFI_VDEV_CFG_MCBC_EXC_TO_HOST_CMD=22`、value=1，
属于 message type 10003，完整消息 +40/+44 为 cmd/value。MP12.2 的命令
分派 `0x4009927c–0x400992a0` 通过 `0x400bf588` 选到第 22 项
`0x400994e0`；非零 value 设置 VDEV+336 bit29，0 在 `0x40099e70` 清位。
RX `0x400067d4–0x400067d8` 检查同一位，设置时跳往 `0x40006d14`。
clear 后继续路径最终在原完整映像显示的 `0x40006410` 间接调用下一阶段。
后续补充已闭合其默认 ETH_RX→IPv4 分派，见下节；这仍不能证明关闭
后所有未知组和广播都能安全回主机或进入 IPv4 MC 硬件规则。

主机代码明确由 mac80211 检查组播 PN/TSC；REO 的该配置仅针对 pairwise
key。NSS type14 MCBC callback 已设置 rxcb.is_mcbc，但原 h_mpdu 在 NSS
enabled 时又将其覆盖为 false，并可能声明 PN_VALIDATED，from_nss 还
无条件声明 DUP_VALIDATED。新增 999-972 保留异常分类、区分普通 host RX，
清除每个 MPDU 的旧 PN 标记，组播重复校验交回 mac80211。实际分支提取的
ASan/UBSan 测试及原生 mac80211 构建通过；未做加密帧 replay 注入验证。
生产 STA 的 MCBC exception 仍保持开启，不用关闭它掩盖该边界。

0072/0073 临时模块的 routed MC 实验已建立 conn592，CREATE ACK 后
accel_mode=2、driver fail/NACK=0，但 slow_path_packets 从 183 增到 538，
no_action_seen=1，尚未证明 STA 组播进入硬件转发。此结果与 host exception
路径相符，但并非该控制位实际造成所有慢路径包的直接证明。

## 2026-10-11 UTCM 地址修正、授权与 STA 下行入口

MP12.2 的启动代码 `0x4000021c–0x40000244` 把 file+0x42c 开始的
0x7f00 字节复制到运行基址 `0x3f000000`。此前完整反汇编仍把这段
显示为 `0x4000042c`，跨段相对 call 的显示目标因此多出 0x0100042c；
不是 Thumb 模式问题。只读按 UTCM 基址重新解码后，原显示
`0x410981ec` 的调用实际是 `0x40097dc0`，原 `0x4109a64c` 实际
是 `0x4009a220`。以下区分运行地址与原显示地址。

普通 RX 运行地址 `0x3f005df8` 检查 peer+36 的授权字段。零值进入
`0x40097dc0–0x40097e04` 的 EtherType 判断，支持一层 0x8100 VLAN，
只允许 EAPOL(0x888e)/WAPI(0x88b4)。ARP/IPv4 返回 0 后进入
`0x3f0062b4–0x3f0062c4`，归还 packet buffer、释放 peer 引用，
没有进入 MCBC/type14 host 交付。这只证明该 RX 入口；不能把
AUTH=0 当作所有既有加速流和 TX 都已停止的证明。

AUTH=0 及 SECURITY 更新调用的 `0x4003f120` 遍历 peer+492+i×84
的八个记录，清除的是 peer+540+i×84 的 28 字节，并拆除排队 buffer，
不是清空全部 8×84。相同记录在 `0x40042104–0x40042254` 使用
802.11 More Fragments、Sequence Control 的 fragment number 和连续
片号，另有 7000 ms 定时器，支持其为分片重组状态。尚无证据把它
等同于完整 GTK/PTK PN/replay 窗口重置。

当前 host 在 SOC 启动后发送
`nss_wifi_vdev_base_set_next_hop(..., NSS_ETH_RX_INTERFACE)`（type10022）。
固件 `0x40098d78–0x40098d8c` 保存 VAP base+444；新建 VDEV 时
复制到 VDEV+232（`0x40098c50`），peer 初始化再把该对象写入
peer+16（`0x4003fd30–0x4003fd38`）。普通 STA 没有发送另可覆盖
peer+16 的 type10029 SET_PEER_NEXT_HOP。

ETH_RX 接口号 158 的 constructor `0x4000f7c0–0x4000f7ec` 将
对象+12 设为 `0x4000f820`。该函数入队并唤醒 NSS worker
`0x3f000e60`；worker 按 Ethernet EtherType 分派，IPv4(0x0800)
经对象+164 的 IPv4 对象+32 进入 `0x3f003820`。默认下一跳和
这次 IPv4 分派不按 STA/AP opmode 或目标 MAC 强制选择 host。
进入 IPv4 engine不等于命中加速规则，需同 tuple 的实际连接证据。

MCBC 分类非零时，运行地址 `0x3f0063a8` 检查 VDEV+336 bit29，
开启后 `0x3f0068f0` 调用 `0x4009a220`，后者在
`0x4009a238` 构造 metadata type14。已定位普通单播路径跳过此调用，
但未覆盖所有间接入口；MCBC 也不能直接等同于 IPv4 组播目的地址。
另有 WDS_EXT(cmd12、VDEV+336 bit9) 的 STA/AP 过滤差异，但当前
普通三地址 STA 创建仅配置 VDEV 和 MCBC exception，并未启用它。
ARP/EAPOL 等非 IPv4 的 ETH_RX+160 最终 host 回调和 IPv4 规则未命中
出口仍未完全闭合，不能据此直接归因广播失败或下行带宽。

## ETH_RX 非 IP / ARP 到主机的出口

进一步只读核对 MP12.2 与 stock11.4，已闭合普通 ETH_RX 非 IP 包的
N2H 出口。UTCM 地址继续使用修正后的运行基址；原始汇编仍保存在上述
`nss-ubi32-20261010/` 目录。这里没有找到新增的 ARP 或广播 MAC 过滤，
也没有证明故障窗口的广播已经到达这个入口。

| 阶段 | MP12.2 | stock11.4 |
|---|---|---|
| ETH_RX worker | `0x3f000e60` | `0x3f000c40` |
| 非 IP 处理 | `0x4000fae0` | `0x4000d880` |
| ETH_RX+160 绑定 N2H interface156 | `0x400a11f4–0x400a11fc` | `0x4009a558–0x4009a560` |
| N2H 构造器 | `0x40072100` | `0x4006dd80` |
| N2H+28 优先入队 | `0x40072e80` | `0x4006eaa0` |
| N2H+12 普通入队 | `0x40073100` | `0x4006ed40` |
| N2H 输出 worker / descriptor 构造 | `0x40073780 / 0x40074d20` | `0x4006f3c0 / 0x40070960` |

MP12.2 worker 在 `0x3f00112c–0x3f001140` 识别 IPv6、PPPoE session 和
VLAN，其他 EtherType 最终在 `0x3f00127c–0x3f001284` 调用非 IP 处理器。
VLAN 外层支持 0x8100/0x88a8，解析后的 ARP 同样走该出口。

`0x4000fb14–0x4000fb28` 比较 EAPOL=0x888e、PPPoE discovery=0x8863、
ARP=0x0806；命中后在 `0x4000fb50–0x4000fb70` 设置 packet+20 bit29，
flush 缓存并调用 N2H+28。其他非 IP 类型走 N2H+12。此 packet bit29
是队列优先标记，与 VDEV+336 bit29 的 MCBC exception 控制位不同。
缓存辅助 `0x3f0003c0` 按 32-byte cacheline flush，没有 ARP 内容判断。

interface156 对象在 `0x400a0aac–0x400a0ad0` 创建，随后经
`0x400a11fc → 0x4000f740` 写入 ETH_RX+160。正常优先入队在
`0x40072f18–0x40072f40` 识别上述标记，输出 worker 在 `0x400737c8`
调用 descriptor 构造器。常规 packet 在 `0x40074f00` 选择
buffer_type=3，并在 `0x40074f70` 写 descriptor+16；interface 从关联
metadata+16 取得，producer index/通知在 `0x4007505c–0x400751b8` 发布。
这段没有按 ARP EtherType 或广播 MAC 丢弃的分支。

当前驱动的 `N2H_BUFFER_PACKET=3` 分派到普通 packet handler，再按
descriptor interface 查找 netdev 和已登记的 VDEV callback。缺失 netdev
或 linearize 失败仍会丢弃；未找到 ARP 白名单或广播 MAC 过滤。stock11.4
的上述协议选择、ARP 优先处理和 type3 构造与 MP12.2 相同。

开启 STA MCBC exception 时，广播 ARP 可能先走 type14 而不进入 ETH_RX；
因此本次只排除了“普通 ETH_RX 新增 ARP 禁送主机”的具体假设。实际
type14 交付、上游 AP 转播和 IPv4 规则未命中出口仍需分别核对。

## 384-byte TLV 与 1816-byte NSS buffer 的 SG 阈值

小内存 profile 的 `ATH11K_DP_RXDMA_NSS_REFILL_RING_SIZE=1816` 实际表示
buffer bytes，其旧注释按 256-byte TLV 预算。当前 QCN6122 的硬件
descriptor 为 384 bytes；BUF_RING filter 虽然不订阅 RX_HEADER，
HTT 的 `offset_valid` 和 `rx_packet_offset=hal_desc_sz` 仍明确提交
384。QCN9074 offset getter 只填各 TLV 位置，没有把 packet offset
改成 256。SOC_INIT 同时提交 `wrip.tlv_size=384`、`rx_buf_len=1816`。

MP12.2 `0x4003979c–0x400397ac` 从 SOC_INIT payload+860/+862
（完整消息+900/+902）读取二者，再调用 `0x40040860`。该函数在
`0x4004088c–0x400408ac` 接受 TLV 256…384，保存 context+102 的
TLV size、+104 的 TLV+64、+106 的 buffer length；buffer 必须大于
TLV 且不超过 2048，没有自动压缩 384 的偏移。

`0x400432c4–0x400432d0`、`0x4004341c–0x40043428`、
`0x40044f60–0x40044f7c` 均计算 buffer_len−tlv_size；前一分支在
`0x400432ec–0x40043300` 按真实 TLV 移动数据起点，再处理 SG。
UTCM 的相应计算位于运行地址 `0x3f006d48–0x3f006d80`。
因此当前单 buffer 数据容量只有 **1432 bytes**，标准 1500 IP MTU
的 1514-byte Ethernet 帧已经超过它。

opt19 受控 P4 窗口第二活动 radio 的 RX delivered 增加 647278，
SG received/sent 增加 646622（99.899%），REO reaped 增加 1293905；
`2×646622+656=1293900`，几乎每个数据包消耗两个 REO descriptor。
SG fail、desc alloc fail 和 hardware desc unavailable 为 0，证明的是
成功拼接，不能据此否认额外处理成本。

同一 AP 会话仅改变 TCP MSS 的实测进一步闭合阈值：MSS1460 窗口
RX delivered/SG/REO 增量为 751329/751306/1502635；MSS1300 为
762231/0/762240。小 MSS 消除了 SG，但吞吐没有同步提高，不能把
SG 认定为全部空口或 320 Mbit/s 瓶颈。源数据和方法见
[opt19 验证](sta-downlink-opt19.md)。

stock11.4 `0x400368b0–0x400368c0 → 0x4003cf00` 使用旧 ABI
payload+856/+858，同样保存 TLV 和 buffer length 并要求后者≤2048。
原厂实际启动参数未采集，不断言原厂采用哪一对数值。

当前 AArch64 NSS EMPTY 路径的 `max_buf_size=1984` 加上
`NET_SKB_PAD=64`，从 skb head 分配、映射并向固件广告 **2048 bytes**。
MTU 更新不低于该下限；reuse 仅允许实际 head 容量≥2048，并映射/广告
`max(tail_offset,2048)`，不足容量的 TX buffer 不标记为 reusable。
当前 paged_mode=0、jumbo_mru=0，core0 min_sizes=1984。

这为保持 offset/TLV=384、仅把共享 NSS buffer bytes 改为 2048 提供
宿主和固件边界依据；不需要扩大 ring 或 pool。该容量核对适用于当前
AArch64 配置，未审计其他 buffer provider 或全部 reuse DMA 方向。
32 位固定 1792 配置不能直接复用这个结论。运行验收见
[opt20 记录](sta-downlink-opt20.md)。

## MP12.2 PROJECT 逐线程统计 ABI 与启停 ACK

当前MP12.2 ver6在`0x400a1be0–0x400a1c10`登记interface204，handler为
`0x400a1d20`。完整消息+12的type0进入WT_STATS_ENABLE，type1为固件
NOTIFY方向，type2配置16项priority map；公共消息头为40 bytes。

`0x400a1c38–0x400a1c48`固定填写完整消息+40的thread count=12、
+44的IRQ number count=128，读取+48的enable byte。这与宿主12-byte
enable payload的`worker_thread_count@0/irq_count@4/enable@8`一致。
成功启停均走原请求的公共ACK路径，保留type、len、cb/app_data和payload；
已开启时重复ENABLE返回error2，不能仅把sysctl提交成功当作开启ACK。

关闭分支`0x400a1c54–0x400a1c88`依次关闭12个context。
helper `0x4000d140`清零统计并把context+300的enable byte设为0。
已有100ms timer随后调用`0x4000d180`，在关闭状态返回2并释放packet，
不再重挂timer。但已经入N2H队列的通知可能晚于关闭ACK抵达。

`0x400a1dc4`申请1328-byte完整通知，`0x400a1e74–0x400a1e84`设置
type1、payload len1288；公共构造器使用version1、response5(NOTIFY)。
payload先含threadno和stats_written各4 bytes，之后entry每项40 bytes：

| entry偏移 | 内容 |
|---:|---|
| 0 / 4 | callback调用次数低32 / 高32 |
| 8 / 12 | UBI32 callback运行地址 / IRQ编号 |
| 16 / 20 / 24 | ticks min / avg / max |
| 28 / 32 / 36 | instructions min / avg / max |

序列化指令为`0x400a1ed8–0x400a1f2c`，步长见`0x400a1ed0/+d4`。
callback值来自实际固件IRQ绑定表，不是公共消息头中的宿主函数指针。
ACK的128是IRQ编号域；当前每context实际分配16×40 bytes活动槽
(`0x4000d06c–0x4000d0a4`)，通知枚举slot0…15。宿主消息数组容量仍为
32，不能据此认为每context同时有128条活动callback。

宿主原有debugfs reader在锁外取得0数量，首次ACK随后发布table时，
reader可能对ZERO_SIZE_PTR调用strlen；原sysctl异步发送且忽略提交
失败，也没有关闭ACK证据。新的0213补丁沿用已登记的nss_control cookie
和callback排空，验证payload len与数量上限，按实际ACK更新状态；快照
在同一锁内取得pointer/geometry并在复制前复核。固件静态ABI闭合与
实际运行启停/首份通知验收需分开记录。

另外，cpu_load_ubi是全core指令吞吐估计：固件
`0x400534e0–0x40053568`合计context指令计数差，宿主按当前频率的75%
指令预算归一化，平均窗口1000 samples。Min/Max是平均值的历史极值，
不是单worker峰值；该指标不能表示DMA/锁等待，也不能用7…11%的读数
断言某一个worker饱和。逐callback统计仍需与实际流量和空口速率对照。

补充软件时基证据：`0x40081d40–0x40081d94`读取同一MMIO
`0x3c000114`，检测32-bit回绕并维护高32位；`0x400819e0`与timer
deadline比较。`0x40081e00–0x40081e30`初始化时基对象+56为
850000000，getter为`0x40081800`。CORE_FREQ handler
`0x40053320/0x400533e0–0x400533f8`将消息+40的frequency交给
`0x40081680`更新这个标量并调整比较值；+44/+48为start_or_end/
stats_enable，与宿主nss_freq.c/nss_hlos_if.h布局相符。
`0x40081528–0x40081540`按floor(F/1000)×50构造deadline，说明
固件软件按CORE_FREQ的Hz标量构造毫秒时基。默认850000000不是当前
硬件频率读数；仍缺timer block寄存器定义、输入clock/divider和当前
软件F与硬件一致性证明。官方binutils直接寄存器operand的0x114别名
int_set0不属于该MMIO地址空间，不能拿它命名这个计数器。继续保留
raw ticks，不把以上静态软件约定变成逐worker利用率。

逐IRQ测量wrapper在`0x3f0006bc–0x3f0006fc`分别读取callback前后
`0x3c000114`和当前context的`context_cnt`。后者与`inst_cnt`为寄存器
别名，因此insn为该context执行的指令差；ticks为前一计数器的原始
32-bit差，尚未证明其Hz或周期/微秒换算。wrapper的部分call/return
开销包含在区间内，callback前的IRQ排队和外层suspend等待不包含。

`0x3f000768–0x3f000774`每次callback返回后以64-bit加一更新count，
不是按packet数量计数；一次callback可处理多包或空ring。ticks与insn
avg在旧值为0时取当前sample，否则为`floor((7*avg_old+sample)/8)`，
min/max为自清零以来的调用样本极值。100ms通知复制但不清零记录；
ENABLE/DISABLE和IRQ解绑清零，整个core的通知也不是一次原子快照。

采集时按`(thread, IRQ, callback)`对齐同一epoch内的前后记录。已知
`0x3f0057e0`为Wi-Fi RX阶段，`0x3f007d00`为TX/TCL阶段。稳定负载下
`Δcount*EMA`可粗略排列相对成本，不能恢复整个窗口的总ticks，也不能
相加换算worker忙碌百分比。callback改变、count下降或重新启停后需
重新建立基线。

空闲首次运行的t2/IRQ39=`0x3f001b60`、t10/IRQ35和36=`0x3f007d00`
均约57056次；t4/IRQ42=`0x40072000`和t9/IRQ41=`0x40073a80`约14264
次。前一组按计数器`2^15`边界重挂timer，后一组按`2^17`，空ring也
会调用；它们不是packet数量，不能仅凭高调用数认定有效负载或瓶颈。

| callback | 反汇编确认的职责 |
|---|---|
| `0x3f001b60` | GMAC RX与TX ring服务，动态budget5…40、初值40；每轮取min(available,budget)，callback可继续下一轮 |
| `0x3f007d00` | Wi-Fi RX释放ring、TX completion及RXDMA refill的组合poll；前两段向helper传budget128，refill完整上限未闭合 |
| `0x4003ba20` | Wi-Fi RX释放/异常软件队列，锁内摘整条链表后逐项处理；新到项留给下次，无已证数值budget |
| `0x40072000` | N2H延迟通知/中断合并timer，扫描pending并发布producer index |
| `0x40073a80` | H2N IRQ/poll自适应timer，每110次检查活动计数，阈值1999控制IRQ57或poll模式 |
| `0x40073740` | H2N EMPTY buffer入池，按7-bit ring的producer/consumer差消费 |
| `0x40073ba0` | H2N command/data入口，先command queue1，再遍历data queue3及后续队列 |
| `0x400819e0` | 公共时基/软件timer deadline服务，不是bulk packet callback |

timer重挂见`0x3f001b60–0x3f001bb4`、`0x3f007d18–0x3f007d38`、
`0x40072038–0x400720d8`；Wi-Fi组合poll的budget参数在
`0x3f007d60/+d64`、`0x3f007dd4/+ddc`，队列唤醒在
`0x3f007d70–0x3f007dc4`。RX链表消费见`0x4003ba34–0x4003baf0`，
H2N模式选择见`0x40073a90–0x40073b44`。

## MP12.2 WBM REO catch-all 与错误码直方图

实际WBM分类链为`0x3f007d00 → 0x3f0044e0 → 0x40044980`，不是
单独的RX ring poll helper。`0x3f004548–0x3f004554`将source1/RXDMA、
2/REO和4/SW交共同处理入口，source0/TQM走TX completion。

`0x40044b18–0x40044bb8`在source2时增加SOC+2436的err_src_reo。
push reason1可先由`0x40043d80`消费；后续将code0…14累计到
SOC+2452+code×4的直方图。code0=NULL queue和code5=FRAME_2K_JUMP
各有专门处理；其余code累计SOC+2444的err_src_reo_code_inv，再归还
buffer和SW descriptor。getter在`0x40049700/+20`，descriptor+8的
bits25:24为push reason，bits30:26为error code，匹配HAL字段。

所以inv是catch-all，包含合法的NON_BA/BA_DUPLICATE、PN失败、越窗、
无BA session、SN=SSN、descriptor状态等原因，不等于非法编码。
不能为了消除计数放宽重复或PN校验。code≥15没有15项直方图槽；
push-reason提前消费和这些额外code也可使直方图和汇总不同步。

SOC_STATS布局已有固件独立证据：`0x4003b448–0x4003b450`构造type10、
payload1068，`0x4003b5f4–0x4003b620`把SOC+2424起164 bytes复制到
完整消息+912（payload+872），然后清零增量块。

| 字段 | payload偏移 |
|---|---:|
| WBM起点 / REO总计 | 872 / 884 |
| NULLQ / inv | 888 / 892 |
| REO[15] | 900 |
| RXDMA[14] | 960 |
| internal[5] | 1016 |
| target_type | 1064 |

target_type写入见`0x4003b82c–0x4003b834`。这些字段与宿主结构一致，
未发现MP12.2数组错位。ath11k已有SOC_STATS消费者累加REO/RXDMA数组，
`soc_dp_stats`可按SOC直接读取；其输出没有整体快照锁，比较时保留
周期同步延迟和跨字段时间差。实际数据只有SOC聚合，仍需负载前后
差分及空口/TID/peer证据，不能直接归属一个iperf tuple或吞吐根因。

### opt25 后续核查：NULLQ 通知与 Frame OOR 分支

MP12.2 getter `0x40049720`直接读取原始code，没有减一。当前HAL
enum及debugfs表的code6为BAR_2K_JUMP，code7才是FRAME_OOR；两者
都进入catch-all，计数后经`0x40044bb8 → 0x40044a90`归还packet，
再由`0x40043060`归还软件descriptor。该WBM错误路径没有提取
peer/TID发送type18，也没有保留packet等待恢复。此结论不覆盖其他
REO输入路径，不能据此判定全部空口OOR行为。

code0经`0x40044d0c`进入NULLQ处理。TID来自当前RX descriptor+164的
bits15…18（getter `0x400497a0`），peer_id来自+176的高16位
（`0x40049960`）。peer存在且sequence-control-valid后发送type18；
构造器未见peer/TID pending位、ACK解除或时间节流。发送后继续当前
packet处理，后续可能进入正常RX入口，也可能被过滤/解封装分支
回收，既不等待host response，也不保证该packet最终forward。

stock11.4同样只有code0/5有特殊分支，type18发送后直接返回当前
packet处理。未找到通知后还必须执行额外NSS同步命令的证据；重复
通知说明再次满足NULLQ通知条件，不能把`wmi_queued`当成Wi-Fi FW
已应用绑定。GET能证明给定paddr的队列可读，仍不能证明RX peer
lookup指向该paddr。

还需限制“通知证明硬件NULLQ”的表述：push_reason=1是routing，
`0x40044b3c–0x40044b40`调用`0x40043d80`；返回0时经
`0x40044ea0–0x40044ea4`回到`0x40044b44`解析code。HAL明确规定
WBM reo_error_code只在push_reason=error_detected时有效，因此这条
静态fall-through可能以无效code0进入同一通知链。尚未取得事件的
push_reason，不能断定真机通知实际来自这一分支。

QCN6122通知前已证buffer组装成功、peer_id映射查找非空及RX
descriptor+180 bit6的sequence-control-valid。未在该路径证明FCS
good、PHY/header good、frame/QoS-control-valid、AST有效或RX MAC/
qaddr与当前peer一致；也未证明上游硬件允许坏FCS帧到达此路径。
因此通知保留为绑定请求，不能据次数推断全部包均为真实NULLQ。

## MP12.2 N2H checksum flags

`0x40074f38–0x40074f48`将内部packet+20的bit2映射为N2H flags
bit0；内部bit3为0时经`0x400751f0`清bit1。`0x40074fbc`将u16
flags写入descriptor+14，FIRST/LAST另由`0x40074fa0/0x40074fb4`
设置bits2/3。普通buffer_type3与内部bit28选择的EXT type13共用
checksum段；MCBC EXT构造器也保留内部checksum状态。

Wi-Fi getter `0x400497c0`读取RX descriptor+80的bits18/19，入口
`0x3f005ce0`依据transport/IPv4 checksum-fail为0设置内部bits3/2。
这与host的IPv4-valid1、transport-valid2及offset14/u16一致；未
找到把0x2用作其他意义的证据。赋值点未同时证明IP/TCP/UDP/header
valid及fragment等条件，硬件对未计算/不支持情况的fail位规定和
全部后续flag改写仍未闭合。位映射证明不能替代完整checksum合同，
也不能据iperf一次控制长度异常认定该ABI损坏。

## MP12.2 EAPOL 可选出口与 metadata ABI

`0x40043c20`检查 EtherType=0x888e，SOC内部 flags bit5 为1时经
`0x40043cf0–0x40043d10 → 0x4009a420`走 EAPOL 专用 EXT 出口；否则
`0x40043d30–0x40043d5c`回到普通 Wi-Fi RX。stock11.4 对应 routing
段 `0x4003ffa0–0x4003ffec`直接进入普通 RX `0x3f0059c0`，未见这一
可选出口。两版本区别不等于当前握手故障的归因。

SOC_INIT 的完整消息基址在 `0x4003cf00`加40成为 payload 起点，
`0x400395f0`将其存入callee a6；`0x400398e4`把 **payload+18（十进制，
即0x12）** 的 flags byte OR 到 SOC内部+178。它相对完整消息为
58/0x3a。host结构的四个u32 hssm 后为 num_tcl（+16）、num_reo（+17）、
flags（+18），与该偏移一致。host目前只条件置位 0x2
`WIFILI_ADDTL_MEM_SEG_SET`和0x10 `WIFILI_MULTISOC_THREAD_MAP_ENABLE`，
没有置0x20；未排除其他固件入口后来改变该内部bit，没有补造宏名
或擅自开启它。

`0x4009a438–0x4009a454`要求至少16字节前缀，在buffer head+4写
pkt_type19、+8写direction、+12写peer_id，调用者给direction=1/RX。
与host metadata offset4、u32 type、enum dir/u16 peer_id布局一致。
构造器没有重算EAPOL MIC/checksum；该bit映射与结构布局不能证明
完整peer→VDEV/N2H interface关联没有过期。

host由callback netdev选arvif，不使用type19 body中的peer_id重选
VDEV；STA交付也不执行AP用的PAE组地址改写。实际捕获的Ethernet
EAPOL不能单独判定它经过普通RX还是type19 callback。启动失败后
EAP ADD遗漏DEL的源码缺口已在opt27修复；WMI发送不含执行ACK，
其边界及原回程捕获见[opt27记录](sta-downlink-opt27.md)。

## SEC_TYPE/AUTH 不替代 Wi-Fi 安装完成

MP12.2 分派表 `0x400beac0 → 0x4003c660`为SEC_TYPE(type21)。处理器
检查SOC/peer后读取完整消息+40/+42/+43/+44；`0x4000fe20–0x4000fe40`
按PTK/GTK scope写peer两组cipher/MIC记录，再调用`0x4003f120`清理
软件状态。消息没有AES密钥、key_idx、generation或WMI完成凭据，
处理器没有检查Wi-Fi固件是否已安装key。清理失败前security记录
已被修改，所以NACK也不等于无副作用。

`0x4003f120–0x4003f1dc`处理8个stride84的软件记录，摘链/回收
buffer、清28字节状态。关联接收路径处理分片和7000ms timer；未
发现这里发布REO UPDATE、清硬件PN窗口或区分同cipher重装key。

AUTH(type44)分派 `0x400beb1c → 0x4003c5b4`，在`0x4003c5d8`将
消息+42写入peer+36。AUTH=1直接结束；AUTH=0另调用同一软件清理
helper（`0x4003c5e0–0x4003c5f4`），但不传播其返回值。其ACK不能
证明所有清理完成。SEC_TYPE自身不会先撤销AUTH。

stock11.4 SEC路径 `0x40038e4c–0x40038e9c → 0x4000dbc0/0x4003b960`，
AUTH路径 `0x40038dcc–0x40038e10`具有相同时序边界；没有找到MP12.2
新增WMI安装完成依赖。NSS ACK不能补证WMI事务，host必须先得到
可信的安装结果。opt28修复该等待/恢复/删除引用边界，详见
[opt28记录](sta-downlink-opt28.md)。REO PN配置仍需独立执行验收，
NSS安全记录也没有完整key-generation读回合同。

## MP12.2 接收授权与硬件 PN 错误出口

普通 STA RX 的运行地址 `0x3f005df8`读取 peer+36 授权字段；
AUTH=0 时 `0x40097dc0`仅允许控制协议，其余经
`0x3f0062b0–0x3f0062c4`计数、回收并释放peer引用。反汇编原始
显示地址对应 `0x40006224`、`0x400066b0–0x400066f0`。这不提供
Wi-Fi key 安装或 REO PN 的完成确认。

WBM REO ERROR_DETECTED 的 raw11为 PN_CHECK_FAILED，raw13为
PN_ERR_FLAG_SET（host `hal_desc.h` 枚举）。固件 `0x40049720`
提取error；`0x40044b80–0x40044bbc`只对0/5特殊处理，11/13计入
INV 后经 `0x40044a90 → 0x3f000a60 → 0x40043060`回收 packet/RX
descriptor，没有发现交给host重试、再次授权或等待PN UPDATE的
路径。PN 检查条件存在于硬件 REO，SEC/AUTH ACK 无法替代其状态。

`0x40044b70–0x40044b7c`更新error histogram，INV聚合点为
`0x40044bb8`；host `soc_stats.reo_error` / debugfs的“PN check fail”
与“PN err”是SOC聚合，不绑定某个peer/key。只有push reason为
ERROR_DETECTED时该error字段才有效；旧routing fallthrough也可能
解析该字段，不能将所有raw值当成有效错误。PN错误计数0不证明
检查已启用，也不能把任意接收drop归类成AUTH失败。

opt29补齐host的PN UPDATE完成等待，见[记录](sta-downlink-opt29.md)。
固件SEC软件分片清理、完整replay行为和后续包的实际queue选择仍
未完成闭合，不能仅以新命令SUCCESS或聚合计数认定整个PN合同。
