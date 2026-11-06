const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs')
const load=file=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(file)).toString('base64'))

test('open-hand dwell fills for two seconds and clicks once without a pinch',async()=>{
 const {HandSelection}=await load('airi_overlay/resident-hand.js'),state=new HandSelection(),button={}
 for(let now=100;now<2100;now+=100){assert.equal(state.update(button,false,now),false);assert.ok(state.progress>=0&&state.progress<1)}
 assert.equal(state.update(button,false,2100),true);assert.equal(state.progress,1)
 for(let now=2200;now<7000;now+=100)assert.equal(state.update(button,false,now),false)
 assert.equal(state.update(undefined,false,7100),false)
 for(let now=7200;now<9200;now+=100)assert.equal(state.update(button,false,now),false)
 assert.equal(state.update(button,false,9200),true)
})
test('dwell cancels when the target changes, tracking stalls, or the clock goes backwards',async()=>{
 const {HandSelection}=await load('airi_overlay/resident-hand.js'),state=new HandSelection(),a={},b={}
 for(let now=0;now<=1900;now+=100)state.update(a,false,now)
 assert.equal(state.update(b,false,2000),false);assert.equal(state.progress,0)
 assert.equal(state.update(b,false,4100),false);assert.equal(state.progress,0)
 assert.equal(state.update(b,false,4000),false);assert.equal(state.progress,0)
 state.update(undefined,false,4200);assert.equal(state.progress,0)
})
test('gaze smoothing is frame-rate independent and returns gently to neutral after loss',async()=>{
 const {ResidentGazeFilter}=await load('airi_overlay/resident-gaze-state.js')
 assert.equal(typeof ResidentGazeFilter,'function')
 const fast=new ResidentGazeFilter(),slow=new ResidentGazeFilter()
 fast.update({x:0,y:0},0);slow.update({x:0,y:0},0)
 let a,b
 for(let now=10;now<=1000;now+=10)a=fast.update({x:1,y:-1},now)
 for(let now=40;now<=1000;now+=40)b=slow.update({x:1,y:-1},now)
 assert.ok(a.x>.99&&a.x<=1&&a.y>=-1);assert.ok(Math.abs(a.x-b.x)<.0001)
 const fading=fast.update(undefined,1010);assert.ok(fading.x>0&&fading.x<a.x)
 for(let now=1020;now<=4000;now+=10)a=fast.update(undefined,now)
 assert.equal(a,undefined)
 fast.reset();assert.equal(fast.update(undefined,5000),undefined)
})
