const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm')
const panel=fs.readFileSync('airi_overlay/resident-service-panel.vue','utf8')
const code=panel.match(/function startDefaultInteraction\(\) \{[\s\S]*?\n\}/)[0]
function fixture(overrides={}){
 const calls=[]
 const scope={cloudResident:true,gaze:{start:hands=>calls.push(hands)},avatarVisible:false,avatarMounted:false,
  automaticCameraAttempted:false,document:{hidden:false},location:{search:''},URLSearchParams,...overrides}
 vm.createContext(scope);vm.runInContext(code,scope)
 return {scope,calls,start:()=>vm.runInContext('startDefaultInteraction()',scope)}
}
test('default interaction waits for actual resident visibility and avatar readiness, then starts both once',()=>{
 const h=fixture();h.start();assert.deepEqual(h.calls,[])
 h.scope.avatarMounted=true;h.start();assert.deepEqual(h.calls,[])
 h.scope.avatarVisible=true;h.start();h.start();assert.deepEqual(h.calls,[true])
})
test('settings, hidden pages, native pages and explicit stopped intent never auto-start capture',()=>{
 for(const extra of [{location:{search:'?estate=1&settings=1'}},{document:{hidden:true}},
  {cloudResident:false},{automaticCameraAttempted:true},{gaze:undefined}]){
  const h=fixture({avatarVisible:true,avatarMounted:true,...extra});h.start();assert.deepEqual(h.calls,[])
 }
})
test('denied or unavailable capture has no automatic retry; entering a new page gets a new bounded attempt',()=>{
 const h=fixture({avatarVisible:true,avatarMounted:true});h.start();h.start();assert.deepEqual(h.calls,[true])
 const next=fixture({avatarVisible:true,avatarMounted:true});next.start();assert.deepEqual(next.calls,[true])
})
