#!/usr/bin/env python3
"""Host-side boot tests, plus fault injection against a patched NSS source tree.

Usage: python3 scripts/tests/test-nss-wifi.py [patched-nss-source-directory
                                          [patched-backports-directory]]
No router access or target module loading is performed.
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
INIT = ROOT / "package/network/services/nss-wifi/files/nss-wifi.init"


def test_boot():
    cases = [
        ("enabled", 1, True, False, "", 0),
        ("disabled", 0, False, False, "", 0),
        ("firmware-timeout", 1, False, False, "", 0),
        ("core-already-loaded", 1, True, True, "", 0),
        ("core-load-failure", 1, False, False, "qca-nss-drv", 1),
        ("dependency-failure", 1, True, False, "mac80211", 1),
        ("ahb-failure", 1, True, False, "ath11k_ahb", 1),
        ("pci-failure", 1, True, False, "ath11k_pci", 1),
    ]
    for name, enabled, ready, loaded, fail, expected in cases:
        with tempfile.TemporaryDirectory(prefix="nss-boot-test-") as tmp:
            base = Path(tmp)
            modules = base / "modules"
            modules.mkdir()
            if loaded:
                (modules / "qca_nss_drv/parameters").mkdir(parents=True)
                (modules / "qca_nss_drv/parameters/core0_ready").write_text("1\n")
            script = INIT.read_text().replace(". /lib/functions.sh", ":")
            script = script.replace("/sys/module", str(modules))
            harness = r'''
config_load() { :; }
config_get_bool() { enabled="$TEST_ENABLED"; }
logger() { :; }
sleep() { echo wait >> "$CALLS"; }
modprobe() {
    echo "modprobe $*" >> "$CALLS"
    [ "$1" != "$FAIL" ]
}
insmod() {
    echo "insmod $*" >> "$CALLS"
    [ "$1" != "$FAIL" ] || return 1
    if [ "$1" = qca-nss-drv ]; then
        mkdir -p "$MODULES/qca_nss_drv/parameters"
        echo "$READY" > "$MODULES/qca_nss_drv/parameters/core0_ready"
    elif [ "$1" = ath11k ]; then
        # NSS symbols remain required even with nss_offload=0.
        [ -d "$MODULES/qca_nss_drv" ] || return 1
    fi
}
'''
            env = dict(os.environ, TEST_ENABLED=str(enabled),
                       READY=str(int(ready)), FAIL=fail, MODULES=str(modules),
                       CALLS=str(base / "calls"))
            result = subprocess.run(["sh"], input=harness + script + "\nstart\n",
                                    text=True, env=env, capture_output=True)
            assert result.returncode == expected, (name, result.stderr)
            calls = (base / "calls").read_text().splitlines()
            if not fail:
                mode = int(enabled and ready)
                assert f"insmod ath11k nss_offload={mode} frame_mode=2" in calls, name
            if loaded:
                assert "insmod qca-nss-drv wifi_only=1" not in calls, name
            if name == "firmware-timeout":
                assert calls.count("wait") == 30, name
            if name in ("disabled", "core-load-failure"):
                assert "wait" not in calls, name
            if name in ("core-load-failure", "dependency-failure"):
                assert not any(c.startswith("insmod ath11k ") for c in calls), name
            if name == "ahb-failure":
                assert "modprobe ath11k_pci" in calls, name
            print(f"PASS boot: {name}")


def test_registration(source):
    text = (source / "nss_wifi_vdev.c").read_text()
    start = text.index("uint32_t nss_register_wifi_vdev_if(")
    end = text.index("EXPORT_SYMBOL(nss_register_wifi_vdev_if);", start)
    function = text[start:end]
    harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#define NSS_DYNAMIC_IF_START 32
#define NSS_MAX_DYNAMIC_INTERFACES 128
#define NSS_CORE_STATUS_SUCCESS 0
#define nss_assert assert
#define nss_warning(...) ((void)0)
struct nss_ctx_instance { int dummy; };
struct net_device { int dummy; };
typedef void (*nss_wifi_vdev_callback_t)(void);
typedef void (*nss_wifi_vdev_ext_data_callback_t)(void);
typedef void (*nss_wifi_vdev_msg_callback_t)(void);
static int dp, msg, core, fail_msg, fail_core;
static void callback(void) {}
static void nss_wifi_vdev_handler(void) {}
static void nss_core_register_subsys_dp(struct nss_ctx_instance *c, int i,
    nss_wifi_vdev_callback_t cb, nss_wifi_vdev_ext_data_callback_t ext,
    void *data, struct net_device *dev, uint32_t features) { dp = 1; }
static uint32_t nss_core_register_msg_handler(struct nss_ctx_instance *c,
    int i, nss_wifi_vdev_msg_callback_t cb) {
    if (fail_msg) return 7;
    msg = 1; return 0;
}
static uint32_t nss_core_register_handler(struct nss_ctx_instance *c,
    int i, void (*cb)(void), void *data) {
    if (fail_core) return 9;
    core = 1; return 0;
}
static uint32_t nss_core_unregister_msg_handler(struct nss_ctx_instance *c, int i) {
    msg = 0; return 0;
}
'''
    main = r'''
int main(void) {
    struct nss_ctx_instance ctx = {0};
    struct net_device dev = {0};
    fail_msg = 1; msg = 2; dp = 2;
    assert(nss_register_wifi_vdev_if(&ctx, 32, callback, callback, callback, &dev, 0) == 7);
    assert(dp == 2 && msg == 2 && !core); /* preserve the existing registrations */
    fail_msg = 0; msg = 0; fail_core = 1; core = 2;
    assert(nss_register_wifi_vdev_if(&ctx, 32, callback, callback, callback, &dev, 0) == 9);
    assert(dp == 2 && !msg && core == 2); /* preserve the existing registrations */
    fail_core = 0; core = 0;
    assert(nss_register_wifi_vdev_if(&ctx, 32, callback, callback, callback, &dev, 0) == 0);
    assert(dp && msg && core); /* retry with the same interface number succeeds */
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="nss-registration-test-") as tmp:
        src = Path(tmp) / "registration.c"
        exe = Path(tmp) / "registration"
        src.write_text(harness + function + main)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Werror", str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS VDEV: message failure, core failure, preserved handlers and retry")


def test_vlan(source):
    text = (source / "drivers/net/wireless/ath/ath11k/mac.c").read_text()
    start = text.index("static int ath11k_get_vlan_groupkey_index(")
    end = text.index("static int ath11k_mac_op_set_key(", start)
    function = text[start:end]
    # Exercise the exact allocation expression from add_interface as well.
    start = text.index("arvif->vlan_keyid_map = ")
    allocation = text[start:text.index(";", start) + 1]
    start = text.index("/* Configure vlan specific parameters */")
    start = text.rfind("spin_lock_bh(", 0, start)
    end = text.index("spin_unlock_bh(", start)
    initialization = text[start:text.index(";", end) + 1]
    harness = r'''
#include <assert.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#define ATH11K_GROUP_KEYS_NUM_MAX 128
#define VLAN_N_VID 4096
#define GFP_KERNEL 0
#define BITS_PER_LONG (8 * sizeof(unsigned long))
#define kcalloc(n, size, flags) calloc(n, size)
struct ath11k { int data_lock; };
struct ath11k_vif {
    struct ath11k *ar;
    unsigned long free_groupidx_map[128 / BITS_PER_LONG];
    uint16_t *vlan_keyid_map;
};
struct ieee80211_key_conf { unsigned int hw_key_idx; };
static int locked;
static void spin_lock_bh(int *l) { assert(!locked); locked = 1; }
static void spin_unlock_bh(int *l) { assert(locked); locked = 0; }
static void clear_bit(unsigned int bit, unsigned long *map) {
    map[bit / BITS_PER_LONG] &= ~(1UL << (bit % BITS_PER_LONG));
}
static void set_bit(unsigned int bit, unsigned long *map) {
    map[bit / BITS_PER_LONG] |= 1UL << (bit % BITS_PER_LONG);
}
static void bitmap_fill(unsigned long *map, unsigned int size) {
    for (unsigned int i = 0; i < size / BITS_PER_LONG; i++) map[i] = ~0UL;
}
static unsigned long find_first_bit(unsigned long *map, unsigned int size) {
    assert(locked);
    for (unsigned int i = 0; i < size; i++)
        if (map[i / BITS_PER_LONG] & (1UL << (i % BITS_PER_LONG))) return i;
    return size;
}
'''
    main = r'''
int main(void) {
    struct ath11k ar_storage = {0};
    struct ath11k *ar = &ar_storage;
    struct ath11k_vif vif = {.ar = ar};
    struct ath11k_vif *arvif = &vif;
    struct ieee80211_key_conf key = {0};
'''
    main += initialization + r'''
    for (unsigned int i = 1; i < 128; i++) {
        assert(ath11k_get_vlan_groupkey_index(&vif, &key) == 0);
        assert(key.hw_key_idx == i && !locked);
    }
    assert(ath11k_get_vlan_groupkey_index(&vif, &key) == -ENOSPC && !locked);
    set_bit(64, vif.free_groupidx_map);
    assert(ath11k_get_vlan_groupkey_index(&vif, &key) == 0 && key.hw_key_idx == 64);
'''
    main += allocation + r'''
    assert(vif.vlan_keyid_map);
    vif.vlan_keyid_map[2048] = 64;
    vif.vlan_keyid_map[4094] = 127;
    assert(vif.vlan_keyid_map[2048] == 64 && vif.vlan_keyid_map[4094] == 127);
    free(vif.vlan_keyid_map);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="nss-vlan-test-") as tmp:
        src = Path(tmp) / "vlan.c"
        exe = Path(tmp) / "vlan"
        src.write_text(harness + function + main)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Werror",
                        "-fsanitize=address,undefined", str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS VLAN: 127 slots, exhaustion, reuse, VLAN 2048/4094 with ASan/UBSan")


if __name__ == "__main__":
    test_boot()
    if len(sys.argv) == 2:
        test_registration(Path(sys.argv[1]))
    elif len(sys.argv) == 3:
        test_registration(Path(sys.argv[1]))
        test_vlan(Path(sys.argv[2]))
