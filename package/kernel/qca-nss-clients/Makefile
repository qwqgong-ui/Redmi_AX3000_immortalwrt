include $(TOPDIR)/rules.mk

PKG_NAME:=qca-nss-clients
PKG_RELEASE:=8
PKG_SOURCE_DATE:=2024-09-11
PKG_SOURCE_VERSION:=51be82d
QSDK_VERSION:=12.5
PKG_VERSION:=$(QSDK_VERSION).$(subst -,.,$(PKG_SOURCE_DATE))~$(PKG_SOURCE_VERSION)
PKG_SOURCE:=$(PKG_NAME)-$(subst ~,.,$(PKG_VERSION)).tar.zst
PKG_SOURCE_URL:=https://github.com/JuliusBairaktaris/nss-packages/releases/download/nss-source-tarballs
PKG_HASH:=876c3898cb4723fccd4a1c870324724dd7c4061ac89ec88db2226fd749c18b38
PKG_BUILD_PARALLEL:=1
PKG_FLAGS:=nonshared
PKG_CONFIG_DEPENDS:=CONFIG_PACKAGE_kmod-qca-nss-drv-bridge-mgr \
  CONFIG_PACKAGE_kmod-qca-nss-drv-qdisc CONFIG_PACKAGE_kmod-qca-nss-drv-igs \
  CONFIG_PACKAGE_kmod-qca-nss-drv-pppoe CONFIG_NSS_FIRMWARE_VERSION_11_4 \
  CONFIG_NSS_DRV_WIFIOFFLOAD_ENABLE

# Qualcomm nss-clients 51be82d, with the non-PPE Linux 6.12 compatibility
# changes from qosmio/nss-packages 0d970dbf0185e3f53709bd803e8a466598023c57.
include $(INCLUDE_DIR)/kernel.mk
include $(INCLUDE_DIR)/package.mk

define KernelPackage/qca-nss-drv-bridge-mgr
  SECTION:=kernel
  CATEGORY:=Kernel modules
  SUBMENU:=Network Devices
  TITLE:=NSS bridge interface manager
  DEPENDS:=@TARGET_qualcommax_ipq50xx +kmod-qca-nss-drv +@NSS_DRV_BRIDGE_ENABLE
  FILES:=$(PKG_BUILD_DIR)/bridge/qca-nss-bridge-mgr.ko
  # Loaded by nss-wifi only after NSS is ready, before wireless interfaces.
endef

define KernelPackage/qca-nss-drv-bridge-mgr/description
  Register Linux bridges and their NSS-backed wireless members with NSS.
  Devices without an NSS interface retain the host forwarding path.
endef

define KernelPackage/qca-nss-drv-qdisc
  SECTION:=kernel
  CATEGORY:=Kernel modules
  SUBMENU:=Network Devices
  TITLE:=NSS firmware queue disciplines and shapers
  DEPENDS:=@TARGET_qualcommax_ipq50xx +kmod-qca-nss-drv +kmod-qca-nss-drv-bridge-mgr +kmod-sched-core +@NSS_DRV_SHAPER_ENABLE +@NSS_DRV_IGS_ENABLE +@NSS_DRV_VIRT_IF_ENABLE
  FILES:=$(PKG_BUILD_DIR)/nss_qdisc/qca-nss-qdisc.ko
  KCONFIG:=CONFIG_NET_CLS_ACT=y
  # Loaded on demand after nss-wifi has started the firmware.
endef

define KernelPackage/qca-nss-drv-qdisc/description
  NSS FIFO, CoDel/FQ-CoDel, token bucket, HTB, BF, priority, WRR/WFQ,
  WRED and blackhole queue disciplines. Uses the NSS firmware backend.
endef

define KernelPackage/qca-nss-drv-igs
  SECTION:=kernel
  CATEGORY:=Kernel modules
  SUBMENU:=Network Devices
  TITLE:=NSS ingress shaping action
  DEPENDS:=@TARGET_qualcommax_ipq50xx +kmod-qca-nss-drv-qdisc +kmod-ifb +kmod-nf-conntrack +kmod-sched-core +@NSS_DRV_IGS_ENABLE
  FILES:=$(PKG_BUILD_DIR)/nss_qdisc/igs/act_nssmirred.ko
  KCONFIG:=CONFIG_NF_CONNTRACK_DSCPREMARK_EXT=y
endef

define KernelPackage/qca-nss-drv-igs/description
  Redirect NSS ingress traffic to an IFB with the nssmirred tc action.
  Conntrack carries the ingress class selected by firewall priority rules.
endef

define KernelPackage/qca-nss-drv-pppoe
  SECTION:=kernel
  CATEGORY:=Kernel modules
  SUBMENU:=Network Devices
  TITLE:=NSS PPPoE session manager
  DEPENDS:=@TARGET_qualcommax_ipq50xx +kmod-qca-nss-drv +kmod-pppoe +@NSS_DRV_PPPOE_ENABLE
  FILES:=$(PKG_BUILD_DIR)/pppoe/qca-nss-pppoe.ko
  # Loaded by nss-wifi after the core is ready, before netifd.
endef

define KernelPackage/qca-nss-drv-pppoe/description
  Publish PPPoE sessions and their lower interfaces to the NSS firmware.
endef

NSS_CLIENTS_MAKE_OPTS:=NSS_QDISC_PPE_ENABLE=n
ifneq ($(CONFIG_PACKAGE_kmod-qca-nss-drv-bridge-mgr),)
NSS_CLIENTS_MAKE_OPTS+=bridge-mgr=y
endif
ifneq ($(CONFIG_PACKAGE_kmod-qca-nss-drv-qdisc),)
NSS_CLIENTS_MAKE_OPTS+=qdisc=y NSS_QDISC_BRIDGE_ENABLE=y
endif
ifneq ($(CONFIG_PACKAGE_kmod-qca-nss-drv-igs),)
NSS_CLIENTS_MAKE_OPTS+=igs=y
endif
ifneq ($(CONFIG_PACKAGE_kmod-qca-nss-drv-pppoe),)
NSS_CLIENTS_MAKE_OPTS+=pppoe=y
endif
NSS_CLIENTS_CFLAGS:=-I$(STAGING_DIR)/usr/include/qca-nss-drv
ifneq ($(CONFIG_NSS_DRV_WIFIOFFLOAD_ENABLE),)
NSS_CLIENTS_CFLAGS+=-DNSS_QDISC_WIFI_SUPPORT
endif
ifneq ($(CONFIG_NSS_FIRMWARE_VERSION_11_4),)
NSS_CLIENTS_CFLAGS+=-DNSS_FIRMWARE_VERSION_11_4
endif

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) \
    M="$(PKG_BUILD_DIR)" SoC=ipq50xx_64 $(NSS_CLIENTS_MAKE_OPTS) \
    NOSTDINC_FLAGS="$(KERNEL_NOSTDINC_FLAGS) $(NSS_CLIENTS_CFLAGS)" \
    CFLAGS_MODULE="-Wno-error" modules
endef

$(eval $(call KernelPackage,qca-nss-drv-bridge-mgr))
$(eval $(call KernelPackage,qca-nss-drv-qdisc))
$(eval $(call KernelPackage,qca-nss-drv-igs))
$(eval $(call KernelPackage,qca-nss-drv-pppoe))
