#!/usr/bin/env python3
"""Execute station rollback and TX snapshots with deterministic callback interleavings."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;typedef uint64_t u64;
#define GFP_KERNEL 0
#define WMI_PEER_TYPE_DEFAULT 0
#define WMI_PEER_USE_4ADDR 1
#define WMI_VDEV_TYPE_AP 1
#define ath11k_warn(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
struct lock {bool held;};
static void spin_lock_bh(struct lock *l){assert(!l->held);l->held=true;}
static void spin_unlock_bh(struct lock *l){assert(l->held);l->held=false;}
#define lockdep_assert_held(l) assert((l)->held)
struct rate_info {unsigned legacy,mcs,nss,bw,he_gi,he_dcm,he_ru_alloc,flags;};
struct stats {u64 counter;};
struct ath11k_base {struct lock base_lock;struct {bool vdev_start_delay;} hw_params;};
struct ath11k {struct ath11k_base *ab;struct lock conf_mutex,tbl_mtx_lock;void *hw;unsigned max_num_stations,num_peers;};
struct ath11k_vif {struct ath11k *ar;unsigned num_stations,vdev_id,vdev_type;bool reinstall_group_keys,is_started;};
struct ath11k_sta {struct ath11k_vif *arvif;struct stats *tx_stats,*rx_stats;unsigned avg_rssi;u64 tx_duration,rx_duration;struct rate_info txrate;};
struct ieee80211_sta {u8 addr[6];struct ath11k_sta drv_priv;};
struct ieee80211_vif {struct ath11k_vif *priv;bool mesh;};
struct ath11k_peer {struct ieee80211_sta *sta;unsigned list;};
struct peer_create_params {unsigned vdev_id,peer_type;u8 *peer_addr;};
static struct ath11k_base ab;
static struct ath11k ar={.ab=&ab};
static struct ath11k_vif av={.ar=&ar,.vdev_id=3};
static struct ieee80211_vif vif={.priv=&av};
static struct ieee80211_sta sta,other;
static struct ath11k_peer peer;
enum stage {OK,INC,GROUP,RX_ALLOC,TX_ALLOC,CREATE,MESH,DP,START,STOP};
static enum stage failure;
static unsigned allocs,live,created,deleted,dp_cleaned,delete_mode,released,unhashed;
static bool extended,peer_present,dp_ready;
#define mutex_lock spin_lock_bh
#define mutex_unlock spin_unlock_bh
static struct ath11k_sta *ath11k_sta_to_arsta(struct ieee80211_sta *s){return &s->drv_priv;}
static struct ath11k_vif *ath11k_vif_to_arvif(struct ieee80211_vif *v){return v->priv;}
static bool ieee80211_vif_is_mesh(struct ieee80211_vif *v){return v->mesh;}
static void *kzalloc(size_t n,int flags){
 (void)flags;assert(ar.conf_mutex.held&&!ab.base_lock.held);allocs++;
 if((failure==RX_ALLOC&&allocs==1)||(failure==TX_ALLOC&&allocs==2))return NULL;
 void *p=calloc(1,n);assert(p);live++;return p;
}
static void kfree(void *p){
 if(!p)return;
 assert(ar.conf_mutex.held&&ab.base_lock.held&&(!peer_present||peer.sta!=&sta));
 assert(live);live--;free(p);
}
static int ath11k_mac_inc_num_stations(struct ath11k_vif *v,struct ieee80211_sta *s){
 (void)s;assert(ar.conf_mutex.held);if(failure==INC)return -ENOSPC;v->num_stations++;return 0;
}
static void ath11k_mac_dec_num_stations(struct ath11k_vif *v,struct ieee80211_sta *s){
 (void)s;assert(ar.conf_mutex.held&&v->num_stations);v->num_stations--;
}
static int ath11k_set_group_keys(struct ath11k_vif *v){(void)v;return failure==GROUP?-EKEYREJECTED:0;}
static bool ath11k_debugfs_is_extd_tx_stats_enabled(struct ath11k *a){(void)a;return extended;}
static void completion(void){
 spin_lock_bh(&ab.base_lock);
 if(peer_present&&peer.sta==&sta){
  assert(sta.drv_priv.rx_stats&&(!extended||sta.drv_priv.tx_stats));
  sta.drv_priv.rx_stats->counter++;
  if(extended)sta.drv_priv.tx_stats->counter++;
 }
 spin_unlock_bh(&ab.base_lock);
}
static int ath11k_peer_create(struct ath11k *a,struct ath11k_vif *v,struct ieee80211_sta *s,struct peer_create_params *p){
 (void)a;assert(ar.conf_mutex.held&&!ab.base_lock.held&&p->vdev_id==v->vdev_id&&p->peer_addr==s->addr);
 assert(s->drv_priv.rx_stats&&(!extended||s->drv_priv.tx_stats));
 created++;if(failure==CREATE)return -EIO;
 peer_present=true;peer.sta=s;peer.list=1;ar.num_peers++;completion();return 0;
}
static struct ath11k_peer *ath11k_peer_find(struct ath11k *a,int id,const u8 *addr){
 (void)a;assert(ab.base_lock.held&&id==3&&addr==sta.addr);return peer_present?&peer:NULL;
}
static int ath11k_wmi_set_peer_param(struct ath11k *a,u8 *addr,unsigned id,unsigned p,unsigned val){
 (void)a;(void)addr;(void)id;(void)p;(void)val;completion();return failure==MESH?-EINVAL:0;
}
static int ath11k_dp_peer_setup(struct ath11k *a,unsigned id,u8 *addr){
 (void)a;(void)id;(void)addr;completion();if(failure==DP)return -ENODEV;dp_ready=true;return 0;
}
static void ath11k_dp_peer_cleanup(struct ath11k *a,unsigned id,u8 *addr){
 (void)a;(void)id;(void)addr;assert(!ab.base_lock.held&&dp_ready);completion();dp_ready=false;dp_cleaned++;
}
static int ath11k_mac_start_vdev_delay(void *hw,struct ieee80211_vif *v){
 (void)hw;completion();if(failure==START)return -EBUSY;v->priv->is_started=true;return 0;
}
static int ath11k_mac_stop_vdev_early(void *hw,struct ieee80211_vif *v){
 (void)hw;if(failure==STOP)return -EBUSY;v->priv->is_started=false;return 0;
}
static int ath11k_peer_delete(struct ath11k *a,unsigned id,u8 *addr){
 (void)a;(void)id;(void)addr;assert(ar.conf_mutex.held&&!ab.base_lock.held&&!dp_ready);deleted++;
 /* NSS/WMI deletion may sleep and dispatch a final stats completion. */
 completion();
 if(!delete_mode){peer_present=false;peer.sta=NULL;assert(ar.num_peers);ar.num_peers--;return 0;}
 if(delete_mode==2)peer.sta=&other;
 return -ETIMEDOUT;
}
static void ath11k_peer_rhash_delete(struct ath11k *a,struct ath11k_peer *p){
 assert(a==&ar&&p==&peer&&ab.base_lock.held&&ar.tbl_mtx_lock.held&&p->sta==&sta);unhashed++;
}
static void list_del(unsigned *node){
 assert(node==&peer.list&&*node&&ab.base_lock.held&&ar.tbl_mtx_lock.held);*node=0;
}
static void ath11k_peer_release(struct ath11k *a,struct ath11k_peer *p){
 assert(a==&ar&&p==&peer&&peer_present&&!p->sta&&!p->list&&!dp_ready);
 assert(ab.base_lock.held&&ar.tbl_mtx_lock.held&&live==1u+extended);
 released++;peer_present=false;
}
static void ewma_avg_rssi_init(unsigned *value){*value=0;}
enum {NL80211_STA_INFO_RX_DURATION,NL80211_STA_INFO_TX_DURATION,NL80211_STA_INFO_TX_BITRATE};
static u64 locked_bit(unsigned b){assert(ab.base_lock.held);return 1ULL<<b;}
#define BIT_ULL(b) locked_bit(b)
struct station_info {u64 rx_duration,tx_duration,filled;struct rate_info txrate;};
'''

CASES = r'''
static void prepare(enum stage stage,bool ext,unsigned mode){
 assert(!live&&!dp_ready&&!ab.base_lock.held&&!ar.conf_mutex.held);
 memset(&sta,0,sizeof(sta));sta.drv_priv.arvif=&av;sta.addr[5]=7;
 av.num_stations=0;av.reinstall_group_keys=true;av.is_started=false;av.vdev_type=0;
 ab.hw_params.vdev_start_delay=true;vif.mesh=true;failure=stage;extended=ext;delete_mode=mode;
 allocs=created=deleted=dp_cleaned=released=unhashed=0;ar.num_peers=0;peer_present=false;peer.sta=NULL;
}
int main(void){
 const int errors[]={0,-ENOSPC,-EKEYREJECTED,-ENOMEM,-ENOMEM,-EIO,-EINVAL,-ENODEV,-EBUSY};
 for(unsigned ext=0;ext<2;ext++)for(unsigned mode=0;mode<3;mode++)for(unsigned stage=INC;stage<=START;stage++){
  if(!ext&&stage==TX_ALLOC)continue;
  prepare(stage,ext,mode);ar.conf_mutex.held=true;
  int ret=ath11k_mac_station_add(&ar,&vif,&sta);
  assert(ret==errors[stage]&&!live&&!av.num_stations&&!sta.drv_priv.tx_stats&&!sta.drv_priv.rx_stats);
  assert(deleted==(stage>=MESH)&&dp_cleaned==(stage==START));
  assert(!peer_present||peer.sta==(mode==2?&other:NULL));
  completion();ar.conf_mutex.held=false;assert(!ab.base_lock.held&&!dp_ready);
 }
 for(unsigned stop=0;stop<2;stop++)for(unsigned ext=0;ext<2;ext++)for(unsigned mode=0;mode<3;mode++){
  prepare(OK,ext,mode);ar.conf_mutex.held=true;
  assert(!ath11k_mac_station_add(&ar,&vif,&sta)&&live==1+ext&&peer.sta==&sta&&dp_ready);
  failure=stop?STOP:OK;
  assert(remove_state()==(mode?-ETIMEDOUT:stop?-EBUSY:0));
  assert(!live&&!av.num_stations&&dp_cleaned==1&&deleted==1);
  assert(ar.num_peers==(mode==2)&&released==(mode==1)&&unhashed==(mode==1));
  assert(peer_present==(mode==2)&&(!peer_present||peer.sta==&other));
  assert(!ab.base_lock.held&&!ar.tbl_mtx_lock.held&&!dp_ready);
  assert(av.is_started==!!stop);completion();ar.conf_mutex.held=false;
 }
 for(unsigned legacy=0;legacy<3;legacy++){
  struct station_info s={0};sta.drv_priv.rx_duration=321;sta.drv_priv.tx_duration=456;
  sta.drv_priv.txrate=(struct rate_info){.legacy=legacy==1?540:0,.nss=legacy==2?2:0,.mcs=7,.bw=3,.he_gi=1,.he_dcm=1,.he_ru_alloc=4,.flags=8};
  tx_snapshot(&sta,&s);
  assert(s.rx_duration==321&&s.tx_duration==456&&!ab.base_lock.held);
  assert(s.filled==((1ULL<<NL80211_STA_INFO_RX_DURATION)|(1ULL<<NL80211_STA_INFO_TX_DURATION)|(legacy?1ULL<<NL80211_STA_INFO_TX_BITRATE:0)));
  if(legacy==1)assert(s.txrate.legacy==540&&s.txrate.flags==8);
  if(legacy==2)assert(!memcmp(&s.txrate,&sta.drv_priv.txrate,sizeof(s.txrate)));
 }
 puts("PASS actual STA state removal: allocation/publication rollback, completion during DELETE, failed DELETE residual unlink/count, foreign STA preservation, early STOP failure cleanup, stats lifetime, locked TX snapshot");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backports', type=Path, required=True)
    parser.add_argument('--draft', type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('sta_extract', Path(__file__).with_name('test-nss-control.py'))
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    relative = Path('drivers/net/wireless/ath/ath11k/mac.c')
    source = ((args.draft or args.backports) / relative).read_text()
    functions = ''.join(extract.function(source, name) for name in (
        'ath11k_mac_station_cleanup', 'ath11k_mac_station_add', 'ath11k_mac_station_remove'))
    state = extract.function(source, 'ath11k_mac_op_sta_state')
    begin = state.index('\n\t\tret = ath11k_mac_station_remove(')
    end = state.index('\n\t} else if (old_state == IEEE80211_STA_AUTH', begin)
    removal = ('static int remove_state_impl(struct ath11k *ar,struct ieee80211_vif *vif,struct ieee80211_sta *sta){\n'
               'struct ath11k_vif *arvif=ath11k_vif_to_arvif(vif);struct ath11k_peer *peer;int ret=0;\n'
               + state[begin:end] + '\nreturn ret;\n}\n'
               '#define remove_state() remove_state_impl(&ar,&vif,&sta)\n')
    stats = extract.function(source, 'ath11k_mac_op_sta_statistics')
    begin = stats.index('\n\tsinfo->rx_duration')
    lock = stats.rfind('\n\tspin_lock_bh(', 0, begin)
    begin = lock if lock >= 0 else begin
    end = stats.index('\n\tath11k_mac_put_chain_rssi')
    snapshot = ('static void tx_snapshot(struct ieee80211_sta *sta,struct station_info *sinfo){\n'
                'struct ath11k_sta *arsta=ath11k_sta_to_arsta(sta);struct ath11k *ar=arsta->arvif->ar;(void)ar;\n'
                + stats[begin:end] + '\n}\n')
    with tempfile.TemporaryDirectory(prefix='nss-sta-stats-') as directory:
        test, binary = Path(directory) / 'test.c', Path(directory) / 'test'
        test.write_text(SHIM + functions + removal + snapshot + CASES)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g',
                        '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                        str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=15,
                       env={**os.environ, 'UBSAN_OPTIONS': 'halt_on_error=1'})


if __name__ == '__main__':
    main()
