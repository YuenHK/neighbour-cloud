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

function palmFacing(vrm,side,camera){
 const at=n=>vrm.humanoid.getRawBoneNode(side+n).getWorldPosition(new THREE.Vector3())
 const wrist=at('Hand'),index=at('IndexProximal'),little=at('LittleProximal')
 // The previous index×little sign measured the dorsal surface. The user
 // identified its visible fingernail/back side in the barrier44 screenshot.
 const palm=little.sub(wrist).cross(index.sub(wrist)).normalize().multiplyScalar(side==='left'?1:-1)
 return palm.dot(camera.clone().sub(wrist).normalize())
}

test('palm measurement rejects the visually confirmed barrier44 back-facing reference pose',()=>{
 const data=JSON.parse(fs.readFileSync('tests/fixtures/vrm-miku-hand-rigs.json','utf8'))[0],vrm=rig(data)
 const backPose={rightShoulder:[0,.7,.8],rightUpperArm:[-2,3,0],rightLowerArm:[0,4,140],rightHand:[-75,4,0],leftUpperArm:[0,0,72],leftLowerArm:[0,0,-5]}
 for(const [name,angles]of Object.entries(backPose))vrm.humanoid.getNormalizedBoneNode(name).quaternion.setFromEuler(new THREE.Euler(...angles.map(n=>n*Math.PI/180)))
 vrm.humanoid.update();vrm.scene.updateMatrixWorld(true)
 assert.ok(palmFacing(vrm,'right',new THREE.Vector3(0,1.4,3))<-.8,'known back-facing pose must never be labelled palm-facing again')
})
test('actual Miku rigs keep palms facing viewers during occasional waves and both hands lowered during care',async()=>{
 const gesture=await load('airi_overlay/resident-gestures.js'),display=await load('airi_overlay/resident-display.js'),gaze=await load('airi_overlay/resident-gaze-state.js')
 for(const data of JSON.parse(fs.readFileSync('tests/fixtures/vrm-miku-hand-rigs.json','utf8'))){
  let now=0;const doc={hidden:false,body:{dataset:{cloudView:'resident'}}},media={matches:false},exports={}
  const scope={exports,require:id=>id==='three'?THREE:id.includes('resident-display')?display:id.includes('gaze-state')?gaze:gesture,document:doc,matchMedia:()=>media,performance:{now:()=>now}}
  vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-vrm-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
  const vrm=rig(data),motion=exports.residentVrmGesture(),camera=new THREE.Vector3(0,1.4,3),director=gesture.createResidentMotionDirector();let raised=0,minDot=1,rests=0
  for(const kind of ['idle','care']){
   if(kind==='care')scope.__NEIGHBOUR_RESIDENT_GESTURE__={kind,start:now,duration:3300,continuous:true}
   for(let i=0;i<(kind==='idle'?14400:1000);i++){
    now+=1000/60;const plan=director.update(now,scope.__NEIGHBOUR_RESIDENT_GESTURE__);motion.update(vrm,1/60);vrm.humanoid.update();vrm.scene.updateMatrixWorld(true)
    if(i<100||i%6)continue
    const pose=gesture.continuousWelcomeBody(now,kind==='care',vrm.meta.metaVersion,plan)
    for(const side of ['left','right']){
     const at=n=>vrm.humanoid.getRawBoneNode(side+n).getWorldPosition(new THREE.Vector3())
     if(Math.abs(pose[side+'LowerArm'][2])<15){assert.ok(at('Hand').y<vrm.humanoid.getRawBoneNode('head').getWorldPosition(new THREE.Vector3()).y-.3,`${data.id}/${side}: other hand really rests below chest`);rests++}
     if(Math.abs(pose[side+'LowerArm'][2])<135)continue
     const dot=palmFacing(vrm,side,camera);minDot=Math.min(minDot,dot);raised++
     assert.ok(dot>.8,`${data.id}/${kind}/${side}: palm facing viewer=${dot}, expected >0.8`)
     assert.ok(at('IndexProximal').y>at('Hand').y+.02,`${data.id}/${side}: fingers must point upward for an open greeting, not down the sleeve`)
     const head=vrm.humanoid.getRawBoneNode('head').getWorldPosition(new THREE.Vector3())
     assert.ok(Math.abs(at('Hand').x-head.x)>.14,`${data.id}/${side}: raised wrist must clear the face instead of resting against the temple`)
    }
   }
  }
  assert.ok(raised>70,`${data.id}: both hand cycles must be exercised`)
  assert.ok(rests>80,`${data.id}: format conversion must preserve the resting arm`)
  media.matches=true;motion.update(vrm);assert.ok(vrm.humanoid.getNormalizedBoneNode('rightHand').quaternion.angleTo(new THREE.Quaternion())<1e-5,'reduced motion restores authored wrist')
 }
})
