const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{pathToFileURL}=require('node:url'),{createRequire}=require('node:module')
const load=file=>import(pathToFileURL(path.resolve(file)).href)

test('continuous welcome waves never have a long idle gap and layer only onto arms, preserving conversational head and lips',async()=>{
 const {continuousWelcomeBody,continuousWelcomeLive2d}=await load('airi_overlay/resident-gestures.js')
 for(let now=0;now<=28000;now+=100){
  const pose=continuousWelcomeBody(now),gentle=continuousWelcomeBody(now,true),live=continuousWelcomeLive2d(now)
  assert.ok(Math.abs(pose.leftUpperArm[2])+Math.abs(pose.rightUpperArm[2])>10)
  assert.ok(Object.values(pose).flat().every(n=>Number.isFinite(n)&&Math.abs(n)<=120))
  assert.ok(Math.abs(gentle.rightUpperArm[2])<Math.abs(pose.rightUpperArm[2]))
  assert.ok(!Object.keys(pose).some(k=>/head|spine|chest|eye|mouth/i.test(k)))
  assert.ok(Object.keys(live).every(k=>/^Param(?:Arm|Hand|Shoulder)/.test(k)))
 }
 assert.notDeepEqual(continuousWelcomeBody(0),continuousWelcomeBody(2800))
 assert.equal(continuousWelcomeBody(NaN),undefined)
})

test('native VRM keeps waving with no gesture, while speaking and while nodding; it restores hidden or reduced-motion poses without drift',async()=>{
 const ts=require(path.resolve('.vendor/airi/node_modules/typescript')),three=createRequire(path.resolve('.vendor/airi/packages/stage-ui-three/package.json'))('three')
 const gesture=await load('airi_overlay/resident-gestures.js'),display=await load('airi_overlay/resident-display.js'),gaze=await load('airi_overlay/resident-gaze-state.js')
 let now=1200;const exports={},media={matches:false},doc={hidden:false,body:{dataset:{cloudView:'resident'}}}
 const scope={exports,require:id=>id==='three'?three:id.includes('resident-display')?display:id.includes('gaze-state')?gaze:gesture,document:doc,matchMedia:()=>media,performance:{now:()=>now}}
 const previous=global.document;global.document=doc
 try{
  vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-vrm-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
  const names=['head','chest','spine','leftShoulder','rightShoulder','leftUpperArm','rightUpperArm','leftLowerArm','rightLowerArm','leftHand','rightHand'],bones=Object.fromEntries(names.map(n=>[n,new three.Object3D()]))
  // Real models start from an authored arms-down pose, not identity. The
  // welcome pose must remain the same and restore that original on exit.
  bones.rightUpperArm.quaternion.setFromEuler(new three.Euler(.1, .2, 1.1))
  bones.leftUpperArm.quaternion.setFromEuler(new three.Euler(.1, -.2, -1.1))
  const baseline=Object.fromEntries(names.map(n=>[n,bones[n].quaternion.clone()]))
  const vrm={humanoid:{getNormalizedBoneNode:n=>bones[n]}},run=()=>{for(let i=0;i<100;i++)motion.update(vrm,1/60)},motion=exports.residentVrmGesture()
  run();assert.ok(bones.rightUpperArm.quaternion.angleTo(new three.Quaternion())>.1,'no active dialogue must still wave')
  const angles=gesture.continuousWelcomeBody(now).rightUpperArm.map(n=>n*Math.PI/180)
  assert.ok(bones.rightUpperArm.quaternion.angleTo(new three.Quaternion().setFromEuler(new three.Euler(...angles)))<1e-5,'authored idle must not push waving hands out of the close-up')
  const first=bones.rightUpperArm.quaternion.clone();for(let i=0;i<1000;i++)motion.update(vrm,1/60);assert.ok(first.angleTo(bones.rightUpperArm.quaternion)<1e-5)
  for(const kind of ['speaking','listen','care']){
   now+=1100;scope.__NEIGHBOUR_RESIDENT_GESTURE__={kind,start:now-650,duration:2600,continuous:kind==='speaking'};run()
   assert.ok(bones.rightUpperArm.quaternion.angleTo(new three.Quaternion())>.05,kind+' must not stop waves')
   assert.ok(bones.head.quaternion.angleTo(new three.Quaternion())>.0001,kind+' retains conversational head motion')
  }
  media.matches=true;motion.update(vrm,1/60);assert.ok(names.every(n=>bones[n].quaternion.angleTo(baseline[n])<1e-5))
  media.matches=false;delete scope.__NEIGHBOUR_RESIDENT_GESTURE__;run();doc.hidden=true;motion.update(vrm,1/60);assert.ok(names.every(n=>bones[n].quaternion.angleTo(baseline[n])<1e-5))
 }finally{global.document=previous}
})

