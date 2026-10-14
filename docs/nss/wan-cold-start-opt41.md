# opt41/42：无线 NSS 冷启动握手失败与隔离结果

## 当前状态

上一轮隔离使用 `r0-nsslan-opt41-fe7e690dcd`，诊断启动暂时选择
`ath11k.nss_offload=0`、`frame_mode=2` 的 Wi-Fi host path；原始六份配置
已逐字节恢复，`nss-wifi.main.enabled=1` 和 packet steering=0 保留。
随后原配置再次以 `nss_offload=1` 启动，同一回程已恢复；当前继续
opt42的新部署轮次。host-path实验不能作为无线NSS完成交付的依据。

STA 回程 WPA/DHCP 已恢复。Fastsh `r3040` 完成真实有线验收：20次
gateway ping、UDP/TCP DNS、绑定 eno1 且 SO_MARK=666 绕过代理的16MiB
HTTPS下载通过；随后恢复有线主路由，普通HTTPS通过，自建备份路由
移除，主机原 Wi-Fi 关闭状态恢复。`r3046` 又完成NSS on的八模块/六
配置/真实有线验收和16MiB NSS IPv4 ACCEL=2；启动故障根因仍未确定。

## 运行证据

opt42冷启动及回退同一opt41时，STA `phy1-sta0` 到原上游
`f4:2a:7d:ab:24:4c`（TP-LINK_3A，5745MHz）持续reason15握手超时。
本机另一张Wi-Fi保持同一上游连接和HTTPS=200，保障诊断期间联网。

`r3029` 在进程内将路由器原回程与主机成功连接的密钥归一化为PMK后
比较，结果一致；没有输出密钥、PMK或其哈希。一次STA重建及PMKSA
清理未恢复连接。不能把故障解释为已证实的错误密码。

`r3033/r3034` 首轮短时抓取未见EAPOL，但当时profile临时禁用，不足以
定位数据路径。`r3035` 确认network0为TEMP-DISABLED，STA NSS格式
encap=2、decap=2、ready=1、failed=0。

`r3036` 用SELECT_NETWORK0清临时禁用后，25秒观察内明确发生两次
关联/四次握手超时，STA netdev仍未看到EtherType888E。
只读用户态AF_PACKET工具仅输出方向、长度和key-info标志，不输出
nonce、MIC、key data或其它数据包内容；未加载新的内核探针。
实验还原supplicant日志级别，六份配置哈希不变。

`r3037` 完整NSS统计中，第一个统计段RX delivered/REO reaped有数值；
第二段RX delivered及REO reaped为0，RX descriptor in-use=511，
TX enqueue=24、TX hardware descriptor reaped=48。
当时未先校对stats注册序号与PHY映射，不能直接把第二段标为STA。
`r3042` 实际symlink证明phy0 AP对应ahb-c000000.wifi/mac0，phy1 STA
对应ahb-b00a040.wifi/mac0。不能单凭未映射的统计段指定函数为根因。

`r3038/r3039` 只改一次启动参数选择，暂存原配置后以Wi-Fi host path
重启；启动后立即恢复六份原配置，原上游WPA/DHCP成功。
无线NSS启动路径被排除后故障消失，提供了与同一硬件、SSID和密钥的
有效对照。初始化还包含NSS队列/接口设置差异，不能将结果狭义等同于
仅某一EAPOL callback错误。

## 源码判断与未完成项

当前NSS STA EAPOL特殊RX在 `nss.c` 交给 `eth_type_trans()` 和
`napi_gro_receive()`，不走mac80211的NL80211控制端口RX。
NSS offload模式不广告control-port-over-NL80211。因此，在确认关联
发生的窗口内，AF_PACKET零帧有意义；尚需区分数据未到callback和
callback前后格式/安全门丢弃。

已有门检查key_failed、format_failed和format_ready；它们不要求STA
已授权、已安装密钥或create_done。key_failed的运行值尚未直接导出。
普通STA重新关联不清除该门，新VDEV创建才清除。

另有RAW undecap依据peer sec_type无条件剥IV/MIC的源码问题；当前STA
采用ETH decap=2，不能用它解释本轮故障。

`r3043` host path的正确STA队列TID0/16均成功取得实际硬件状态，
TID0 processed MSDU=38440，TID16=0。`r3045` 原配置重启到NSS on后
WPA/DHCP成功；同一BSSID队列TID0 processed MSDU=135、TID16=0，
NSS REO通知received/notify/not_ready/failed均0，因此这次成功样本不
支持早到REO通知丢失的归因。两次GET_QUEUE_STATS均有有效完整payload
和当前队列实例匹配。

待办：继续验证NSS开启下的冷启动稳定性并保留失败证据；完成opt42
混合协议组播、AP生命周期与有线/AP单播验收。故障当前呈间歇性，不能
把一次重新启动成功写成已定位或修复，也不能以host path替代完整目标。
