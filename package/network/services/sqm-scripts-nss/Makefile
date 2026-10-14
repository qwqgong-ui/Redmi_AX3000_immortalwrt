include $(TOPDIR)/rules.mk

PKG_NAME:=sqm-scripts-nss
PKG_VERSION:=20261012
PKG_RELEASE:=3
PKG_LICENSE:=GPL-2.0

# Firmware tree/convergence logic from nss-packages
# 94f44cc3bd4259b9b49f186f157e90e06b5ab003, adapted for qca-dsa-nss.
include $(INCLUDE_DIR)/package.mk

define Package/sqm-scripts-nss
  SECTION:=net
  CATEGORY:=Base system
  TITLE:=SQM scripts for NSS firmware scheduling
  DEPENDS:=@TARGET_qualcommax_ipq50xx +sqm-scripts +tc-full +nftables-json +kmod-qca-nss-drv-qdisc +kmod-qca-nss-drv-igs
  PKGARCH:=all
endef

define Package/sqm-scripts-nss/description
  NSS token bucket and FQ-CoDel SQM with IFB ingress shaping, firewall
  class selection and independent WAN lanes on a shared DSA conduit.
  Queues are configured through SQM, with logical network and wireless VIF
  bindings that recover after reconnects. Installing this package sets no rates.
endef

define Build/Compile
endef

define Package/sqm-scripts-nss/install
	$(INSTALL_DIR) $(1)/usr/lib/sqm $(1)/etc/hotplug.d/iface $(1)/etc/init.d
	$(INSTALL_DATA) ./files/nss-edma.qos ./files/nss-edma.qos.help ./files/nss-fq.qos ./files/nss-fq.qos.help $(1)/usr/lib/sqm/
	$(INSTALL_BIN) ./files/nss-sqm-watch $(1)/usr/lib/sqm/nss-sqm-watch
	$(INSTALL_BIN) ./files/nss-sqm.init $(1)/etc/init.d/nss-sqm
	$(INSTALL_DATA) ./files/nss-sqm-hotplug $(1)/etc/hotplug.d/iface/12-nss-sqm
endef

$(eval $(call BuildPackage,sqm-scripts-nss))
