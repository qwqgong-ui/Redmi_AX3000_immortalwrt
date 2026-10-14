# opt32：实机头部前缀与原回程交错对照

opt32在opt31上增加有界前缀诊断，mac80211 release30。此记录保留当时
结果；后续opt33修正PPDU及头部前缀校验，不改写本轮原始数据。

## 前缀证据

仅显式QCN6122 monitor试验记录：在实际120字节hdr_status内检查
0、4、8、12、16、20、24、28八个候选偏移，分别保存FC、RA、TA、
Seq、QoS匹配位图和非零字节数。候选匹配不改变HDR_MATCH或TRUSTED，
不导出payload、PN、密钥或合成帧；默认不分配记录环。

canonical补丁零fuzz/逐字节还原、prepare一致、模块/完整镜像、实际
descriptor上的ASan/UBSan以及格式门禁回归通过。原配置安装后模块
hash一致，原STA/DHCP、Ethernet encap/decap和有线NSS就绪。

原回程同TCP两轮8MiB共16MiB，用时4.65369秒、整段28.841Mbit/s，
body28.843/58.286Mbit/s。这是取证窗口，不作为补丁吞吐收益。
9份快照合并16514条不可变ordinal，produced16514、缺号0。

独立有效MPDU_START字段及匹配PPDU筛选到12403条原AP→STA DATA，
全部decap2；其中12392条header LEN132、1条LEN118、10条LEN110。
全部在hdr_status+0匹配FC、RA、TA、Seq、QoS；部分Seq单独有其他
候选匹配，但五字段交集均仅bit0。头部前缀不是空白，也没有证明偏移改变。

12403条header前缀字的高16位均匹配MPDU_START的PPDU，低16位均0。
opt31/32按低16位比较是校验错误；LEN132超出固定124字节前缀的
完整TLV判断仍需保留边界。此轮HDR_MATCH/TRUSTED均0。FC Retry1670、
FCS_BAD698，仅是被观察到的首buffer样本，不是全部空口MPDU的分母。

公共QSDK固定提交
[b86ca757](https://github.com/CodeLinaro-mirror/qsdk_platform_vendor_qcom-opensource_wlan_qca-wifi-host-cmn/tree/b86ca7570225b90dc9ed38b0ab3248ce71e02a74)
的li/hal_li_rx.h同样使用4字节tag、4字节前缀和120字节rx_pkt_hdr；
li/hal_li_generic_api.h的RX_HEADER处理跳过4字节前缀。高16位PPDU
来自上述实机独立核对，公共代码未给出该前缀字的完整位定义。

## 默认关闭诊断后的交错对照

保持同一端点162.159.140.220、证书检查/SNI speed.cloudflare.com，
电脑SO_MARK666绕过本机代理，socket按源IP/接口绑定。每项新TCP后
同连接两轮8MiB，顺序直连Wi-Fi→LAN→LAN→直连Wi-Fi。

| 路径 | 整段Mbit/s | 两轮body Mbit/s |
|---|---:|---:|
| 电脑直连上游Wi-Fi，前 | 21.740 | 22.088 / 34.662 |
| 原STA→NSS→有线电脑，第一组 | 23.697 | 21.084 / 57.689 |
| 原STA→NSS→有线电脑，第二组 | 29.300 | 29.917 / 63.374 |
| 电脑直连上游Wi-Fi，后 | 9.316 | 9.897 / 10.495 |

两条LAN实际tuple为.1.127:45332/45333→162.159.140.220:443，分别
保留15/12个ECM连接快照，均观察到ACCEL=2，slow_path最大5，driver
fail、NACK、flush、no_action_total均0；瞬时no_action_seen曾为1，
不能写成每个快照都0。包含诊断SSH的窗口CPU busy16.71/16.98%，
softirq3.19/2.60%，不是精确TCP body窗口的CPU成本。

电脑直连信号−81至−82dBm，后组末次RX27Mbit/s/40MHz/NSS1；路由器
一组末次RX260Mbit/s/80MHz/NSS2、−77dBm。两端radio及条件不同；
结果不隔离RF与NSS，也不证明WAN单独限速。它不支持直接把这组公网
低速归为NSS固定上限，不能宣称原中继带宽目标解决。

monitor已删除，原配置逐字节恢复并以默认开关重启，两个SOC PN/密钥、
NSS、aging40000、STA/DHCP和有线DNS/HTTPS通过；交错试验也清理了
自己的ECM节点/抓包进程，六份配置hash不变，电脑Wi-Fi恢复关闭。
原始数据与镜像在桌面Redmi_AX3000_NSS_opt32。

factory SHA256：7957e6ac3a8b80106d3200aee41ceb33e31d53f8c0e0cf099804908a7901d2ad。
