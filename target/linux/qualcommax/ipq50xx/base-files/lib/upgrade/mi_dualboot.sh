. /lib/functions.sh

mi_dualboot_check_image() {
	local ret=0
	local file_type
	local kernel_volume
	local mtd
	local rootfs_volume

	file_type="$(head -c 3 "$1")"
	if [ "$file_type" != "UBI" ]; then
		v "Unsupported file type: $file_type"
		v "Please use ubi file"
		ret=1
	else
		# Redmi AX3000 UBI uses 2 KiB pages and 172-byte volume records.
		kernel_volume="$(dd if="$1" bs=1 skip=4112 count=6 2>/dev/null)"
		rootfs_volume="$(dd if="$1" bs=1 skip=4284 count=6 2>/dev/null)"
		if [ "$kernel_volume" != "kernel" ] || [ "$rootfs_volume" != "rootfs" ]; then
			v "Unsupported UBI volume layout: kernel=$kernel_volume rootfs=$rootfs_volume"
			v "Please use the squashfs factory UBI, not the initramfs recovery UBI"
			ret=1
		fi
	fi

	mtd="$(grep -oE 'ubi.mtd=[a-zA-Z0-9_-]*' /proc/cmdline | cut -d= -f2)"
	if [ "$mtd" != "rootfs" ] && [ "$mtd" != "rootfs_1" ]; then
		v "Unable to determine UBIPART: ubi.mtd=$mtd"
		ret=1
	fi

	if ! fw_printenv >/dev/null; then
		v "Failed to read U-Boot env"
		ret=1
	fi

	return "$ret"
}

mi_dualboot_do_upgrade() {
	local current
	local mtd
	local mtdnum
	local ubidev

	mkdir -p /var/lock
	fw_printenv >/dev/null || return 1

	mtd="$(grep -oE 'ubi.mtd=[a-zA-Z0-9_-]*' /proc/cmdline | cut -d= -f2)"
	case "$mtd" in
	rootfs)
		CI_UBIPART="rootfs_1"
		current=0
		;;
	rootfs_1)
		CI_UBIPART="rootfs"
		current=1
		;;
	*)
		v "Unable to determine UBIPART: ubi.mtd=$mtd"
		return 1
		;;
	esac

	mtdnum="$(find_mtd_index "$CI_UBIPART")"
	[ -n "$mtdnum" ] || {
		v "Unable to find MTD partition: $CI_UBIPART"
		return 1
	}

	v "Flashing to $CI_UBIPART (mtd$mtdnum)"
	ubiformat "/dev/mtd$mtdnum" -f "$1" -y || return 1
	sync

	ubiattach --mtdn "$mtdnum" || return 1

	ubidev="$(nand_find_ubi "$CI_UBIPART")"
	[ -n "$ubidev" ] || {
		v "Unable to find UBI device for $CI_UBIPART"
		return 1
	}

	if [ -z "$(nand_find_volume "$ubidev" kernel)" ]; then
		v "\"kernel\" volume does not exist; vendor U-Boot can fail to switch slots."
		return 1
	fi
	if [ -z "$(nand_find_volume "$ubidev" rootfs)" ]; then
		v "\"rootfs\" volume does not exist; refusing to switch slots."
		return 1
	fi

	[ -f "$UPGRADE_BACKUP" ] && CI_UBIPART="$CI_UBIPART" nand_restore_config "$UPGRADE_BACKUP"

	fw_setenv flag_try_sys1_failed 0 || return 1
	fw_setenv flag_try_sys2_failed 0 || return 1
	fw_setenv flag_last_success "$current" || return 1
	fw_setenv flag_ota_reboot 1 || return 1
	fw_setenv flag_boot_success || return 1
}
