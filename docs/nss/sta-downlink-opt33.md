# opt33：修正QCN6122 monitor PPDU与MAC头前缀校验

当前工作固件为r0-nsslan-opt33-fe7e690dcd，mac80211 release31，NSS
driver release31、nss-wifi release10保持。正常NSS转发和六份配置保持，
原5GHz中继带宽目标仍未完成。

## 源码修正

[opt32实机证据](sta-downlink-opt32.md)确认固定hdr_status偏移可匹配
MAC字段，前缀字的PPDU在高16位，低16位为0。新增999-999zzzz补丁：
按高16位校验PPDU，并拒绝低16位非零；MAC头比较前分别要求FC、RA、
TA、Seq有效，QoS按其有效位和TID独立检查，Retry与info11一致。

只对实机已观察的LEN132增加明确的截断处理：MAC头长度必须位于
实际120字节hdr_status内，标记HDR_TRUNCATED，禁止TRUSTED；不读取
声明尾部或Ethernet payload来补全TLV。其他超出124字节的未知长度
仍拒绝。原始header_ppdu列继续保存原32位前缀字，解析PPDU用高16位。

候选偏移诊断只给出位图，不提升信任。HDR_MATCH表示有界MAC头与
独立描述符字段一致，TRUSTED是额外描述符/未截断/FCS条件的组合；
两者都不代表已经输出完整空口帧。未输出payload、PN、密钥或合成pcap。

canonical补丁镜像一致、零fuzz/逐字节还原、六份prepare文件一致；
模块和四profile镜像生成通过。实际compact结构和Linux header helpers
上的ASan/UBSan覆盖短buffer、候选偏移、PPDU高16位/保留位、未知
长度拒绝、已知截断不信任尾部、每字段有效位、continuation/FCS。
格式private ACK/实际response边界/取消与生命周期/monitor unwind回归
通过；controller语法及git diff --check通过。没有重跑未改动的所有旧组。

## 实机验收

保留配置刷入后四模块hash一致，原STA/DHCP、有线NSS与Ethernet模式
就绪。同TCP两轮8MiB共16MiB，4.94196秒、整段27.159Mbit/s，body
24.414/62.705Mbit/s；不能将时变取证窗口写成补丁带宽收益。

9份快照合并15886条不变ordinal，produced15886、缺号0。全部前缀字
高16位匹配MPDU_START PPDU，低16位非零数0。独立有效字段筛选到
12292条原AP→STA DATA，全为decap2，全部HDR_MATCH；其中12283条
LEN132被标记截断且不获TRUSTED，9条较短TLV通过额外条件。

这组FC Retry1435、FCS_BAD559，是首buffer观察样本，不是完整空口
发送分母；不能据此计算端到端丢包率。原始MAC字段交叉验证已闭合，
完整加密帧、聚合布局、硬件时间与TCP缺口对应关系仍未验收。正常
monitor RAW/NATIVE consumer仍不能直接消费NSS复制的Ethernet DATA。

已删除自建monitor并精确恢复配置，以默认开关重启：nss_monitor_test=N、
concurrent_decap=0、monitor_metadata enabled:0，不再分配记录环。
原5GHz STA/DHCP、NSS enabled/ready、格式ready、两个SOC PN/密钥
outstanding0/poisoned0、aging40000、ext_rx_stats0以及有线UDP/TCP DNS、
HTTPS检查通过，电脑Wi-Fi恢复关闭。

原始数据、四镜像、源码/测试与哈希归档在桌面Redmi_AX3000_NSS_opt33，
附已验收的opt32回退。性能归因仍参考[opt32交错对照](sta-downlink-opt32.md)：
电脑直连同上游也低且无线条件不同，没有证明NSS是固定吞吐上限。

factory SHA256：5b4553905a1c5b6403ad617ffd4463ca3959ba548911bb9bf0557e178e2a3a63。
