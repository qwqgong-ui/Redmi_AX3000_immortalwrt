#!/usr/bin/env python3
"""Execute the real ath11k AHB SSR notifier that releases NSS before userpd power up."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "nss_ssr_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define NOTIFY_DONE 0
#define NOTIFY_OK 1
enum { QCOM_SSR_BEFORE_POWERUP, QCOM_SSR_AFTER_POWERUP, QCOM_SSR_BEFORE_SHUTDOWN,
	QCOM_SSR_AFTER_SHUTDOWN };
#define ATH11K_FLAG_REGISTERED 1
#define ATH11K_FLAG_UNREGISTERING 2
struct mutex { int held; };
struct notifier_block { int (*notifier_call)(struct notifier_block *, unsigned long, void *); };
struct ath11k_base {
	unsigned long dev_flags;
	struct mutex core_lock;
	struct { bool enabled; } nss;
	unsigned char drv_priv[] __attribute__((aligned(sizeof(void *))));
};
struct ath11k_ahb { void *tgt_rproc; struct notifier_block ssr_nb; void *ssr_handle; };
static int teardowns, teardown_result, infos, errs;
static bool test_bit(int b, unsigned long *f) { return *f & (1UL << b); }
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held = 1; }
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held = 0; }
static void ath11k_info(struct ath11k_base *ab, const char *f, ...) { infos++; }
static void ath11k_err(struct ath11k_base *ab, const char *f, ...) { errs++; }
static int ath11k_nss_teardown(struct ath11k_base *ab)
{
	assert(ab->core_lock.held);
	teardowns++;
	return ab->nss.enabled ? teardown_result : 0;
}
'''

TEST = r'''
static union { struct ath11k_base ab; unsigned char raw[sizeof(struct ath11k_base) + sizeof(struct ath11k_ahb)]; } dev;

static int fire(unsigned long event)
{
	struct ath11k_ahb *ab_ahb = (struct ath11k_ahb *)dev.ab.drv_priv;

	return ath11k_ahb_ssr_notify(&ab_ahb->ssr_nb, event, NULL);
}

int main(void)
{
	dev.ab.nss.enabled = true;
	assert(fire(QCOM_SSR_BEFORE_POWERUP) == NOTIFY_DONE && !teardowns);

	dev.ab.dev_flags = 1UL << ATH11K_FLAG_REGISTERED;
	assert(fire(QCOM_SSR_BEFORE_SHUTDOWN) == NOTIFY_DONE);
	assert(fire(QCOM_SSR_AFTER_SHUTDOWN) == NOTIFY_DONE);
	assert(fire(QCOM_SSR_AFTER_POWERUP) == NOTIFY_DONE && !teardowns);

	teardown_result = -5;
	assert(fire(QCOM_SSR_BEFORE_POWERUP) == NOTIFY_OK);
	assert(teardowns == 1 && dev.ab.nss.enabled && errs == 1 && !infos);

	teardown_result = 0;
	assert(fire(QCOM_SSR_BEFORE_POWERUP) == NOTIFY_OK);
	assert(teardowns == 2 && !dev.ab.nss.enabled && infos == 1);

	assert(fire(QCOM_SSR_BEFORE_POWERUP) == NOTIFY_OK);
	assert(teardowns == 3 && infos == 1);

	dev.ab.nss.enabled = true;
	dev.ab.dev_flags |= 1UL << ATH11K_FLAG_UNREGISTERING;
	assert(fire(QCOM_SSR_BEFORE_POWERUP) == NOTIFY_DONE && teardowns == 3);
	assert(!dev.ab.core_lock.held);
	return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    args = parser.parse_args()
    ath11k = args.backports / 'drivers/net/wireless/ath/ath11k'
    core = (ath11k / 'core.c').read_text()
    ahb = (ath11k / 'ahb.c').read_text()
    code = (SHIM + extract.function(core, 'ath11k_core_release_nss') +
            extract.function(ahb, 'ath11k_ahb_ssr_notify') + TEST)
    with tempfile.TemporaryDirectory(prefix='nss-ssr-release-') as tmp:
        src, exe = Path(tmp) / 'test.c', Path(tmp) / 'test'
        src.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=20)
    print('PASS actual ath11k_ahb_ssr_notify: NSS released under core_lock only before a '
          'registered userpd powers up; failure keeps NSS enabled; shutdown, first boot and '
          'unregistering events are ignored')


if __name__ == '__main__':
    main()
