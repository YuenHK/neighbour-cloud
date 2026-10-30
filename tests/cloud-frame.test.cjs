const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ready = import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync('airi_overlay/cloud-frame.js')).toString('base64'))
const origin = 'https://neighbour.example'
const nonce = 'a'.repeat(32)
function port(){return {messages:[],closed:false,postMessage(data){this.messages.push(data)},close(){this.closed=true}}}
test('only the current exact-origin frame receives the in-memory identity',async()=>{
 const {createFrameBroker}=await ready
 const frame={}, other={}, p=port();let calls=0
 const broker=createFrameBroker({origin,frameWindow:()=>frame,tokenProvider:()=>{calls++;return {token:'h.p.s',expiresAtMs:Date.now()+300000}}})
 const event={origin,source:frame,data:{type:'neighbour-cloud-identity-v1',nonce},ports:[p]}
 for(const patch of [{origin:'https://elsewhere.example'},{source:other},{ports:[]},{data:{type:event.data.type,nonce:'bad'}}])broker.receive({...event,...patch})
 assert.equal(calls,0);assert.equal(p.messages.length,0)
 broker.receive(event);assert.equal(calls,1);assert.equal(p.messages[0].token,'h.p.s')
 broker.close();assert.equal(p.closed,true);assert.equal(p.messages.at(-1).type,'neighbour-cloud-signed-out')
 broker.receive(event);assert.equal(calls,1)
})
test('a replaced frame and revoked identity cannot obtain a subsequent token',async()=>{
 const {createFrameBroker}=await ready
 const old={},current={};let selected=old
 const broker=createFrameBroker({origin,frameWindow:()=>selected,tokenProvider:()=>{throw new Error('revoked')}})
 selected=current
 const p=port();broker.receive({origin,source:old,data:{type:'neighbour-cloud-identity-v1',nonce},ports:[p]})
 assert.equal(p.messages.length,0)
 broker.receive({origin,source:current,data:{type:'neighbour-cloud-identity-v1',nonce},ports:[p]})
 assert.equal(p.messages[0].type,'neighbour-cloud-signed-out');assert.equal(p.closed,true)
})
test('child handshake binds nonce and exact parent origin, then observes sign-out',async()=>{
 const {frameIdentity}=await ready
 const channel={port1:port(),port2:port()};channel.port1.start=()=>{}
 let posted,closed=0
 const parent={postMessage(...args){posted=args}}
 const pending=frameIdentity({target:{},parent,origin,channel,nonce,onClose:()=>closed++})
 assert.equal(posted[1],origin);assert.deepEqual(posted[2],[channel.port2])
 channel.port1.onmessage({data:{type:'neighbour-cloud-identity-v1',nonce:'b'.repeat(32),token:'h.p.s',expiresAtMs:Date.now()+300000}})
 const identity={token:'h.p.s',expiresAtMs:Date.now()+300000}
 channel.port1.onmessage({data:{type:'neighbour-cloud-identity-v1',nonce,...identity}})
 assert.deepEqual(await pending,identity)
 channel.port1.onmessage({data:{type:'neighbour-cloud-signed-out'}})
 assert.equal(closed,1);assert.equal(channel.port1.closed,true)
})
test('a direct page never requests identity; unavailable parent has a bounded wait',async()=>{
 const {frameIdentity}=await ready
 const self={postMessage(){assert.fail('no direct-page token request')}}
 await assert.rejects(frameIdentity({target:self,parent:self,origin}))
 const channel={port1:port(),port2:port()};channel.port1.start=()=>{}
 await assert.rejects(frameIdentity({target:{},parent:{postMessage(){}},origin,channel,timeoutMs:5}),/unavailable/)
 assert.equal(channel.port1.closed,true)
})
