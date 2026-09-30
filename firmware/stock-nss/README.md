# 原厂 IPQ5018 NSS 固件参考

这两个 BIN 从用户持有的 AP-MP02.1 原厂路由器 `/lib/firmware/` 只读复制，内嵌版本字符串为 `NSS.MP.11.4-7-R`，用于 NSS ABI 和移植分析。

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| [qca-nss0-retail.bin](ipq5018/qca-nss0-retail.bin) | 761612 | `d90f7dd2d12d48445765ba013ffcc9a4e7a4448cd1dc497dfffe3d0b726298cd` |
| [qca-nss0.bin](ipq5018/qca-nss0.bin) | 761612 | `d90f7dd2d12d48445765ba013ffcc9a4e7a4448cd1dc497dfffe3d0b726298cd` |

原厂 `qca-nss0.bin` 是指向 `./qca-nss0-retail.bin` 的软链接。这里保存两份内容一致的普通文件，复制/打包时不依赖软链接支持；Git 会按相同内容存储同一个 blob。

原厂 BusyBox 没有可用的 `sha256sum`，传输后用原厂 `md5sum` 与本地 MD5 比较，再在本地计算 SHA256。远端 MD5、字节数、来源路径和 SHA256 均记录在 [快照 manifest](../../docs/nss/stock-ap-mp02.1/manifest.json) 中，可用以下命令重新验证：

```sh
python3 scripts/nss/verify-reference.py
```

当前 OpenWrt profile 使用 NSS **12.2**，这份原厂 **11.4** BIN 没有接入固件构建、没有替换 `nss-firmware` 包。不同版本的消息和统计结构必须连同驱动及 ath11k 一起审查，详见 [NSS 开发交接](../../docs/nss/README.md)。
