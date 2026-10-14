# opt29 原回程单空口、TCP 与 monitor decap 取证

本轮沿用已运行的opt29，没有改固件、PN/SSN、BA窗口或aging。
原5GHz下行低速仍未解决；新增观测用于定位损失与补齐NSS并存
monitor的格式合同，不将公网样本当成无线转发容量上限。

## 受控路径和恢复

电脑保留eno1→路由器的有线连接，将自己的wlan0暂设unmanaged，
仅启用5745/80MHz/中心5775的被动monitor。电脑未关联上游AP，
数据路径为公网→TP-LINK_3A→路由器5GHz STA→有线电脑，只有
一次空口传输。monitor按路由器MAC44:df:65:b0:63:2e过滤；
同时抓eno1上指定TCP端口与固定服务器的报文，snaplen均160。

TLS验证、hostname/SNI保留，只有下载socket绑定eno1、使用mark666
绕过电脑原透明代理。路由器当前规则仅local/main/default，目标
经192.168.15.1/phy1-sta0；这一读回没有发现路由器内的隧道路由，
不证明上游AP/ISP没有其他路径影响。

三个阶段读取原peer的TID0/16硬件GET；每份均SUCCESS/payload100/
current_instance1、generation/paddr一致，四项aging40000。
每个capture的finally删除自己的monitor/进程，恢复Wi-Fi软关闭、
wlan0 managed=yes及六份配置。最终STA/DHCP、NSS ready1、无PN/
REO pending正常，eno1的UDP/TCP DNS与HTTPS16384字节通过。

## 有效传输结果

| 试验 | 数据量和连接 | 完整请求Mbit/s | 数据区间Mbit/s |
|---|---|---:|---:|
| r2577 | 单次8MiB | 25.078 | 38.007 |
| r2580 | 同一TCP/TLS连接，4次8MiB | 31.994 | 38.561 / 34.915 / 50.043 / 41.759 |

两组SYN计数均为2（客户端/服务端各1），长连接没有重新建连。
首轮16MiB请求non200而中止，保留原始capture及失败记录；该次
没有有效吞吐数据，不混入表格。工具后来保留具体HTTP状态和
响应前缀，并将单请求限定8MiB。

长连接四个响应的CF-Ray均带`-FRA`。该字段说明Cloudflare的处理
位置，Argo等场景下也可能反映连接origin的节点；不能单凭它
定位用户出口或入口。[Cloudflare官方说明](https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-ray)

服务端ACK的RTT中位数为205.239/210.574ms，最低204.531/208.107ms。
电脑TCP窗口缩放11、服务端13，接收窗口最大约11/23MiB，没有
window_full或zero_window。窗口耗尽没有本轮证据；长RTT及
TCP恢复时延参与公网结果，不能据14–50Mbit/s认定NSS固定上限。

## 缺口修复时序和观测边界

按完整TCP sequence区间归并，收到的payload没有重复覆盖，最终
不存在未填补的接收缺口。两组分别163/2055次区间缺口填补，中位
等待205.389/302.368ms；均没有小于100ms的填补，长组最长约
1309ms。TShark将不少首次到达的低序号包标为suspected fast
retransmission；“首次到达”不排除原包在LAN之前丢失后重传。
等待接近端到端RTT，与重传恢复一致，不能因此定位到WAN、空口
或NSS中的某一段。GRO会合并LAN包，计包数不是原始空口分母。

空口observer几乎只捕获router→AP：短组1980帧（bad-FCS标记63、
未标bad的retry276），长组7521帧（bad1007、未标bad的retry1511）。
其AP→router DATA与确认下行的STA→AP BA均为0，不能解释为没有
下行或没有发BA；电脑显然没有完整观测弱AP的下行。observer的
RSSI约-38dBm针对路由器发射，不能代替路由器接收AP的RSSI。

TID0 generation18/paddr0x4e0bf000：短组processed MPDU70612→76509、
late247→251、hole1468→1555；长组processed98360→122411、
late435→512、hole1639→2386。TID16 generation34始终processed0。
这些是原peer累计状态，含背景流量；保持窄字段原始值，不把
hole/late直接除以TCP包数或推断硬件BA窗口。

解析器适配本机TShark的True/False输出，并区分服务端ACK RTT与
电脑立即ACK的本地延迟。初版的Boolean及RTT混算结果不用作结论。
独立原生display filter按`==1/==0`复核DATA/FCS/retry/SYN计数通过；
两组tcpdump kernel drops均0。原始pcap、TSV、JSON及失败记录保留。

## 新的NSS并存monitor缺口

QCN6122有monitor buffer/status及host消费链，NSS跳过monitor VDEV
注册；但mac80211被动monitor打开会重算既有STA offload。当前
ath11k没有SUPPORTS_CONC_MON_RX_DECAP，STA RX_DECAP_ENABLED被
清除后，`ath11k_mac_op_update_vif_offload()`把Wi-Fi FW切到
NATIVE_WIFI，却不更新NSS模式。初始add_interface还把TX参数
同时用于NSS encap/decap；STA在monitor已存在时创建也可能分离。

NSS `vdev_set_cmd()`在发送前修改宿主encap/decap，只返回提交状态；
普通RX按缓存`arvif->nss.decap`解封装。这是明确源码缺口，尚未在
设备上执行不安全的NSS1并存monitor试验。不能盲设concurrent-decap
能力，也不能仅以两条控制命令ACK之后写缓存来宣称安全切换。

MP12.2 INTERFACE_CMD type10003，cmd2接受0=RAW/1=NATIVE_WIFI/
2=ETHERNET，`0x400bf590→0x40099720`校验，`0x40099ee8–0x40099f14`
直接改变VDEV+232关联对象及+246 mode。该分支没有已证的旧RX
排空或包generation；普通N2H公开ABI也没有逐包decap字段。
stock11.4同样直接更新mode。ACK不能充当已经证明的格式fence。

后续修复需闭合初始TX/RX独立选择、ACK后发布committed状态、
转换期旧包边界和失败恢复，以及NATIVE的3/4-address/QoS/A-MSDU/
EAPOL/MCBC头型。当前STA MEC在解封装前按ethhdr读取源地址、
WDS_LEARN仅eth_decap处理，不能把现有NATIVE接收当完整合同。
HTT peer stats默认FLUSH_TQM含义也未由目标Wi-Fi FW证明，本轮
没有将它当成无副作用抓包辅助命令使用。

原始证据位于桌面opt29目录的original-airpath-1/2及
original-airpath-long-1；本轮新增控制器/解析器和源码证据另行归档。
