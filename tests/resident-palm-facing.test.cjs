const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{pathToFileURL}=require('node:url'),{createRequire}=require('node:module')
const req=createRequire(path.resolve('.vendor/airi/packages/stage-ui-three/package.json'))
const THREE=req('three'),{VRMHumanoid}=req('@pixiv/three-vrm'),ts=require(path.resolve('.vendor/airi/node_modules/typescript'))
const load=file=>import(pathToFileURL(path.resolve(file)).href)
function rig(data){
 const nodes=data.nodes.map(n=>{const b=new THREE.Object3D();b.name=n.name||'';if(n.translation)b.position.fromArray(n.translation);if(n.rotation)b.quaternion.fromArray(n.rotation);if(n.scale)b.scale.fromArray(n.scale);if(n.matrix){b.matrix.fromArray(n.matrix);b.matrix.decompose(b.position,b.quaternion,b.scale)}return b})
 data.nodes.forEach((n,i)=>(n.children||[]).forEach(c=>nodes[i].add(nodes[c])))
 const scene=new THREE.Group();data.roots.forEach(i=>scene.add(nodes[i]));scene.updateMatrixWorld(true)
 const bones={};for(const b of Array.isArray(data.humanBones)?data.humanBones:Object.entries(data.humanBones).map(([bone,b])=>({bone,...b})))bones[b.bone]={node:nodes[b.node]}
 const humanoid=new VRMHumanoid(bones);scene.add(humanoid.normalizedHumanBonesRoot)
 // Same VRM0 facing conversion used by the native loader. Camera is in front.
 if(data.version.startsWith('0'))scene.rotation.y=Math.PI
 scene.updateMatrixWorld(true)
 return {humanoid,scene,meta:{metaVersion:data.version.startsWith('0')?'0':'1'}}
}
test('actual Miku rigs present an open palm to the viewer throughout each raised-hand phase, including gentle care',async()=>{
 const gesture=await load('airi_overlay/resident-gestures.js'),display=await load('airi_overlay/resident-display.js'),gaze=await load('airi_overlay/resident-gaze-state.js')
 for(const data of JSON.parse(fs.readFileSync('tests/fixtures/vrm-miku-hand-rigs.json','utf8'))){
  let now=0;const doc={hidden:false,body:{dataset:{cloudView:'resident'}}},media={matches:false},exports={}
  const scope={exports,require:id=>id==='three'?THREE:id.includes('resident-display')?display:id.includes('gaze-state')?gaze:gesture,document:doc,matchMedia:()=>media,performance:{now:()=>now}}
  vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-vrm-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
  const vrm=rig(data),motion=exports.residentVrmGesture(),camera=new THREE.Vector3(0,1.4,3);let raised=0,minDot=1,rests=0
  for(const kind of ['idle','care']){
   if(kind==='care')scope.__NEIGHBOUR_RESIDENT_GESTURE__={kind,start:now,duration:3300,continuous:true}
   for(let i=0;i<1000;i++){
    now+=1000/60;motion.update(vrm,1/60);vrm.humanoid.update();vrm.scene.updateMatrixWorld(true)
    if(i<100||i%6)continue
    const pose=gesture.continuousWelcomeBody(now,kind==='care',vrm.meta.metaVersion)
    for(const side of ['left','right']){
     const at=n=>vrm.humanoid.getRawBoneNode(side+n).getWorldPosition(new THREE.Vector3())
     if(Math.abs(pose[side+'LowerArm'][2])<15){assert.ok(at('Hand').y<vrm.humanoid.getRawBoneNode('head').getWorldPosition(new THREE.Vector3()).y-.3,`${data.id}/${side}: other hand really rests below chest`);rests++}
     if(Math.abs(pose[side+'LowerArm'][2])<135)continue
     const wrist=at('Hand'),index=at('IndexProximal'),pinky=at('LittleProximal')
     const normal=index.sub(wrist).cross(pinky.sub(wrist)).normalize().multiplyScalar(side==='left'?1:-1)
     const dot=normal.dot(camera.clone().sub(wrist).normalize());minDot=Math.min(minDot,dot);raised++
     assert.ok(dot>.8,`${data.id}/${kind}/${side}: palm facing viewer=${dot}, expected >0.8`)
    }
   }
  }
  assert.ok(raised>150,`${data.id}: both hand cycles must be exercised`)
  assert.ok(rests>80,`${data.id}: format conversion must preserve the resting arm`)
  media.matches=true;motion.update(vrm);assert.ok(vrm.humanoid.getNormalizedBoneNode('rightHand').quaternion.angleTo(new THREE.Quaternion())<1e-5,'reduced motion restores authored wrist')
 }
})
