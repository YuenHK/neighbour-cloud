const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor

test('the real resident entry installs auth before importing Vue and clears it on exit',async()=>{
 const source=fs.readFileSync('deploy/cloud/web/frame-entry.js','utf8').replace(/^import .*\n/gm,'').replace('await import(entry)','await load(entry)')
 const global={}, events={}, order=[];let clears=0
 const transport={clearAuth(){clears++}}
 const document={querySelector(){return {content:'/assets/resident-123.js'}},body:{replaceChildren(){assert.fail('entry should load')}}}
 const bridge=async()=>{order.push('identity');return {token:'h.p.s',expiresAtMs:Date.now()+300000}}
 const make=options=>{assert.equal(options.tokenProvider().token,'h.p.s');order.push('transport');return transport}
 const load=async path=>{assert.equal(global.__NEIGHBOUR_CLOUD__,true);assert.equal(global.__NEIGHBOUR_CLOUD_TRANSPORT__,transport);assert.equal(path,'/assets/resident-123.js');order.push('Vue')}
 await new AsyncFunction('createCloudTransport','frameIdentity','globalThis','window','parent','location','document','load',source)(make,bridge,global,{addEventListener(name,fn){events[name]=fn}},{},{origin:'https://neighbour.example'},document,load)
 assert.deepEqual(order,['identity','transport','Vue']);events.pagehide();assert.equal(clears,1)
})

test('a failed frame identity never imports Vue or obtains a provider fallback',async()=>{
 const source=fs.readFileSync('deploy/cloud/web/frame-entry.js','utf8').replace(/^import .*\n/gm,'').replace('await import(entry)','await load(entry)')
 let error=''
 const document={body:{replaceChildren(node){error=node.textContent}},createElement(){return {}}}
 await new AsyncFunction('createCloudTransport','frameIdentity','globalThis','window','parent','location','document','load',source)(()=>assert.fail('no transport'),async()=>{throw Error('denied')},{},{},{},{origin:'https://neighbour.example'},document,()=>assert.fail('no model/media UI'))
 assert.match(error,/登入頁/)
})

test('cloud admin adapter removes native operator headers and never accepts a claimed identity',async()=>{
 const source=fs.readFileSync('deploy/cloud/web/admin-request.js','utf8')
 const {cloudFetch}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
 await assert.rejects(cloudFetch('/api/v1/events'),/transport_required/)
 const calls=[]
 globalThis.__NEIGHBOUR_CLOUD__=true
 globalThis.__NEIGHBOUR_CLOUD_TRANSPORT__={fetch:async(path,init)=>{calls.push({path,init});return new Response('{}')}}
 try{
  await cloudFetch('/api/v1/service-desk/requests',{headers:{'X-Operator-Key':'local-placeholder','Content-Type':'application/json'}})
  assert.equal(calls[0].init.headers.has('X-Operator-Key'),false)
  assert.equal(calls[0].init.headers.get('content-type'),'application/json')
  await assert.rejects(cloudFetch('/api/v1/events',{headers:{Authorization:'Bearer forged'}}),/identity_override/)
  assert.equal(calls.length,1)
 }finally{delete globalThis.__NEIGHBOUR_CLOUD__;delete globalThis.__NEIGHBOUR_CLOUD_TRANSPORT__}
})