test('extreme LED framing doubles source41 view size at both native and scaled CSS resolutions, without affecting ordinary phones or staff',async()=>{
 const {residentDisplayMagnification,isNarrowLedViewport}=await load('airi_overlay/resident-display.js')
 const previous={document:global.document,innerWidth:global.innerWidth,innerHeight:global.innerHeight}
 try{
  global.document={body:{dataset:{cloudView:'resident'}}}
  for(const [w,h,expected] of [[128,384,2],[256,768,2],[512,1536,2],[800,2400,2],[390,844,1],[768,1024,1],[1280,720,1],[0,768,1]]){
   global.innerWidth=w;global.innerHeight=h;assert.equal(residentDisplayMagnification(),expected,`${w}x${h}`);assert.equal(isNarrowLedViewport(w,h),expected===2)
  }
  global.innerWidth=256;global.innerHeight=768;global.document.body.dataset.cloudView='settings';assert.equal(residentDisplayMagnification(),1)
 }finally{Object.assign(global,previous)}
})

test('Live2D arm rig waves without an active gesture and throughout speaking, restores reduced motion, and never writes nonexistent arms',async()=>{
 const ts=require(path.resolve('.vendor/airi/node_modules/typescript')),gesture=await load('airi_overlay/resident-gestures.js'),gaze=await load('airi_overlay/resident-gaze-state.js')
 let now=1300;const exports={},media={matches:false},doc={hidden:false,body:{dataset:{cloudView:'resident'}}}
 const scope={exports,require:id=>id.includes('gaze-state')?gaze:gesture,matchMedia:()=>media,document:doc,performance:{now:()=>now}}
 vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
 const ids=['ParamArmRA','ParamHandR'],values={ParamArmRA:.1,ParamHandR:0},writes=[]
 const model={getModel:()=>({parameters:{ids,minimumValues:[-1,-1],maximumValues:[1,1]}}),getParameterValueById:k=>values[k]||0,setParameterValueById:(k,v)=>{values[k]=v;writes.push(k)}}
 const ctx={model,modelParameters:{value:Object.freeze({})}},plugin=exports.residentGesturePlugin()
 plugin(ctx);const arm=values.ParamArmRA;assert.notEqual(arm,.1)
 for(let i=0;i<1000;i++)plugin(ctx);assert.ok(Math.abs(values.ParamArmRA-arm)<1e-7)
 scope.__NEIGHBOUR_RESIDENT_GESTURE__={kind:'speaking',start:now-500,duration:2600,continuous:true};plugin(ctx);assert.notEqual(values.ParamArmRA,.1)
 assert.equal(writes.includes('ParamArmLA'),false);assert.ok(Object.values(values).every(Number.isFinite))
 media.matches=true;plugin(ctx);assert.ok(Math.abs(values.ParamArmRA-.1)<1e-7)
})

test('2x LED close-up centres an off-centre Live2D head instead of a wide lower-body accessory',async()=>{
 const {galleryFraming}=await load('airi_overlay/gallery-fit.js')
 const previous={document:global.document,innerWidth:global.innerWidth,innerHeight:global.innerHeight}
 try{
  global.document={body:{dataset:{cloudView:'resident'}}};global.innerWidth=256;global.innerHeight=768
  const vertices=[[100,0,300,0,300,500,100,500],[0,800,1000,800,1000,2000,0,2000]]
  const model={internalModel:{width:1000,height:2000,settings:{json:{}},coreModel:{getDrawableCount:()=>2,getDrawableOpacity:()=>1},getDrawableVertices:i=>vertices[i],localTransform:{apply:p=>p}}}
  const fit=galleryFraming(model,{width:256,height:768},{scale:1,x:0,y:0},'unaltered-model')
  assert.ok(Math.abs((200-500)*fit.scale+fit.x-128)<1e-7,'head should be centred without changing original model')
  assert.deepEqual(model.internalModel.settings.json,{})
 }finally{Object.assign(global,previous)}
})
