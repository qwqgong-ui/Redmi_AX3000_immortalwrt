#!/usr/bin/env python3
"""Exercise the prepared kernel's real IPv4/IPv6 multicast offload API bodies."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    for match in re.finditer(r'\b' + re.escape(name) + r'\s*\(', source):
        brace = source.find('{', match.end())
        semi = source.find(';', match.end())
        if brace < 0 or 0 <= semi < brace:
            continue
        start = source.rfind('\n', 0, match.start()) + 1
        depth = 0
        for index in range(brace, len(source)):
            depth += (source[index] == '{') - (source[index] == '}')
            if not depth:
                return source[start:index + 1]
    raise ValueError('Missing actual function: ' + name)


SHIM = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
typedef uint32_t u32, __be32;
typedef uint64_t u64;
typedef uint8_t u8;
typedef _Atomic long atomic_long_t;
typedef _Atomic long atomic64_t;
struct in6_addr { u8 bytes[16]; };
#define __rcu
#define MAXVIFS 32
#define MAXMIFS 32
#define RT_TABLE_DEFAULT 253
#define RT6_TABLE_DFLT 253
#define MFC_DELETED 4
#define IPMR_MFC_EVENT_UPDATE 1
#define IPMR_MFC_EVENT_DELETE 2
#define IP6MR_MFC_EVENT_UPDATE 1
#define IP6MR_MFC_EVENT_DELETE 2
#define BIT(i) (1U << (i))
#define EXPORT_SYMBOL(x)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x) = (v))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define atomic_long_add(v,p) atomic_fetch_add((p),(long)(v))
#define atomic64_inc_return(p) (atomic_fetch_add((p),1) + 1)
struct net { int id; };
static struct net init_net, other_net = {1};
static bool net_eq(struct net *a, struct net *b) { return a == b; }
struct net_device { int ifindex; };
struct rhlist_head { struct rhlist_head *next; };
struct mr_mfc;
struct list_head { struct mr_mfc *first, *next; };
struct vif_device {
    struct net_device *dev;
    atomic_long_t pkt_in, pkt_out, bytes_in, bytes_out;
};
struct mr_mfc {
    struct rhlist_head mnode;
    unsigned short mfc_parent;
    int mfc_flags;
    u64 offload_cookie;
    union { struct {
        unsigned char ttls[32];
        atomic_long_t pkt, bytes;
        unsigned long lastuse;
    } res; } mfc_un;
    struct list_head list;
};
struct @CACHE@ { struct mr_mfc _c; };
struct mr_table {
    struct net *net;
    u32 id;
    struct vif_device vif_table[32];
    struct list_head mfc_cache_list;
};
#define list_for_each_entry(c,head,member) \
    for ((c)=(head)->first; (c); (c)=(c)->member.next)
#define read_pnet(p) (*(p))
#define ASSERT_RTNL() ((void)0)
static _Thread_local int lock_depth, rcu_depth;
static pthread_mutex_t mrt_lock = PTHREAD_MUTEX_INITIALIZER;
static void spin_lock_bh(pthread_mutex_t *p) {
    assert(!lock_depth); pthread_mutex_lock(p); lock_depth++;
}
static void spin_unlock_bh(pthread_mutex_t *p) {
    assert(lock_depth == 1); lock_depth--; pthread_mutex_unlock(p);
}
#define lockdep_assert_held(p) assert(lock_depth == 1)
static pthread_mutex_t rcu_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t rcu_wait = PTHREAD_COND_INITIALIZER;
static int readers;
static atomic_bool sync_started;
static void rcu_read_lock(void) {
    pthread_mutex_lock(&rcu_lock); readers++; rcu_depth++;
    pthread_mutex_unlock(&rcu_lock);
}
static void rcu_read_unlock(void) {
    pthread_mutex_lock(&rcu_lock); readers--; rcu_depth--;
    pthread_cond_broadcast(&rcu_wait); pthread_mutex_unlock(&rcu_lock);
}
static void synchronize_rcu(void) {
    atomic_store(&sync_started, true);
    pthread_mutex_lock(&rcu_lock);
    while (readers) pthread_cond_wait(&rcu_wait, &rcu_lock);
    pthread_mutex_unlock(&rcu_lock);
}
#define rcu_dereference(p) __atomic_load_n(&(p), __ATOMIC_ACQUIRE)
#define rcu_access_pointer(p) __atomic_load_n(&(p), __ATOMIC_ACQUIRE)
#define rcu_assign_pointer(p,v) __atomic_store_n(&(p),(v),__ATOMIC_RELEASE)
#define RCU_INIT_POINTER(p,v) rcu_assign_pointer(p,v)
static pthread_mutex_t @P@_offload_mutex = PTHREAD_MUTEX_INITIALIZER;
#define mutex_lock(p) pthread_mutex_lock(p)
#define mutex_unlock(p) pthread_mutex_unlock(p)
typedef void (*@P@_mfc_event_offload_callback_t)(@CBARGS@, u32, u32[], u8);
static @P@_mfc_event_offload_callback_t @P@_offload_cb;
static atomic64_t @P@_offload_serial = 100;
enum fib_event_type { FIB_EVENT_ENTRY_ADD, FIB_EVENT_ENTRY_REPLACE, FIB_EVENT_ENTRY_DEL };
static unsigned long jiffies = 12345;
static struct mr_table table;
static struct @CACHE@ entries[2];
static struct net_device devices[32];
static bool has_table = true, has_entry = true;
@ADDRDECL@
static struct mr_table *__@P@_get_table(struct net *net, u32 id) {
    assert(rcu_depth && lock_depth);
    return has_table && net == &init_net && id == 253 ? &table : NULL;
}
static struct @CACHE@ *@P@_cache_find(struct mr_table *mrt, @ADDRARGS@) {
    assert(rcu_depth && lock_depth && mrt == &table);
    assert(@ADDREQ@);
    return has_entry ? &entries[0] : NULL;
}
static struct net_device *vif_dev_read(const struct vif_device *vif) {
    assert(rcu_depth && lock_depth); return vif->dev;
}
'''


TEST = r'''
static void fixture(void) {
    memset(&table, 0, sizeof(table)); memset(entries, 0, sizeof(entries));
    table.net = &init_net; table.id = 253;
    table.mfc_cache_list.first = &entries[0]._c;
    entries[0]._c.offload_cookie = 42;
    entries[1]._c.offload_cookie = 43;
    @ADDRSET@
    for (int i=0; i<32; i++) {
        devices[i].ifindex = 1000+i; table.vif_table[i].dev = &devices[i];
    }
    entries[0]._c.mfc_un.res.ttls[2] = 1;
    entries[0]._c.mfc_un.res.ttls[31] = 1;
    has_table = has_entry = true;
}
static int find(struct net *net, u32 capacity, u32 *dst, u64 *cookie) {
    return @P@_find_mfc_entry(net, @ADDRCALL@, capacity, dst, cookie);
}
static int stats(u64 cookie) {
    return @P@_mfc_stats_update(&init_net, @ADDRCALL@, cookie, 1, 64, 1, 64);
}
static int event_count;
static u8 events[8];
static void record_cb(@CBARGSNAME@, u32 count, u32 indices[], u8 op) {
    assert(rcu_depth && !lock_depth); assert(@CBEQ@);
    assert(event_count < 8); events[event_count++] = op;
    if (op == 1) assert(count == 2 && indices[0] == 1002 && indices[1] == 1031);
    else assert(count == 0 && indices == NULL);
}
static void notify(enum fib_event_type event) {
    @P@_offload_mfc_notify(&init_net, 253, &entries[0], event);
}
static void *stat_thread(void *arg) {
    (void)arg; for (int i=0; i<20000; i++) assert(stats(42) == 0); return NULL;
}
static void *host_thread(void *arg) {
    (void)arg;
    for (int i=0; i<20000; i++) {
        atomic_long_add(1, &table.vif_table[0].pkt_in);
        atomic_long_add(1, &table.vif_table[2].pkt_out);
    }
    return NULL;
}
static pthread_mutex_t callback_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t callback_wait = PTHREAD_COND_INITIALIZER;
static bool callback_entered, callback_release;
static atomic_bool unregister_done;
static void blocking_cb(@CBARGSNAME@, u32 count, u32 indices[], u8 op) {
    (void)group; (void)origin; (void)count; (void)indices; (void)op;
    assert(rcu_depth && !lock_depth);
    pthread_mutex_lock(&callback_mutex); callback_entered = true;
    pthread_cond_broadcast(&callback_wait);
    while (!callback_release) pthread_cond_wait(&callback_wait, &callback_mutex);
    pthread_mutex_unlock(&callback_mutex);
}
static void *notify_thread(void *arg) { (void)arg; notify(FIB_EVENT_ENTRY_ADD); return NULL; }
static void *unregister_thread(void *arg) {
    (void)arg; @P@_unregister_mfc_event_offload_callback();
    atomic_store(&unregister_done, true); return NULL;
}
int main(void) {
    u32 dst[32]; u64 cookie; pthread_t a, b;
    fixture(); cookie=0; assert(find(&init_net,32,dst,&cookie)==2);
    assert(dst[0]==1002 && dst[1]==1031 && cookie==42);
    for (int i=0;i<32;i++) entries[0]._c.mfc_un.res.ttls[i]=1;
    assert(find(&init_net,32,dst,&cookie)==32);
    for (int i=0;i<32;i++) assert(dst[i]==1000+(u32)i);
    memset(dst,0xa5,sizeof(dst)); cookie=777;
    assert(find(&init_net,16,dst,&cookie)==-EINVAL && cookie==777);
    for (int i=0;i<32;i++) assert(dst[i]==0xa5a5a5a5U);
    fixture(); table.vif_table[31].dev=NULL;
    assert(find(&init_net,32,dst,&cookie)==-ENODEV && cookie==777);
    assert(stats(42)==-ENODEV && atomic_load(&table.vif_table[0].pkt_in)==0);
    fixture(); has_table=false; assert(find(&init_net,32,dst,&cookie)==-ENOENT);
    fixture(); has_entry=false; assert(find(&init_net,32,dst,&cookie)==-ENOENT);
    fixture(); assert(find(&other_net,32,dst,&cookie)==-EOPNOTSUPP);
    entries[0]._c.mfc_un.res.ttls[2]=8;
    assert(find(&init_net,32,dst,&cookie)==-EOPNOTSUPP);
    fixture(); entries[0]._c.mnode.next=&entries[1]._c.mnode;
    assert(find(&init_net,32,dst,&cookie)==-EOPNOTSUPP);
    assert(stats(42)==-EOPNOTSUPP);
    fixture(); entries[0]._c.mfc_flags=MFC_DELETED;
    assert(find(&init_net,32,dst,&cookie)==-ENOENT && stats(42)==-ENOENT);
    fixture(); assert(stats(41)==-ESTALE && stats(0)==-ESTALE);
    assert(stats(42)==0 && atomic_load(&table.vif_table[0].pkt_in)==1);
    assert(atomic_load(&entries[0]._c.mfc_un.res.pkt)==1);
    assert(atomic_load(&table.vif_table[31].bytes_out)==64);
    assert(entries[0]._c.mfc_un.res.lastuse==jiffies);
    rcu_read_lock(); spin_lock_bh(&mrt_lock);
    @P@_offload_vif_invalidate(&table,31);
    spin_unlock_bh(&mrt_lock); rcu_read_unlock();
    assert(stats(42)==-ESTALE);
    assert(find(&init_net,32,dst,&cookie)==2 && cookie!=42);
    assert(stats(cookie)==0);
    fixture(); pthread_create(&a,NULL,stat_thread,NULL);
    pthread_create(&b,NULL,host_thread,NULL); pthread_join(a,NULL); pthread_join(b,NULL);
    assert(atomic_load(&table.vif_table[0].pkt_in)==40000);
    assert(atomic_load(&table.vif_table[2].pkt_out)==40000);
    assert(atomic_load(&entries[0]._c.mfc_un.res.pkt)==20000);
    fixture(); assert(!@P@_register_mfc_event_offload_callback(NULL));
    assert(@P@_register_mfc_event_offload_callback(record_cb));
    assert(!@P@_register_mfc_event_offload_callback(record_cb));
    notify(FIB_EVENT_ENTRY_ADD); assert(event_count==1 && events[0]==1);
    event_count=0; notify(FIB_EVENT_ENTRY_REPLACE);
    assert(event_count==2 && events[0]==2 && events[1]==1);
    event_count=0; @P@_offload_vif_notify(&table,2);
    assert(event_count==2 && events[0]==2 && events[1]==1);
    event_count=0; table.vif_table[31].dev=NULL;
    notify(FIB_EVENT_ENTRY_REPLACE); assert(event_count==1 && events[0]==2);
    fixture(); event_count=0; entries[0]._c.mnode.next=&entries[1]._c.mnode;
    notify(FIB_EVENT_ENTRY_ADD); assert(event_count==1 && events[0]==2);
    fixture(); event_count=0; notify(FIB_EVENT_ENTRY_DEL);
    assert(event_count==1 && events[0]==2);
    event_count=0; @P@_offload_mfc_notify(&other_net,253,&entries[0],FIB_EVENT_ENTRY_ADD);
    @P@_offload_mfc_notify(&init_net,99,&entries[0],FIB_EVENT_ENTRY_ADD);
    assert(event_count==0);
    @P@_unregister_mfc_event_offload_callback();
    assert(@P@_register_mfc_event_offload_callback(blocking_cb));
    atomic_store(&sync_started,false);
    pthread_create(&a,NULL,notify_thread,NULL);
    pthread_mutex_lock(&callback_mutex);
    while (!callback_entered) pthread_cond_wait(&callback_wait,&callback_mutex);
    pthread_mutex_unlock(&callback_mutex);
    pthread_create(&b,NULL,unregister_thread,NULL);
    while (!atomic_load(&sync_started)) usleep(100);
    assert(!atomic_load(&unregister_done));
    pthread_mutex_lock(&callback_mutex); callback_release=true;
    pthread_cond_broadcast(&callback_wait); pthread_mutex_unlock(&callback_mutex);
    pthread_join(a,NULL); pthread_join(b,NULL);
    assert(atomic_load(&unregister_done) && readers==0);
    puts("@P@: bounds, unique route, TTL, cookie, atomic stats, events and RCU unregister passed");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    args = parser.parse_args()
    functions = ('offload_cache_find', 'offload_ifindexes', 'find_mfc_entry',
                 'mfc_stats_update', 'register_mfc_event_offload_callback',
                 'unregister_mfc_event_offload_callback', 'offload_mfc_notify',
                 'offload_vif_notify', 'offload_vif_invalidate')
    for ipv6 in (False, True):
        prefix = 'ip6mr' if ipv6 else 'ipmr'
        source = (args.kernel / ('net/ipv6/ip6mr.c' if ipv6 else 'net/ipv4/ipmr.c')).read_text()
        bodies = '\n\n'.join(function(source, prefix + '_' + name) for name in functions)
        if ipv6:
            replacements = dict(CACHE='mfc6_cache', P=prefix,
                CBARGS='struct in6_addr *, struct in6_addr *',
                CBARGSNAME='struct in6_addr *group, struct in6_addr *origin',
                ADDRDECL='static struct in6_addr test_origin={{1}}, test_group={{0xff,1}};',
                ADDRARGS='const struct in6_addr *origin, const struct in6_addr *group',
                ADDREQ='!memcmp(origin,&test_origin,16) && !memcmp(group,&test_group,16)',
                ADDRCALL='&test_origin, &test_group',
                ADDRSET='entries[0].mf6c_origin=test_origin; entries[0].mf6c_mcastgrp=test_group;',
                CBEQ='!memcmp(origin,&test_origin,16) && !memcmp(group,&test_group,16)')
            cache_address_fields = 'struct in6_addr mf6c_origin, mf6c_mcastgrp;'
        else:
            replacements = dict(CACHE='mfc_cache', P=prefix,
                CBARGS='__be32, __be32', CBARGSNAME='__be32 group, __be32 origin',
                ADDRDECL='static __be32 test_origin=0x0100000a, test_group=0x0100ffef;',
                ADDRARGS='__be32 origin, __be32 group',
                ADDREQ='origin==test_origin && group==test_group',
                ADDRCALL='test_origin, test_group',
                ADDRSET='entries[0].mfc_origin=test_origin; entries[0].mfc_mcastgrp=test_group;',
                CBEQ='origin==test_origin && group==test_group')
            cache_address_fields = '__be32 mfc_origin, mfc_mcastgrp;'
        shim = SHIM.replace('struct @CACHE@ { struct mr_mfc _c; };',
                            'struct @CACHE@ { struct mr_mfc _c; ' + cache_address_fields + ' };')
        generated = shim + '\n' + bodies + '\n' + TEST
        for key, value in replacements.items():
            generated = generated.replace('@' + key + '@', value)
        with tempfile.TemporaryDirectory(prefix='nss-mcast-') as directory:
            path = Path(directory) / (prefix + '.c')
            path.write_text(generated)
            binary = path.with_suffix('')
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-pthread', '-Wall', '-Wextra', '-Werror', str(path),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
