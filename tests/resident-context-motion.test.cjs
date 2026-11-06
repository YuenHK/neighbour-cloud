const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const load = file => import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync(file)).toString('base64'))
const motion = load('airi_overlay/resident-gestures.js')
test('existing Cantonese content selects warm and relevant gestures with distress taking priority', async () => {
 const {residentConversationGesture: select} = await motion
 for(const [text, expected] of [['早晨','greeting'],['多謝你','thanks'],['垃圾應該點樣分類？','explain'],['好呀','agree'],['我考到試好開心','celebrate'],['我唔開心，想死','care'],['好開心但好擔心媽媽','care'],['我考試失敗，唔開心','care'],['今晚去煮飯','speaking']]) assert.equal(select(text),expected,text)
 assert.equal(select('同我傾下','你承受緊好多壓力，我陪住你。'),'care')
 assert.equal(select('我考試冇成功'),'speaking')
})
test('idle invitation is quiet, bounded and waits for conversation inactivity; care and draft block it', async () => {
 const {shouldResidentWelcome: ready, gestureOffsets} = await motion
 const idle={visible:true,mounted:true,hidden:false,busy:false,speaking:false,messages:4,draft:'',care:false,lastAt:0,lastActivity:10000}
 assert.equal(ready(idle,60000),false);assert.equal(ready(idle,90000),true)
 for(const extra of [{care:true},{draft:'仲想講'},{busy:true},{speaking:true},{hidden:true},{visible:false},{lastAt:70000}]) assert.equal(ready({...idle,...extra},90000),false)
 const g={kind:'idle',start:0,duration:5800}
 assert.ok(gestureOffsets(g,1450).x>0);assert.ok(gestureOffsets(g,4350).x<0)
 assert.equal(gestureOffsets(g,6000),undefined)
})
test('spoken gestures keep phase across chunks; a welcome wave or bow never loops through a whole answer', async () => {
 const {residentSpeechGesture,gestureOffsets} = await motion
 residentSpeechGesture(true,false,'greeting');const first=global.__NEIGHBOUR_RESIDENT_GESTURE__
 residentSpeechGesture(true,false,'greeting');assert.equal(global.__NEIGHBOUR_RESIDENT_GESTURE__,first)
 assert.deepEqual(gestureOffsets(first,first.start+first.duration+1300),gestureOffsets({kind:'speaking',start:first.start+first.duration,duration:2600,continuous:true},first.start+first.duration+1300))
 residentSpeechGesture(true,true,'celebrate');assert.equal(global.__NEIGHBOUR_RESIDENT_GESTURE__.kind,'care')
 residentSpeechGesture(false);assert.equal(global.__NEIGHBOUR_RESIDENT_GESTURE__,undefined)
})
test('Live2D arm motion only touches existing rig parameters, never drifts, restores and retains native animation',async()=>{
 const ts=require(path.resolve('.vendor/airi/node_modules/typescript')),gesture=await motion,gaze=await load('airi_overlay/resident-gaze-state.js')
 const exports={},media={matches:false},scope={exports,require:id=>id.includes('gaze-state')?gaze:gesture,matchMedia:()=>media,document:{hidden:false},performance:{now:()=>1300}}
 vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
 const p={ids:['ParamArmRA','ParamHandR','ParamBodyAngleY'],minimumValues:[-1,-1,-1],maximumValues:[1,1,1]},values={ParamArmRA:.2,ParamHandR:.1,ParamBodyAngleY:0},writes=[]
 const model={getModel:()=>({parameters:p}),getParameterValueById:key=>values[key]||0,setParameterValueById:(key,value)=>{values[key]=value;writes.push(key)}}
 const ctx={model,modelParameters:{value:Object.freeze({})}},plugin=exports.residentGesturePlugin()
 scope.__NEIGHBOUR_RESIDENT_GESTURE__={kind:'greeting',start:0,duration:3200}
 plugin(ctx);const arm=values.ParamArmRA;assert.notEqual(arm,.2)
 for(let i=0;i<1000;i++)plugin(ctx)
 assert.ok(Math.abs(values.ParamArmRA-arm)<1e-7);assert.ok(Object.values(values).every(Number.isFinite))
 assert.equal(writes.includes('ParamArmLA'),false);assert.equal(writes.some(x=>/Mouth|EyeLOpen|EyeROpen/.test(x)),false)
 values.ParamArmRA=.7;plugin(ctx);media.matches=true;plugin(ctx)
 assert.ok(Math.abs(values.ParamArmRA-.7)<1e-7,'must restore new authored animation, not an older baseline')
 assert.ok(Math.abs(values.ParamHandR-.1)<1e-7)
})
test('visibility return only resumes previously active camera, not off, denied, pending or settings',()=>{
 const panel=fs.readFileSync('airi_overlay/resident-service-panel.vue','utf8'),code=panel.match(/function resumeVisibleInteraction\(\) \{[\s\S]*?\n\}/)[0]
 for(const state of ['tracking','searching','off','unavailable','starting']){
  let calls=0
  const s={document:{hidden:true},gazeState:{value:state},resumeCameraOnVisible:false,automaticCameraAttempted:true,startDefaultInteraction:()=>calls++}
  vm.runInContext(code,vm.createContext(s));vm.runInContext('resumeVisibleInteraction()',s)
  s.document.hidden=false;vm.runInContext('resumeVisibleInteraction()',s);vm.runInContext('resumeVisibleInteraction()',s)
  assert.equal(calls,['tracking','searching'].includes(state)?1:0,state)
 }
 assert.match(panel,/addEventListener\('visibilitychange', resumeVisibleInteraction, true\)/)
 assert.match(panel,/removeEventListener\('visibilitychange', resumeVisibleInteraction, true\)/)
})
