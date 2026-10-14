# opt28：WMI 密钥完成、恢复唤醒和删除引用生命周期

继续补齐 NSS 与排查 5 GHz 下行。设备已保留配置安装
`r0-nsslan-opt28-fe7e690dcd`，完整镜像、模块及运行验证完成；
没有将此密钥生命周期修复当作原回程带宽已改善的证据。

## 确定缺口与实现

原 `ath11k_install_key()` 只重置 ar 级 completion，不重置旧成功
status；恢复代码直接 complete 等待者，可能使没有收到安装完成
的操作返回成功。WMI callback 也没有匹配 vdev/MAC/key_idx/flags。
实际原 C 的 recovery-wake 测试错误返回0，修复后返回ESHUTDOWN。

`999-998`用 base_lock 保护请求登记、终态和唤醒，conf_mutex串行
调用者。只有活动且未终结的匹配 wire tuple 才完成本次等待；
timeout与callback在同一锁下裁决，crash/关闭显式返回失败，finish
再次检查关闭和实际故障位。匹配NACK与send失败并存也视为身份
矛盾，不用被close覆盖后的result猜测是否收到过reply。

WMI transport收到unified_ready并完成HTT请求后才开放全局admission；
core stop、恢复、unregister/destroy先关闭，单radio仅正常start
末尾可打开局部门。destroy唤醒installer后等待conf_mutex退出，
清active RCU指针并排空读者，随后才free ar。

已发送后缺少明确完成或被中断的事务使该radio key-channel进入
poison。mask保存在ath11k_base，普通VDEV、Wi-Fi重启、ar重建及
自动固件恢复均不清除；需创建新的base，当前维护方式为设备重启。
一条迟到ACK不能证明未来同tuple复用安全。未修改原1秒等待默认值。
成功A的重复event在成功后的同tuple B期间仍无法从wire字段区别；
没有cookie，不能宣称消除所有固件重复/乱序歧义。

新0400 `wmi_key_stats`只记录宿主状态、数值身份和计数，不记录
key、MIC或nonce。它是软件观察，不能当作硬件key/PN readback。

## 关闭流程中的密钥引用

mac80211 即使收到 DISABLE_KEY 错误仍释放 key 对象。关门后拒绝
WMI 删除必须与宿主引用清理分开：仅按原peer和keys[idx]==key
解除引用、软件PN及对应VLAN组槽，保留replacement/剩余GTK/PTK。
DISABLE不覆盖已有hw_key_idx；bitmap操作不嵌套data_lock/base_lock。
closed clear_peer_keys先解除引用，再跳过命令构造，避免继续读取
已经失去宿主所有权的metadata。软件detach不等于固件删除ACK，
也没有在关闭时发送额外PN UPDATE或重装旧key。

原peer在等待期间被unmap/替换并进入DMA保留列表时，也必须解除
已pin原实例的匹配key指针；该分支不扫描其他旧key，不修改当前
replacement、STA PN或VLAN槽。增加“保留原peer＋上层释放key”
的实际C回归后重建；修复前候选镜像单独保存，从未刷入设备。

## 验证范围

新增实际C ASan/UBSan测试覆盖正确/NACK/错误tuple、超时及迟到、
发布失败矛盾、crash唤醒、故障位边界、关闭并发、实际destroy与
installer/RCU reader交错、base poison跨ar保留。旧C的错误成功
已用实际install/event/core recovery函数复现。

key回归增加实际mac_unregister→DISABLE→上层free→clear路径，
并检测closed clear不读失效metadata、VLAN共槽及旧key/replacement。
WMI lifetime、key、key ACK、TX gate、EAP route、shared DMA和
REO通知共七组canonical C通过；关联fixture已跟随新接口更新，
并未用fixture代替WMI本身的并发测试。CI接入新测试。

六份canonical补丁零fuzz还原，与草稿和干净prepared逐字一致。
mac80211 release25、NSS driver release30；干净AArch64编译和
严格modpost通过，最终包含保留peer修复的clean build为r2529，
最终image构建为r2531；六份final prepared与草稿再次逐字一致。

最终factory UBI SHA256：
`c99e3b9ee5d836b480aacc144936645a75ca555dc517988f3238f1aed0721c24`。
ath11k：`cf1090faf197112e5b2563438fc47a7fdc6dbdd4b4264f2ef58c9b2ce0b74ed4`；
AHB：`a1f5bcc9b1c2d812887d6ba76d4d31f4aa384b954f4261b3cb6c7c30743263b9`；
PCI：`6a72726f2565fbeaa7900f29c75dfc68f9a066fb060467d2cdc1b06f724e1bd3`；
NSS drv仍为`2a5172ea10c04938342bf6883143c65cddf3fcd369ee07825cf37073b571fc36`。
四份profiles image的实际size/hash逐项匹配；最终镜像、opt27回退
及0600原配置备份已保存桌面opt28目录。升级前独立Wi-Fi的UDP/TCP
DNS和HTTPS200/16384字节通过；r2534仅发送一次保留配置升级。

## 真机验证与未完成项

r2534只发送一次sysupgrade，新版启动、四个模块哈希及六份原配置
哈希已确认。首次boot的AP/STA为1/1、2/2匹配完成，GTK flags=1。
r2535随后正常radio1 down/up：AP累计7/7、STA5/5，last AP PTK
flags=0、STA GTK flags=1，expected/received vdev/MAC/index/flags一致。
双频mismatched/unexpected/timeouts/aborted/send_failed/poison均0，
admitting1、active0、closed0。当前正常事务的精确echo已有运行证据，
不能把它扩展为所有固件故障或成功后的重复event合同。

同次抓包完整M1–M4，M1→M2 3.820ms、M3→M4 4.890ms，supplicant
COMPLETED、DHCP正常。0400数值stats未包含key bytes；DEBUG/TRACING
仍编译关闭，没有使用原始安装命令或密钥dump。配置与日志设置恢复。

当前NSS1、有线ready1/error0/uncertain0、PROJECT0、ext统计0，四项
aging仍40000；QCN/内部REO UPDATE success为74/74、104/104。
最终电脑恢复本轮开始的Wi-Fi软关闭状态，经eno1/路由器联网：
UDP/TCP DNS均rcode0、2个answer，HTTPS200/16384字节通过。

一段新版本公网LAN下载4MiB至同一地址162.159.140.220，完整请求
15.245Mbit/s、body区间25.724Mbit/s。它发生于另一时段、没有同刻
host/NSS对照，不作为稳定带宽提升结论；此前上游/WAN/RF波动未
被排除。镜像、回退、备份、握手/数值stats与诊断源码已保存桌面。

NSS SEC_TYPE/AUTH ACK不包含Wi-Fi安装凭据；host时序责任见
固件反汇编记录。REO PN配置仍以异步提交返回，不能把本次WMI
完成修复宣称为完整硬件PN执行合同。healthy DISABLE失败的NSS
失效策略、完整VLAN key-owner模型及硬件删除状态仍需审查。
原回程间歇握手与带宽问题尚未解决；其他NSS功能缺口仍见README。

后续[opt29](sta-downlink-opt29.md)补齐独立REO PN执行完成等待及
NSS授权关闭门禁；以上“仍为异步提交”是opt28版本的历史边界。
