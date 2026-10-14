# opt38b：ordinary AP 的生产组播入口控制

已保留配置刷入 `r0-nsslan-opt38b-fe7e690dcd`。ath11k release34、
NSS clients release3、NSS driver release32、ECM release7。
完整 NSS 补齐目标继续；本轮没有自动启用 ME，也没有完成自动 MDB 发布。

## 生产改动

[0042 补丁](../../package/kernel/qca-nss-clients/patches/0042-bridge-keep-AP-multicast-policy-on-host.patch)
在非 PPE bridge manager 的公共 JOIN 入口排除 AP/AP_VLAN，覆盖
CHANGEUPPER、late reconcile 和显式 port JOIN。reconcile 不为新 AP
反复等待 NSS 注册。VDEV 注册、普通 NSS TX 和 IPv4 NAT 继续保留。

若发现既有 AP 成员，不能仅按保存的 ifnum 发 LEAVE：编号可能已经
复用。本轮保留 leaving/uncertain 记录及设备引用，拒绝新的成功加入；
只有保持该接口实例注册的拥有者才能调用显式 revoke。LEAVE 失败继续
保留记录。重试次数仍有上限。本轮冷启动 AP 从未 JOIN；热切换、旧
成员代次及固件在途数据排空不能以冷启动记录为证明。

新增只读 `qca_nss_bridge_mgr/parameters/ap_host_ports`，在 RTNL 下报告
当前 AP 的 NSS ifnum、成员记录和 uncertain 状态。它是主机记录，
不能独立证明固件 FDB 或队列已经清空。

[ath11k 补丁](../../package/kernel/mac80211/patches/nss/ath11k/999-999zzzzzzz-ath11k-route-ordinary-AP-MCBC-RX-to-host.patch)
把私有 ACK 请求、admission 和 exchange 移出 DEBUGFS 条件，在 ordinary
AP NSS UP 之前发送 cmd22=1。它不依赖 `nss_me_test`，不启用 ME，不
修改 AP_BRIDGE 单播开关；命令失败时撤销已启动的 WMI AP 并清 is_up。
当前自动控制限 Ethernet encap/decap；其它既有格式跳过此新命令。
允许合法 RESTARTED 恢复阶段，仍要求已注册、格式就绪及正常生命周期。
缓存命令 ACK 之前也检查这些门，避免关闭后的缓存 ACK 被当作可用。

固件静态依据是 ordinary Wi-Fi RX 的 MCBC 提前异常入口；本轮只对
当前三地址 AP 做端到端交付验证，没有增加 type14 路径计数，不声称
所有 WDS/extended RX、AP_VLAN 或在途包已经通过该入口。

## 验证与修正

实际 C 回归覆盖 AP/AP_VLAN 公共 JOIN 排除、STA 晚加入/重复 JOIN、
未知旧拥有者保留、显式拥有者 LEAVE ACK/失败及引用平衡。私有请求
回归覆盖 ACK/error/len/echo、身份、取消排空、生命周期、生产 cmd22、
RESTARTED 和旧格式跳过；ASan/UBSan 通过。恢复和非 Ethernet 行为
是源码/实际函数证据，尚未做整机恢复或 RAW/NATIVE_WIFI 实机验证。
新测试已接入 CI，原 STA bridge 回归已按实际 STA 类型更新。

修正后的五个 prepared 文件与编辑源逐字节相同。完整构建 `r2891`
全部步骤 exit0；实际对象含 `ath11k_nss_me_host_rx` 和 AP 只读参数。
早先构建 `r2886` 没有包含审查修正，不作为最终交付证据。

首个 opt38 镜像刷入后，八模块准确、六配置一致且有线验收通过，但
根文件系统的版本文本仍是 opt37，观察程序因版本不匹配返回75。
它不是一次尚未完成的启动，也没有重发该升级。自定义 version 文件
没有纳入 base-files 的依赖，且各次 revision 最后一个字段相同，导致
旧 base-files 被复用。本轮给 Makefile 增加可选 version 文件依赖。

