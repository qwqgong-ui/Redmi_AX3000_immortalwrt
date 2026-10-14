# opt35：ME ACK事务、真实交付与自动ND前置核对

最新运行固件为`r0-nsslan-opt35-fe7e690dcd`，ath11k和NSS driver均为
release32。前置ND/256帧基线是在opt34完成；下方新增的ME事务与
交付对照是在保留配置刷入opt35后完成。NSS完整补齐目标继续，
MDB自动消费、全范围回退和多个客户端的复制/离组尚未完成。

## 自动IPv6邻居发现的双端取证

新增有限时长的双端控制帧抓取工具：AF_PACKET/ETH_P_ALL，不开启
promiscuous或monitor；只保留自建端点及路由器的IPv6 ND/MLD控制帧，
每份pcap最多30秒。请求和应答均按软件接口观察，不等同于空口取证。

原TP-LINK_3A上游：两端分别看到了自己发出的NS，未看到对端NS或NA。
电脑原连接IPv6关闭且addr_gen_mode=1，第一次MLD源为`::`。补齐临时
链路本地地址后，MLD已有有效fe80源，但两端邻居仍未建立，双向各
5个ping均失败。仅此证据不能区分上游AP、STA数据面及接收端路径。

受控对照：电脑切到路由器原2.4GHz AP，原有线主出口持续通过HTTPS。
临时在br-lan和电脑wlan0配置同一ULA网段，不重建路由器radio。
双向各5/5 ping通过，抓包确认电脑NS进入br-lan、路由器NA返回电脑，
邻居为REACHABLE。此结果验证该AP/LAN通路的自动ND，不能推广到
原5GHz STA回程，也不构成NSS ME表同步验证。

所有IPv6地址和原运行开关恢复，电脑重新连接TP-LINK_3A。六份配置
hash未变；最终有线和独立Wi-Fi均通过UDP/TCP DNS与带证书校验的
HTTPS，普通网页访问通过。

## 桥组播交付基线

原br-lan multicast_snooping=0，phy0-ap0 multicast_to_unicast=1、
multicast_flood=1。为获得成员状态，试验中仅将snooping临时设为1。
自建LAN macvlan namespace用192.168.1.250，先通过ARP DAD核对地址
未占用；电脑AP端订阅239.35.0.1:45355，发送256个1024字节的序号
数据包，核对来源、序号和完整载荷。

收到229个不同序号，缺27个，unexpected=0；没有达到256帧完整交付。
当前工具尚未单独记录重复数量，不能据此声称无重复。NSS IPv4 MC
CREATE/UPDATE/DESTROY前后均0，不能把这组交付作为MC规则加速证明。
丢失发生点尚未定位，不直接归因NSS或无线条件。snooping恢复0，
自建namespace和netdev删除，六份配置hash保持。

## 源码与固件合同核对

NSS driver已有group/member/reset/toggle消息与tracked传输；内核有
逐主机MDB snapshot、dirty notifier及MCU发布API。当前ath11k没有
MDB→ME worker、建表消费或发布状态；VDEV notification仍是TODO。
256帧基线和ND通过均没有补上这条控制链。

普通Ethernet TX的两个固件调用者先检查DA首字节的组播位，再调用ME
wrapper，提供软件M2U→普通NSS TX的候选回退。ME内部没有足够证据
支持统一的单播立即退出；特殊或间接入口也未闭合。因此需要实测
ME空表时的组播DA与STA单播DA对照，不能仅凭Linux M2U基线启用ME。

ENABLE_ME是type10003、cmd3、8字节cmd/value；关闭值4，模式5/6启用
双表。新增静态核对确认：enable5/6也把表选择重置为0，不能在每次
toggle后重新enable并假定所选表保留。关闭4保留global mode/选择。
普通ath11k set_cmd只有提交结果，不能作为ACK事务；应使用独立的
private request、type/interface/ACK/error/长度/回显检查和取消排空。

本次后续实测闭合了普通AP的ACK回显及单客户端收发，结果见下方。
在途数据语义、全范围未知组回退仍待验证。下一实现必须保持完整目标：MDB/STA/key/VDEV代次失效，
备用表reset/build的逐项ACK，toggle后按原seq发布MCU，未知/不支持
组实际交付，以及停止/删除时先排空再释放，不能仅增加观察计数。

原始pcap、配置hash、失败序号、清理结果及工具在桌面
`Redmi_AX3000_NSS_opt35_ND`。相关已验证固件见[opt34记录](sta-downlink-opt34.md)。

## opt35实现与完整固件交付

新增[ath11k ME控制补丁](../../package/kernel/mac80211/patches/nss/ath11k/999-999zzzzz-ath11k-add-ACK-bound-ME-control-transactions.patch)
和[实际C事务测试](../../scripts/tests/test-nss-me-control.py)。
接口为root专用debugfs `phy*/ath11k/nss_me_control`，模块参数
`nss_me_test`默认N。当前仅允许显式ordinary AP试验，不启动MDB worker，
不设置bridge MCU，也不自动启用ME。

每条请求使用独立内存、tracked cookie和完成等待，校验type、interface、
ACK、error、实际长度和逐字节payload回显；返回后先取消/排空callback再
释放。提交前后复核NSS/VDEV和key门；memberadd只接受同VIF已授权STA，
pin实际peer及NSS state，使用真实peer_id，RA MAC也填入该STA。
已经提交但未明确成功的请求标记uncertain，仅允许mode4恢复。
表选择shadow与格式状态分离，成功enable5/6重新选择表0。

