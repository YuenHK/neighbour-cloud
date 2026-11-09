const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{pathToFileURL}=require('node:url')
const load=file=>import(pathToFileURL(path.resolve(file)).href)

test('brief welcome returns both arms to rest instead of holding them up throughout a conversation',async()=>{
 const {continuousWelcomeBody}=await load('airi_overlay/resident-gestures.js')
 let leftRest=0,rightRest=0
 for(let now=0;now<33000;now+=100){
  const p=continuousWelcomeBody(now),l=Math.abs(p.leftLowerArm[2]),r=Math.abs(p.rightLowerArm[2])
  if(now>3600)assert.ok(Math.max(l,r)<15,'both arms rest between invitations')
  assert.ok(p.rightUpperArm[2]<=5 && p.leftUpperArm[2]>=-5,'welcome must not force both upper arms over the head')
  if(l<15)leftRest++;if(r<15)rightRest++
 }
 assert.ok(leftRest>60&&rightRest>60,'both arms need real resting phases, rather than two permanently raised arms')
})

test('ambient gestures vary head tilt, nod and body while gaze remains directed to the resident',async()=>{
 const {residentAmbientOffsets}=await load('airi_overlay/resident-gestures.js')
 const samples=[0,1300,4500,11000,17000].map(t=>residentAmbientOffsets(t,'idle',false))
 for(const key of ['x','y','z','body'])assert.ok(new Set(samples.map(x=>x[key])).size>2,key)
 for(const t of [1300,4500,11000]){
  assert.equal(residentAmbientOffsets(t,'listen',true).x,0,'camera gaze wins over looking around')
  assert.ok(Math.abs(residentAmbientOffsets(t,'care',false).body)<=Math.abs(residentAmbientOffsets(t,'idle',false).body))
 }
 assert.equal(residentAmbientOffsets(NaN),undefined)
})

test('Live2D starts gently and adds only a small smooth fraction of an existing arm range; native motion and reduced-motion restore survive',async()=>{
 const ts=require(path.resolve('.vendor/airi/node_modules/typescript')),gesture=await load('airi_overlay/resident-gestures.js'),gaze=await load('airi_overlay/resident-gaze-state.js')
 let now=1300;const exports={},media={matches:false},scope={exports,require:id=>id.includes('gaze-state')?gaze:gesture,matchMedia:()=>media,document:{hidden:false,body:{dataset:{cloudView:'resident'}}},performance:{now:()=>now}}
 vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
 const ids=['ParamArmRA','ParamHandR'],values={ParamArmRA:.2,ParamHandR:0},writes=[]
 const model={getModel:()=>({parameters:{ids,minimumValues:[-1,-1],maximumValues:[1,1]}}),getParameterValueById:k=>values[k]||0,setParameterValueById:(k,v)=>{values[k]=v;writes.push(k)}}
 const plugin=exports.residentGesturePlugin(),ctx={model,modelParameters:{value:Object.freeze({})}}
 plugin(ctx);assert.ok(Math.abs(values.ParamArmRA-.2)<=.02,'first frame must not yank an arm towards its maximum')
 let previous=values.ParamArmRA
 for(let i=0;i<900;i++){
  now+=16;plugin(ctx);assert.ok(Math.abs(values.ParamArmRA-.2)<=.16);assert.ok(Math.abs(values.ParamArmRA-previous)<=.025);previous=values.ParamArmRA
 }
 assert.equal(writes.includes('ParamArmLA'),false)
 values.ParamArmRA=.6;plugin(ctx);media.matches=true;plugin(ctx);assert.ok(Math.abs(values.ParamArmRA-.6)<1e-7,'restore new authored pose')
})
