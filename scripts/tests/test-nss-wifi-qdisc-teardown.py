#!/usr/bin/env python3
"""Execute mac80211's ndo_stop hook before the NSS interface disappears."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define CPTCFG_MAC80211_NSS_SUPPORT 1
struct Qdisc_ops {const char *id;};
struct Qdisc {struct Qdisc_ops *ops;};
struct ieee80211_local {bool hw;};
struct ieee80211_sub_if_data {struct ieee80211_local *local;void *nssctx;};
struct net_device {struct Qdisc *qdisc;struct ieee80211_sub_if_data *priv;bool deactivated;};
#define IEEE80211_DEV_TO_SUB_IF(d) ((d)->priv)
#define ieee80211_hw_check(hw,flag) (*(hw))
static bool rtnl,registered,freed;
static unsigned sequence,free_sequence,remove_sequence;
static struct Qdisc *dereference(struct Qdisc *q){assert(rtnl);return q;}
#define rtnl_dereference(q) dereference(q)
static void dev_shutdown(struct net_device *dev){
 assert(rtnl&&dev->deactivated&&registered&&!freed);
 freed=true;free_sequence=++sequence;dev->qdisc=NULL;
}
static void nss_virt_if_destroy_sync(void *ctx){(void)ctx;}
#define sdata_info(...) ((void)0)
'''

CASES = r'''
int main(void){
 const char *types[]={"nssfq_codel","nsstbl","nssprio","cake","fq_codel","noqueue"};
 for(unsigned offload=0;offload<2;offload++)for(unsigned type=0;type<6;type++){
  struct Qdisc_ops ops={types[type]};struct Qdisc q={&ops};
  struct ieee80211_local local={offload};struct ieee80211_sub_if_data sdata={.local=&local};
  struct net_device dev={.qdisc=&q,.priv=&sdata,.deactivated=true};
  rtnl=registered=true;freed=false;sequence=free_sequence=remove_sequence=0;
  stop_prefix(&dev);
  /* drv_remove_interface follows the real ndo_stop prefix. Its BASE gate
   * is still live for synchronous qdisc FREE, and closes afterwards. */
  bool nss=offload&&type<3;
  assert(freed==nss&&(nss?!dev.qdisc:dev.qdisc==&q));
  registered=false;remove_sequence=++sequence;
  assert(!nss||free_sequence<remove_sequence);
 }
 struct ieee80211_local local={true};struct ieee80211_sub_if_data sdata={.local=&local};
 struct net_device dev={.priv=&sdata,.deactivated=true};rtnl=registered=true;freed=false;
 stop_prefix(&dev);assert(!freed&&!dev.qdisc);
 puts("PASS actual ndo_stop hook: synchronous NSS FREE before VDEV removal, null root, software qdisc and disabled-offload isolation");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    parser.add_argument('--draft', type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('teardown_extract', Path(__file__).with_name('test-nss-control.py'))
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    source = ((args.draft or args.backports) / 'net/mac80211/iface.c').read_text()
    helper = extract.function(source, 'ieee80211_shutdown_nss_qdisc')
    stop = extract.function(source, 'ieee80211_stop')
    begin = stop.index('#ifdef CPTCFG_MAC80211_NSS_SUPPORT')
    end = stop.index('#endif', begin) + len('#endif')
    prefix = ('static void stop_prefix(struct net_device *dev){\n'
              'struct ieee80211_sub_if_data *sdata=IEEE80211_DEV_TO_SUB_IF(dev);\n'
              + stop[begin:end] + '\n}\n')
    with tempfile.TemporaryDirectory(prefix='nss-wifi-qdisc-teardown-') as directory:
        source, binary = Path(directory) / 'test.c', Path(directory) / 'test'
        source.write_text(SHIM + helper + prefix + CASES)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                        '-Werror', '-Wno-unused-function', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15)


if __name__ == '__main__':
    main()
