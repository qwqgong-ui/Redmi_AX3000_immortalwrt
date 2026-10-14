#!/usr/bin/env python3
"""Exercise the actual ECM denied-interface parser, locks and flow retirement."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile

SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/types.h>
#define IFNAMSIZ 16
#define GFP_KERNEL 0
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define DEBUG_TRACE(...) ((void)0)
#define ECM_INTERFACE_ACCEL_DENIED_HASH_BITS 5
#define ECM_INTERFACE_ACCEL_DENIED_DEVICE_HTABLE_SIZE 32
#define ECM_DB_OBJ_DIR_MAX 4
#define ECM_DB_OBJ_DIR_TO 1
#define ECM_MULTICAST_ENABLE 1
#define ECM_DB_MULTICAST_IF_MAX 2
#define ECM_DB_IFACE_HEIRARCHY_MAX 4
typedef struct { int value; } atomic_t;
static int atomic_read(atomic_t *v) { return v->value; }
static void atomic_inc(atomic_t *v) { v->value++; }
static void atomic_dec(atomic_t *v) { v->value--; }
static void atomic_set(atomic_t *v,int n) { v->value=n; }
struct hlist_node { struct hlist_node *next, **pprev; };
struct hlist_head { struct hlist_node *first; };
#define DEFINE_HASHTABLE(name,bits) struct hlist_head name[1<<(bits)]
#define DEFINE_SPINLOCK(name) pthread_mutex_t name=PTHREAD_MUTEX_INITIALIZER
#define DEFINE_MUTEX(name) pthread_mutex_t name=PTHREAD_MUTEX_INITIALIZER
#define spin_lock_bh(p) assert(!pthread_mutex_lock(p))
#define spin_unlock_bh(p) assert(!pthread_mutex_unlock(p))
#define mutex_lock(p) assert(!pthread_mutex_lock(p))
#define mutex_unlock(p) assert(!pthread_mutex_unlock(p))
#define hlist_entry(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define hlist_for_each_safe(p,n,h) for((p)=(h)->first;(p)&&((n)=(p)->next,1);(p)=(n))
#define hlist_for_each_entry_safe(p,n,h,m) \
 for(struct hlist_node *_q=(h)->first;_q&&((p)=hlist_entry(_q,__typeof__(*(p)),m),(n)=_q->next,1);_q=(n))
#define hash_for_each(t,b,p,m) \
 for((b)=0;(b)<ARRAY_SIZE(t);(b)++) \
 for(struct hlist_node *_q=(t)[b].first;_q&&((p)=hlist_entry(_q,__typeof__(*(p)),m),1);_q=_q->next)
#define hash_for_each_safe(t,b,n,p,m) \
 for((b)=0;(b)<ARRAY_SIZE(t);(b)++) hlist_for_each_entry_safe(p,n,&(t)[b],m)
static void hlist_add_head(struct hlist_node *n,struct hlist_head *h) {
 n->next=h->first; if(n->next)n->next->pprev=&n->next;h->first=n;n->pprev=&h->first;
}
static void hlist_del(struct hlist_node *n) { *n->pprev=n->next;if(n->next)n->next->pprev=n->pprev; }
static unsigned ecm_db_jhash_rnd=123;
static uint32_t jhash(const void *s,size_t n,unsigned seed) {
 const unsigned char *p=s;while(n--)seed=seed*33+*p++;return seed;
}
static _Atomic long allocations,frees;
static void *kzalloc(size_t n,int g) { void *p=calloc(1,n);if(p)allocations++;return p; }
static void kfree(void *p) { if(p){frees++;free(p);} }
#define scnprintf snprintf
static ssize_t memory_read_from_buffer(void *dst,size_t len,loff_t *pos,const void *src,size_t n) {
 if(*pos<0)return -EINVAL;if((size_t)*pos>=n)return 0;
 n-=*pos;if(n>len)n=len;memcpy(dst,(const char *)src+*pos,n);*pos+=n;return n;
}
static char *strim(char *s) {
 while(isspace((unsigned char)*s))s++;
 char *end=s+strlen(s);while(end>s&&isspace((unsigned char)end[-1]))*--end=0;return s;
}
static bool dev_valid_name(const char *s) {
 return *s&&strcmp(s,".")&&strcmp(s,"..")&&!strpbrk(s," /:\t\n");
}
static void strscpy(char *d,const char *s,size_t n) { assert(strlen(s)<n);strcpy(d,s); }
struct net_device { int ifindex; const char *name; };
static int init_net;
static struct net_device sta={.ifindex=10,.name="phy1-sta0"},lan={.ifindex=20,.name="lan1"};
static struct net_device *dev_get_by_name(void *net,const char *name) {
 return !strcmp(name,"phy1-sta0")?&sta:NULL;
}
static struct net_device *dev_get_by_index(void *net,int index) { return index==10?&sta:index==20?&lan:NULL; }
static void dev_put(struct net_device *dev) { assert(dev==&sta||dev==&lan); }
typedef int ip_addr_t[1];
struct ecm_db_iface_instance { int identifier; };
struct ecm_db_connection_instance {
 struct ecm_db_connection_instance *next;
 struct ecm_db_iface_instance *interfaces[4];
 unsigned defunct, refs;
 bool multicast,allocation_fail;
 struct ecm_db_iface_instance *fanout;
};
static struct ecm_db_iface_instance wan_iface={10},lan_iface={20};
static struct ecm_db_connection_instance lan_flow,wan_flow,mc_flow;
static struct ecm_db_connection_instance *ecm_db_connections_get_and_ref_first(void) {
 wan_flow.refs++;return &wan_flow;
}
static struct ecm_db_connection_instance *ecm_db_connection_get_and_ref_next(struct ecm_db_connection_instance *ci) {
 if(ci->next)ci->next->refs++;return ci->next;
}
static int ecm_db_connection_interfaces_get_and_ref(struct ecm_db_connection_instance *ci,struct ecm_db_iface_instance **out,int dir) {
 if(!ci->interfaces[dir])return 4;out[3]=ci->interfaces[dir];return 3;
}
static int ecm_db_iface_interface_identifier_get(struct ecm_db_iface_instance *ii) { return ii->identifier; }
static void ecm_db_connection_interfaces_deref(struct ecm_db_iface_instance **i,int f) {}
static void ecm_db_connection_make_defunct(struct ecm_db_connection_instance *ci) { ci->defunct++; }
static void ecm_db_connection_deref(struct ecm_db_connection_instance *ci) { assert(ci->refs);ci->refs--; }
static void ecm_db_connection_address_get(struct ecm_db_connection_instance *ci,int dir,int *addr) { addr[0]=ci->multicast; }
static bool ecm_ip_addr_is_multicast(int *addr) { return addr[0]; }
static int ecm_db_multicast_connection_to_interfaces_get_and_ref_all(struct ecm_db_connection_instance *ci,struct ecm_db_iface_instance **out,int32_t **first) {
 if(ci->allocation_fail)return 0;
 struct ecm_db_iface_instance **rows=kzalloc(2*4*sizeof(*rows),0);
 *first=kzalloc(2*sizeof(**first),0);*out=(struct ecm_db_iface_instance *)rows;
 (*first)[0]=3;(*first)[1]=4;rows[3]=ci->fanout;return 1;
}
static int32_t *ecm_db_multicast_if_first_get_at_index(int32_t *first,int row) { return &first[row]; }
static void *ecm_db_multicast_if_heirarchy_get(struct ecm_db_iface_instance *out,int row) {
 return ((struct ecm_db_iface_instance **)out)+row*4;
}
static void ecm_db_multicast_connection_to_interfaces_deref_all(struct ecm_db_iface_instance *out,int32_t *first) { kfree(out);kfree(first); }
'''

TEST = r'''
static int update(const char *request) {
 size_t n=strlen(request);loff_t pos=0;
 return ecm_interface_accel_denied_handler(1,(void *)request,&n,&pos);
}
static void *reader(void *unused) {
 for(int i=0;i<10000;i++) {
  char snapshot[514];size_t n=sizeof(snapshot);loff_t p=0;
  (void)ecm_interface_lookup_in_denied_list("race0");
  assert(!ecm_interface_accel_denied_read(snapshot,&n,&p));assert(n<=sizeof(snapshot));
 }
 return NULL;
}
static void *writer(void *unused) {
 for(int i=0;i<5000;i++){assert(!update("add race0 race0"));assert(!update("del race0"));}
 return NULL;
}
int main(void) {
 char snapshot[514],huge[257];size_t n;loff_t p;
 wan_flow.next=&lan_flow;wan_flow.interfaces[2]=&wan_iface;
 lan_flow.interfaces[0]=&lan_iface;
 lan_flow.next=&mc_flow;mc_flow.multicast=true;mc_flow.fanout=&wan_iface;
 assert(!update("add phy1-sta0"));
 assert(ecm_interface_lookup_in_denied_list("phy1-sta0"));
 assert(wan_flow.defunct==1 && !lan_flow.defunct && !wan_flow.refs && !lan_flow.refs);
 assert(mc_flow.defunct==1 && !mc_flow.refs);
 assert(!ecm_interface_connection_accel_allowed(&wan_flow));
 assert(ecm_interface_connection_accel_allowed(&lan_flow));
 assert(!ecm_interface_connection_accel_allowed(&mc_flow));
 mc_flow.fanout=&lan_iface;assert(ecm_interface_connection_accel_allowed(&mc_flow));
 mc_flow.allocation_fail=true;assert(!ecm_interface_connection_accel_allowed(&mc_flow));
 mc_flow.allocation_fail=false;
 assert(!update("add phy1-sta0"));assert(atomic_read(&ecm_interface_accel_denied_list_count)==1);
 assert(!update("add ghost0"));assert(!update("del ghost0"));
 assert(!ecm_interface_lookup_in_denied_list("ghost0"));
 assert(update("")==-EINVAL);assert(update("add")==-EINVAL);assert(update("bad phy1-sta0")==-EINVAL);
 assert(update("add fine0 0123456789abcdef")==-EINVAL);
 assert(!ecm_interface_lookup_in_denied_list("fine0"));
 assert(update("add eth/0")==-EINVAL);assert(update("add ..")==-EINVAL);
 memset(huge,'x',256);n=256;p=0;
 assert(ecm_interface_accel_denied_handler(1,huge,&n,&p)==-EINVAL);
 n=8;p=0;assert(ecm_interface_accel_denied_handler(1,"add\0eth0",&n,&p)==-EINVAL);
 assert(!update("del phy1-sta0"));
 for(int i=0;i<32;i++){char cmd[32];snprintf(cmd,sizeof(cmd),"add test%d",i);assert(!update(cmd));}
 assert(update("add overflow0")==-ENOSPC);
 n=sizeof(snapshot);p=0;assert(!ecm_interface_accel_denied_read(snapshot,&n,&p));assert(n<=513);
 ecm_interface_accel_denied_clear();assert(!atomic_read(&ecm_interface_accel_denied_list_count));
 pthread_t threads[4];
 for(int i=0;i<4;i++)assert(!pthread_create(&threads[i],NULL,i<2?reader:writer,NULL));
 for(int i=0;i<4;i++)assert(!pthread_join(threads[i],NULL));
 ecm_interface_accel_denied_clear();assert(allocations==frees);
 puts("PASS actual ECM denied list: parser bounds, atomic request validation, duplicate/capacity, absent-device deletion, targeted NAT hierarchy retirement, concurrent read/update and unload cleanup");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ecm', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('extract_nss', Path(__file__).with_name('test-nss-control.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source = (args.ecm / 'ecm_interface.c').read_text()
    declarations = re.search(r'static DEFINE_HASHTABLE\(ecm_interface_accel_denied_list,.*?\n};', source, re.S).group()
    functions = ''.join(helper.function(source, name) for name in (
        'ecm_interface_lookup_in_denied_list_locked', 'ecm_interface_lookup_in_denied_list',
        'ecm_interface_denied_iface', 'ecm_interface_denied_connection',
        'ecm_interface_connection_accel_allowed', 'ecm_interface_denied_defunct', 'ecm_interface_accel_denied_read',
        'ecm_interface_accel_denied_handler', 'ecm_interface_accel_denied_clear'))
    with tempfile.TemporaryDirectory(prefix='nss-ecm-denied-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(SHIM + declarations + functions + TEST)
        subprocess.run(['cc', '-std=gnu11', '-g', '-O1', '-pthread', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True, timeout=30)


if __name__ == '__main__':
    main()
