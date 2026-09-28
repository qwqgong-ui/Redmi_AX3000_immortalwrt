# Redmi AX3000 NSS 无线实验分支

本分支以 `redmi_ax3000-25.12` 的 `37f38d8b364bf0c58e6ad0385501404d885961f4`
为基线，保留 Linux 6.12 和现有有线网络驱动，首先接入 IPQ5018 内置无线及
QCN6122 的 ath11k NSS 收发路径。

这是移植和上机验证用的镜像。编译成功、固件文件存在、`nss_offload=1` 都不
能单独证明无线流量已卸载。本仓库没有 Redmi AX3000 真机的运行验证结果。

## 本阶段范围

- 将 mac80211/ath11k NSS 补丁接入现有 6.18.39 backports，仍运行于 Linux 6.12。
- 接入支持 IPQ50xx 的 QSDK NSS 核心驱动、其内核兼容及 IPQ50xx 时钟/复位修正。
- 使用 IPQ5018 **MP** 固件 `NSS.FW.12.2-156`，固定来源包和 SHA-256。
- 增加 NSS 中断、时钟和 16 MiB 固件保留内存。保留区为
  `0x40000000..0x40ffffff`，内核装载地址仍为 `0x41000000`。
- ath11k 和 NSS 都选择 256 MB 内存配置。
- `nss-wifi` 服务在 NSS 固件完成握手后加载无线驱动。固件 30 秒内未就绪时，
  改用普通 ath11k 主机收发路径。已经加载无线驱动后，更改配置须重启。
- NSS 驱动默认 `wifi_only=1`，不接管以太网的 `qca-nss-dp` 数据通路。

本阶段未接入 ECM，不宣称路由/NAT 连接卸载。802.11s、WDS、动态 VLAN 和
监控模式也不在本轮验收范围内；先验证两个频段的普通 AP。

## 构建

```sh
./scripts/feeds update -a
./scripts/feeds install -a
cp configs/redmi-ax3000-nss-wifi.config .config
make defconfig
make -j"$(nproc)" download
make -j"$(nproc)" V=s
```

独立工作流 `.github/workflows/nss-wifi.yml` 在推送
`redmi_ax3000-25.12-nss-wifi` 后构建，产物放在 Actions artifact。
它检查必要配置是否被 `defconfig` 保留，以及镜像清单是否包含固件、NSS
驱动、ath11k 和启动服务。不会自动更新正式 release 或包仓库。

本地已使用本仓库 Linux 6.12.108 / GCC 14.3.0 的 SDK 编译并打包
`qca-nss-drv`、mac80211、ath11k（AHB/PCI），以及 NSS 固件和启动服务。
已检查实际模块的 NSS 符号依赖、固件装载文件名和无线模块的自动加载配置；
对应内核的设备树编译、配置生成及工作流/脚本静态检查通过。
完整镜像由本分支 CI 构建；以上检查不替代真机启动和流量验证。

## 上机验收

保留可用的有线管理连接，使用产物中的 initramfs 镜像先验证启动，按本机
已有的恢复/启动方式操作；这里不改动引导器和分区表。

启动后运行：

```sh
nss-wifi-status
cat /sys/module/qca_nss_drv/parameters/core0_ready
cat /sys/module/qca_nss_drv/parameters/wifi_only
cat /sys/module/ath11k/parameters/nss_offload
cat /sys/module/ath11k/parameters/frame_mode
```

预期 `core0_ready=1`、`wifi_only=Y`、`nss_offload=1`、`frame_mode=2`。
检查日志中 NSS core 成功启动、两张无线网卡均建立 NSS 接口，没有超时、
Q6 assert、Oops 或不断重启。`iw dev` 应能看到两个频段的 AP。

分别连接 2.4 GHz 和 5 GHz 客户端，验证关联、WPA2/WPA3 握手、DHCP、DNS、
IPv4/IPv6 双向流量、断线重连及无线重载。用同一客户端、信道、服务端比较
启用/关闭 NSS 后的吞吐和 CPU 使用率，并在传输前后保存
`/sys/kernel/debug/qca-nss-drv/stats/wifili*`，确认对应无线接口的收发计数增长。
仅看到参数为启用状态或 NSS 空闲计数不算通过。

关闭无线 NSS，回到主机路径：

```sh
uci set nss-wifi.main.enabled='0'
uci commit nss-wifi
reboot
```

重新启用把值改成 `1` 后重启。不要在运行中卸载 NSS 或强制重载无线驱动。
关闭卸载后该实验设备树仍保留 16 MiB NSS 内存；完全恢复原内存布局需启动
原分支的镜像。

## 参考与来源

保留导入补丁的原始版权和作者信息。大部分无线补丁原始实现来自 Qualcomm
QSDK，经 qosmio 维护及 kuncy7 的 IPQ50xx 适配；本分支只接入无线阶段所需部分。

- [hzyitc 的 QSDK 5.4 参考分支](https://github.com/hzyitc/openwrt-redmi-ax3000/tree/ab1f9ffa5b5b62f252a5e87eb23f51f4e2544511)：IPQ50xx NSS/ath11k 接入参考。
- [Qualcomm NSS 固件仓库](https://github.com/quic/qca-sdk-nss-fw)：原参考版本的 IPQ5018 MP 固件。当前实验采用较新的 12.2-156，不能混用 IPQ60xx 的 CP 或 IPQ807x 的 HK 文件。
- [kuncy7 无线补丁基线](https://github.com/kuncy7/openwrt-nss-edma/tree/556a9ec7639c3973b486dd6da5b3d39eae4ef5e7/package/kernel/mac80211/patches/nss)：基于 qosmio 的 6.18 backports 系列，包括 IPQ5018/QCN6122 接入与低内存修正。
- [后续无线修正](https://github.com/kuncy7/openwrt-nss-edma/tree/2f00ddef/package/kernel/mac80211/patches/nss/ath11k)：补充 999-959 至 999-963 的 EAPOL、回调、锁及接收描述符修正。
- [NSS 包参考版本](https://github.com/kuncy7/nss-packages/tree/23ba3ccc5d92815e51872ba950de8dd35988eec5)：NSS 14.0 源码 `d7ef98b1d3d31346981d3a1abff5152a206374af` 和补丁。省去绑定其有线 EDMA 驱动的启动门槛，使用现有 qca-nss-dp API，并默认禁止有线接管。
- [固件来源包](https://github.com/qosmio/qca-sdk-nss-fw/releases/tag/v2025.05.01)：SHA-256 `10a4b1e69470db150915cb063525436494b8ae4eebb8b50ea6ad894082d7abb0`。
