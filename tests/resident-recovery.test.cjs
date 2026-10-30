const test=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs')
const source=import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync('airi_overlay/resident-recovery.js')).toString('base64'))

test('maintenance refusal retries the original intent once only after read-only readiness',async()=>{
 const {recoveringFetch}=await source
 const calls=[];let probes=0
 const body=JSON.stringify({submission_id:'a'.repeat(32),messages:[{role:'user',content:'synthetic'}]})
 const fetch=recoveringFetch({fetch:async(path,init)=>{
  calls.push({path,body:init.body})
  if(path.endsWith('/session'))return new Response('{}',{status:++probes===2?200:503})
  return calls.length===1?Response.json({code:'service_maintenance',operation_outcome:'not_attempted'},{status:503}):new Response('{}')
 }},{wait:async()=>{}})
 assert.equal((await fetch('/api/v1/resident/chat',{method:'POST',body})).status,200)
 assert.equal(calls.filter(x=>x.path.endsWith('/chat')).length,2)
 assert.ok(calls.filter(x=>x.path.endsWith('/chat')).every(x=>x.body===body))
})

test('unknown storage failure and lost network acknowledgement never replay',async()=>{
 const {recoveringFetch}=await source
 let calls=0
 const fetch=recoveringFetch({fetch:async()=>{calls++;return Response.json({code:'storage_unavailable',operation_outcome:'unknown'},{status:503})}})
 assert.equal((await fetch('/api/v1/resident/chat',{method:'POST',body:'same'})).status,503)
 assert.equal(calls,1)
 const lost=recoveringFetch({fetch:async()=>{calls++;throw Error('lost acknowledgement')}})
 await assert.rejects(lost('/api/v1/resident/chat',{method:'POST',body:'same'}))
 assert.equal(calls,2)
})

test('initialization recovery shares a task, stops after two attempts, and cancels on close',async()=>{
 const {InputRecovery}=await source
 const recovery=new InputRecovery({wait:async()=>{}})
 let calls=0
 const work=()=>{calls++;throw Error('offline')}
 const first=recovery.run('vad',work)
 assert.equal(recovery.run('vad',work),first)
 assert.equal(await first,false)
 assert.equal(calls,2)
 assert.equal(await recovery.run('vad',work),false)
 recovery.close()
 assert.equal(await recovery.run('other',work),false)
 assert.equal(calls,2)
})

test('boundary authentication failure can renew once without changing body or replaying other failures',async()=>{
 const {recoveringFetch}=await source
 let calls=0,renewed=0
 const fetch=recoveringFetch({fetch:async(_path,init)=>{assert.equal(init.body,'unchanged');return new Response('{}',{status:++calls===1?401:200})}},{renew:async()=>{renewed++;return true}})
 assert.equal((await fetch('/api/v1/resident/chat',{method:'POST',body:'unchanged'})).status,200)
 assert.equal(calls,2);assert.equal(renewed,1)
})
