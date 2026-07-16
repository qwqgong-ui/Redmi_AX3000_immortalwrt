# Redmi AX3000 ImmortalWrt 24.10 package repository

This orphan branch contains the signed OPKG repositories produced from
ImmortalWrt `24.10-SNAPSHOT` (`r33982-c0cdf3733a`) for
`qualcommax/ipq50xx`, Linux `6.6.143`, package architecture
`aarch64_cortex-a53`.

## Repository layout

- `targets/qualcommax/ipq50xx/packages`: target and kernel packages
- `packages/aarch64_cortex-a53/base`: base packages
- `packages/aarch64_cortex-a53/luci`: LuCI packages
- `packages/aarch64_cortex-a53/packages`: community packages
- `packages/aarch64_cortex-a53/routing`: routing packages
- `packages/aarch64_cortex-a53/telephony`: telephony packages
- `keys/3be516e97a0356ec`: public key used to verify all repository indexes
- `distfeeds.conf`: ready-to-use OPKG feed configuration

## Configure OPKG

The matching firmware already contains the repository signing key. Replace
`/etc/opkg/distfeeds.conf` with the published `distfeeds.conf`, then run:

```sh
opkg update
```

All six `Packages` indexes were verified against the included public key
before publication.

The matching firmware release is
`v24.10-snapshot-r33982-c0cdf3733a` on the repository's GitHub Releases page.
