#!/usr/bin/env python3
"""Execute the real ath11k_core_reset() and check NSS release before power down."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "nss_reset_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define ATH11K_FLAG_REGISTERED 1
#define ATH11K_RESET_MAX_FAIL_COUNT_FIRST 3
#define ATH11K_RESET_MAX_FAIL_COUNT_FINAL 5
#define ATH11K_RESET_TIMEOUT_HZ 100
#define ATH11K_RESET_FAIL_TIMEOUT_HZ 100
#define ATH11K_RECOVER_START_TIMEOUT_HZ 100
#define ATH11K_DBG_BOOT 0
#define container_of(p, t, m) ((t *)((char *)(p) - __builtin_offsetof(t, m)))
typedef struct { int v; } atomic_t;
static int atomic_read(atomic_t *a) { return a->v; }
static void atomic_set(atomic_t *a, int v) { a->v = v; }
static int atomic_inc_return(atomic_t *a) { return ++a->v; }
static void atomic_inc(atomic_t *a) { a->v++; }
static void atomic_dec(atomic_t *a) { a->v--; }
struct work_struct { int unused; };
struct completion { int done; };
struct mutex { int held; };
static unsigned long jiffies = 1000;
#define time_before(a, b) ((long)((a) - (b)) < 0)
struct ath11k_base {
	unsigned long dev_flags;
	atomic_t fail_cont_count, reset_count, recovery_count, recovery_start_count;
	unsigned long reset_fail_timeout;
	struct completion reset_complete, recovery_start, reconfigure_complete;
	bool is_reset;
	struct mutex core_lock;
	struct { bool enabled; } nss;
	struct work_struct reset_work;
};
static char trace[256];
static int teardown_result;
static void step(const char *s) { strcat(trace, s); strcat(trace, ","); }
static bool test_bit(int b, unsigned long *f) { return *f & (1UL << b); }
static void ath11k_warn(struct ath11k_base *ab, const char *f, ...) {}
static void ath11k_err(struct ath11k_base *ab, const char *f, ...) {}
static void ath11k_info(struct ath11k_base *ab, const char *f, ...) {}
static void ath11k_dbg(struct ath11k_base *ab, int m, const char *f, ...) {}
static void reinit_completion(struct completion *c) { c->done = 0; }
static void complete(struct completion *c) { c->done++; }
static long wait_for_completion_timeout(struct completion *c, long t) { return 1; }
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held = 1; }
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held = 0; }
static void ath11k_coredump_collect(struct ath11k_base *ab) {}
static void ath11k_core_pre_reconfigure_recovery(struct ath11k_base *ab) { step("pre"); }
static void ath11k_core_post_reconfigure_recovery(struct ath11k_base *ab) { step("post"); }
static void ath11k_hif_irq_disable(struct ath11k_base *ab) { step("irq"); }
static void ath11k_hif_stop(struct ath11k_base *ab) { step("stop"); }
static int ath11k_nss_teardown(struct ath11k_base *ab)
{
	assert(ab->core_lock.held && ab->nss.enabled);
	step("teardown");
	return teardown_result;
}
static void ath11k_hif_power_down(struct ath11k_base *ab, bool k)
{
	assert(!ab->nss.enabled && !ab->core_lock.held);
	step("down");
}
static void ath11k_hif_power_up(struct ath11k_base *ab) { step("up"); }
'''

TEST = r'''
static struct ath11k_base fresh(void)
{
	struct ath11k_base ab = { .dev_flags = 1UL << ATH11K_FLAG_REGISTERED };

	ab.nss.enabled = true;
	trace[0] = 0;
	return ab;
}

int main(void)
{
	struct ath11k_base ab = fresh();

	teardown_result = 0;
	ath11k_core_reset(&ab.reset_work);
	assert(!strcmp(trace, "pre,post,irq,stop,teardown,down,up,"));
	assert(ab.is_reset && atomic_read(&ab.reset_count) == 1 && !ab.nss.enabled);

	ab = fresh();
	teardown_result = -5;
	ath11k_core_reset(&ab.reset_work);
	assert(!strcmp(trace, "pre,post,irq,stop,teardown,"));
	assert(!ab.is_reset && !atomic_read(&ab.reset_count) && ab.reset_complete.done == 1);
	assert(ab.nss.enabled && atomic_read(&ab.fail_cont_count) == ATH11K_RESET_MAX_FAIL_COUNT_FINAL);

	trace[0] = 0;
	ath11k_core_reset(&ab.reset_work);
	assert(!trace[0]);
	return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    args = parser.parse_args()
    core = (args.backports / 'drivers/net/wireless/ath/ath11k/core.c').read_text()
    code = (SHIM + extract.function(core, 'ath11k_core_release_nss') +
            extract.function(core, 'ath11k_core_reset') + TEST)
    with tempfile.TemporaryDirectory(prefix='nss-reset-release-') as tmp:
        src, exe = Path(tmp) / 'test.c', Path(tmp) / 'test'
        src.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-Wno-unused-but-set-variable',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=20)
    print('PASS actual ath11k_core_reset: CE IRQs stopped through hif_stop() so hif_start() restores them; NSS released '
          'under core_lock before power down; a failed release keeps the target powered, completes the '
          'reset and stops automatic retries')


if __name__ == '__main__':
    main()
