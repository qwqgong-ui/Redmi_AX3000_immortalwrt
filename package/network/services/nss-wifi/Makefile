include $(TOPDIR)/rules.mk

PKG_NAME:=nss-wifi
PKG_RELEASE:=13
PKG_LICENSE:=GPL-2.0-only

include $(INCLUDE_DIR)/package.mk

define Package/nss-wifi
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Redmi AX3000 NSS Wi-Fi offload
  DEPENDS:=@TARGET_qualcommax_ipq50xx_DEVICE_redmi_ax3000 +kmod-ath11k-ahb +kmod-ath11k-pci +kmod-qca-nss-drv +kmod-qca-nss-drv-bridge-mgr +kmod-qca-nss-ecm +kmod-qca-dsa-nss +nss-firmware +@ATH11K_NSS_SUPPORT +ubus +jsonfilter +jshn
endef

define Package/nss-wifi/description
  Start the NSS firmware before ath11k and enable wireless RX/TX offload.
  Register wireless bridge interfaces and accelerate supported IPv4/IPv6
  routed and supported bridged connections through ECM. QCA DSA ports use
  verified 802.1Q VLAN interfaces on the NSS physical data plane.
endef

define Package/nss-wifi/conffiles
/etc/config/nss-wifi
endef

define Build/Compile
	$(TARGET_CC) $(TARGET_CPPFLAGS) $(TARGET_CFLAGS) $(TARGET_LDFLAGS) \
		-o $(PKG_BUILD_DIR)/nss-relay-wait ./files/nss-relay-wait.c
	$(TARGET_CC) $(TARGET_CPPFLAGS) $(TARGET_CFLAGS) $(TARGET_LDFLAGS) \
		-o $(PKG_BUILD_DIR)/nss-relay-neighbor ./files/nss-relay-neighbor.c
endef

define Package/nss-wifi/install
	$(INSTALL_DIR) $(1)/etc/init.d $(1)/etc/config $(1)/usr/sbin $(1)/usr/lib
		$(INSTALL_BIN) ./files/nss-wifi.init $(1)/etc/init.d/nss-wifi
		$(INSTALL_BIN) ./files/nss-lan.init $(1)/etc/init.d/nss-lan
	$(INSTALL_CONF) ./files/nss-wifi.config $(1)/etc/config/nss-wifi
	$(INSTALL_BIN) ./files/nss-wifi-status $(1)/usr/sbin/nss-wifi-status
	$(INSTALL_BIN) ./files/nss-relay.init $(1)/etc/init.d/nss-relay
	$(INSTALL_BIN) ./files/nss-relay-watch $(1)/usr/sbin/nss-relay-watch
	$(INSTALL_DATA) ./files/nss-relay-state.sh $(1)/usr/lib/nss-relay-state.sh
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/nss-relay-wait $(1)/usr/lib/nss-relay-wait
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/nss-relay-neighbor $(1)/usr/lib/nss-relay-neighbor
	$(INSTALL_BIN) ./files/nss-relay-neighbor-watch $(1)/usr/sbin/nss-relay-neighbor-watch
	$(INSTALL_BIN) ./files/nss-neighbor.init $(1)/etc/init.d/nss-neighbor
endef

$(eval $(call BuildPackage,nss-wifi))
