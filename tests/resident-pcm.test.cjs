const test=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs')
const modulePromise=import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync('airi_overlay/resident-pcm.js','utf8')).toString('base64'))
const flush=()=>new Promise(resolve=>setImmediate(resolve))
function context(){return {state:'running',currentTime:0,destination:{},nodes:[],resume:async()=>{},close:async()=>{},createBuffer(c,n,r){return {duration:n/r,getChannelData:()=>new Float32Array(n)}},createBufferSource(){const n={connect(){},disconnect(){},start(){n.started=true},stop(){n.stopped=true}};this.nodes.push(n);return n}}}

test('paragraph breaks and formatting-only deltas preserve text without empty synthesis or cancelling later speech',async()=>{
 const {ResidentPcm}=await modulePromise
 const {readResidentReply,residentSpeechText}=await import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync('airi_overlay/resident-response.js','utf8')).toString('base64'))
 const ctx=context(),inputs=[];let failed=0
 const player=new ResidentPcm({context:ctx,failed:()=>failed++,fetcher:async(_url,init)=>{
  const {input}=JSON.parse(init.body);inputs.push(input)
  if(!input.trim())return new Response('{}',{status:400})
  return new Response('data: '+JSON.stringify({audio:Buffer.alloc(512).toString('base64')})+'\n\ndata: {"done":true}\n\n')
 }})
 const parts=['回收物可以分類。','\n','\n',' ** ','一般垃圾另行處理。']
 const response=new Response(parts.map(content=>'data: '+JSON.stringify({choices:[{delta:{content}}]})+'\n\n').join('')+'data: [DONE]\n\n',{headers:{'Content-Type':'text/event-stream'}})
 const answer=await readResidentReply(response,delta=>player.write(residentSpeechText(delta)),new AbortController().signal)
 player.end();await player.chain
 assert.equal(answer,parts.join(''));assert.equal(failed,0)
 assert.deepEqual(inputs,['回收物可以分類。','一般垃圾另行處理。'])
 assert.equal(ctx.nodes.length,2);assert.equal(player.controller.signal.aborted,false)
 player.cancel()
})

test('voice retries only a confirmed pre-synthesis busy response, not an unknown provider failure',async()=>{
 const {ResidentPcm}=await modulePromise
 const ctx=context();let calls=0,failed=0
 const fetcher=async()=>{calls++;return new Response(calls===1?'data: {"error":"busy"}\n\n':'data: '+JSON.stringify({audio:Buffer.alloc(512).toString('base64')})+'\n\ndata: {"done":true}\n\n')}
 const player=new ResidentPcm({context:ctx,fetcher,wait:async()=>{},failed:()=>failed++})
 player.write('public synthetic sentence');await player.chain
 assert.equal(calls,2);assert.equal(failed,0);assert.equal(ctx.nodes.length,1);player.cancel()
 calls=0
 const unknown=new ResidentPcm({context:context(),wait:async()=>{},failed:()=>failed++,fetcher:async()=>{calls++;return new Response('data: {"error":"voice_unavailable"}\n\n')}})
 unknown.write('public synthetic sentence');await unknown.chain
 assert.equal(calls,1);assert.equal(failed,1)
})
test('first audio schedules before final frame; cancel stops nodes and blocks late audio',async()=>{
 const {ResidentPcm}=await modulePromise
 const ctx=context();let stream,started=0
 const player=new ResidentPcm({context:ctx,started:()=>started++,fetcher:async()=>({ok:true,body:new ReadableStream({start(controller){stream=controller}})})})
 player.write('synthetic');await flush()
 stream.enqueue(new TextEncoder().encode('data: '+JSON.stringify({audio:Buffer.alloc(4096).toString('base64')})+'\n\n'))
 await flush();assert.equal(started,1);assert.equal(ctx.nodes.length,1)
 player.cancel();assert.equal(ctx.nodes[0].stopped,true)
 stream.enqueue(new TextEncoder().encode('data: {"done":true}\n\n'));stream.close()
 await player.chain;assert.equal(ctx.nodes.length,1)
})
test('truncated audio fails once and never silently reports completion',async()=>{
 const {ResidentPcm}=await modulePromise
 let failures=0,ended=0
 const player=new ResidentPcm({context:context(),failed:()=>failures++,ended:()=>ended++,fetcher:async()=>({ok:true,body:new ReadableStream({start(c){c.close()}})})})
 player.write('synthetic');player.end();await player.chain
 assert.equal(failures,1);assert.equal(ended,0)
})

test('voice timings include VAD-to-ASR wait, deduplicate marks and transmit no text',async()=>{
 const {ResidentTiming}=await modulePromise
 let now=6000, body
 const original=global.fetch
 global.fetch=async(url,options)=>{body=JSON.parse(options.body);return {ok:true}}
 try {
  const timing=new ResidentTiming(()=>now,5500)
  timing.mark('asr_ready');timing.mark('asr_ready');await timing.report()
  assert.deepEqual(body,{marks:{asr_ready:500}})
  now=6300;timing.mark('first_text');await timing.report()
  assert.deepEqual(body,{marks:{first_text:800}})
  timing.mark('first_text');await timing.report()
  assert.deepEqual(body,{marks:{first_text:800}})
 } finally {global.fetch=original}
})
