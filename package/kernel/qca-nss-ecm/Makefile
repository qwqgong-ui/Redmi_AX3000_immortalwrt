include $(TOPDIR)/rules.mk

PKG_NAME:=qca-nss-ecm
PKG_RELEASE:=10
PKG_SOURCE_DATE:=2026-09-06
PKG_SOURCE_VERSION:=7894b769eeb64f1c44fde547a107a8b866997590
QSDK_VERSION:=14.0
PKG_VERSION:=$(QSDK_VERSION).$(subst -,.,$(PKG_SOURCE_DATE))~$(PKG_SOURCE_VERSION)
PKG_SOURCE:=$(PKG_NAME)-$(subst ~,.,$(PKG_VERSION)).tar.zst
PKG_SOURCE_URL:=https://github.com/JuliusBairaktaris/nss-packages/releases/download/nss-source-tarballs
PKG_HASH:=a4d5f4c4a6c4bfac3ded4af993c88249f7afc4444ed78368f367eda4ef231886
PKG_BUILD_PARALLEL:=1
PKG_FLAGS:=nonshared
PKG_CONFIG_DEPENDS:=CONFIG_IPV6 CONFIG_BRIDGE_VLAN_FILTERING CONFIG_NSS_FIRMWARE_VERSION_12_2 CONFIG_ATH11K_MEM_PROFILE_256M \
  CONFIG_PACKAGE_kmod-qca-nss-drv-igs CONFIG_PACKAGE_kmod-qca-nss-drv-pppoe

# Qualcomm QSDK 14.0 ECM, win.nss.1.0.r39. Kernel/connection-sync compatibility
# patches are pinned to kuncy7/nss-packages 94f44cc3bd4259b9b49f186f157e90e06b5ab003.
include $(INCLUDE_DIR)/kernel.mk
include $(INCLUDE_DIR)/package.mk

define KernelPackage/qca-nss-ecm
  SECTION:=kernel
  CATEGORY:=Kernel modules
  SUBMENU:=Network Support
  TITLE:=NSS connection acceleration manager
  DEPENDS:=@TARGET_qualcommax_ipq50xx +kmod-qca-nss-drv +kmod-qca-nss-drv-bridge-mgr +kmod-qca-dsa-nss +kmod-nf-conntrack +@NSS_DRV_IPV6_ENABLE +@NSS_DRV_VIRT_IF_ENABLE +PACKAGE_kmod-qca-nss-drv-pppoe:kmod-pppoe
  FILES:=$(PKG_BUILD_DIR)/ecm.ko $(LINUX_DIR)/net/bridge/netfilter/nf_conntrack_bridge.ko
  KCONFIG:=CONFIG_NF_CONNTRACK_EVENTS=y CONFIG_NF_CONNTRACK_EVENTS_OBSERVER=y CONFIG_NF_CONNTRACK_BRIDGE=m
endef

define KernelPackage/qca-nss-ecm/description
  IPv4 TCP/UDP routing and NAT, IPv6 routing and connection-tracked bridging
  through verified NSS wireless and QCA tag_8021q DSA interfaces.
endef

define KernelPackage/qca-nss-ecm/conffiles
/etc/config/ecm
endef

define KernelPackage/qca-nss-ecm/install
	$(INSTALL_DIR) $(1)/etc/init.d $(1)/etc/config
	$(INSTALL_BIN) ./files/qca-nss-ecm.init $(1)/etc/init.d/qca-nss-ecm
	$(INSTALL_CONF) ./files/ecm.config $(1)/etc/config/ecm
endef

# QCA tag_8021q ports use a physical conduit plus a VLAN layer. Keep the
# incompatible legacy DSA mapping and unsupported tunnel/PPE backends disabled.
ECM_MAKE_OPTS:= \
  ECM_FRONT_END_NSS_ENABLE=y ECM_FRONT_END_SFE_ENABLE=n ECM_FRONT_END_PPE_ENABLE=n \
  ECM_NON_PORTED_SUPPORT_ENABLE=n ECM_MULTICAST_ENABLE=y ECM_MCAST_LINUX_SNOOPER_SUPPORT=y \
  ECM_INTERFACE_VLAN_ENABLE=y ECM_INTERFACE_DSA_ENABLE=n \
  ECM_INTERFACE_BOND_ENABLE=n ECM_INTERFACE_MACVLAN_ENABLE=n \
  ECM_INTERFACE_OVS_BRIDGE_ENABLE=n ECM_INTERFACE_SKIP_ACCEL_ENABLE=y \
  ECM_INTERFACE_PPPOE_ENABLE=$(if $(CONFIG_PACKAGE_kmod-qca-nss-drv-pppoe),y,n) \
  ECM_INTERFACE_PPP_ENABLE=$(if $(CONFIG_PACKAGE_kmod-qca-nss-drv-pppoe),y,n) ECM_INTERFACE_PPTP_ENABLE=n \
  ECM_INTERFACE_L2TPV2_ENABLE=n ECM_INTERFACE_L2TPV3_ENABLE=n \
  ECM_INTERFACE_GRE_ENABLE=n ECM_INTERFACE_GRE_TAP_ENABLE=n \
  ECM_INTERFACE_GRE_TUN_ENABLE=n ECM_INTERFACE_IPSEC_ENABLE=n \
  ECM_INTERFACE_SIT_ENABLE=n ECM_INTERFACE_TUNIPIP6_ENABLE=n \
  ECM_INTERFACE_MAP_T_ENABLE=n ECM_INTERFACE_RAWIP_ENABLE=n \
  ECM_INTERFACE_VXLAN_ENABLE=n \
  ECM_CLASSIFIER_DSCP_ENABLE=$(if $(CONFIG_PACKAGE_kmod-qca-nss-drv-igs),y,n) \
  ECM_CLASSIFIER_DSCP_IGS=$(if $(CONFIG_PACKAGE_kmod-qca-nss-drv-igs),y,n) \
  ECM_CLASSIFIER_MARK_ENABLE=y ECM_CLASSIFIER_PCC_ENABLE=n \
  ECM_256M_PROFILE=$(if $(CONFIG_ATH11K_MEM_PROFILE_256M),y,n)

ifneq ($(CONFIG_IPV6),)
ECM_MAKE_OPTS+=ECM_IPV6_ENABLE=y
else
ECM_MAKE_OPTS+=ECM_IPV6_ENABLE=n
endif

ifneq ($(CONFIG_BRIDGE_VLAN_FILTERING),)
ECM_MAKE_OPTS+=ECM_BRIDGE_VLAN_FILTERING_ENABLE=y
else
ECM_MAKE_OPTS+=ECM_BRIDGE_VLAN_FILTERING_ENABLE=n
endif

EXTRA_CFLAGS:=-I$(STAGING_DIR)/usr/include/qca-nss-drv
ifneq ($(CONFIG_NSS_FIRMWARE_VERSION_12_2),)
EXTRA_CFLAGS+=-DNSS_FIRMWARE_VERSION_12_2
endif

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) $(ECM_MAKE_OPTS) \
    M="$(PKG_BUILD_DIR)" SoC=ipq50xx \
    NOSTDINC_FLAGS="$(KERNEL_NOSTDINC_FLAGS) $(EXTRA_CFLAGS)" \
    CFLAGS_MODULE="-Wno-error" modules
endef

$(eval $(call KernelPackage,qca-nss-ecm))
