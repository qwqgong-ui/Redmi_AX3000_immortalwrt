#!/usr/bin/env python3
"""Execute the real q6v5 multipd root-crash user PD stop/restart sequence."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "mpd_extract", Path(__file__).with_name("test-nss-control.py"))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define MAX_UPD 3
#define UPD_SWID 0x12
#define READ_ONCE(x) (x)
#define dev_err(...) ((void)0)
typedef uint8_t u8;
typedef uint32_t u32;
enum rproc_state { RPROC_OFFLINE, RPROC_SUSPENDED, RPROC_RUNNING, RPROC_CRASHED };
struct device { struct device *parent; void *drvdata; };
struct mutex { int held; };
struct firmware { int id; };
struct rproc { enum rproc_state state; void *priv; const char *name; const char *firmware;
	struct mutex lock; int start_result; int starts, stops; };
struct qcom_q6v5 { struct rproc *rproc; bool running; int stop_bit; };
struct wcss_data { u32 pasid; };
struct q6_wcss { struct device *dev; const struct wcss_data *desc; void *mem_region;
	unsigned long mem_phys, mem_size; struct userpd *upd[MAX_UPD]; bool upd_restarting; };
struct userpd { u8 pd_asid; struct device *dev; struct qcom_q6v5 q6; };
static char trace[512];
static struct q6_wcss *root_wcss;
static void step(const char *s) { strcat(trace, s); strcat(trace, ","); }
static void *dev_get_drvdata(struct device *d) { return d->drvdata; }
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held = 1; }
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held = 0; }
static void msleep(int ms) { (void)ms; }
static int request_firmware(const struct firmware **fw, const char *name, struct device *d)
{ static struct firmware f; *fw = &f; return 0; }
static void release_firmware(const struct firmware *fw) {}
static int qcom_q6v5_request_stop(struct qcom_q6v5 *q6, void *s) { step("req_stop"); return 0; }
static int qcom_scm_internal_wifi_shutdown(u32 p) { step("wifi_off"); return 0; }
static int qcom_scm_msa_unlock(u32 p) { step("msa_unlock"); return 0; }
static void rproc_shutdown(struct rproc *r) { assert(!root_wcss->upd_restarting); step("root_shutdown"); }
static int rproc_boot(struct rproc *r) { assert(!root_wcss->upd_restarting); step("root_boot"); return 0; }
static int qcom_mdt_load_pd_seg(struct device *d, const struct firmware *fw, const char *n,
	u32 pasid, u8 asid, void *mem, unsigned long phys, unsigned long size, void *reloc)
{ step("load_seg"); return 0; }
static int wcss_pd_stop(struct rproc *rproc);
static int rproc_stop(struct rproc *r, bool crashed)
{
	assert(crashed && r->state == RPROC_CRASHED && root_wcss->upd_restarting);
	r->stops++;
	step("upd_stop");
	wcss_pd_stop(r);
	r->state = RPROC_OFFLINE;
	return 0;
}
static int rproc_start(struct rproc *r, const struct firmware *fw)
{
	assert(r->lock.held && root_wcss->upd_restarting);
	r->starts++;
	step("upd_start");
	if (!r->start_result)
		r->state = RPROC_RUNNING;
	return r->start_result;
}
'''

TEST = r'''
static struct device root_dev, upd_dev[2];
static struct rproc root = { .state = RPROC_RUNNING, .name = "root" };
static struct rproc urp[2] = { { .name = "pd-1", .firmware = "f1" }, { .name = "pd-2", .firmware = "f2" } };
static struct userpd upds[2];
static struct q6_wcss wcss;
static const struct wcss_data desc = { .pasid = 0x19 };

int main(void)
{
	int i;

	root_wcss = &wcss;
	root.priv = &wcss;
	root_dev.drvdata = &root;
	wcss.dev = &root_dev;
	wcss.desc = &desc;
	for (i = 0; i < 2; i++) {
		upd_dev[i].parent = &root_dev;
		upds[i] = (struct userpd){ .pd_asid = i + 1, .dev = &upd_dev[i],
			.q6 = { .rproc = &urp[i], .running = true, .stop_bit = 1 } };
		urp[i].priv = &upds[i];
		urp[i].state = RPROC_RUNNING;
		wcss.upd[i] = &upds[i];
	}

	wcss_pd_stop(&urp[1]);
	assert(!strcmp(trace, "req_stop,msa_unlock,root_shutdown,"));
	trace[0] = 0;
	wcss_pd_load(&urp[1], NULL);
	assert(!strcmp(trace, "root_boot,load_seg,"));

	urp[1].state = RPROC_OFFLINE;
	trace[0] = 0;
	q6_wcss_stop_userpds(&wcss);
	assert(!strcmp(trace, "upd_stop,wifi_off,msa_unlock,"));
	assert(wcss.upd_restarting && urp[0].state == RPROC_SUSPENDED && !upds[0].q6.running);
	assert(urp[1].state == RPROC_OFFLINE && !urp[1].stops);

	trace[0] = 0;
	wcss_pd_load(&urp[0], NULL);
	assert(!strcmp(trace, "load_seg,"));

	urp[1].state = RPROC_SUSPENDED;
	urp[1].start_result = -5;
	trace[0] = 0;
	assert(!q6_wcss_restart_userpds(&root));
	assert(!strcmp(trace, "upd_start,upd_start,"));
	assert(urp[0].state == RPROC_RUNNING && urp[1].state == RPROC_CRASHED);
	assert(!wcss.upd_restarting && !urp[0].lock.held && !urp[1].lock.held);

	root.state = RPROC_CRASHED;
	wcss.upd_restarting = true;
	assert(q6_wcss_restart_userpds(&root) == -ETIMEDOUT && !wcss.upd_restarting);
	return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    args = parser.parse_args()
    mpd = (args.kernel / 'drivers/remoteproc/qcom_q6v5_mpd.c').read_text()
    code = SHIM + '#include <errno.h>\n'
    for name in ('wcss_pd_stop', 'wcss_pd_load', 'q6_wcss_stop_userpds', 'q6_wcss_restart_userpds'):
        code += extract.function(mpd, name)
    code += TEST
    with tempfile.TemporaryDirectory(prefix='mpd-rootpd-') as tmp:
        src, exe = Path(tmp) / 'test.c', Path(tmp) / 'test'
        src.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-Wno-unused-variable', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=20)
    print('PASS actual q6v5 multipd root crash: running user PDs stop through their own op '
          'with the root left alone, restart under their lock once the root runs, and the '
          'normal stop/load path still releases and boots the root')


if __name__ == '__main__':
    main()
