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
        ("monitor-validation", 1, True, False, "", 0),
        ("disabled", 0, False, False, "", 0),
        ("firmware-timeout", 1, False, False, "", 0),
        ("core-already-loaded", 1, True, True, "", 0),
        ("core-load-failure", 1, False, False, "qca-nss-drv", 1),
        ("dependency-failure", 1, True, False, "mac80211", 1),
        ("bridge-failure", 1, True, False, "qca-nss-bridge-mgr", 1),
        ("ahb-failure", 1, True, False, "ath11k_ahb", 1),
        ("pci-failure", 1, True, False, "ath11k_pci", 1),
        ("rx-config-failure", 1, True, False, "", 0),
        ("rx-irq-write-failure", 1, True, False, "", 0),
        ("single-cpu", 1, True, False, "", 0),
        ("missing-rx-irq", 1, True, False, "", 0),
    ]
    for name, enabled, ready, loaded, fail, expected in cases:
        with tempfile.TemporaryDirectory(prefix="nss-boot-test-") as tmp:
            base = Path(tmp)
            modules = base / "sys/module"
            modules.mkdir(parents=True)
            cpu = base / "sys/devices/system/cpu/cpu1"
            cpu.mkdir(parents=True)
            (cpu / "online").write_text("0\n" if name == "single-cpu" else "1\n")
            proc = base / "proc"
            rps = proc / "sys/dev/nss/rps"
            rps.mkdir(parents=True)
            (rps / "enable").write_text("0\n")
            if name == "rx-config-failure":
                (rps / "hash_bitmap").mkdir()
            else:
                (rps / "hash_bitmap").write_text("3\n")
            for irq in (48, 49):
                irq_dir = proc / "irq" / str(irq)
                irq_dir.mkdir(parents=True)
                if name == "rx-irq-write-failure" and irq == 49:
                    (irq_dir / "smp_affinity_list").mkdir()
                else:
                    (irq_dir / "smp_affinity_list").write_text("0-1\n")
            (proc / "interrupts").write_text(" 48: 0 0 GIC nss_queue0\n" +
                ("" if name == "missing-rx-irq" else " 49: 0 0 GIC nss_queue1\n"))
            if loaded:
                (modules / "qca_nss_drv/parameters").mkdir(parents=True)
                (modules / "qca_nss_drv/parameters/core0_ready").write_text("1\n")
            script = INIT.read_text().replace(". /lib/functions.sh", ":")
            script = script.replace("/proc/", "@PROC@")
            script = script.replace("/sys/", str(base / "sys") + "/")
            script = script.replace("@PROC@", str(proc) + "/")
            harness = r'''
config_load() { :; }
config_get_bool() {
    case "$1" in
        enabled) enabled="$TEST_ENABLED" ;;
        monitor_test) monitor_test="$TEST_MONITOR" ;;
        *) return 1 ;;
    esac
}
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
            env = dict(os.environ, TEST_ENABLED=str(enabled), TEST_MONITOR=str(int(name == "monitor-validation")),
                       READY=str(int(ready)), FAIL=fail, MODULES=str(modules),
                       CALLS=str(base / "calls"))
            result = subprocess.run(["sh"], input=harness + script + "\nstart\n",
                                    text=True, env=env, capture_output=True)
            assert result.returncode == expected, (name, result.stderr)
            calls = (base / "calls").read_text().splitlines()
            if not fail:
                mode = int(enabled and ready)
                suffix = f" nss_monitor_test={int(name == 'monitor-validation')}" if mode else ""
                assert f"insmod ath11k nss_offload={mode} frame_mode=2" + suffix in calls, name
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
            if name == "bridge-failure":
                assert "insmod ath11k nss_offload=1 frame_mode=2 nss_monitor_test=0" in calls, name
                assert "modprobe ath11k_ahb" in calls, name
            steered = enabled and ready and name not in ("core-load-failure", "dependency-failure",
                "rx-config-failure", "rx-irq-write-failure", "single-cpu", "missing-rx-irq")
            assert (rps / "enable").read_text().strip() == str(int(bool(steered))), name
            if steered:
                assert (proc / "irq/48/smp_affinity_list").read_text() == "0", name
                assert (proc / "irq/49/smp_affinity_list").read_text() == "1", name
            print(f"PASS boot: {name}")


def test_registration(source):
    text = (source / "nss_wifi_vdev.c").read_text()
    start = text.index("uint32_t nss_register_wifi_vdev_if(")
    end = text.index("EXPORT_SYMBOL(nss_register_wifi_vdev_if);", start)
    function = text[start:end]
    unreg_start = text.index("void nss_unregister_wifi_vdev_if(")
    unreg_end = text.index("EXPORT_SYMBOL(nss_unregister_wifi_vdev_if);", unreg_start)
    unregister = text[unreg_start:unreg_end]
    harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#define NSS_DYNAMIC_IF_START 32
#define NSS_MAX_DYNAMIC_INTERFACES 128
#define NSS_CORE_STATUS_SUCCESS 0
#define NSS_CORE_STATUS_FAILURE 1
#define NSS_CONTROL_WIFI_VDEV 1
#define nss_assert assert
#define nss_warning(...) ((void)0)
struct nss_ctx_instance { int dummy; };
static struct { int wifi_handler_id; struct nss_ctx_instance nss[1]; } nss_top_main;
struct net_device { int dummy; };
typedef void (*nss_wifi_vdev_callback_t)(void);
typedef void (*nss_wifi_vdev_ext_data_callback_t)(void);
typedef void (*nss_wifi_vdev_msg_callback_t)(void);
static int dp, msg, core, fail_msg, fail_core, fail_gate, unreg_phase;
static int nss_wifi_vdev_registration_lock;
static void mutex_lock(int *lock) { assert(!*lock); *lock = 1; }
static void mutex_unlock(int *lock) { assert(*lock); *lock = 0; }
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
    if (unreg_phase) { assert(unreg_phase == 2); unreg_phase = 3; }
    msg = 0; return 0;
}
static void nss_core_unregister_subsys_dp(struct nss_ctx_instance *c, int i) {
    if (unreg_phase) { assert(unreg_phase == 1); unreg_phase = 2; }
    dp = 0;
}
static uint32_t nss_core_unregister_handler(struct nss_ctx_instance *c, int i) {
    if (unreg_phase) { assert(unreg_phase == 3); unreg_phase = 4; }
    core = 0; return 0;
}
static int nss_control_open(struct nss_ctx_instance *c, int family, int i) { return !fail_gate; }
static void nss_control_close(struct nss_ctx_instance *c, int family, int i) {
    assert(nss_wifi_vdev_registration_lock && dp && msg && core && !unreg_phase);
    unreg_phase = 1;
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
    dp = msg = core = 0; fail_gate = 1;
    assert(nss_register_wifi_vdev_if(&ctx, 32, callback, callback, callback, &dev, 0) == NSS_CORE_STATUS_FAILURE);
    assert(!dp && !msg && !core && !nss_wifi_vdev_registration_lock);
    fail_gate = 0;
    assert(nss_register_wifi_vdev_if(&ctx, 32, callback, callback, callback, &dev, 0) == 0);
    nss_unregister_wifi_vdev_if(32);
    assert(!dp && !msg && !core && !nss_wifi_vdev_registration_lock && unreg_phase == 4);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="nss-registration-test-") as tmp:
        src = Path(tmp) / "registration.c"
        exe = Path(tmp) / "registration"
        src.write_text(harness + function + unregister + main)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Werror", str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS VDEV: message/core/gate failure, preserved handlers, unlocked rollback, retry and drain-before-unpublish")


def test_vlan(source):
    text = (source / "drivers/net/wireless/ath/ath11k/mac.c").read_text()
    start = text.index("static int ath11k_get_vlan_groupkey_index(")
    # Only this function; unrelated key helpers may follow it.
    end = text.index("\n}\n", start) + 3
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


def test_rps(source):
    text = (source / "nss_rps.c").read_text()
    names = ("nss_rps_pri_map_parse", "nss_rps_cfg_handler",
             "nss_rps_hash_bitmap_cfg_handler", "nss_rps_pri_map_cfg_handler")
    functions = ""
    for name in names:
        start = text.index("static int " + name + "(")
        end = text.index("\n}\n", start) + 3
        functions += text[start:end] + "\n"
    start = text.index("struct nss_rps_pri_map_parse_data {")
    parsed_struct = text[start:text.index("};", start)+3]
    harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define compat_const const
#define loff_t int64_t
#define NSS_SUCCESS 0
#define NSS_RPS_MAX_CORE_HASH_BITMAP 3
#define NSS_MAX_NUM_PRI 4
#define NSS_HOST_MAX_NUM_CORES 2
#define NSS_HOST_CORES 2
#define NSS_N2H_RPS_PRI_DEFAULT -1
#define NSS_RPS_PRI_MAP_PARAM_FIELD_COUNT 2
#define nss_warning(...) ((void)0)
#define nss_info(...) ((void)0)
#define nss_info_always(...) ((void)0)
typedef uint32_t u32;
struct ctl_table { int *data; };
struct nss_ctx_instance { int unused; };
struct nss_top_instance { struct nss_ctx_instance nss[2]; int num_nss; };
static struct nss_top_instance nss_top_main={.num_nss=1};
static int nss_rps_config, nss_rps_hash_bitmap=3;
static int nss_rps_pri_map[4]={-1,-1,-1,-1};
static int cfg_result,cfg_calls,v4_result,v6_result,v4_calls,v6_calls,v4_values[4],pri_result;
static int proc_dointvec(const struct ctl_table *c,int write,void *buf,size_t *len,loff_t *pos) {
 if(write) *c->data=*(int *)buf;
 return 0;
}
static int nss_rps_cfg(struct nss_ctx_instance *c,int enable) { assert(enable==1); ++cfg_calls; return cfg_result; }
static int nss_rps_ipv4_hash_bitmap_cfg(struct nss_ctx_instance *c,int bitmap) {
 assert(v4_calls<4); v4_values[v4_calls++]=bitmap; return v4_result;
}
static int nss_rps_ipv6_hash_bitmap_cfg(struct nss_ctx_instance *c,int bitmap) { ++v6_calls; return v6_result; }
static int nss_rps_pri_map_cfg(struct nss_ctx_instance *c,int *map) { return pri_result; }
static void nss_rps_pri_map_usage(void) {}
static int nss_rps_pri_map_print(void *b,size_t *l,loff_t *p,int *map) { return 0; }
'''
    main = r'''
static int configure(int (*handler)(const struct ctl_table *,int,void *,size_t *,loff_t *),int *value,int next) {
 struct ctl_table ctl={.data=value}; size_t len=sizeof(next); loff_t pos=0;
 return handler(&ctl,1,&next,&len,&pos);
}
int main(void) {
 assert(!configure(nss_rps_cfg_handler,&nss_rps_config,0) && !cfg_calls && !nss_rps_config);
 assert(!configure(nss_rps_cfg_handler,&nss_rps_config,1) && cfg_calls==1 && nss_rps_config==1);
 assert(configure(nss_rps_cfg_handler,&nss_rps_config,0)==-EOPNOTSUPP && nss_rps_config==1 && cfg_calls==1);
 assert(configure(nss_rps_cfg_handler,&nss_rps_config,2)==-EINVAL && nss_rps_config==1 && cfg_calls==1);
 assert(configure(nss_rps_cfg_handler,&nss_rps_config,-1)==-EINVAL && nss_rps_config==1 && cfg_calls==1);
 nss_rps_config=0; cfg_result=1;
 assert(configure(nss_rps_cfg_handler,&nss_rps_config,1)==-EIO && !nss_rps_config);
 cfg_result=0;
#if defined(NSS_DRV_IPV4_ENABLE) && defined(NSS_DRV_IPV6_ENABLE)
 assert(!configure(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,0));
 assert(!nss_rps_hash_bitmap && v4_values[0]==0 && v6_calls==1);
 v4_calls=v6_calls=0;
 assert(!configure(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,2));
 assert(nss_rps_hash_bitmap==2 && v4_values[0]==2 && v6_calls==1);
 nss_rps_hash_bitmap=3; v4_calls=v6_calls=0; v4_result=1;
 assert(configure(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,2)==-EIO);
 assert(nss_rps_hash_bitmap==3 && v4_calls==1 && !v6_calls);
 v4_result=0; v6_result=1; v4_calls=v6_calls=0;
 assert(configure(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,2)==-EIO);
 assert(nss_rps_hash_bitmap==3 && v4_calls==2 && v4_values[0]==2 && v4_values[1]==3);
 v6_result=0; v4_calls=v6_calls=0;
 assert(configure(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,4)==-EINVAL && nss_rps_hash_bitmap==3 && !v4_calls);
 assert(configure(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,-1)==-EINVAL && nss_rps_hash_bitmap==3 && !v4_calls);
#else
 assert(configure(nss_rps_hash_bitmap_cfg_handler,&nss_rps_hash_bitmap,2)==-EOPNOTSUPP);
 assert(nss_rps_hash_bitmap==3 && !v4_calls && !v6_calls);
#endif
 struct nss_rps_pri_map_parse_data out;
 char inputs[][6]={"0 1","0 -1","0 -1\n","3 1\n"};
 for(unsigned i=0;i<4;++i) {
  size_t len=strlen(inputs[i]); assert(!nss_rps_pri_map_parse(inputs[i],&len,&out));
  assert(out.pri==(i==3?3:0) && out.core==((i==1 || i==2)?-1:1));
 }
 char overlong[]="0 -1 \n"; size_t len=sizeof(overlong)-1;
 assert(nss_rps_pri_map_parse(overlong,&len,&out)==-EINVAL);
 char bad_pri[]="4 1\n"; len=sizeof(bad_pri)-1; assert(nss_rps_pri_map_parse(bad_pri,&len,&out)!=0);
 char bad_cpu[]="0 2\n"; len=sizeof(bad_cpu)-1; assert(nss_rps_pri_map_parse(bad_cpu,&len,&out)!=0);
 struct ctl_table ctl={0}; loff_t pos=0; char value[]="0 1\n"; len=sizeof(value)-1;
 pri_result=1; assert(nss_rps_pri_map_cfg_handler(&ctl,1,value,&len,&pos)==-EIO && nss_rps_pri_map[0]==-1);
 pri_result=0; pos=0; len=sizeof(value)-1;
 assert(!nss_rps_pri_map_cfg_handler(&ctl,1,value,&len,&pos) && nss_rps_pri_map[0]==1);
 return 0;
}
'''
    for supported in (True, False):
        with tempfile.TemporaryDirectory(prefix="nss-rps-test-") as tmp:
            src, exe = Path(tmp) / "rps.c", Path(tmp) / "rps"
            defines = "#define NSS_DRV_IPV4_ENABLE\n#define NSS_DRV_IPV6_ENABLE\n" if supported else ""
            src.write_text(defines + harness + parsed_struct + functions + main)
            subprocess.run(["cc", "-std=gnu11", "-Wall", "-Werror", "-Wno-unused-function",
                            "-fsanitize=address,undefined", str(src), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
        print("PASS RPS: state, ACK errors, bitmap rollback and priority input (" +
              ("IPv4/IPv6 enabled" if supported else "unsupported protocols") + ")")


if __name__ == "__main__":
    test_boot()
    if len(sys.argv) == 2:
        test_registration(Path(sys.argv[1]))
        test_rps(Path(sys.argv[1]))
    elif len(sys.argv) == 3:
        test_registration(Path(sys.argv[1]))
        test_rps(Path(sys.argv[1]))
        test_vlan(Path(sys.argv[2]))
