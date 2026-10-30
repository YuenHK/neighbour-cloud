const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const load = file => import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync(file)).toString('base64'))
const apiModule = load('airi_overlay/resident-api.js')
const pcmModule = load('airi_overlay/resident-pcm.js')
const ids = { sessionId: 'a'.repeat(32), turnId: 'b'.repeat(32) }

test('cloud microphone audio uses only the authenticated transcription route and preserves the input identity', async () => {
  const {createResidentApi} = await apiModule
  const calls=[]
  const api=createResidentApi({cloud:true, transport:()=>({fetch:async (path,init)=>{
    calls.push({path,init}); return new Response(JSON.stringify({text:'你好街坊。',engine:'cloudflare-whisper-free',model:'@cf/openai/whisper-large-v3-turbo'}))
  }}),fetcher:()=>{throw Error('no Notebook fallback')}})
  const raw=new Uint8Array(8044), controller=new AbortController()
  assert.equal(await api.transcribe(new Blob([raw],{type:'audio/wav'}),{sessionId:ids.sessionId,inputId:ids.turnId},controller.signal),'你好街坊。')
  assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/v1/resident/transcription')
  const body=JSON.parse(calls[0].init.body)
  assert.deepEqual(Object.keys(body).sort(),['audio','input_id','session_id'])
  assert.equal(body.session_id,ids.sessionId);assert.equal(body.input_id,ids.turnId)
  assert.deepEqual(Buffer.from(body.audio,'base64'),Buffer.from(raw))
  assert.equal(calls[0].init.signal.aborted,false)
  controller.abort();assert.equal(calls[0].init.signal.aborted,true)
})

test('transcription rejects cancelled, oversized, unconfigured or alternate-engine audio without retries', async () => {
  const {createResidentApi} = await apiModule
  let calls=0, finish
  const api=createResidentApi({cloud:true,transport:()=>({fetch:async()=>{calls++;return new Promise(resolve=>{finish=resolve})}})})
  const audio=new Blob([new Uint8Array(8044)],{type:'audio/wav'}), controller=new AbortController()
  const pending=api.transcribe(audio,{sessionId:ids.sessionId,inputId:ids.turnId},controller.signal)
  await new Promise(resolve=>setImmediate(resolve));controller.abort()
  finish(new Response(JSON.stringify({text:'舊居民',engine:'cloudflare-whisper-free',model:'@cf/openai/whisper-large-v3-turbo'})))
  await assert.rejects(pending,{name:'AbortError'});assert.equal(calls,1)
  await assert.rejects(api.transcribe(new Blob([new Uint8Array(1440045)]),{sessionId:ids.sessionId,inputId:ids.turnId}))
  const native=createResidentApi({fetcher:()=>{throw Error('must not change native SenseVoice')}})
  await assert.rejects(native.transcribe(audio,{sessionId:ids.sessionId,inputId:ids.turnId}))
  const wrong=createResidentApi({cloud:true,transport:()=>({fetch:async()=>new Response(JSON.stringify({text:'不採用',engine:'other',model:'paid'}))})})
  await assert.rejects(wrong.transcribe(audio,{sessionId:ids.sessionId,inputId:ids.turnId}))
})

test('cloud chat and plan completion use the injected transport and fixed Gemma with the same turn', async () => {
  const { createResidentApi } = await apiModule
  const calls = []
  const native = () => { throw Error('must never reach Notebook fetch') }
  const transport = { fetch: async (path, init) => { calls.push({ path, init }); return new Response('{}') } }
  const api = createResidentApi({ cloud: true, transport: () => transport, fetcher: native })
  const controller = new AbortController()
  const body = { messages: [{ role: 'user', content: '公開廣東話測試' }], submission_id: ids.turnId, session_id: ids.sessionId }
  await api.chat(body, controller.signal)
  const plan = { object: 'resident.plan', system_prompt: '溫柔香港廣東話', messages: body.messages }
  await api.completePlan(plan, ids, controller.signal)
  assert.deepEqual(calls.map(c => c.path), ['/api/v1/resident/chat', '/api/v1/resident/model/v1/chat/completions'])
  assert.equal(JSON.parse(calls[0].init.body).native_settings, true)
  const completion = JSON.parse(calls[1].init.body)
  assert.equal(completion.model, 'gemma-4-26b-a4b-it')
  assert.equal(completion.stream, true)
  assert.deepEqual(completion.messages.slice(1), body.messages)
  assert.equal(calls[1].init.headers['X-Resident-Session'], ids.sessionId)
  assert.equal(calls[1].init.headers['X-Resident-Turn'], ids.turnId)
  assert.ok(calls.every(c => c.init.signal === controller.signal && c.init.credentials === 'omit'))
  assert.ok(calls.every(c => !Object.keys(c.init.headers).some(k => /authorization|key/i.test(k))))
  assert.equal(body.native_settings, undefined)
})

