. /lib/functions.sh

mi_dualboot_check_image() {
	local ret=0
	local file_type
	local kernel_volume
	local mtd
	local mtdnum
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

	mtdnum="$(find_mtd_index rootfs)"
	if [ -z "$mtdnum" ]; then
		v "Unable to find MTD partition: rootfs"
		ret=1
	fi

	if ! fw_printenv >/dev/null; then
		v "Failed to read U-Boot env"
		ret=1
	fi

	return "$ret"
}

mi_dualboot_do_upgrade() {
	local mtdnum

	mkdir -p /var/lock
	fw_printenv >/dev/null || return 1

	# The 25.12 DTS exposes the complete 0x0a80000-0x07f00000 firmware
	# area as one MTD partition.  Do not look for the rootfs_1 partition
	# that was injected by Xiaomi U-Boot with the old 24.10 DTS.
	CI_UBIPART="rootfs"
	mtdnum="$(find_mtd_index "$CI_UBIPART")"
	[ -n "$mtdnum" ] || {
		v "Unable to find MTD partition: $CI_UBIPART"
		return 1
	}

	# Keep U-Boot on the only partition described by the target DTS.
	fw_setenv flag_boot_rootfs 0 || return 1
	fw_setenv flag_last_success 0 || return 1
	fw_setenv flag_ota_reboot 0 || return 1
	fw_setenv flag_boot_success 1 || return 1
	fw_setenv flag_try_sys1_failed 0 || return 1
	fw_setenv flag_try_sys2_failed 0 || return 1

	v "Flashing single rootfs partition (mtd$mtdnum)"
	nand_do_upgrade "$1"
}