ASan/UBSan测试提取实际请求callback、admit、exchange和真实8/28/112
字节消息结构，覆盖NACK/error、错回显、边界长度、NOTIFY、错接口、
取消时callback、超时和peer/key/VDEV失效。原format与control回归通过。
clean prepare后五个文件与编辑源一致，严格modpost及四种完整镜像构建通过。
首次测试shim typedef和首次模块编译缺少`net/ip.h`的失败均已修正，
最终成功记录与初次失败分别留存。

factory UBI SHA256：
`65bebbef004442760cc5fd0afca6b9b36d74ea80f9395635cb44f6563dcbfc5f`。
保留opt34回退镜像及刷前配置备份。只发送一次sysupgrade，SSH断开后
观察同一次启动，没有因第一轮未观察到启动而重发。
新版本、8个模块hash、6份配置hash、NSS ready、有线接管及原STA/DHCP
均通过。`nss_monitor_test=N`，没有启用monitor记录环。

## 真实ME控制与普通TX交付

AP为原2.4GHz `phy0-ap0`，vdev0/ifnum31；电脑临时连接该AP，MAC
`38:7a:0e:d4:9a:04`、IP `192.168.1.100`。LAN侧使用隔离macvlan
namespace `192.168.1.250`，先做ARP DAD。仅临时将bridge snooping和
AP multicast_to_unicast均设0，以区别固件ME复制和Linux软件复制。
每轮128帧、1024字节UDP载荷、独立phase/sequence、35ms间隔；发送端
及接收端pcap保留实际Ethernet DA，同时核对UDP完整载荷和重复。

真实ACK均为response0/error0、exact echo、result0：mode为8字节，
group为28字节，member为112字节，reset/toggle为0字节。
成员模式为EXCLUDE空源列表，尚未测INCLUDE、IPv6或多源过滤。

| 状态与输入DA | UDP接收/128 | 接收Ethernet DA | 重复/异常 |
|---|---:|---|---:|
| ME关闭，组播DA | 125 | 01:00:5e:23:00:01 | 0/0 |
| ME关闭，STA单播DA | 128 | STA MAC | 0/0 |
| mode5空表，组播DA | 0 | 无 | 0/0 |
| mode5空表，STA单播DA | 128 | STA MAC | 0/0 |
| mode5建组/成员/toggle，组播DA | 128 | STA MAC | 0/0 |
| mode5已建表，STA单播DA | 128 | STA MAC | 0/0 |
| mode5未知组239.35.0.2，组播DA | 0 | 无 | 0/0 |
| mode6建组/成员/toggle，组播DA | 128 | STA MAC | 0/0 |
| mode6已建表，STA单播DA | 128 | STA MAC | 0/0 |
| 再次关闭ME，组播DA | 128 | 01:00:5e:23:00:01 | 0/0 |

这证明本次ordinary AP条件下，ME实际复制工作，单播DA能够绕过ME；
同时证明空/未知组的组播DA没有得到回退。首轮关闭ME的基线缺序号
1/2/3，整组probe因此返回失败；末轮通过不能抹掉首轮失败，也不
把空表/未知组的预期丢弃说成完整组播验收。仅一个接收STA，不能
宣称多STA fanout、source filter、离组、ageing或控制组已经通过。

首个控制probe使用BusyBox `printf '%s\\n'`，命令本身得到有效ACK但
工具返回1；改为无换行的单次write后11条控制及清理均返回0。原失败
输出保留，不把这个写入工具问题归因固件拒绝。

所有probe结束后确认mode4、test gate N、snooping0、M2U1，namespace
及netdev删除，电脑恢复原上游连接，六份配置未变。关闭ME后另做
16MiB有线绑定TLS，明确排除本机透明代理：单一tuple
`192.168.1.127:45327 -> 162.159.140.220:443`为
`nss_v4.ported.accel_mode=2`，实收16777216字节、6.616秒、20.288Mbit/s。
这项只确认NSS正常转发，不宣称回程性能提升。

## 本机联网与自动管理剩余条件

刷写时保留电脑直连上游Wi-Fi，普通Cloudflare和Arch HTTPS在路由器
重启期间均返回200。临时用本机Mihomo的loopback API固定出口wlan0，
未修改其配置文件，也未记录凭据。恢复automatic后最初普通HTTPS
通过；后续Wi-Fi/AP及主路由切换造成代理连接超时，而绑定LAN的
直连TLS仍正常。恢复独立Wi-Fi、重新固定出口并仅重启现有Mihomo
服务后，两项普通HTTPS再次返回200。当前开发期间保留这条独立
备用出口，后续结束时还原已保存的原interface-name。

源码核对显示Linux桥逐主机M2U不覆盖匿名成员、router及flooding；
ECM MC CREATE/UPDATE可直接指定AP的NSS ifnum，绕过宿主TX。
此外NSS bridge JOIN及AP_BRIDGE固件内部转发尚未证明没有旁路。
所以不能直接把bridge MCU=true视为完整回退或在途数据屏障。
下一阶段需定位普通TX/旁路，闭合未知组、广播/控制组和现存规则
撤销，再接MDB完整快照、STA/key/VDEV代次、双表事务和seq发布。

本次镜像、精确模块hash、配置备份、pcap、每轮序号、ACK字段、
清理结果、流量与构建/源码测试证据在桌面`Redmi_AX3000_NSS_opt35`。