test('cloud missing login transport and malformed plan never fall back to native or replay', async () => {
  const { createResidentApi } = await apiModule
  let nativeCalls = 0, cloudCalls = 0
  const api = createResidentApi({ cloud: true, fetcher: async () => { nativeCalls++; return new Response() } })
  await assert.rejects(api.chat({ messages: [] }), /cloud_transport_not_ready/)
  const configured = createResidentApi({ cloud: true, transport: () => ({ fetch: async () => { cloudCalls++; return new Response('', { status: 503 }) } }) })
  await assert.rejects(configured.completePlan({ object: 'resident.plan', system_prompt: '', messages: [] }, ids), /invalid_cloud_plan/)
  await assert.rejects(configured.completePlan({ object: 'resident.plan', system_prompt: '公開', messages: [{ role: 'system', content: '不應由歷史注入' }] }, ids), /invalid_cloud_plan/)
  assert.equal((await configured.chat({ messages: [] })).status, 503)
  assert.equal(nativeCalls, 0)
  assert.equal(cloudCalls, 1)
})

test('native API preserves the existing endpoint and AIRI planning path', async () => {
  const { createResidentApi } = await apiModule
  const calls = []
  const api = createResidentApi({ fetcher: async (...args) => { calls.push(args); return new Response('{}') } })
  await api.chat({ messages: [], airi_system_prompt: '已有角色設定' })
  assert.equal(calls[0][0], 'http://127.0.0.1:8000/api/v1/resident/chat')
  assert.equal(JSON.parse(calls[0][1].body).airi_system_prompt, '已有角色設定')
  assert.equal(api.pcm.endpoint, 'http://127.0.0.1:8765/v1/audio/resident-stream')
  assert.equal(api.timing.endpoint, 'http://127.0.0.1:8000/api/v1/resident/timing')
})

test('cloud PCM and content-free timing both use the authenticated same-origin transport', async () => {
  const { createResidentApi } = await apiModule
  const { ResidentPcm, ResidentTiming } = await pcmModule
  const calls = []
  const api = createResidentApi({ cloud: true, transport: () => ({ fetch: async (path, init) => {
    calls.push({ path, body: JSON.parse(init.body) })
    if (path.endsWith('resident-stream')) return new Response('data: {"error":"synthetic_no_audio"}\n\n')
    return new Response('{}')
  } }) })
  const context = { state: 'running', resume: async () => {} }
  const pcm = new ResidentPcm({ ...api.pcm, context })
  pcm.write('公開曉曼樣本'); pcm.end(); await pcm.chain
  let now = 100
  const timing = new ResidentTiming(() => now, undefined, api.timing)
  now = 125; timing.mark('first_text'); await timing.report()
  assert.deepEqual(calls.map(c => c.path), ['/_audio/v1/audio/resident-stream', '/api/v1/resident/timing'])
  assert.deepEqual(calls[0].body, { model: 'azure-hiumaan-f0', voice: 'zh-HK-HiuMaanNeural', input: '公開曉曼樣本', speed: 1 })
  assert.deepEqual(calls[1].body, { marks: { first_text: 25 } })
})

test('timing transport failure is best effort and cannot break a resident turn', async () => {
  const { ResidentTiming } = await pcmModule
  const timing = new ResidentTiming(() => 100, undefined, { fetcher: () => { throw Error('unavailable') }, endpoint: '/api/v1/resident/timing' })
  timing.mark('first_text')
  await assert.doesNotReject(timing.report())
})
