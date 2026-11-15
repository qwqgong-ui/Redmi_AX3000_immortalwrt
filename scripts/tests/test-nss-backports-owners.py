#!/usr/bin/env python3
"""Run real debugfs stats readers against recovery, and NSS mesh band selection."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile

PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
typedef unsigned long long u64;typedef uint32_t u32;typedef uint16_t u16;typedef uint8_t u8;
#define IEEE80211_NUM_TIDS 16
#define __user
#define GFP_KERNEL 0
'''
SHIM = r'''
struct lock {bool held;};
static void lock(struct lock *l){assert(!l->held);l->held=true;}
static void unlock(struct lock *l){assert(l->held);l->held=false;}
#define mutex_lock lock
#define mutex_unlock unlock
#define spin_lock_bh lock
#define spin_unlock_bh unlock
struct ath11k_base {struct lock base_lock;};
struct ath11k {struct ath11k_base *ab;struct lock conf_mutex,data_lock;};
struct ath11k_vif {struct ath11k *ar;};
struct ath11k_sta {struct ath11k_vif *arvif;struct ath11k_htt_tx_stats *tx_stats;struct ath11k_rx_peer_stats *rx_stats;};
struct ieee80211_sta {struct ath11k_sta drv_priv;};
struct file {void *private_data;};
static struct ath11k_sta *ath11k_sta_to_arsta(struct ieee80211_sta *s){return &s->drv_priv;}
static struct ieee80211_sta sta;
static struct ath11k_base ab;
static struct ath11k ar={.ab=&ab};
static struct ath11k_vif vif={.ar=&ar};
static bool inject_alloc,inject_parse,fail_alloc;
static void *read_buffer;
static void ath11k_mac_station_cleanup(struct ieee80211_sta *);
static void recover(void){
 assert(!ar.conf_mutex.held&&!ab.base_lock.held);lock(&ar.conf_mutex);lock(&ab.base_lock);
 ath11k_mac_station_cleanup(&sta);unlock(&ab.base_lock);unlock(&ar.conf_mutex);
}
static void *kzalloc(size_t n,int flags){
 (void)flags;if(inject_alloc){inject_alloc=false;recover();}if(fail_alloc)return NULL;
 assert(!read_buffer);read_buffer=calloc(1,n);assert(read_buffer);return read_buffer;
}
static void kfree(void *p){if(p==read_buffer)read_buffer=NULL;free(p);}
static int scnprintf(char *buf,size_t size,const char *format,...){
 /* Both live writers own base_lock. Check every formatted stats access. */
 assert(ab.base_lock.held&&size);va_list args;va_start(args,format);int n=vsnprintf(buf,size,format,args);va_end(args);
 assert(n>=0);return (size_t)n>=size?(int)size-1:n;
}
static ssize_t simple_read_from_buffer(char *out,size_t count,loff_t *pos,const char *buf,size_t len){
 if((size_t)*pos>=len)return 0;size_t n=len-*pos;if(n>count)n=count;memcpy(out,buf+*pos,n);*pos+=n;return n;
}
static int kstrtoint_from_user(const char *buf,size_t count,int base,int *reset){
 (void)base;assert(count==1&&*buf=='1');if(inject_parse){inject_parse=false;recover();}*reset=1;return 0;
}
struct ieee80211_tx_info {unsigned flags,band;};
struct sk_buff {u8 data[14];struct ieee80211_tx_info info;};
struct channel {unsigned band;};
struct ieee80211_chanctx_conf {struct {struct channel *chan;} def;};
struct ieee80211_local {bool hw;};
struct ieee80211_sub_if_data {struct {unsigned driver_flags;} vif;};
#define ieee80211_hw_check(hw,flag) (*(hw))
#define IEEE80211_VIF_NSS_OFFLOAD_DEBUG_MODE 1
#define IEEE80211_TX_CTL_HW_80211_ENCAP 2
#define IEEE80211_SKB_CB(s) (&(s)->info)
static bool is_multicast_ether_addr(const u8 *a){return a[0]&1;}
'''
CASES = r'''
static void prepare(void){
 assert(!read_buffer&&!ar.conf_mutex.held&&!ar.data_lock.held&&!ab.base_lock.held);
 sta.drv_priv=(struct ath11k_sta){.arvif=&vif,.tx_stats=calloc(1,sizeof(struct ath11k_htt_tx_stats)),.rx_stats=calloc(1,sizeof(struct ath11k_rx_peer_stats))};
 assert(sta.drv_priv.tx_stats&&sta.drv_priv.rx_stats);inject_alloc=inject_parse=fail_alloc=false;
}
int main(void){
 struct file file={.private_data=&sta};char buf[16384];
 for(unsigned rx=0;rx<2;rx++)for(unsigned scenario=0;scenario<4;scenario++){
  prepare();loff_t pos=0;
  if(scenario==1)fail_alloc=true;
  if(scenario==2)inject_alloc=true;
  if(scenario==3)recover();
  ssize_t n=rx?ath11k_dbg_sta_dump_rx_stats(&file,buf,sizeof(buf),&pos):ath11k_dbg_sta_dump_tx_stats(&file,buf,sizeof(buf),&pos);
  assert(scenario==0?n>0:n==(scenario==1?-ENOMEM:-ENOENT));
  assert(!read_buffer&&!ar.conf_mutex.held&&!ar.data_lock.held&&!ab.base_lock.held);recover();
 }
 for(unsigned race=0;race<2;race++){
  prepare();loff_t pos=0;sta.drv_priv.rx_stats->num_msdu=123;inject_parse=race;
  assert(ath11k_dbg_sta_reset_rx_stats(&file,"1",1,&pos)==(race?-ENOENT:1));
  if(!race)assert(!sta.drv_priv.rx_stats->num_msdu);
  assert(!ar.conf_mutex.held&&!ab.base_lock.held);recover();
 }
 struct ieee80211_local local={.hw=true};struct ieee80211_sub_if_data sdata={.vif={1}};
 struct sk_buff skb={0};struct channel channel={0};struct ieee80211_chanctx_conf ctx={.def={&channel}};
 for(unsigned band=0;band<3;band++){
  channel.band=band;memset(&skb.info,0xa5,sizeof(skb.info));
  assert(mesh_branch(&local,&sdata,&skb,&ctx,8)==1&&skb.info.band==band&&skb.info.flags==10);
 }
 assert(mesh_branch(&local,&sdata,&skb,NULL,8)==-ENOTCONN);
 skb.data[0]=1;assert(!mesh_branch(&local,&sdata,&skb,&ctx,8));
 skb.data[0]=0;local.hw=false;assert(!mesh_branch(&local,&sdata,&skb,&ctx,8));
 puts("PASS actual debugfs TX/RX read/reset vs recovery, allocation failures, balanced locks, and NSS mesh channel band/no-channel handling");
}
'''


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    parser.add_argument('--draft', type=Path)
    args = parser.parse_args()
    extract = load('owner_functions', 'test-nss-control.py')
    types = load('owner_types', 'test-reo-command-lifetime.py')
    ath = args.backports / 'drivers/net/wireless/ath/ath11k'

    def read(relative):
        p = args.draft / relative if args.draft else args.backports / relative
        return (p if p.exists() else args.backports / relative).read_text()

    core = (ath / 'core.h').read_text()
    headers = '\n'.join((ath / name).read_text() for name in ('core.h', 'hal_rx.h', 'rx_desc.h', 'hal_desc.h'))
    declarations = ''.join(types.declaration(core, 'struct', name) for name in
                           ('ath11k_rx_peer_rate_stats', 'ath11k_rx_peer_stats', 'ath11k_htt_data_stats', 'ath11k_htt_tx_stats'))
    debug = read('drivers/net/wireless/ath/ath11k/debugfs_sta.c')
    functions = ''.join(extract.function(debug, name) for name in
                        ('ath11k_dbg_sta_dump_tx_stats', 'ath11k_dbg_sta_dump_rx_stats', 'ath11k_dbg_sta_reset_rx_stats'))
    needed = set(re.findall(r'\b(?:HAL_RX_|ATH11K_|MAX_MU_)[A-Z0-9_]+\b', declarations + functions))
    enums = [m[0] for m in re.finditer(r'enum \w+\s*\{.*?\};', headers, re.S)
             if needed.intersection(re.findall(r'\b[A-Z][A-Z0-9_]+\b', m[0]))]
    macros = [line for line in headers.splitlines() if line.startswith('#define ')
              and line.split()[1] in needed]
    definitions = '\n'.join(macros + enums)
    cleanup = extract.function(read('drivers/net/wireless/ath/ath11k/mac.c'), 'ath11k_mac_station_cleanup')
    tx = extract.function(read('net/mac80211/tx.c'), 'ieee80211_build_hdr')
    begin = tx.index('if (ieee80211_hw_check(&local->hw, SUPPORTS_NSS_OFFLOAD) &&')
    start = tx.index('{', begin)
    depth = 1
    end = start + 1
    while depth:
        depth += (tx[end] == '{') - (tx[end] == '}')
        end += 1
    mesh = '''static int mesh_branch(struct ieee80211_local *local,struct ieee80211_sub_if_data *sdata,
      struct sk_buff *skb,struct ieee80211_chanctx_conf *chanctx_conf,unsigned info_flags){
      struct ieee80211_tx_info *info;unsigned band=0;int ret=0;
    ''' + tx[begin:end] + '\nreturn 0;\nnss_mesh:return 1;\nfree:return ret;\n}\n'
    with tempfile.TemporaryDirectory(prefix='nss-backports-owner-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(PRELUDE + definitions + declarations + SHIM + cleanup + functions + mesh + CASES)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=15)


if __name__ == '__main__':
    main()
