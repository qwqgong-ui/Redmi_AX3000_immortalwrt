#!/usr/bin/env python3
"""Run the actual dnsmasq retry scheduler across deadlines and clock boundaries."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('dns_retry_extract', Path(__file__).with_name('test-nss-control.py'))
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

SHIM = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <limits.h>
#include <errno.h>
#include <sys/socket.h>
#define TCP_TIMEOUT 5
typedef uint32_t u32;
struct dns_header { unsigned short id,flags; };
struct frec { struct { unsigned log_id; } frec_src;void *sentto;time_t time;u32 forward_timestamp,forward_start_timestamp;int forward_delay,flags;void *stash;size_t stash_len;struct frec *next,*blocking_query; };
struct daemon_state { int fast_retry_time,fast_retry_timeout,dns_tcp_send_timeout,dns_tcp_receive_timeout;struct frec *frec_list;void *packet,*srv_save,*log_source_addr;unsigned log_display_id; };
static struct daemon_state state,*daemon=&state;
static u32 fake_millis,wall_millis;
static int sends,clock_failure;
static int send_ms,receive_ms;
static int test_setsockopt(int fd,int level,int option,const void *value,socklen_t size) {
 assert(fd==7&&level==SOL_SOCKET&&size==sizeof(struct timeval));const struct timeval *t=value;
 assert(t->tv_sec>=0&&t->tv_usec>=0&&t->tv_usec<1000000);int ms=t->tv_sec*1000+t->tv_usec/1000;
 if(option==SO_SNDTIMEO)send_ms=ms;else {assert(option==SO_RCVTIMEO);receive_ms=ms;}return 0;
}
#define setsockopt test_setsockopt
static int fastopen_calls,fastopen_error;
static ssize_t test_sendmsg(int fd,const struct msghdr *msg,int flags) { assert(fd==7&&msg&&flags==MSG_FASTOPEN);fastopen_calls++;if(fastopen_error){errno=fastopen_error;fastopen_error=0;return -1;}return 31; }
static int retry_send(ssize_t result) { if(result>=0){errno=0;return 0;}return errno==EINTR||errno==EAGAIN; }
#define sendmsg test_sendmsg
#define FREC_GONE_TO_TCP 1
static int test_clock_gettime(clockid_t clock,struct timespec *t) { assert(clock==CLOCK_MONOTONIC);if(clock_failure)return -1;t->tv_sec=fake_millis/1000;t->tv_nsec=(fake_millis%1000)*1000000;return 0; }
static int test_gettimeofday(struct timeval *t,void *zone) { (void)zone;t->tv_sec=wall_millis/1000;t->tv_usec=(wall_millis%1000)*1000;return 0; }
#define clock_gettime test_clock_gettime
#define gettimeofday test_gettimeofday
static void blockdata_retrieve(void *stash,size_t len,void *dst) { assert(stash&&len==sizeof(struct dns_header));memcpy(dst,stash,len); }
static void forward_query(int fd,void *a,void *b,unsigned iface,struct dns_header *packet,size_t len,size_t limit,time_t now,struct frec *f,unsigned flags,int generated) {
 (void)a;(void)b;(void)iface;(void)limit;(void)now;(void)flags;assert(fd==-1&&generated&&len==sizeof(*packet)&&packet->id==42);sends++;f->forward_timestamp=fake_millis;
}
'''

CASES = r'''
static struct dns_header question={42,0},packet;
static struct frec f;
static void init(u32 start,int timeout,int delay) {
 memset(&f,0,sizeof(f));state=(struct daemon_state){.fast_retry_time=delay,.fast_retry_timeout=timeout,.frec_list=&f,.packet=&packet};
 f.sentto=(void *)1;f.time=9;f.forward_start_timestamp=f.forward_timestamp=start;f.forward_delay=delay;f.stash=&question;f.stash_len=sizeof(question);fake_millis=start;sends=0;
}
int main(void) {
 /* A query at .800 seconds must still retry at +1.5 s, even though the
  * second-resolution clock has crossed two integer seconds. */
 init(9800,2000,500);assert(fast_retry(9)==500&&sends==0);
 fake_millis=10300;assert(fast_retry(10)==1000&&sends==1);
 fake_millis=11300;assert(fast_retry(11)==500&&sends==2);
 fake_millis=11800;assert(fast_retry(11)==-1&&sends==2);
 /* Preserve non-integral-second budgets and wake precisely at expiry. */
 init(10000,1250,500);fake_millis=10500;assert(fast_retry(10)==750&&sends==1);
 fake_millis=11249;assert(fast_retry(11)==1&&sends==1);
 fake_millis=11250;assert(fast_retry(11)==-1&&sends==1);
 /* Modular elapsed time tolerates the 32-bit millisecond wrap. */
 init(UINT32_MAX-600,2000,500);fake_millis=f.forward_start_timestamp+500;assert(fast_retry(1000)==1000&&sends==1);
 fake_millis=f.forward_start_timestamp+1500;assert(fast_retry(1001)==500&&sends==2);
 /* Wall-clock steps and large backoffs cannot cut short or overflow retry. */
 init(20000,2000,500);fake_millis=20500;assert(fast_retry((time_t)INT_MAX)==1000&&sends==1);
 fake_millis=21500;assert(fast_retry(0)==500&&sends==2);
 init(0,INT_MAX,INT_MAX/2+1);fake_millis=INT_MAX/2+1;assert(fast_retry(0)==INT_MAX/2&&f.forward_delay==INT_MAX&&sends==1);
#ifdef HAVE_DNSSEC
 init(0,2000,500);f.blocking_query=&f;fake_millis=500;assert(fast_retry(1)==-1&&sends==0);
 f.blocking_query=NULL;f.flags=FREC_GONE_TO_TCP;assert(fast_retry(1)==-1&&sends==0);
#endif
 init(0,0,500);fake_millis=500;assert(fast_retry(1)==-1&&sends==0);
 fake_millis=1234;wall_millis=99999;assert(dnsmasq_milliseconds()==1234);
 wall_millis=0;assert(dnsmasq_milliseconds()==1234);
 clock_failure=1;wall_millis=5678;assert(dnsmasq_milliseconds()==5678);
 state.dns_tcp_send_timeout=state.dns_tcp_receive_timeout=0;set_upstream_tcp_timeouts(7);assert(send_ms==5000&&receive_ms==10000);
 state.dns_tcp_send_timeout=500;state.dns_tcp_receive_timeout=1500;set_upstream_tcp_timeouts(7);assert(send_ms==500&&receive_ms==1500);
 state.dns_tcp_send_timeout=state.dns_tcp_receive_timeout=INT_MAX;set_upstream_tcp_timeouts(7);assert(send_ms==INT_MAX&&receive_ms==INT_MAX);
 struct msghdr message={0};state.dns_tcp_send_timeout=500;fastopen_error=EAGAIN;fastopen_calls=0;
 assert(send_upstream_tcp_fastopen(7,&message)==-1&&errno==EAGAIN&&fastopen_calls==1);
 fastopen_error=EINTR;fastopen_calls=0;assert(send_upstream_tcp_fastopen(7,&message)==31&&errno==0&&fastopen_calls==2);
 state.dns_tcp_send_timeout=0;fastopen_error=EAGAIN;fastopen_calls=0;assert(send_upstream_tcp_fastopen(7,&message)==31&&errno==0&&fastopen_calls==2);
 puts("DNS retry: second-boundary loss, exact millisecond deadline, wrap, clock steps, overflow and DNSSEC gating passed");return 0;
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    forward = (args.source / 'forward.c').read_text()
    option = (args.source / 'option.c').read_text()
    assert 'target->forward_start_timestamp = dnsmasq_milliseconds();' in forward
    assert 'daemon->fast_retry_timeout = retry;' in option and 'retry/1000' not in option
    assert option.count('daemon->fast_retry_timeout = TIMEOUT * 1000;') == 2
    bodies = extractor.function((args.source / 'util.c').read_text(), 'dnsmasq_milliseconds')
    bodies += extractor.function(forward, 'fast_retry')
    bodies += extractor.function(forward, 'set_upstream_tcp_timeouts')
    bodies += extractor.function(forward, 'send_upstream_tcp_fastopen')
    for dnssec in (False, True):
        with tempfile.TemporaryDirectory(prefix='dns-retry-window-') as temp:
            source, binary = Path(temp) / 'test.c', Path(temp) / 'test'
            source.write_text(SHIM + bodies + CASES)
            flags = ['-DHAVE_DNSSEC'] if dnssec else []
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Werror',
                            '-fsanitize=address,undefined', '-g', *flags, str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

if __name__ == '__main__':
    main()
