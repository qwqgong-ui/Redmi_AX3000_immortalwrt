include $(TOPDIR)/rules.mk

PKG_NAME:=nss-wifi
PKG_RELEASE:=3
PKG_LICENSE:=GPL-2.0-only

include $(INCLUDE_DIR)/package.mk

define Package/nss-wifi
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Redmi AX3000 NSS Wi-Fi offload
  DEPENDS:=@TARGET_qualcommax_ipq50xx_DEVICE_redmi_ax3000 +kmod-ath11k-ahb +kmod-ath11k-pci +kmod-qca-nss-drv +nss-firmware +@ATH11K_NSS_SUPPORT
endef

define Package/nss-wifi/description
  Start the NSS firmware before ath11k and enable wireless RX/TX offload.
  Ethernet, routing and NAT remain on the existing host path.
endef

define Package/nss-wifi/conffiles
/etc/config/nss-wifi
endef

define Build/Compile
endef

define Package/nss-wifi/install
	$(INSTALL_DIR) $(1)/etc/init.d $(1)/etc/config $(1)/usr/sbin
	$(INSTALL_BIN) ./files/nss-wifi.init $(1)/etc/init.d/nss-wifi
	$(INSTALL_CONF) ./files/nss-wifi.config $(1)/etc/config/nss-wifi
	$(INSTALL_BIN) ./files/nss-wifi-status $(1)/usr/sbin/nss-wifi-status
endef

$(eval $(call BuildPackage,nss-wifi))