新增 [真实镜像版本检查](../../scripts/nss/verify-image-version.py)，组装
factory UBI 中的完整 SquashFS，并与 sysupgrade tar 的实际根文件系统
比较，读取内部 openwrt_release。旧 opt38 实际镜像被此检查拒绝；
不 clean 的增量构建 `r2901` exit0，新 opt38b 的两个实际 payload 均为
正确版本。四种镜像/profile hash 和已验收 opt37 回退 hash 也通过。
initramfs 的 hash 被核对，本轮没有单独启动它。

opt38b factory SHA256：
`3e45c64dfada8a71bd2b81baa2d08e23fcb562447f2d5c3b63543d97958c4748`。
opt37 回退 SHA256：
`00adb7a264d0cba7c6567f9a467c8e4b29d8b54f8027e7593b87edd901aca125`。

## 实机结果

两次升级各发送一次；两次发送后的普通 HTTPS 均通过独立上游 Wi-Fi
返回200。本机刷前 Wi-Fi 为关闭，刷后先建立原自有 eno1 metric48，
恢复代理出口 eno1、删除自有备用 metric47，再关闭 Wi-Fi；普通纯有线
HTTPS200。没有改 NM 持久配置，保留 packet_steering=0。

opt38b `r2905`：新版本、八个准确模块、六配置、NSS READY、DSA ready、
原 STA/DHCP 均通过；phy0-ap0 的 NSS ifnum 有效，成员0/uncertain0，
默认试验N，rx_mcbc_known1/rx_mcbc1。实际有线 UDP/TCP DNS、20/20
网关、16777216字节证书校验 HTTPS 全部通过，网卡错误及丢包增量0。
该次下载35.373Mbit/s，属于实际回程验收，不表示已完成原性能目标。

首个 AP probe 在启用本机 Wi-Fi 后立即连接，返回4，未进入发包阶段；
后续诊断显示 NM 初始状态 unavailable，失败和清理记录保留。修正为等待设备就绪、
扫描并指定已核对的 AP BSSID 后，`r2909` 三轮各128个1024字节载荷：

| 路径 | UDP/L2 | 重复/异常 | 接收 DA |
|---|---|---|---|
| AP→有线组播 | 128/128 | 0/0 | 01:00:5e:26:00:01 |
| 有线→AP 组播 | 128/128 | 0/0 | 01:00:5e:26:00:01 |
| 有线→AP 单播 DA | 128/128 | 0/0 | 38:7a:0e:d4:9a:04 |

试验开关全程N，没有写手动 ME 或 rxmcbc 命令；pcap、原配置 hash、
临时 namespace/接口清理和 Wi-Fi 关闭均核对。该单播 DA 测试载荷
仍使用组播 IP，单独的 AP Internet 流在下一段验证。

`r2910` 有线 `192.168.1.127:45327`，`r2912` AP 客户端
`192.168.1.100:45328`，分别对 `162.159.140.220:443` 完成16MiB实收，
各自捕获唯一 `nss_v4.ported.accel_mode=2` 连接。原配置均相同，自建
char 节点删除；AP 测试后恢复原 radio 关闭和主有线出口。这证明新
AP 排除门保留当前 AP Internet 及 NSS 加速连接。取证暂停 body 并
限制接收窗口，其速率不能用作性能比较或证明每个包都走硬件。

## 继续工作

下一步接自动 MDB worker、完整当前谓词的 MCU 发布和 TX 回退。
已知组失效后的数据必须保留 native bridge 选择的完整目标集合，
不能丢失来源/出口上下文后简单向全部 STA 复制。还需 STA/key/VDEV
生命周期撤销、多 STA 和 IPv6 组播、WDS/extended 路径及性能验收。
本轮端到端交付不替代这些未完成项。

最终镜像、回退、真实 payload 检查、源码、配置备份和验收在桌面
`Redmi_AX3000_NSS_opt38b`；首个 opt38 版本故障在 `Redmi_AX3000_NSS_opt38`。
