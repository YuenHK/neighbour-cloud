const test=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs')
const moduleSource=fs.readFileSync('airi_overlay/cloud-session.js','utf8')
const moduleReady=import('data:text/javascript;base64,'+Buffer.from(moduleSource).toString('base64'))
const origin='https://neighbour.example'
const token=(label='resident')=>'header.'+Buffer.from(JSON.stringify({exp:300,sub:label})).toString('base64url')+'.signature'
const proof=(acceptance=false,role='staff')=>new Response(JSON.stringify({authenticated:true,storage_acceptance:acceptance,role}))
const flush=()=>new Promise(resolve=>setImmediate(resolve))

test('verified production identity alone mounts the UI and token never appears in status events',async()=>{
 const {createCloudSession}=await moduleReady
 const calls=[],states=[];let lookup,closed=0
 const session=createCloudSession({origin,now:()=>1000,onState:s=>states.push(s),onClear:()=>closed++,
  onReady:provider=>{lookup=provider},fetcher:async(url,init)=>{calls.push({url,init});return proof()}})
 assert.deepEqual(await session.accept(token()),{state:'ready',role:'staff'})
 assert.equal(calls[0].url,origin+'/api/v1/resident/session')
 assert.equal(calls[0].init.headers.Authorization,'Bearer '+token())
 assert.equal(calls[0].init.credentials,'omit');assert.equal(calls[0].init.redirect,'error')
 assert.equal(lookup().token,token());assert.doesNotMatch(JSON.stringify(states),/signature|header/)
 session.clear();assert.throws(()=>lookup());assert.equal(closed,2)
})

test('storage acceptance cannot mount a resident or retain a useable token',async()=>{
 const {createCloudSession}=await moduleReady;let mounts=0
 const session=createCloudSession({origin,now:()=>1000,fetcher:async()=>proof(true),onReady:()=>mounts++})
 assert.deepEqual(await session.accept(token()),{state:'storage_acceptance'})
 assert.equal(mounts,0);assert.throws(()=>session.token())
})

test('a browser-claimed role or failed backend response cannot unlock the UI',async()=>{
 const {createCloudSession}=await moduleReady
 for(const response of [proof(false,'admin'),new Response('{}'),new Response('{}',{status:401})]){
  let mounts=0
  const session=createCloudSession({origin,now:()=>1000,fetcher:async()=>response,onReady:()=>mounts++})
  assert.deepEqual(await session.accept(token('claimed-staff')),{state:'unavailable'});assert.equal(mounts,0)
 }
})

test('clear cancels pending identity and ignores a late backend proof',async()=>{
 const {createCloudSession}=await moduleReady;let finish,signal,mounts=0
 const session=createCloudSession({origin,now:()=>1000,onReady:()=>mounts++,fetcher:async(_url,init)=>{
  signal=init.signal;return new Promise(resolve=>{finish=resolve})
 }})
 const pending=session.accept(token());await flush();session.clear()
 assert.equal(signal.aborted,true);assert.deepEqual(await pending,{state:'cancelled'})
 finish(proof());await flush();assert.equal(mounts,0);assert.throws(()=>session.token())
})

test('a replacement login fences the previous user and malformed input never calls the backend',async()=>{
 const {createCloudSession}=await moduleReady;let finish,calls=0,mounts=0
 const session=createCloudSession({origin,now:()=>1000,onReady:()=>mounts++,fetcher:async()=>{
  calls++;return calls===1?new Promise(resolve=>{finish=resolve}):proof()
 }})
 assert.deepEqual(await session.accept('PRIVATE-MALFORMED'),{state:'unavailable'});assert.equal(calls,0)
 const old=session.accept(token('old'));await flush()
 assert.deepEqual(await session.accept(token('new')),{state:'ready',role:'staff'})
 assert.deepEqual(await old,{state:'cancelled'});finish(proof());await flush()
 assert.equal(session.token().token,token('new'));assert.equal(mounts,1)
})

test('a disposed resident frame cannot acquire the replacement Google identity',async()=>{
 const {createCloudSession}=await moduleReady;const providers=[]
 const session=createCloudSession({origin,now:()=>1000,fetcher:async()=>proof(),onReady:p=>{providers.push(p)}})
 await session.accept(token('first'));assert.equal(providers[0]().token,token('first'))
 await session.accept(token('next'));assert.equal(providers[1]().token,token('next'))
 assert.throws(()=>providers[0](),/cloud_sign_in_changed/)
})
