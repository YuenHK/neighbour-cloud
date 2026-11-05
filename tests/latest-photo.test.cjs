const test=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs')
const vm=require('node:vm')
function fixture(){
 const jobs=[],created=[],revoked=[],shown=[]
 const context={AbortController,AbortSignal,fetch:()=>{},URL:{createObjectURL:blob=>{const url='blob:'+blob;created.push(url);return url},revokeObjectURL:url=>revoked.push(url)}}
 vm.runInNewContext(fs.readFileSync('edge_hub/static/latest-photo.js','utf8'),context)
 const view=new context.NeighbourLatestPhoto('blob:first',()=>new Promise(resolve=>jobs.push(resolve)),context.URL)
 return {view,jobs,created,revoked,shown,apply:url=>shown.push(url)}
}
const response=id=>({ok:true,blob:async()=>id})
test('late earlier photo cannot overwrite the latest chosen side',async()=>{
 const h=fixture()
 const left=h.view.load('/api/v1/patrol/events/a/photo?side=left',{},h.apply)
 const right=h.view.load('/api/v1/patrol/events/a/photo?side=right',{},h.apply)
 h.jobs[1](response('right'));assert.equal(await right,true)
 h.jobs[0](response('left'));assert.equal(await left,false)
 assert.deepEqual(h.shown,['blob:right']);assert.deepEqual(h.created,['blob:right'])
 h.view.close();assert.deepEqual(h.revoked,['blob:first','blob:right'])
})
test('closing during fetch suppresses late pixels and releases the current URL',async()=>{
 const h=fixture();const task=h.view.load('/api/v1/patrol/events/a/photo',{},h.apply)
 h.view.close();h.jobs[0](response('late'));assert.equal(await task,false)
 assert.deepEqual(h.created,[]);assert.deepEqual(h.shown,[]);assert.deepEqual(h.revoked,['blob:first'])
})
test('a failed new view retains the current image for verification',async()=>{
 const h=fixture();const task=h.view.load('/api/v1/patrol/events/a/photo',{},h.apply)
 h.jobs[0]({ok:false});await assert.rejects(task,/photo_unavailable/)
 assert.deepEqual(h.revoked,[]);assert.equal(h.view.activeUrl,'blob:first')
})

test('default photo requests use the cloud module identity adapter rather than native fetch',async()=>{
 const calls=[],shown=[]
 const context={AbortController,AbortSignal,URL:{createObjectURL:()=> 'blob:left',revokeObjectURL:()=>{}},
  fetch:()=>{throw new Error('unidentified_native_fetch')},
  cloudFetch:async(...args)=>{calls.push(args);return response('left')}}
 // CloudAdminAssets adds a lexical `cloudFetch as fetch` import to this native module.
 vm.runInNewContext('const fetch = cloudFetch;\n'+fs.readFileSync('edge_hub/static/latest-photo.js','utf8'),context)
 const view=new context.NeighbourLatestPhoto('blob:first')
 assert.equal(await view.load('/api/v1/patrol/events/a/photo?side=left',{},url=>shown.push(url)),true)
 assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/v1/patrol/events/a/photo?side=left')
 assert.deepEqual(shown,['blob:left']);view.close()
})
