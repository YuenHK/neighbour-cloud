const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const load=file=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(file)).toString('base64'))
test('face targeting is spatial, rejects invalid/low-confidence values and expires in memory',async()=>{
 const {selectResidentFace,readResidentGaze,clearResidentGaze}=await load('airi_overlay/resident-gaze-state.js')
 const face=(x,size=40,score=.9)=>({boundingBox:{originX:x,originY:30,width:size,height:size},categories:[{score}]})
 assert.equal(selectResidentFace([face(0,20),face(80,60)],200,200).x,.55)
 assert.equal(selectResidentFace([face(0,20),face(80,60)],200,200,{x:.05,y:.2}).x,.05)
 assert.equal(selectResidentFace([face(10,40,.3)],200,200),undefined)
 assert.equal(selectResidentFace([face(NaN)],200,200),undefined)
 global.__NEIGHBOUR_RESIDENT_GAZE__={x:5,y:-5,at:100}
 assert.deepEqual(readResidentGaze(1000),{x:1,y:-1});assert.equal(readResidentGaze(1500),undefined)
 clearResidentGaze();assert.equal(readResidentGaze(100),undefined)
})
test('selection uses a stable two-second dwell without pinch and rearms only after leaving',async()=>{
 const {HandSelection,residentPalm}=await load('airi_overlay/resident-hand.js'),state=new HandSelection(),button={}
 assert.equal(residentPalm([]),undefined)
 assert.equal(state.update(button,false,100),false)
 for(let now=200;now<=2000;now+=100)assert.equal(state.update(button,false,now),false)
 assert.equal(state.update(button,false,2100),true)
 assert.equal(state.update(button,false,2200),false)
 assert.equal(state.update(undefined,false,2300),false)
 assert.equal(state.update(button,false,2400),false)
 assert.equal(state.update(button,false,2500),false)
})
test('idle greeting never interrupts speech, drafts, existing conversation, hidden pages or startup',async()=>{
 const {shouldResidentWelcome}=await load('airi_overlay/resident-gestures.js')
 const state={visible:true,mounted:true,hidden:false,busy:false,speaking:false,messages:0,draft:'',lastAt:0}
 assert.equal(shouldResidentWelcome(state,45001),true)
 for(const patch of [{visible:false},{mounted:false},{hidden:true},{busy:true},{speaking:true},{messages:1},{draft:'未傳送'}])
  assert.equal(shouldResidentWelcome({...state,...patch},50000),false)
 assert.equal(shouldResidentWelcome(state,44000),false)
})
test('startup repair coalesces failures, permits one initialization retry, and cancels stale navigation',async()=>{
 const{StartupRepair}=await load('deploy/cloud/web/startup-repair.js');let calls=0,unblock
 const repair=new StartupRepair({wait:()=>new Promise(resolve=>unblock=resolve)})
 const a=repair.run('frame',()=>{calls++;return true}),b=repair.run('frame',()=>{calls++;return true})
 assert.equal(a,b);unblock();assert.equal(await a,true);assert.equal(calls,1)
 assert.equal(await repair.run('frame',()=>{calls++;return true}),false)
 const cancelled=repair.run('next',()=>{calls++;return true});repair.reset();unblock()
 assert.equal(await cancelled,false);assert.equal(calls,1)
 assert.equal(await repair.run('busy',()=>{calls++;return true},()=>false),false)
})
test('camera imports do not ask permission; late permission resolution after cancellation stops all tracks',async()=>{
 const ts=require(path.resolve('.vendor/airi/node_modules/typescript'))
 let calls=0,stops=0,resolve,cleared=0;const states=[],events=new Map()
 const scope={exports:{},require:()=>({clearResidentGaze:()=>cleared++,selectResidentFace:()=>undefined}),
  navigator:{mediaDevices:{getUserMedia:()=>{calls++;return new Promise(r=>resolve=r)}}},
  document:{addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:()=>{}},
  window:{addEventListener:()=>{},removeEventListener:()=>{}},setTimeout,clearTimeout,console}
 vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/resident-gaze.js','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
 const gaze=new scope.exports.ResidentGaze(state=>states.push(state));assert.equal(calls,0)
 const starting=gaze.start();assert.equal(calls,1);gaze.stop()
 resolve({getTracks:()=>[{stop:()=>stops++}]});await starting;await Promise.resolve()
 assert.ok(stops>=1);assert.ok(cleared>=2);assert.equal(states.at(-1),'off')
 gaze.dispose()
})
