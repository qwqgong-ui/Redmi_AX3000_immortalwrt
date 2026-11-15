import { create } from 'MODULE';
function check(value, text) { if (!value) die(`FAIL: ${text}\n`); }
let env;
function reset() {
	env = { ready: true, objects: ['unrelated', 'wpa_supplicant.phy1-sta0', 'wpa_supplicant.bad/name'],
		status: 'mode=station\nwpa_state=COMPLETED\nfreq=5745\nbssid=02:11:22:33:44:55\n',
		tables: {
			routes: [{family:2,table:254,type:1,oif:'phy1-sta0',gateway:'192.0.2.1'}],
			addresses: [{family:2,dev:'phy1-sta0',flags:0,local:'192.0.2.2',address:'192.0.2.2/24'}],
			neighbors: [{family:2,dev:'phy1-sta0',state:4,dst:'192.0.2.1',lladdr:'02:aa:bb:cc:dd:ee'}],
		}, link: {index:19,up:true,mac:'02:22:33:44:55:66'}, now:100, calls:[], result:0,
		queries:{objects:0,status:0,tables:0} };
	return create({ ready:()=>env.ready,
		objects:()=>{env.queries.objects++;return env.objects;},
		status:object=>{check(object=='wpa_supplicant.phy1-sta0','valid object only');env.queries.status++;return env.status;},
		tables:()=>{env.queries.tables++;return env.tables;}, link:iface=>env.link, now:()=>env.now,
		refresh:iface=>{push(env.calls,iface);return env.result;} });
}
let watch=reset(); check(watch.pass(),'initial snapshot');
check(length(env.calls)==1,'first connection refresh');
for(let i=0;i<100;i++) { env.now++; check(watch.pass(),'idle pass'); }
check(length(env.calls)==1,'100 idle passes without helper');
check(env.queries.objects==101 && env.queries.status==101 && env.queries.tables==101,'one shared snapshot per pass');
env.now=399; watch.pass(); check(length(env.calls)==1,'300 second cadence not early');
env.now=400; watch.pass(); check(length(env.calls)==2,'periodic refresh');
env.link.index++; watch.pass(); check(length(env.calls)==3,'recreated interface');
env.tables.addresses[0].local='192.0.2.3'; watch.pass(); check(length(env.calls)==4,'DHCP identity change');
env.tables.neighbors[0].lladdr='02:aa:bb:cc:dd:ed'; watch.pass(); check(length(env.calls)==5,'gateway MAC change');
watch.link_event('unrelated',0,false); watch.pass(); check(length(env.calls)==5,'unrelated link event');
watch.link_event('phy1-sta0',[0x10001,0xffffffff],false); watch.pass();
check(length(env.calls)==5,'online change-mask event preserves cadence');
watch.link_event('phy1-sta0',[1,0x10000],false); watch.pass(); check(length(env.calls)==6,'fast same-BSSID reconnect');
env.status=null; check(!watch.pass(),'transient status failure');
env.status='mode=station\nwpa_state=COMPLETED\nfreq=5745\nbssid=02:11:22:33:44:55\n';
watch.pass(); check(length(env.calls)==6,'failed observation retains cadence');
env.tables.routes=null; check(!watch.pass(),'failed netlink snapshot');
env.tables.routes=[]; watch.pass(); check(length(env.calls)==6,'no route no helper');
env.tables.routes=[{family:2,table:254,type:1,oif:'phy1-sta0',gateway:'192.0.2.1'}];
watch.pass(); check(length(env.calls)==7,'route returns');
env.ready=false; watch.pass(); check(length(env.calls)==7,'NSS unavailable');
env.ready=true; watch.pass(); check(length(env.calls)==8,'NSS returns');
env.status='mode=station\nwpa_state=DISCONNECTED\nfreq=5745\nbssid=02:11:22:33:44:55\n';
watch.pass(); check(length(env.calls)==8,'disconnected');

for(let result in [1,2]) {
	watch=reset(); env.result=result; watch.pass();
	for(let i=0;i<29;i++) { env.now++; watch.pass(); }
	check(length(env.calls)==1,'error and SKIP both back off');
	env.now++; watch.pass(); check(length(env.calls)==2,'30 second retry');
}
watch=reset();
unshift(env.tables.addresses,{family:2,dev:'phy1-sta0',label:'phy1-sta0:alias',flags:0,local:'198.51.100.2',address:'198.51.100.2/24'});
watch.pass();check(length(env.calls)==1,'base-interface IPv4 matches SIOCGIFADDR despite primary alias');
for(let invalid in ['frequency','BSSID','offlink','route-table','neighbor-state','neighbor-mac','down','zero-ip','secondary']) {
	watch=reset();
	if(invalid=='frequency') env.status=replace(env.status,'5745','2412');
	if(invalid=='BSSID') env.status=replace(env.status,'02:11','03:11');
	if(invalid=='offlink') env.tables.routes[0].gateway='198.51.100.1';
	if(invalid=='route-table') env.tables.routes[0].table=100;
	if(invalid=='neighbor-state') env.tables.neighbors[0].state=32;
	if(invalid=='neighbor-mac') env.tables.neighbors[0].lladdr='ff:ff:ff:ff:ff:ff';
	if(invalid=='down') env.link.up=false;
	if(invalid=='zero-ip') env.tables.addresses[0].local='0.0.0.0';
	if(invalid=='secondary') env.tables.addresses[0].flags=1;
	watch.pass(); check(!length(env.calls),`reject ${invalid}`);
}
print('PASS native neighbor: 100 idle passes without helper, cadence/backoff, interface/IP/MAC identity, rapid reconnect, failed observations and invalid topology\n');
