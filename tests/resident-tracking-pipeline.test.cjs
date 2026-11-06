const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
function load(overrides={}){
 const ts=require(path.resolve('.vendor/airi/node_modules/typescript'))
 const scope={exports:{},require:()=>({clearResidentGaze(){},selectResidentFace(){}}),
  document:{addEventListener(){},removeEventListener(){}},window:{addEventListener(){},removeEventListener(){}},
  performance:{now:()=>1000},setTimeout:()=>1,clearTimeout(){},Reflect,console,...overrides}
 vm.runInContext(ts.transpileModule(fs.readFileSync('airi_overlay/resident-gaze.js','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,vm.createContext(scope))
 return {ResidentGaze:scope.exports.ResidentGaze,scope}
}
test('inference schedules the remaining frame budget instead of adding a fixed 200ms wait',()=>{
 let delay
 const {ResidentGaze}=load({setTimeout:(_fn,ms)=>{delay=ms;return 1}}),gaze=new ResidentGaze(()=>{})
 gaze.frameStarted=970;gaze.worker={};gaze.acceptFaces({detections:[],width:384,height:216},gaze.generation)
 assert.ok(delay>=0&&delay<=40,'processing time must count towards a roughly 16fps budget')
})
test('camera bitmap preserves the actual wide-camera aspect ratio and is bounded',async()=>{
 let options,posted
 const {ResidentGaze}=load({createImageBitmap:async(_video,value)=>{options=value;return {width:value.resizeWidth,height:value.resizeHeight,close(){}}}})
 const gaze=new ResidentGaze(()=>{})
 gaze.video={videoWidth:1280,videoHeight:720,currentTime:1,readyState:2}
 gaze.worker={postMessage:value=>{posted=value}}
 await gaze.frame(gaze.generation)
 assert.equal(options.resizeWidth,384);assert.equal(options.resizeHeight,216)
 assert.equal(posted.type,'frame')
})
