# Redmi AX3000 ImmortalWrt 25.12 full APK repository

This branch contains the signed APK repositories produced by the complete
ImmortalWrt build for the Redmi AX3000:

- source branch: `redmi_ax3000-25.12`
- source commit: `6d3ae4641e07410a2e3f9db81ef51836a83686ad`
- firmware version: `r38005-6d3ae4641e`
- target: `qualcommax/ipq50xx`
- package architecture: `aarch64_cortex-a53`
- kernel: Linux 6.12.94
- build environment: Debian 12 (Bookworm) amd64

The repository contains 11,521 APK files from the full package selection:

- target and kernel packages: 1,300
- base: 756
- LuCI: 3,562
- packages: 4,858
- routing: 56
- telephony: 874
- video: 115

## Repository layout

- `targets/qualcommax/ipq50xx/packages`: target and kernel packages
- `packages/aarch64_cortex-a53/base`: base packages
- `packages/aarch64_cortex-a53/luci`: LuCI packages
- `packages/aarch64_cortex-a53/packages`: community packages
- `packages/aarch64_cortex-a53/routing`: routing packages
- `packages/aarch64_cortex-a53/telephony`: telephony packages
- `packages/aarch64_cortex-a53/video`: multimedia packages
- `keys/public-key.pem`: local ECDSA repository public key
- `distfeeds.list`: ready-to-use APK repository list

## Configure APK

The matching firmware already contains this repository key as
`/etc/apk/keys/public-key.pem`. Replace the distribution feed list and refresh
APK with:

```sh
wget -O /etc/apk/repositories.d/distfeeds.list \
  https://raw.githubusercontent.com/qwqgong-ui/Redmi_AX3000_immortalwrt/packages-25.12/distfeeds.list
apk update
```

All seven repository indexes were verified with the included public key, and
all 11,521 APK files passed an integrity check. Do not use this repository with
24.10 or a different kernel build.

Matching firmware release:
[`v25.12-debian-r38005-6d3ae4641e`](https://github.com/qwqgong-ui/Redmi_AX3000_immortalwrt/releases/tag/v25.12-debian-r38005-6d3ae4641e)
