# opt31：QCN6122 monitor 首 buffer 元数据取证

当前运行 `r0-nsslan-opt31-fe7e690dcd`，在opt30b的格式/ACK/发布门基础上
增加只读metadata，不更改正常NSS转发。目标仍是补齐NSS及定位5GHz下行
低速，当前没有证明带宽问题解决。

## 实现与验证

mac80211 release29；新增 `999-999zz` 补丁。NSS driver release31、
nss-wifi release10保持。canonical补丁一致、零fuzz还原通过，重新prepare
文件与草稿一致；模块/镜像构建、6组metadata/format/key/TX/host-ring/
boot回归通过。parser使用实际384字节compact结构、实际Linux FC/header
helpers，ASan/UBSan覆盖短buffer、tag/length、有效位、PPDU及头字段比较、
continuation/FCS拒绝。未采集或重构完整空口payload。

记录点位于普通monitor pop经过MPDU_START与PPDU检查后的原首buffer，
且此前没有消耗/缺失buffer，不依赖被helper改写的link FIRST/LAST。
只有非continuation才读取MSDU_END/attention；每字段有效位分别保存。
环8192项，仅显式QCN6122试验分配，默认不分配。锁为发布/快照复制的
叶子锁；锁内不打印、不查peer、不拿conf/base/mon/SRNG锁。序号跨radio
lifetime保留，session从monitor启动计数标记；不把16位PPDU当跨会话唯一键。

## 实机结果

保留原配置安装后module hash及六配置hash一致，原STA/DHCP、Ethernet模式
和有线NSS正常。受控monitor期间同TCP两轮8MiB共16MiB、3.64835秒，
整段36.789Mbit/s，body35.587/101.897Mbit/s。连接预热、链路时变和observer
开销未排除，不能归因为补丁增益。LAN10048包，kernel drops0。

8个metadata快照合并13444条不变ordinal，覆盖produced13444，没有缺号。
MPDU_START tag207/LEN92、MSDU_END tag210/LEN68、attention tag211/LEN12
均一致。样本decap2为13271、RAW173；独立有效FC/RA/TA/Seq及匹配PPDU
筛选到11865条原AP→STA DATA，TID0为11864，TID5为1。

这组354条FC Retry置位，与info11 Retry核对不一致数0；115条FCS_BAD，
11865条MSDU_END/attention DONE可读且硬件FIRST+LAST成立，continuation0。
这些是观察到的首buffer样本，不是完整空口发送分母，也不能由此计算
端到端丢包率或定位WAN/NSS/RF哪一段丢包。

独立原始header交叉验证未通过：RX_HEADER tag214中11961条LEN132，
超过当前固定header区域的124字节假设；其余常见LEN36/18/24。
保守parser没有越界放宽，header_match0、trusted0。不能把独立MPDU_START
字段已可读说成原始80211头已验证，也不能猜偏移后发布合成pcap。
实际TLV长度/prefix/monitor布局需进一步核对。

已删除自建monitor，精确恢复配置并从原配置重启：`nss_monitor_test=N`、
`concurrent_decap=0`、`monitor_metadata enabled:0`。默认工作固件opt31，
原STA/DHCP、有线NSS、格式ready、两个SOC PN/密钥、aging40000及有线
UDP/TCP DNS、HTTPS验证通过，电脑Wi-Fi恢复关闭。固件及原始数据在桌面
`Redmi_AX3000_NSS_opt31`，附已验证的opt30b回退。

factory SHA256：506b29ceae879082e3989d95462b7893d542190bff9e168663f3d10c129fac90。
