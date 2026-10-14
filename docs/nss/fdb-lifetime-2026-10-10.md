# 2026-10-10 NSS FDB 撤销与启动时序修复

已修复 Linux bridge 与 ECM 的 FDB 通知格式不匹配。原 MAC 移动和老化路径
传递裸 6 字节 MAC，ECM 却按 `struct br_fdb_event` 读取旧端口、新端口和 MAC。
对原准备源码的 ASan 回归可在实际 ECM 移动回调中复现越界读取。

修复位于
`target/linux/qualcommax/patches-6.12/0602-bridge-preserve-nss-fdb-event-and-refresh-lifetime.patch`：

- 普通 ADD/DEL 完整初始化事件，并只读取一次目的端口快照。
- 学习、手工替换和 external-learn 替换在修改前保存旧端口和 local 身份。
  两个远端之间移动使用原 update chain；远端变为 local 或无端口时，使用
  旧远端的 DEL 事件撤销加速连接，避免向既有 move 消费者传递 NULL 端口。
- 老化沿用原来的单次 DEL，不再发送重复的裸 MAC update。
- 三个 NSS FDB 辅助函数在同一 RCU 区间内检查 bridge port 并访问 FDB。
  `br_fdb_has_entry()` 的返回值仍只供当前 ECM 判断是否存在，不能作为退出
  RCU 后可解引用的 FDB 引用。

`scripts/tests/test-nss-fdb.py` 提取实际准备的内核生产者与 ECM 消费者，
覆盖学习、重复学习、sticky/local、老化、删除、手工和 external-learn
替换、创建新条目及 RCU 保护。修复版通过 ASan/UBSan，旧版触发 ASan。
AArch64 的 `br_fdb.o` 交叉编译通过；完整镜像的 vmlinux 含修复函数。
该回归是单线程模型，不等于验证真实 RCU 回收或无线漫游。

真机验证使用 opt7，factory UBI SHA256 为
`53e09788dffa5f7478da7cf2d81afc35e65e1cd4b94eb66febc5ef00b4f5fbb3`。
电脑保持直接上游 Wi-Fi 联网，另建独立有线 macvlan 命名空间，端点为
`192.168.1.252`、MAC `02:00:50:18:00:f7`。该命名空间没有桌面透明代理规则。

测试是限速 20 MB HTTPS 下载，同时仅替换此测试 MAC 的 bridge FDB 端口：

| 观测 | 替换前 | 替换后 |
|---|---:|---:|
| ECM connection serial | 2 | 4 |
| TCP 端口 | 45110→443 | 45110→443 |
| NSS accel_mode | 2 | 2 |
| NSS IPv4 create_requests | 1 | 2 |
| NSS IPv4 destroy_requests | 0 | 1 |
| NSS IPv4 destroy_misses | 0 | 0 |

旧 serial 从快照消失，新 serial 4 的接收累计统计由 2088 增至 1116216
字节，`slow_path_packets` 保持 3。有线控制器全程 READY、无错误；原 TCP
传输完成 20000000 字节，用时 38.657 秒。测试后恢复 LAN FDB 并删除测试
命名空间、邻居与 ECM 节点。该证据验证 FDB 管理替换导致规则撤销和重新
加速；没有模拟真实无线客户端漫游，也不作为峰值吞吐。

本轮另外发现启动竞态：有线 NSS 请求可能早于 LAN 链路就绪，或者 ECM
启动时控制器已经启用但正因链路变化暂时不 READY。`nss-lan.init` 现在最多
等待五轮，完全释放的 owner 才重新申请；已启用的 owner 只等待其自身恢复，
不会重复写入启用参数。未知分配或未释放资源不会被盲目重试。

`scripts/tests/test-nss-lan-init.py` 的 15 个场景通过，覆盖禁用、未就绪、
模块失败、立即成功、链路延迟、资源残留、不确定分配、已有 owner 恢复
以及超时。nss-wifi release 为 9。

最终已保留配置刷入 `r0-nsslan20261010opt9-fe7e690dcd`，factory UBI SHA256：
`bf288c3d4f23a4c217bd4faf7f6a253056474b89a8590c4e836ea6f770639cae`。
首轮启动 NSS 在 uptime 40.711 秒 READY，ECM 在 42.119 秒注册路由与桥接
入口。随后另做一次软件重启，boot ID 改变，NSS 在 34.057 秒 READY、ECM
在 34.982 秒完成同样的入口注册。首次 39 秒观测时无线尚无默认路由，稍后
5 GHz STA 完成认证和 DHCP；90 秒检查时公网 ping 为 3/3，不能将早期
观测误判为持续断网。

两轮均自动达到 `enabled=1 ready=1 provider_held=1 error=0`，无需手动启用。
实际 init 文件 SHA256 与源码一致：
`3e55160ae90ade5179938fc671455b5e016e34e7834e8cc59be11e4607f5119d`。
无线文件仍为原始备份 SHA256
`7956835d0821810fda9dbd0345ab5612177aec62b8cf8702312690fd5136a6d1`，
保留 2.4 GHz AP＋5 GHz STA 和无线优先默认路由。电脑互联网继续直连上游
Wi-Fi，桌面保存了最终镜像和每次刷入前的配置备份。

后续已完成 [opt9 HE160 对照及 600 秒持续负载](performance-2026-10-10.md#opt9-同条件复测)，
单向 758–931 Mbit/s，持续双向 328 / 847 Mbit/s，持续窗口平均 CPU 3.70%。
完整组播同步尚未接入，IPv6 仍未运行验收。

原始 live FDB、ECM 与 NSS IPv4 统计位于桌面
`Redmi_AX3000_NSS_继续开发_20261010/opt7-fdb-*`。
最终重启原始记录为同目录的 `opt9-after-warm-reboot.log` 和
`opt9-warm-settled.log`。
