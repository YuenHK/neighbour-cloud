const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs'),vm=require('node:vm'),{pathToFileURL}=require('node:url'),{createRequire}=require('node:module')
const load=file=>import(pathToFileURL(path.resolve(file)).href)
test('LED viewport threshold includes smaller displays but not ordinary phones, landscape or invalid dimensions',async()=>{
 const {isLedViewport}=await load('airi_overlay/resident-display.js')
 for(const [w,h,expected] of [[256,768,true],[192,640,true],[128,384,true],[256,769,false],[257,768,false],[390,844,false],[768,256,false],[0,768,false],[-1,2,false],[NaN,768,false]]) assert.equal(isLedViewport(w,h),expected,`${w}x${h}`)
})
test('LED Live2D framing contains original models without changing author metadata and reverts outside LED',async()=>{
 const original={document:global.document,innerWidth:global.innerWidth,innerHeight:global.innerHeight}
 try{
  global.document={body:{dataset:{cloudView:'resident'}}};global.innerWidth=256;global.innerHeight=768
  const {galleryFraming}=await load('airi_overlay/gallery-fit.js')
  const model={internalModel:{width:1000,height:2000,settings:{json:{}},coreModel:{getDrawableCount:()=>1,getDrawableOpacity:()=>1},getDrawableVertices:()=>[0,0,1000,2000],localTransform:{apply:p=>p}}},fallback=Object.freeze({scale:9,x:400,y:-200})
  const value=galleryFraming(model,{width:248,height:480},fallback,'user-own-model')
  assert.notEqual(value,fallback);assert.ok(value.scale*2000<480);assert.ok(value.scale*1000<248)
  assert.deepEqual(model.internalModel.settings.json,{})
  global.innerWidth=1280;global.innerHeight=720;assert.equal(galleryFraming(model,{width:390,height:500},fallback,'user-own-model'),fallback)
  global.innerWidth=256;global.document.body.dataset.cloudView='settings';assert.equal(galleryFraming(model,{width:248,height:480},fallback),fallback)
 }finally{Object.assign(global,original)}
})
test('VRM LED full-body fitting leaves camera and saved preferences intact, has no drift and restores on resize',async()=>{
 const ts=require(path.resolve('.vendor/airi/node_modules/typescript')),three=createRequire(path.resolve('.vendor/airi/packages/stage-ui-three/package.json'))('three')
 const exports={},doc={body:{dataset:{cloudView:'resident'}}},display=await load('airi_overlay/resident-display.js'),gesture=await load('airi_overlay/resident-gestures.js'),gaze=await load('airi_overlay/resident-gaze-state.js')
 const original={document:global.document,innerWidth:global.innerWidth,innerHeight:global.innerHeight}
 global.document=doc;global.innerWidth=256;global.innerHeight=768
 try{
  const scope={exports,require:id=>id==='three'?three:id.includes('resident-display')?display:id.includes('gaze-state')?gaze:gesture,document:doc,innerWidth:256,innerHeight:768}
  vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/cloud-vrm-gestures.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
  const root=new three.Group(),model=new three.Group();root.add(model);root.position.set(2,4,0);model.add(new three.Mesh(new three.BoxGeometry(1,2,.1),new three.MeshBasicMaterial()))
  const camera=new three.PerspectiveCamera(40,256/480,.01,100);camera.position.set(0,1,3);camera.lookAt(0,1,0);camera.updateMatrixWorld(true)
  const before={position:root.position.clone(),scale:root.scale.clone(),camera:camera.position.clone(),quaternion:camera.quaternion.clone()};const fit=exports.residentVrmDisplay()
  fit.update({scene:model},camera)
  assert.ok(root.position.equals(before.position)&&root.scale.equals(before.scale),'view fitting must not disturb VRM physics transforms')
  assert.equal(camera.view?.enabled,true)
  const position=root.position.clone(),scale=root.scale.clone(),box=new three.Box3().setFromObject(model)
  for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){const p=new three.Vector3(x,y,z).project(camera);assert.ok(Math.abs(p.x)<.9&&Math.abs(p.y)<.9,JSON.stringify(p))}
  for(let i=0;i<500;i++)fit.update({scene:model},camera)
  assert.ok(root.position.equals(position)&&root.scale.equals(scale));assert.ok(camera.position.equals(before.camera)&&camera.quaternion.equals(before.quaternion))
  global.innerWidth=1280;global.innerHeight=720;scope.innerWidth=1280;scope.innerHeight=720;fit.update({scene:model},camera)
  assert.ok(root.position.equals(before.position)&&root.scale.equals(before.scale))
  assert.equal(camera.view,null)
 }finally{Object.assign(global,original)}
})
