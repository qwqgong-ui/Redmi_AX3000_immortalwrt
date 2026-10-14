#!/usr/bin/env python3
"""Test the actual AP fanout guard and the native Linux MFC invalidation path."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('ecm_functions',
    Path(__file__).with_name('test-nss-ecm-multicast.py'))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <netinet/in.h>
typedef uint32_t __be32;
#define ECM_MULTICAST_ENABLE 1
#define ECM_MCAST_LINUX_SNOOPER_SUPPORT 1
#define DEBUG_ASSERT(condition, ...) assert(condition)
#define READ_ONCE(x) (x)
enum nl80211_iftype { NL80211_IFTYPE_UNSPECIFIED, NL80211_IFTYPE_ADHOC,
 NL80211_IFTYPE_STATION, NL80211_IFTYPE_AP, NL80211_IFTYPE_AP_VLAN };
struct wireless_dev { void *wiphy; enum nl80211_iftype iftype; };
_Static_assert(offsetof(struct wireless_dev, iftype) == sizeof(void *), "wireless_dev public prefix");
struct net_device { int ifindex, refs; struct wireless_dev *ieee80211_ptr; };
struct ecm_db_iface_instance { int ifindex; };
struct ecm_db_connection_instance { int unused; };
struct ecm_front_end_connection_instance { struct ecm_db_connection_instance *ci; };
static int init_net, readers, gets, put_count, array_refs, invalidations, snapshot_available;
static struct wireless_dev wireless[3];
static struct net_device devices[6];
static struct ecm_db_iface_instance iface[6];
static struct ecm_db_iface_instance *matrix[ECM_DB_MULTICAST_IF_MAX][ECM_DB_IFACE_HEIRARCHY_MAX];
static int32_t first[ECM_DB_MULTICAST_IF_MAX];
static struct ecm_db_connection_instance ci;
static void rcu_read_lock(void) { readers++; }
static void rcu_read_unlock(void) { assert(readers>0); readers--; }
static struct net_device *dev_get_by_index(int *net, int index) {
 assert(net==&init_net && readers>0);
 for(int i=0;i<6;i++) if(devices[i].ifindex==index) { gets++; devices[i].refs++; return &devices[i]; }
 return NULL;
}
static void dev_put(struct net_device *dev) { assert(dev->refs>1); dev->refs--; put_count++; }
static int ecm_db_iface_interface_identifier_get(struct ecm_db_iface_instance *entry) { return entry->ifindex; }
static int ecm_db_multicast_connection_to_interfaces_get_and_ref_all(struct ecm_db_connection_instance *conn,
 struct ecm_db_iface_instance **all, int32_t **starts) {
 assert(conn==&ci && !array_refs);
 if(!snapshot_available) return 0;
	array_refs++; *all=(struct ecm_db_iface_instance *)matrix; *starts=first;
	return snapshot_available==2 ? 0 : 1;
}
static void ecm_db_multicast_connection_to_interfaces_deref_all(struct ecm_db_iface_instance *all, int32_t *starts) {
 assert(array_refs==1 && all==(struct ecm_db_iface_instance *)matrix && starts==first);
 array_refs--;
}
static void ecm_interface_multicast_invalidate(void) { invalidations++; }
'''

TEST = r'''
static void reset(void) {
 memset(matrix,0,sizeof(matrix)); memset(wireless,0,sizeof(wireless));
 memset(devices,0,sizeof(devices)); memset(iface,0,sizeof(iface));
 readers=gets=put_count=array_refs=invalidations=0; snapshot_available=1;
 for(int i=0;i<ECM_DB_MULTICAST_IF_MAX;i++) first[i]=ECM_DB_IFACE_HEIRARCHY_MAX;
 for(int i=0;i<6;i++) { devices[i].ifindex=10+i; devices[i].refs=1; iface[i].ifindex=10+i; }
 wireless[0].iftype=NL80211_IFTYPE_AP;
 wireless[1].iftype=NL80211_IFTYPE_AP_VLAN;
 wireless[2].iftype=NL80211_IFTYPE_STATION;
 devices[1].ieee80211_ptr=&wireless[0];
 devices[2].ieee80211_ptr=&wireless[1];
 devices[3].ieee80211_ptr=&wireless[2];
}
static void balanced(void) {
 assert(!readers && !array_refs && gets==put_count);
 for(int i=0;i<6;i++) assert(devices[i].refs==1);
}
static bool check(void) {
 struct ecm_front_end_connection_instance fe={.ci=&ci};
 struct ecm_db_iface_instance *before[ECM_DB_MULTICAST_IF_MAX][ECM_DB_IFACE_HEIRARCHY_MAX];
 int32_t starts[ECM_DB_MULTICAST_IF_MAX];
 memcpy(before,matrix,sizeof(before)); memcpy(starts,first,sizeof(starts));
 bool result=ecm_nss_common_multicast_outputs_allowed(&fe);
 assert(!memcmp(before,matrix,sizeof(matrix)) && !memcmp(starts,first,sizeof(first)));
 balanced(); return result;
}
int main(void) {
 const int last=ECM_DB_IFACE_HEIRARCHY_MAX-1;
 reset(); assert(!check());
 first[0]=last; matrix[0][last]=&iface[0]; assert(check());
 first[1]=last-1; matrix[1][last-1]=&iface[3]; matrix[1][last]=&iface[4]; assert(check());
 for(int type=1;type<=2;type++) for(int row=0;row<ECM_DB_MULTICAST_IF_MAX;row++)
 for(int layer=0;layer<ECM_DB_IFACE_HEIRARCHY_MAX;layer++) {
  reset();
  /* Wired output first, then an AP at any inner or outer layer: reject ALL. */
  first[0]=last; matrix[0][last]=&iface[0];
  first[row]=layer;
  for(int i=layer;i<ECM_DB_IFACE_HEIRARCHY_MAX;i++) matrix[row][i]=&iface[0];
  matrix[row][layer]=&iface[type]; assert(!check());
 }
 reset(); first[3]=last; matrix[3][last]=&iface[5]; iface[5].ifindex=999;
 assert(!check());
 reset(); first[0]=last-2; matrix[0][last-2]=&iface[0]; matrix[0][last]=&iface[0];
 assert(!check()); /* Missing intermediate hierarchy entry. */
 reset(); first[2]=-1; assert(!check());
 reset(); first[2]=ECM_DB_IFACE_HEIRARCHY_MAX+1; assert(!check());
	reset(); snapshot_available=0; assert(!check());
	reset(); snapshot_available=2; assert(!check()); /* Allocated zero-entry snapshot. */
 reset(); first[0]=last; matrix[0][last]=&iface[3]; assert(check());
 wireless[2].iftype=NL80211_IFTYPE_AP; assert(!check());
 reset(); uint32_t out[2]={12,13}; struct in6_addr group={}, source={};
 ecm_mfc_update_event_callback(1,2,2,out,3);
 ecm_nss_multicast_ipv6_mfc_update_event_callback(&group,&source,2,out,3);
 assert(invalidations==2 && out[0]==12 && out[1]==13); balanced();
 puts("PASS actual AP/AP_VLAN whole fanout guard, all hierarchy positions, stale device, refs and native MFC invalidation");
 return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ecm', type=Path, required=True)
    args = parser.parse_args()
    root = args.ecm / 'frontends/nss'
    db_types = (args.ecm / 'ecm_db/ecm_db_types.h').read_text()
    constants = '\n'.join(re.search(r'(?m)^#define ' + name + r' \d+', db_types)[0]
        for name in ('ECM_DB_MULTICAST_IF_MAX', 'ECM_DB_IFACE_HEIRARCHY_MAX'))
    common = (root / 'ecm_nss_common.h').read_text()
    body = '\n'.join(extract.function(db_types, name) for name in (
        'ecm_db_multicast_if_first_get_at_index', 'ecm_db_multicast_if_heirarchy_get'))
    body += '\n' + '\n'.join(extract.function(common, name) for name in (
        'ecm_nss_common_multicast_fanout_allowed',
        'ecm_nss_common_multicast_outputs_allowed'))
    for version, callback in ((4, 'ecm_mfc_update_event_callback'),
                              (6, 'ecm_nss_multicast_ipv6_mfc_update_event_callback')):
        source = (root / f'ecm_nss_multicast_ipv{version}.c').read_text()
        create = extract.function(source, f'ecm_nss_multicast_ipv{version}_connection_accelerate')
        first_guard = create.index('ecm_nss_common_multicast_fanout_allowed(')
        assert create.index('ecm_db_multicast_connection_to_interfaces_get_and_ref_all(') < first_guard
        assert first_guard < create.index('for (vif = 0;')
        final_guard = create.index('ecm_nss_common_multicast_outputs_allowed(')
        assert final_guard < create.index(f'nss_ipv{version}_tx(')
        assert 'ecm_db_multicast_connection_to_interfaces_deref_all(' in create[first_guard:]
        body += '\n' + extract.function(source, callback)
    with tempfile.TemporaryDirectory(prefix='nss-ecm-ap-') as temporary:
        source = Path(temporary) / 'fanout.c'
        binary = source.with_suffix('')
        source.write_text(constants + '\n' + SHIM + body + TEST)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1',
            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
            '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
            str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
