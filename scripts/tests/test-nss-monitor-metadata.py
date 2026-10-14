#!/usr/bin/env python3
"""Test actual compact descriptor, Linux header helpers and bounded monitor parser."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile

def module(filename):
    spec=importlib.util.spec_from_file_location(filename,Path(__file__).with_name(filename))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
extractor=module('test-nss-control.py')
structures=module('test-nss-wifili.py')

SHIM=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
typedef uint16_t __le16;typedef uint32_t __le32;typedef uint64_t __le64;
#define __packed __attribute__((packed))
#ifndef __attribute_const__
#define __attribute_const__ __attribute__((const))
#endif
#define struct_group(NAME,...) union { struct { __VA_ARGS__ }; struct { __VA_ARGS__ } NAME; }
#define ETH_ALEN 6
#define BIT(n) (UINT32_C(1)<<(n))
#define GENMASK(h,l) ((UINT32_MAX>>(31-(h)))&~((UINT32_C(1)<<(l))-1))
#define FIELD_GET(mask,v) (((v)&(mask))>>__builtin_ctz(mask))
#define FIELD_PREP(mask,v) (((u32)(v)<<__builtin_ctz(mask))&(mask))
#define cpu_to_le16(v) (v)
#define le16_to_cpu(v) (v)
#define le32_to_cpu(v) (v)
static void ether_addr_copy(u8 *to,const u8 *from){memcpy(to,from,6);}
static bool ether_addr_equal(const u8 *a,const u8 *b){return !memcmp(a,b,6);}
static u16 get_unaligned_le16(const void *p){u16 value;memcpy(&value,p,2);return value;}
'''

CASES=r'''
_Static_assert(sizeof(struct hal_rx_desc_qcn9074)==384,"actual compact ABI");
_Static_assert(offsetof(struct hal_rx_desc_qcn9074,hdr_status_tag)==256,"header TLV tag offset");
_Static_assert(offsetof(struct hal_rx_desc_qcn9074,hdr_status)==264,"header bytes offset");
static struct hal_rx_desc_qcn9074 d;static struct ath11k_mon_meta_record record;
static u32 tag(u32 value,unsigned len){return FIELD_PREP(HAL_TLV_HDR_TAG,value)|FIELD_PREP(HAL_TLV_HDR_LEN,len);}
static void fresh(void){
 memset(&d,0,sizeof(d));
 d.mpdu_start_tag=tag(HAL_RX_MPDU_START,sizeof(d.mpdu_start));d.msdu_end_tag=tag(HAL_RX_MSDU_END,sizeof(d.msdu_end));d.rx_attn_tag=tag(HAL_RX_ATTENTION,sizeof(d.attention));d.hdr_status_tag=tag(HAL_RX_HEADER,124);
 d.mpdu_start.phy_ppdu_id=7;d.phy_ppdu_id=FIELD_PREP(HAL_RX_DESC_QCN6122_MON_HDR_PPDU_ID,7);d.mpdu_start.frame_ctrl=0x0288;d.mpdu_start.seq_ctrl=42<<4;d.mpdu_start.qos_ctrl=5;
 d.mpdu_start.info11=RX_MPDU_START_INFO11_MPDU_FCTRL_VALID|RX_MPDU_START_INFO11_MAC_ADDR1_VALID|RX_MPDU_START_INFO11_MAC_ADDR2_VALID|RX_MPDU_START_INFO11_MPDU_SEQ_CTRL_VALID|RX_MPDU_START_INFO11_MPDU_QOS_CTRL_VALID|FIELD_PREP(RX_MPDU_START_INFO11_MPDU_SEQ_NUM,42);
 d.mpdu_start.info9=FIELD_PREP(RX_MPDU_START_INFO9_TID,5);d.mpdu_start.info12=FIELD_PREP(RX_MPDU_START_INFO12_DECAP_TYPE,2);
 memcpy(d.mpdu_start.addr1,"RA1234",6);memcpy(d.mpdu_start.addr2,"TA1234",6);
 d.msdu_end.info4=RX_MSDU_END_INFO4_FIRST_MSDU|RX_MSDU_END_INFO4_LAST_MSDU;d.attention.info2=RX_ATTENTION_INFO2_MSDU_DONE;
 struct ieee80211_hdr *h=(void *)d.hdr_status;h->frame_control=d.mpdu_start.frame_ctrl;h->seq_ctrl=d.mpdu_start.seq_ctrl;memcpy(h->addr1,d.mpdu_start.addr1,6);memcpy(h->addr2,d.mpdu_start.addr2,6);u16 qos=5;memcpy(ieee80211_get_qos_ctl(h),&qos,2);
}
static void decode(void){ath11k_mon_meta_decode(&d,sizeof(d),7,0,&record);}
int main(void){
 for(size_t n=0;n<384;n++){void *short_buffer=malloc(n?n:1);memset(short_buffer,0,n);ath11k_mon_meta_decode(short_buffer,n,7,0,&record);assert(!record.flags);free(short_buffer);}
 fresh();decode();assert(record.flags&ATH11K_MON_META_TRUSTED);assert(record.decap==2&&record.tid==5&&record.seq_ctrl==(42<<4));
 u32 bits[]={RX_MPDU_START_INFO11_MPDU_FCTRL_VALID,RX_MPDU_START_INFO11_MAC_ADDR1_VALID,RX_MPDU_START_INFO11_MAC_ADDR2_VALID,RX_MPDU_START_INFO11_MPDU_SEQ_CTRL_VALID,RX_MPDU_START_INFO11_MPDU_QOS_CTRL_VALID};
 for(unsigned i=0;i<sizeof(bits)/sizeof(bits[0]);i++){fresh();d.mpdu_start.info11&=~bits[i];decode();assert(!(record.flags&ATH11K_MON_META_TRUSTED));}
 for(unsigned n=0;n<160;n++){fresh();d.hdr_status_tag=tag(HAL_RX_HEADER,n);decode();if(n<30||(n>124&&n!=132))assert(!(record.flags&ATH11K_MON_META_HDR_VALID));}
 fresh();d.mpdu_start_tag=tag(HAL_RX_MPDU_START,sizeof(d.mpdu_start)-1);decode();assert(!(record.flags&ATH11K_MON_META_MPDU_VALID));
 fresh();d.mpdu_start_tag=tag(HAL_RX_MPDU_START,sizeof(d.mpdu_start)+1);decode();assert(!(record.flags&ATH11K_MON_META_MPDU_VALID));
 fresh();d.hdr_status_tag=tag(HAL_RX_HEADER+1,124);decode();assert(!(record.flags&ATH11K_MON_META_TRUSTED));
 fresh();d.phy_ppdu_id++;decode();assert(!(record.flags&ATH11K_MON_META_HDR_MATCH));
 fresh();d.phy_ppdu_id=FIELD_PREP(HAL_RX_DESC_QCN6122_MON_HDR_PPDU_ID,8);decode();assert(!(record.flags&ATH11K_MON_META_HDR_MATCH));
 fresh();d.phy_ppdu_id=7;decode();assert(!(record.flags&ATH11K_MON_META_HDR_MATCH));
 fresh();ath11k_mon_meta_decode(&d,sizeof(d),8,0,&record);assert(!(record.flags&ATH11K_MON_META_PPDU_MATCH));
 fresh();d.attention.info1=RX_ATTENTION_INFO1_FCS_ERR;decode();assert((record.flags&ATH11K_MON_META_FCS_BAD)&&!(record.flags&ATH11K_MON_META_TRUSTED));
 fresh();ath11k_mon_meta_decode(&d,sizeof(d),7,RX_MSDU_DESC_INFO0_MSDU_CONTINUATION,&record);assert((record.flags&ATH11K_MON_META_CONTINUATION)&&!(record.flags&ATH11K_MON_META_END_VALID)&&!(record.flags&ATH11K_MON_META_TRUSTED));
 fresh();d.msdu_end.info4&=~RX_MSDU_END_INFO4_LAST_MSDU;decode();assert(!(record.flags&ATH11K_MON_META_TRUSTED));
 fresh();d.attention.info2=0;decode();assert(!(record.flags&ATH11K_MON_META_DONE));
 fresh();d.mpdu_start.info11|=RX_MPDU_START_INFO11_MPDU_RETRY;decode();assert(!(record.flags&ATH11K_MON_META_HDR_MATCH));
 fresh();d.mpdu_start.info9=0;decode();assert(!(record.flags&ATH11K_MON_META_QOS_VALID));
 fresh();d.mpdu_start.seq_ctrl++;decode();assert(!(record.flags&ATH11K_MON_META_SEQ_VALID));
 fresh();d.hdr_status[10]^=1;decode();assert(!(record.flags&ATH11K_MON_META_HDR_MATCH));
 fresh();d.mpdu_start.frame_ctrl=0x0388;struct ieee80211_hdr *h=(void *)d.hdr_status;h->frame_control=0x0388;u16 qos=5;memcpy(ieee80211_get_qos_ctl(h),&qos,2);decode();assert(record.flags&ATH11K_MON_META_TRUSTED);d.hdr_status_tag=tag(HAL_RX_HEADER,35);decode();assert(!(record.flags&ATH11K_MON_META_HDR_VALID));
 /* The known truncated profile can match its bounded MAC prefix, never its tail. */
 fresh();d.hdr_status_tag=tag(HAL_RX_HEADER,132);decode();assert(record.header_bytes==120&&record.header_nonzero>0&&record.header_ppdu==(7U<<16));assert((record.probe_fc&record.probe_ra&record.probe_ta&record.probe_seq&record.probe_qos)&1);assert((record.flags&(ATH11K_MON_META_HDR_VALID|ATH11K_MON_META_HDR_MATCH|ATH11K_MON_META_HDR_TRUNCATED))==(ATH11K_MON_META_HDR_VALID|ATH11K_MON_META_HDR_MATCH|ATH11K_MON_META_HDR_TRUNCATED));assert(!(record.flags&ATH11K_MON_META_TRUSTED));
 for(unsigned off=0;off<=28;off+=4){fresh();u8 saved[36];memcpy(saved,d.hdr_status,sizeof(saved));memset(d.hdr_status,0,sizeof(d.hdr_status));memcpy(d.hdr_status+off,saved,sizeof(saved));d.hdr_status_tag=tag(HAL_RX_HEADER,132);decode();assert((record.probe_fc&record.probe_ra&record.probe_ta&record.probe_seq&record.probe_qos)==BIT(off/4));assert(!(record.flags&ATH11K_MON_META_TRUSTED));}
 fresh();memset(d.hdr_status,0,sizeof(d.hdr_status));d.hdr_status_tag=tag(HAL_RX_HEADER,132);decode();assert(!record.header_nonzero&&!record.probe_fc&&!record.probe_ra&&!record.probe_ta&&!record.probe_seq&&!record.probe_qos);
 fresh();d.hdr_status_tag=tag(HAL_RX_HEADER+1,132);decode();assert(!record.header_bytes&&!record.probe_fc);
 for(unsigned len=0;len<256;len++){fresh();d.hdr_status_tag=tag(HAL_RX_HEADER,len);decode();assert(record.header_bytes==(len<4?0:(len-4>120?120:len-4)));}
 fresh();d.mpdu_start.info11&=~RX_MPDU_START_INFO11_MAC_ADDR1_VALID;decode();assert(!record.probe_ra);
 fresh();d.hdr_status_tag=tag(HAL_RX_HEADER,29);decode();assert(!record.probe_qos);d.hdr_status_tag=tag(HAL_RX_HEADER,30);decode();assert(record.probe_qos&1);
 puts("PASS actual 384-byte compact layout, actual Linux FC/header helpers, bounded prefix probe, high16 PPDU/reserved-bit checks, known truncated profile without tail trust, per-field validity, continuation/FCS rejection and no payload reconstruction");return 0;
}
'''

def defines(text,prefixes):
    return '\n'.join(line for line in text.splitlines() if line.startswith('#define ') and any(line.split()[1].startswith(prefix) for prefix in prefixes) and not line.endswith('\\'))+'\n'

def main():
    p=argparse.ArgumentParser();p.add_argument('--ath11k-source',type=Path,required=True);p.add_argument('--kernel-source',type=Path,required=True);a=p.parse_args()
    rx=(a.ath11k_source/'rx_desc.h').read_text();hal=(a.ath11k_source/'hal_desc.h').read_text();core=(a.ath11k_source/'core.h').read_text();dp=(a.ath11k_source/'dp_rx.c').read_text()
    ieee=(a.kernel_source/'include/linux/ieee80211.h').read_text();util=(a.kernel_source/'net/wireless/util.c').read_text()
    defs=defines(rx,('HAL_RX_DESC_','RX_MPDU_START_INFO','RX_MSDU_END_INFO','RX_ATTENTION_INFO'))+defines(hal,('HAL_TLV_HDR_','RX_MSDU_DESC_INFO0_'))+defines(core,('ATH11K_MON_META_',))+defines(ieee,('IEEE80211_FCTL_','IEEE80211_FTYPE_','IEEE80211_STYPE_','IEEE80211_QOS_CTL_LEN','IEEE80211_HT_CTL_LEN'))
    for name in ('HAL_RX_MPDU_START','HAL_RX_MSDU_END','HAL_RX_ATTENTION','HAL_RX_HEADER'):
        match=re.search(r'\b'+name+r'\s*=\s*(\d+)',hal);defs+=f'#define {name} {match[1]}\n'
    for name in ('rx_attention','rx_msdu_end_qcn9074','rx_msdu_start_qcn9074','rx_mpdu_start_qcn9074','rx_mpdu_end','hal_rx_desc_qcn9074'):defs+=structures.structure(rx,name)
    for name in ('ieee80211_hdr','ieee80211_qos_hdr','ieee80211_qos_hdr_4addr'):defs+=structures.structure(ieee,name)
    defs+=structures.structure(core,'ath11k_mon_meta_record')
    for name in ('ieee80211_is_ext','ieee80211_is_data','ieee80211_is_data_qos','ieee80211_is_mgmt','ieee80211_is_ctl','ieee80211_has_a4','ieee80211_has_order','ieee80211_get_qos_ctl'):defs+=extractor.function(ieee,name)
    defs+=extractor.function(util,'ieee80211_hdrlen')
    defs+=extractor.function(dp,'ath11k_mon_meta_tlv')+extractor.function(dp,'ath11k_mon_meta_probe')+extractor.function(dp,'ath11k_mon_meta_decode')
    with tempfile.TemporaryDirectory(prefix='nss-mon-meta-') as tmp:
        source=Path(tmp)/'test.c';binary=Path(tmp)/'test';source.write_text(SHIM+defs+CASES)
        subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Werror','-O1','-g','-fsanitize=address,undefined','-fno-pie','-no-pie',str(source),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
if __name__=='__main__':main()
