const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs')
const load=file=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(file)).toString('base64'))
const pcm=load(process.env.PCM_TEST_SOURCE||'airi_overlay/resident-pcm.js')
function context(){
 const graph=[];let id=0
 const node=kind=>({id:++id,kind,connect(to){graph.push([this,to]);return to},disconnect(){this.disconnected=true},start(){this.started=true},stop(){this.stopped=true}})
 return {graph,state:'running',currentTime:0,destination:node('output'),resume:async()=>{},createGain:()=>node('analysis'),createBuffer:(_,n,r)=>({duration:n/r,getChannelData:()=>new Float32Array(n)}),createBufferSource:()=>node('pcm')}
}
test('multi-chunk utterance has one stable analysis bus, one audible edge per chunk and identity-scoped cleanup',async()=>{
 const {ResidentPcm}=await pcm,ctx=context(),events=[]
 const original=global.dispatchEvent;global.dispatchEvent=e=>{events.push(e);return true}
 try{
  const frame='data: '+JSON.stringify({audio:Buffer.alloc(512).toString('base64')})+'\n\n'
  const fetcher=async()=>new Response(frame.repeat(4)+'data: {"done":true}\n\n')
  const player=new ResidentPcm({context:ctx,fetcher});player.write('第一句');player.write('第二句');await player.chain
  const starts=events.filter(e=>e.type==='resident-pcm-node')
  assert.equal(starts.length,1);assert.equal(starts[0].detail.source.kind,'analysis')
  const bus=starts[0].detail.source
  assert.equal(ctx.graph.filter(([from,to])=>from.kind==='pcm'&&to===ctx.destination).length,8)
  assert.equal(ctx.graph.filter(([from,to])=>from.kind==='pcm'&&to===bus).length,8)
  assert.equal(ctx.graph.filter(([from,to])=>from===bus&&to===ctx.destination).length,0,'analysis must not double audible output')
  player.cancel();player.cancel()
  assert.equal(events.filter(e=>e.type==='resident-pcm-ended').length,1)
  assert.equal(events.at(-1).detail.source,bus);assert.equal(bus.disconnected,true)
  const next=new ResidentPcm({context:ctx,fetcher});next.write('下一位');await next.chain
  assert.notEqual(events.filter(e=>e.type==='resident-pcm-node').at(-1).detail.source,bus);next.cancel()
 }finally{global.dispatchEvent=original}
})
test('analysis failure leaves voice playback and blank-line filtering intact',async()=>{
 const {ResidentPcm}=await pcm,ctx=context();ctx.createGain=()=>{throw Error('analysis unavailable')};let failures=0,calls=0
 const player=new ResidentPcm({context:ctx,failed:()=>failures++,fetcher:async()=>{calls++;return new Response('data: '+JSON.stringify({audio:Buffer.alloc(512).toString('base64')})+'\n\ndata: {"done":true}\n\n')}})
 player.write('\n ');player.write('保留原聲線');await player.chain
 assert.equal(calls,1);assert.equal(failures,0);assert.equal(ctx.graph.filter(([,to])=>to===ctx.destination).length,1);player.cancel()
})
test('speech gestures last beyond the first sentence and clear on audio end without storing conversation',async()=>{
 const {residentSpeechGesture,gestureOffsets}=await load('airi_overlay/resident-gestures.js')
 residentSpeechGesture(true);const value=global.__NEIGHBOUR_RESIDENT_GESTURE__
 assert.ok(gestureOffsets(value,value.start+value.duration*3.25))
 residentSpeechGesture(false);assert.equal(global.__NEIGHBOUR_RESIDENT_GESTURE__,undefined)
})
test('VRM gestures preserve the idle pose, do not accumulate rotation and respect reduced motion',async()=>{
 const path=require('node:path'),vm=require('node:vm'),{createRequire}=require('node:module')
 const ts=fs.existsSync('.vendor/airi/node_modules/typescript')?require(path.resolve('.vendor/airi/node_modules/typescript')):require('typescript')
 const three=fs.existsSync('.vendor/airi/packages/stage-ui-three/package.json')?createRequire(path.resolve('.vendor/airi/packages/stage-ui-three/package.json'))('three'):require('three')
 const gestures=await load('airi_overlay/resident-gestures.js')
 const output=ts.transpileModule(fs.readFileSync('airi_overlay/cloud-vrm-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const media={matches:false},exports={},scope={exports,require:id=>id==='three'?three:gestures,matchMedia:()=>media,document:{hidden:false},performance:{now:()=>1000}}
 const ctx=vm.createContext(scope);vm.runInContext(output,ctx)
 const head=new three.Object3D(),chest=new three.Object3D(),idle=new three.Quaternion().setFromEuler(new three.Euler(.1,.2,.3))
 head.quaternion.copy(idle);chest.quaternion.copy(idle)
 const vrm={humanoid:{getNormalizedBoneNode:name=>({head,chest}[name])}},driver=exports.residentVrmGesture()
 ctx.__NEIGHBOUR_RESIDENT_GESTURE__={kind:'speaking',start:0,duration:2600}
 for(let i=0;i<1000;i++)driver.update(vrm)
 assert.ok(head.quaternion.angleTo(idle)>.005);assert.ok(head.quaternion.angleTo(idle)<.15,'rotation accumulated beyond gentle gesture')
 media.matches=true;driver.update(vrm);assert.ok(head.quaternion.angleTo(idle)<1e-7)
 media.matches=false;driver.update(vrm)
 const newIdle=new three.Quaternion().setFromEuler(new three.Euler(.2,.1,.1));head.quaternion.copy(newIdle)
 driver.update(vrm);driver.restore();assert.ok(head.quaternion.angleTo(newIdle)<1e-7,'new native animation was overwritten')
 assert.ok(chest.quaternion.angleTo(idle)<1e-7)
})

test('conversational limbs animate shoulders, elbows and wrists, blend back, and never touch locomotion or mouth',async()=>{
 const path=require('node:path'),vm=require('node:vm'),{createRequire}=require('node:module')
 const ts=fs.existsSync('.vendor/airi/node_modules/typescript')?require(path.resolve('.vendor/airi/node_modules/typescript')):require('typescript')
 const three=fs.existsSync('.vendor/airi/packages/stage-ui-three/package.json')?createRequire(path.resolve('.vendor/airi/packages/stage-ui-three/package.json'))('three'):require('three')
 const gestures=await load('airi_overlay/resident-gestures.js'),exports={},media={matches:false}
 const scope={exports,require:id=>id==='three'?three:gestures,matchMedia:()=>media,document:{hidden:false},performance:{now:()=>1000}}
 vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-vrm-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
 const names=['head','chest','spine','leftShoulder','rightShoulder','leftUpperArm','rightUpperArm','leftLowerArm','rightLowerArm','leftHand','rightHand','hips','leftUpperLeg','rightUpperLeg']
 const bones=Object.fromEntries(names.map(name=>[name,new three.Object3D()]));let mouthWrites=0
 const idle=new three.Quaternion().setFromEuler(new three.Euler(.03,.02,.01));Object.values(bones).forEach(b=>b.quaternion.copy(idle))
 const vrm={humanoid:{getNormalizedBoneNode:name=>bones[name]},expressionManager:{setValue(){mouthWrites++}}},driver=exports.residentVrmGesture()
 scope.__NEIGHBOUR_RESIDENT_GESTURE__={kind:'greeting',start:0,duration:2300}
 for(let i=0;i<600;i++)driver.update(vrm,1/60)
 assert.ok(bones.rightUpperArm.quaternion.angleTo(idle)>.25,'greeting has no visible arm raise')
 assert.ok(bones.rightLowerArm.quaternion.angleTo(idle)>.25,'greeting has no elbow bend')
 assert.ok(bones.rightHand.quaternion.angleTo(idle)>.15,'greeting has no wrist movement')
 for(const name of ['hips','leftUpperLeg','rightUpperLeg'])assert.ok(bones[name].quaternion.equals(idle),'locomotion changed')
 assert.equal(mouthWrites,0)
 const previous=bones.rightUpperArm.quaternion.clone();delete scope.__NEIGHBOUR_RESIDENT_GESTURE__
 driver.update(vrm,1/60)
 assert.ok(bones.rightUpperArm.quaternion.angleTo(previous)<.15,'arm snapped when speech/gesture ended')
 for(let i=0;i<300;i++)driver.update(vrm,1/60)
 for(const name of names)assert.ok(bones[name].quaternion.angleTo(idle)<1e-6,`${name} did not return to native pose`)
 scope.__NEIGHBOUR_RESIDENT_GESTURE__={kind:'speaking',start:0,duration:2600,continuous:true}
 for(let i=0;i<200;i++)driver.update(vrm,1/60)
 media.matches=true;driver.update(vrm,1/60)
 Object.values(bones).forEach(b=>assert.ok(b.quaternion.angleTo(idle)<1e-6))
 assert.doesNotThrow(()=>driver.update({humanoid:{getNormalizedBoneNode:()=>undefined}},1/60))
})

test('body speech uses alternating emphasis and quiet beats instead of repeating the greeting wave',async()=>{
 const {bodyGestureOffsets}=await load('airi_overlay/resident-gestures.js')
 assert.equal(typeof bodyGestureOffsets,'function')
 const gesture={kind:'speaking',start:0,duration:2600,continuous:true}
 const a=bodyGestureOffsets(gesture,1300),b=bodyGestureOffsets(gesture,3900),quiet=bodyGestureOffsets(gesture,6500)
 assert.ok(Math.abs(a.rightUpperArm[2])>Math.abs(a.leftUpperArm[2]))
 assert.ok(Math.abs(b.leftUpperArm[2])>Math.abs(b.rightUpperArm[2]))
 assert.ok(Math.abs(quiet.rightUpperArm[2])<Math.abs(a.rightUpperArm[2])*.5)
 assert.equal(bodyGestureOffsets({...gesture,start:NaN},1000),undefined)
})
