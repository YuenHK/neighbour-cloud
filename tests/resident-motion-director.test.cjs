const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url')
const load=()=>import(pathToFileURL(path.resolve('airi_overlay/resident-gestures.js')).href)
test('idle greets briefly then really rests; invitation intervals vary and do not force left/right alternation',async()=>{
 const {createResidentMotionDirector}=await load(),d=createResidentMotionDirector();let rest=0,wave=0,last='rest',sides=[]
 for(let t=0;t<240000;t+=100){const p=d.update(t);if(p.action==='rest')rest++;if(p.action==='wave'){wave++;if(last!=='wave')sides.push(p.side)}last=p.action}
 assert.ok(rest>1900,'at least 79% quiet rest');assert.ok(wave<260,'short invitations, not perpetual waves');assert.ok(sides.includes('left')&&sides.includes('right'));assert.ok(sides.some((x,i)=>i&&x===sides[i-1]),'dominant hand can repeat naturally')
})
test('listening suppresses attention-seeking; concern stays calm after audio stops until a new visitor',async()=>{
 const {createResidentMotionDirector}=await load(),d=createResidentMotionDirector();d.update(0)
 for(let t=1000;t<15000;t+=100)assert.equal(d.update(t,{kind:'listen',start:1000,duration:1700,continuous:true},true).action,'rest')
 assert.equal(d.update(15000,{kind:'care',start:15000,duration:3300,continuous:true}).kind,'care')
 for(let t=16000;t<65000;t+=100){const p=d.update(t);assert.equal(p.kind,'care');assert.equal(p.action,'rest')}
 assert.equal(d.update(66000,{kind:'greeting',start:66000,duration:3200}).kind,'greeting')
 assert.equal(d.update(67000,{kind:'greeting',start:66000,duration:3200}).action,'wave')
})
test('explanations use brief presenting gestures and pauses, without greeting waves; finite smooth arm targets',async()=>{
 const {createResidentMotionDirector,continuousWelcomeBody}=await load(),d=createResidentMotionDirector(),seen=new Set();d.update(0)
 let prev
 for(let t=4000;t<40000;t+=16){const p=d.update(t,{kind:'explain',start:4000,duration:3600,continuous:true},true);seen.add(p.action);assert.notEqual(p.action,'wave');const b=continuousWelcomeBody(t,false,'0',p);assert.ok(Object.values(b).flat().every(x=>Number.isFinite(x)&&Math.abs(x)<=150));if(prev)assert.ok(Math.max(...Object.keys(b).flatMap(k=>b[k].map((x,i)=>Math.abs(x-prev[k][i]))))<8,'no limb snaps');prev=b}
 assert.ok(seen.has('rest')&&seen.has('offer')&&seen.has('beat'))
})
