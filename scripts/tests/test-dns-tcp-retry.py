#!/usr/bin/env python3
"""Run real dnsmasq TCP failover and local-error restoration after poisoned replies."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('dns_tcp_extract', Path(__file__).with_name('test-nss-control.py'))
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

SHIM = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <syslog.h>
#include <netinet/in.h>
#include <unistd.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;
#include "dns-protocol.h"
#define daemon dns_test_state
#define EXTR_NAME_EXTRACT 1
#define EXTR_NAME_COMPARE 2
#define RW_WRITE_ONCE 2
#define RW_READ_ONCE 3
#define SERV_GOT_TCP 32768
#define EDE_NETERR 23
#define MS_DEBUG 0
static void my_syslog(int priority,const char *format,...) { (void)priority;(void)format; }
#define _(s) (s)
union mysockaddr { struct sockaddr sa;struct sockaddr_in in; };
struct server { union mysockaddr addr,source_addr;int tcpfd,flags,last_server;char interface[16]; };
static struct { char namebuff[256],addrbuff[256];int dns_tcp_send_timeout;struct server *serverarray[2]; } state,*daemon=&state;
enum { GOOD,BAD_NAME,BAD_ID,PREFIX_EOF,BODY_EOF,SHORT_HEADER,BAD_TYPE,ALLOC_FAILURE };
static struct { int server,step,mode; } connections[32];
static struct server servers[2];
static unsigned next_fd,submits[2],mode,body_size,alloc_fail_once,restore_fail,all_fail;
static unsigned char query[256],expected[256];
static int fake_socket(int family,int type,int protocol) {
 assert(family==AF_INET&&type==SOCK_STREAM&&!protocol&&next_fd<32);return next_fd++;
}
static int fake_connect(int fd,const struct sockaddr *address,socklen_t len) {
 (void)len;unsigned index=ntohs(((const struct sockaddr_in *)address)->sin_port);
 assert(index<2);connections[fd].server=index;return 0;
}
static int fake_close(int fd) { (void)fd;return 0; }
static socklen_t sa_len(union mysockaddr *address) { (void)address;return sizeof(struct sockaddr_in); }
static int local_bind(int fd,union mysockaddr *address,char *interface,int a,int b) {
 (void)fd;(void)address;(void)interface;(void)a;(void)b;return 1;
}
static void set_upstream_tcp_timeouts(int fd) { (void)fd; }
static int prettyprint_addr(union mysockaddr *address,char *buf) { (void)address;(void)buf;return 53; }
static int extract_name(struct dns_header *header,size_t length,unsigned char **position,
 char *name,int action,int extra) {
 unsigned char *p=*position,*end=(unsigned char *)header+length;char result[256];unsigned n=0;
 while(p<end&&*p){unsigned label=*p++;if(label>63||p+label>end||n+label+1>=sizeof(result))return 0;
  memcpy(result+n,p,label);n+=label;p+=label;result[n++]='.';}
 if(p>=end||p+1+extra>end)return 0;
 p++;result[n]=0;*position=p;
 if(action==EXTR_NAME_COMPARE)return !strcmp(name,result);
 assert(action==EXTR_NAME_EXTRACT);memcpy(name,result,n+1);return 1;
}
static int expand_buf(struct iovec *buffer,size_t size) {
 if(restore_fail){restore_fail=0;return 0;}
 if(alloc_fail_once&&size==482){alloc_fail_once=0;return 0;}
 if(size>buffer->iov_len){void *next=realloc(buffer->iov_base,size);assert(next);buffer->iov_base=next;buffer->iov_len=size;}
 return 1;
}
static int read_writev(int fd,struct iovec *iov,int count,int direction) {
 assert(count==2&&direction==RW_WRITE_ONCE&&iov[0].iov_len==2&&iov[1].iov_len==body_size);
 u16 prefix;memcpy(&prefix,iov[0].iov_base,2);
 /* This is the wire framing check that fails for the actual old 482/51 case. */
 assert(ntohs(prefix)==body_size&&!memcmp(iov[1].iov_base,expected,body_size));
 unsigned index=connections[fd].server;assert(++submits[index]<=3);
 connections[fd].mode=index==0?(int)mode:(all_fail?PREFIX_EOF:GOOD);connections[fd].step=0;return 1;
}
static int read_write(int fd,unsigned char *buffer,size_t size,int direction) {
 assert(direction==RW_READ_ONCE);int kind=connections[fd].mode;
 unsigned length=(kind==BAD_NAME||kind==BODY_EOF||kind==ALLOC_FAILURE)?482:
  kind==SHORT_HEADER?4:body_size;
 if(!connections[fd].step++){
  assert(size==2);
  if(kind==PREFIX_EOF){buffer[0]=1;return 0;}
  u16 prefix=htons(length);memcpy(buffer,&prefix,2);return 1;
 }
 assert(size==length);memset(buffer,0,size);memcpy(buffer,expected,size<body_size?size:body_size);
 if(kind==BODY_EOF){if(size>=2)((struct dns_header *)buffer)->id^=1;return 0;}
 if(size>=sizeof(struct dns_header)){
  struct dns_header *header=(void *)buffer;header->hb3|=HB3_QR;
  if(kind==BAD_NAME)buffer[sizeof(*header)+1]='z';
  if(kind==BAD_ID)header->id^=1;
  if(kind==BAD_TYPE)buffer[body_size-4]=0x12;
 }
 return 1;
}
static ssize_t send_upstream_tcp_fastopen(int fd,struct msghdr *message) {
 fake_connect(fd,message->msg_name,message->msg_namelen);
 read_writev(fd,message->msg_iov,message->msg_iovlen,RW_WRITE_ONCE);errno=0;return body_size+2;
}
union all_addr { struct { int rcode,ede; } log; };
static void log_query(unsigned flags,char *name,union all_addr *addr,char *arg,int type) {
 (void)flags;(void)name;(void)arg;(void)type;assert(addr->log.rcode==REFUSED&&addr->log.ede==EDE_NETERR);
}
#define socket fake_socket
#define connect fake_connect
#define close fake_close
#ifndef TEST_FASTOPEN
#undef MSG_FASTOPEN
#endif
'''

TEST = r'''
static void fresh(unsigned kind) {
 memset(&state,0,sizeof(state));memset(connections,0,sizeof(connections));memset(servers,0,sizeof(servers));
 next_fd=submits[0]=submits[1]=all_fail=restore_fail=0;mode=kind;alloc_fail_once=kind==ALLOC_FAILURE;
 for(unsigned i=0;i<2;i++){servers[i].tcpfd=-1;servers[i].addr.in.sin_family=AF_INET;
  servers[i].addr.in.sin_port=htons(i);state.serverarray[i]=&servers[i];}
 struct dns_header header={.id=htons(0x1234),.hb3=HB3_RD,.qdcount=htons(1)};
 memcpy(query,&header,sizeof(header));unsigned char tail[]={4,'t','e','s','t',7,'i','n','v','a','l','i','d',0,0,1,0,1};
 memcpy(query+sizeof(header),tail,sizeof(tail));body_size=sizeof(header)+sizeof(tail);memcpy(expected,query,body_size);
}
static void attempt(unsigned kind,bool reused) {
 fresh(kind);struct iovec reply={0};struct server *selected=NULL;
 if(reused){servers[0].tcpfd=next_fd++;servers[0].flags=SERV_GOT_TCP;connections[0].server=0;}
 ssize_t result=tcp_talk(0,2,0,(void *)query,body_size,&reply,0,0,&selected);
 assert(result==(ssize_t)body_size&&selected==&servers[1]);
 assert(submits[0]==(reused?2:1)&&submits[1]==1&&!memcmp(query,expected,body_size));
 assert(((struct dns_header *)reply.iov_base)->id==((struct dns_header *)query)->id);free(reply.iov_base);
}
int main(void) {
 for(unsigned kind=BAD_NAME;kind<=ALLOC_FAILURE;kind++)attempt(kind,false);
 attempt(PREFIX_EOF,true);attempt(BODY_EOF,true);
 fresh(BAD_NAME);struct iovec reply={0};struct server *selected=NULL;all_fail=1;
 assert(!tcp_talk(0,2,0,(void *)query,body_size,&reply,0,0,&selected));
 assert(local_error_restore((void *)query,body_size,&reply,0)==EDE_NETERR);
 assert(!memcmp(reply.iov_base,query,body_size));free(reply.iov_base);
 /* The failure path must grow an output initially smaller than a query with
  * an OPT record. This constructs the wire record; it does not run add_do_bit. */
 fresh(GOOD);unsigned char opt[]={0,0,41,4,208,0,0,0x80,0,0,0};
 memcpy(query+body_size,opt,sizeof(opt));body_size+=sizeof(opt);
 ((struct dns_header *)query)->arcount=htons(1);memcpy(expected,query,body_size);
 reply=(struct iovec){.iov_base=malloc(8),.iov_len=8};assert(reply.iov_base);
 memset(reply.iov_base,0xa5,8);assert(local_error_restore((void *)query,body_size,&reply,0)==EDE_NETERR);
 assert(reply.iov_len>=body_size&&!memcmp(reply.iov_base,query,body_size));free(reply.iov_base);
 /* DNSSEC debug changes only the upstream query CD bit. The actual local
  * error builder must receive the client's original CD value in either case. */
 for(unsigned cd=0;cd<=1;cd++){
  fresh(GOOD);((struct dns_header *)query)->hb4|=HB4_CD;
  reply=(struct iovec){0};
  assert(local_error_restore((void *)query,body_size,&reply,cd?HB4_CD:0)==EDE_NETERR);
  setup_reply(reply.iov_base,0,EDE_NETERR);
  assert(!!(((struct dns_header *)reply.iov_base)->hb4&HB4_CD)==cd);
  assert(((struct dns_header *)reply.iov_base)->id==((struct dns_header *)query)->id);
  assert(!memcmp((char *)reply.iov_base+sizeof(struct dns_header),query+sizeof(struct dns_header),body_size-sizeof(struct dns_header)));
  free(reply.iov_base);
 }
 fresh(GOOD);reply=(struct iovec){.iov_base=malloc(8),.iov_len=8};assert(reply.iov_base);
 memset(reply.iov_base,0xa5,8);void *saved=reply.iov_base;restore_fail=1;
 assert(local_error_restore((void *)query,body_size,&reply,0)==-1&&reply.iov_base==saved&&reply.iov_len==8);
 for(unsigned i=0;i<8;i++)assert(((unsigned char *)reply.iov_base)[i]==0xa5);
 free(reply.iov_base);
 fresh(BAD_NAME);reply=(struct iovec){0};
 assert(tcp_talk(0,2,1,(void *)query,body_size,&reply,0,0,&selected)==(ssize_t)body_size);
 assert(!submits[0]&&submits[1]==1);free(reply.iov_base);
 puts("PASS actual TCP failover: mismatched name/ID, partial prefix/body EOF, short header, wrong type, allocation failure, cached-connection reconnect, rotated start, local-error identity/CD restoration and restore allocation failure");
}
'''


def failure_body(source):
    marker = 'if ((m = tcp_talk(first, last, start, header, size, bigbuff, have_mark, mark, &serv)) == 0)'
    tail = source[source.index(marker) + len(marker):].lstrip()
    if not tail.startswith('{'):
        return tail[:tail.index(';') + 1]
    depth = 0
    for index, char in enumerate(tail):
        depth += (char == '{') - (char == '}')
        if not depth:
            return tail[:index + 1]
    raise ValueError('Missing TCP failure block')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    forward = (args.source / 'forward.c').read_text()
    body = extract.function(forward, 'tcp_talk')
    restore = ('static int local_error_restore(struct dns_header *header,size_t size,struct iovec *bigbuff,int checking_disabled) {\n'
               'struct dns_header *out_header=bigbuff->iov_base;int ede=-1;do {\n' + failure_body(forward) +
               '\n} while(0);(void)out_header;return ede;\n}')
    definitions = (args.source / 'dnsmasq.h').read_text().splitlines()
    source_flags = '\n'.join(line for line in definitions if any(
        line.startswith('#define ' + name + ' ') for name in ('F_NOERR', 'F_NXDOMAIN', 'F_RCODE', 'F_IPV4', 'F_IPV6', 'F_CONFIG')))
    setup = extract.function((args.source / 'rfc1035.c').read_text(), 'setup_reply')
    for fastopen in (False, True):
        with tempfile.TemporaryDirectory(prefix='dns-tcp-retry-') as directory:
            source, binary = Path(directory) / 'test.c', Path(directory) / 'test'
            source.write_text(source_flags + '\n' + SHIM + body + restore + setup + TEST)
            flags = ['-DTEST_FASTOPEN'] if fastopen else []
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-g', '-O1', '-Wall', '-Wextra',
                            '-Wno-unused-parameter', '-Wno-unused-function', '-Werror=implicit-function-declaration',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                            *flags, '-I', str(args.source), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=15,
                           env={**os.environ, 'UBSAN_OPTIONS': 'halt_on_error=1'})


if __name__ == '__main__':
    main()
