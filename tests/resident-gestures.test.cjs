const assert=require('node:assert/strict'),test=require('node:test'),path=require('node:path'),{pathToFileURL}=require('node:url')
test('resident gestures are bounded, return to rest and never alter saved pose or lips',async()=>{
 const {residentGesture,gestureOffsets}=await import(pathToFileURL(path.resolve('airi_overlay/resident-gestures.js')))
 const {residentGesturePlugin}=await import(pathToFileURL(path.resolve('airi_overlay/cloud-gestures.ts')))
 const original={performance:global.performance,document:global.document,matchMedia:global.matchMedia}
 let now=1000,reduced=false
 Object.defineProperty(global,'performance',{configurable:true,value:{now:()=>now}})
 global.document={hidden:false};global.matchMedia=()=>({get matches(){return reduced}})
 try{
  for(const kind of ['greeting','listen','speaking','care']){
   const state={kind,start:1000,duration:2400}
   for(let n=0;n<=24;n++){
    const value=gestureOffsets(state,1000+n*100)
    assert.ok(value&&Object.values(value).every(x=>Number.isFinite(x)&&Math.abs(x)<=5))
   }
   assert.equal(gestureOffsets(state,4000),undefined)
  }
  const pose=Object.freeze({angleX:3,angleY:2,angleZ:1,bodyAngleZ:0})
  const saved=JSON.stringify(pose),applied={}
  const plugin=residentGesturePlugin()
  residentGesture('listen');now=1600
  plugin({modelParameters:{value:pose},model:{setParameterValueById:(key,value)=>{applied[key]=value}}})
  assert.notEqual(applied.ParamAngleY,pose.angleY)
  assert.equal(JSON.stringify(pose),saved)
  assert.deepEqual(Object.keys(applied).sort(),['ParamAngleX','ParamAngleY','ParamAngleZ','ParamBodyAngleZ'].sort())
  reduced=true;plugin({modelParameters:{value:pose},model:{setParameterValueById:(key,value)=>{applied[key]=value}}})
  assert.equal(applied.ParamAngleY,pose.angleY)
  residentGesture('clear');assert.equal(global.__NEIGHBOUR_RESIDENT_GESTURE__,undefined)
 }finally{
  Object.defineProperty(global,'performance',{configurable:true,value:original.performance})
  global.document=original.document;global.matchMedia=original.matchMedia
 }
})
