include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=qca-dsa-nss
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only
PKG_BUILD_PARALLEL:=1

include $(INCLUDE_DIR)/package.mk

define KernelPackage/qca-dsa-nss
  SECTION:=kernel
  CATEGORY:=Kernel modules
  SUBMENU:=Network Devices
  TITLE:=NSS data plane for QCA 802.1Q DSA ports
  DEPENDS:=@TARGET_qualcommax_ipq50xx +kmod-qca-nss-drv +kmod-qca-nss-drv-bridge-mgr +@NSS_DRV_VLAN_ENABLE
  KCONFIG:=CONFIG_NET_DSA_TAG_QCA_8021Q=y CONFIG_NET_DSA_TAG_8021Q=y
  FILES:=$(PKG_BUILD_DIR)/qca-dsa-nss.ko
endef

define KernelPackage/qca-dsa-nss/Description
  Preserve DSA user ports and use verified NSS VLAN nodes on their physical
  conduit. Configuration ACK, bridge membership and rule teardown are
  coordinated before publishing or releasing an interface number.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) -C "$(LINUX_DIR)" M="$(PKG_BUILD_DIR)" \
		NOSTDINC_FLAGS="$(KERNEL_NOSTDINC_FLAGS) -I$(STAGING_DIR)/usr/include/qca-nss-drv" modules
endef

$(eval $(call KernelPackage,qca-dsa-nss))
