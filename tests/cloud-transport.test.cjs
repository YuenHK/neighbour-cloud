const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const load = path => import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync(path, 'utf8')).toString('base64'))
const transportModule = () => load('airi_overlay/cloud-transport.js')
const origin = 'https://neighbour.example'
const flush = () => new Promise(resolve => setImmediate(resolve))
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return {promise, resolve} }
const token = label => ({token: 'header.' + Buffer.from(label).toString('base64url') + '.signature', expiresAtMs: 300000})

test('formal governance reads use the same memory-only Google transport and reject unrelated settings', async () => {
  const {createCloudTransport} = await transportModule()
  const urls = []
  const api = createCloudTransport({origin, now: () => 1000, tokenProvider: () => token('staff'),
    fetcher: async url => {urls.push(url); return new Response('{}')}})
  await api.fetch('/api/v1/governance/retention')
  await api.fetch('/api/v1/governance/audit?limit=20')
  await assert.rejects(api.fetch('/api/v1/governance/settings'))
  assert.deepEqual(urls, [origin + '/api/v1/governance/retention', origin + '/api/v1/governance/audit?limit=20'])
})

test('coalesced auth is reused for allowed same-origin requests without changing caller input', async () => {
  const {createCloudTransport} = await transportModule()
  const waiting = deferred(), requests = []
  let signins = 0
  const api = createCloudTransport({origin, now: () => 1000,
    tokenProvider: () => { signins++; return waiting.promise },
    fetcher: async (url, options) => { requests.push({url, options}); return new Response('{}') }})
  const body = JSON.stringify({submission_id: 'a'.repeat(32), message: 'PUBLIC-SYNTHETIC'})
  const options = Object.freeze({method: 'POST', headers: {'Content-Type': 'application/json'}, body})
  const first = api.fetch('/api/v1/service-desk/requests', options)
  const second = api.fetch('/api/v1/service-desk/quota')
  await flush(); assert.equal(signins, 1); assert.equal(requests.length, 0)
  waiting.resolve(token('synthetic-owner'))
  await Promise.all([first, second])
  assert.equal(requests.length, 2)
  for (const request of requests) {
    assert.ok(request.url.startsWith(origin + '/api/v1/'))
    assert.equal(request.options.headers.get('authorization'), 'Bearer ' + token('synthetic-owner').token)
    assert.equal(request.options.credentials, 'omit')
    assert.equal(request.options.redirect, 'error')
    assert.equal(request.options.mode, 'same-origin')
    assert.equal(request.options.cache, 'no-store')
    assert.equal(request.options.referrerPolicy, 'no-referrer')
  }
  assert.equal(requests[0].options.body, body)
  assert.equal(options.headers.Authorization, undefined)
  await api.fetch('/api/v1/resident/model/v1/chat/completions', {method: 'POST', body: '{}'})
  assert.equal(signins, 1)
})

test('external, loopback, hardware, key headers and redirect overrides fail before sign-in', async () => {
  const {createCloudTransport} = await transportModule()
  let signins = 0, calls = 0
  const api = createCloudTransport({origin, tokenProvider: () => {signins++; return token('synthetic')},
    fetcher: async () => {calls++; return new Response('{}')}})
  for (const path of ['https://PRIVATE.example/api/v1/resident/chat', '//PRIVATE.example/path',
    'http://127.0.0.1:8000/api/v1/resident/chat', '/api/v1/ep/fleet/connect', '/robots', '/settings',
    '/api/v1/resident/chat#PRIVATE', '/api/v1/patrol/events/id/privacy-approve']) {
    await assert.rejects(api.fetch(path), error => !error.message.includes('PRIVATE'))
  }
  for (const init of [{headers:{Authorization:'PRIVATE'}}, {headers:{'X-Operator-Key':'PRIVATE'}},
    {headers:{'Ocp-Apim-Subscription-Key':'PRIVATE'}}, {redirect:'follow'}, {credentials:'include'},
    {mode:'no-cors'}, {method:'TRACE'}, {method:'GET',body:'PRIVATE'}]) {
    await assert.rejects(api.fetch('/api/v1/resident/chat', init), error => !error.message.includes('PRIVATE'))
  }
  assert.equal(signins, 0); assert.equal(calls, 0)
})

test('cancelled auth wait returns promptly while another request shares the sign-in', async () => {
  const {createCloudTransport} = await transportModule()
  const waiting = deferred(), abort = new AbortController(), calls = []
  const api = createCloudTransport({origin, now: () => 1000, tokenProvider: () => waiting.promise,
    fetcher: async url => {calls.push(url); return new Response('{}')}})
  const cancelled = api.fetch('/api/v1/service-desk/quota', {signal:abort.signal})
  const active = api.fetch('/api/v1/service-desk/summary')
  abort.abort()
  await assert.rejects(cancelled, {name:'AbortError'})
  waiting.resolve(token('synthetic'))
  await active; assert.equal(calls.length, 1)
  const already = new AbortController(); already.abort()
  await assert.rejects(api.fetch('/api/v1/service-desk/quota', {signal:already.signal}), {name:'AbortError'})
  assert.equal(calls.length, 1)
})

test('clearAuth fences a late token and does not silently change identity on a waiting request', async () => {
  const {createCloudTransport} = await transportModule()
  const first = deferred(), calls = []
  let count = 0
  const api = createCloudTransport({origin, now: () => 1000,
    tokenProvider: () => ++count === 1 ? first.promise : token('new-owner'),
    fetcher: async (_url, options) => {calls.push(options.headers.get('authorization')); return new Response('{}')}})
  const old = api.fetch('/api/v1/service-desk/quota')
  await flush(); api.clearAuth()
  await assert.rejects(old, /cloud_sign_in_changed/)
  first.resolve(token('old-owner')); await flush()
  await api.fetch('/api/v1/service-desk/quota')
  assert.deepEqual(calls, ['Bearer ' + token('new-owner').token])
})

test('401 invalidates auth for a future call but is never replayed automatically', async () => {
  const {createCloudTransport} = await transportModule()
  let signins = 0, calls = 0
  const api = createCloudTransport({origin, now: () => 1000, tokenProvider: () => {signins++; return token('synthetic')},
    fetcher: async () => {calls++; return new Response('{}', {status:401})}})
  assert.equal((await api.fetch('/api/v1/resident/chat', {method:'POST',body:'{}'})).status, 401)
  assert.equal(calls, 1); assert.equal(signins, 1)
  assert.equal((await api.fetch('/api/v1/resident/chat', {method:'POST',body:'{}'})).status, 401)
  assert.equal(calls, 2); assert.equal(signins, 2)
})

test('malformed, expiring and timed out sign-ins send no API request or raw credential error', async () => {
  const {createCloudTransport} = await transportModule()
  let calls = 0
  for (const value of [{token:'PRIVATE\nVALUE',expiresAtMs:300000}, {...token('near-expiry'),expiresAtMs:1001},
    {...token('invalid-expiry'),expiresAtMs:Infinity}, null]) {
    const api = createCloudTransport({origin, now: () => 1000, tokenProvider: () => value,
      fetcher: () => {calls++; throw new Error('must not send')}})
    await assert.rejects(api.fetch('/api/v1/service-desk/quota'), error => !error.message.includes('PRIVATE'))
  }
  const failing = createCloudTransport({origin, tokenProvider: () => {throw new Error('PRIVATE-CREDENTIAL')},
    fetcher: () => {calls++}})
  await assert.rejects(failing.fetch('/api/v1/service-desk/quota'), /cloud_sign_in_unavailable/)
  const slow = createCloudTransport({origin, tokenProvider: () => new Promise(() => {}), authTimeoutMs:20,
    fetcher: () => {calls++}})
  await assert.rejects(slow.fetch('/api/v1/service-desk/quota'), /cloud_sign_in_unavailable/)
  assert.equal(calls, 0)
})

test('unknown-write 503 body and original submission identity pass through without retry', async () => {
  const {createCloudTransport} = await transportModule()
  let calls = 0
  const receipt = {code:'storage_unavailable',operation_outcome:'unknown',retry_policy:'same_submission_id_same_content'}
  const api = createCloudTransport({origin, now: () => 1000, tokenProvider: () => token('synthetic'),
    fetcher: async (_url, init) => {calls++; assert.equal(JSON.parse(init.body).submission_id, 'a'.repeat(32));
      return Response.json(receipt, {status:503})}})
  const response = await api.fetch('/api/v1/service-desk/requests', {method:'POST',body:JSON.stringify({submission_id:'a'.repeat(32)})})
  assert.equal(response.status, 503); assert.deepEqual(await response.json(), receipt); assert.equal(calls, 1)
})

test('Gemma JSON and HiuMaan PCM use the same scoped identity without any real audio', async () => {
  const {createCloudTransport} = await transportModule()
  const {ResidentPcm} = await load('airi_overlay/resident-pcm.js')
  let signins = 0
  const requests = []
  const api = createCloudTransport({origin, now: () => 1000, tokenProvider: () => {signins++; return token('resident')},
    fetcher: async (url, init) => {
      requests.push({url, init})
      if (url.endsWith('/resident/chat')) return Response.json({reply:'PUBLIC'})
      const frames = 'data: ' + JSON.stringify({audio:Buffer.alloc(4096).toString('base64'),sample_rate:24000,channels:1,format:'pcm_s16le'}) + '\n\ndata: {"done":true}\n\n'
      return new Response(frames, {headers:{'content-type':'text/event-stream'}})
    }})
  const context = {state:'running',currentTime:0,destination:{},nodes:[],resume:async()=>{},
    createBuffer(_c,n,r){return {duration:n/r,getChannelData:()=>new Float32Array(n)}},
    createBufferSource(){const n={connect(){},disconnect(){},start(){n.started=true},stop(){n.stopped=true}};this.nodes.push(n);return n}}
  await api.fetch('/api/v1/resident/chat', {method:'POST',body:'{}'})
  const pcm = new ResidentPcm({context, fetcher:api.fetch, endpoint:'/_audio/v1/audio/resident-stream'})
  pcm.write('PUBLIC-SYNTHETIC'); await pcm.chain
  assert.equal(context.nodes.length, 1)
  assert.equal(signins, 1); assert.equal(requests[1].url, origin + '/_audio/v1/audio/resident-stream')
  assert.equal(JSON.parse(requests[1].init.body).voice, 'zh-HK-HiuMaanNeural')
  pcm.cancel(); assert.equal(context.nodes[0].stopped, true)
})

test('proactive refresh coalesces and a late old-token 401 cannot wipe a newer sign-in', async () => {
  const {createCloudTransport} = await transportModule()
  const oldReply = deferred()
  let now = 1000, signins = 0, calls = 0
  const api = createCloudTransport({origin, now: () => now,
    tokenProvider: () => ({...token('owner-' + ++signins), expiresAtMs: now + 120000}),
    fetcher: async () => ++calls === 1 ? oldReply.promise : new Response('{}')})
  const old = api.fetch('/api/v1/service-desk/quota')
  await flush(); now += 70000
  await Promise.all([api.fetch('/api/v1/service-desk/quota'), api.fetch('/api/v1/service-desk/summary')])
  assert.equal(signins, 2)
  oldReply.resolve(new Response('{}', {status:401})); await old
  await api.fetch('/api/v1/service-desk/quota')
  assert.equal(signins, 2); assert.equal(calls, 4)
})

test('network and in-flight cancellation preserve one attempt and redact raw errors', async () => {
  const {createCloudTransport} = await transportModule()
  let calls = 0
  const failing = createCloudTransport({origin, now: () => 1000, tokenProvider: () => token('synthetic'),
    fetcher: async () => {calls++; throw new TypeError('PRIVATE-NETWORK-DETAIL')}})
  await assert.rejects(failing.fetch('/api/v1/service-desk/requests', {method:'POST',body:'{}'}), /cloud_request_failed/)
  assert.equal(calls, 1)
  const abort = new AbortController()
  const active = createCloudTransport({origin, now: () => 1000, tokenProvider: () => token('synthetic'),
    fetcher: async (_url, options) => {
      calls++
      assert.equal(options.signal.aborted, false)
      return new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('PRIVATE', 'AbortError'))))
    }})
  const request = active.fetch('/api/v1/service-desk/requests', {method:'POST',body:'{}',signal:abort.signal})
  await flush(); abort.abort()
  await assert.rejects(request, error => error.name === 'AbortError' && !error.message.includes('PRIVATE'))
  assert.equal(calls, 2)
})

test('timed-out late token is fenced while a later manual request can recover', async () => {
  const {createCloudTransport} = await transportModule()
  const late = deferred(), authorizations = []
  let signins = 0
  const api = createCloudTransport({origin, now: () => 1000, authTimeoutMs:20,
    tokenProvider: () => ++signins === 1 ? late.promise : token('recovered'),
    fetcher: async (_url, options) => {authorizations.push(options.headers.get('authorization')); return new Response('{}')}})
  await assert.rejects(api.fetch('/api/v1/service-desk/quota'), /cloud_sign_in_unavailable/)
  await api.fetch('/api/v1/service-desk/quota')
  late.resolve(token('expired-attempt')); await flush()
  await api.fetch('/api/v1/service-desk/quota')
  assert.deepEqual(authorizations, Array(2).fill('Bearer ' + token('recovered').token))
  assert.equal(signins, 2)
})

test('invalid cloud origins never invoke sign-in or implicitly use localhost', async () => {
  const {createCloudTransport} = await transportModule()
  let signins = 0
  for (const base of ['http://127.0.0.1:8000', origin + '/', origin + '/PRIVATE',
    'https://PRIVATE@neighbour.example', origin + ':444', origin + '?PRIVATE']) {
    assert.throws(() => createCloudTransport({origin:base,tokenProvider:()=>{signins++; return token('synthetic')}}),
      error => error.message === 'cloud_transport_configuration_required')
  }
  assert.equal(signins, 0)
})

test('default fetch keeps its global receiver when exposed as a transport method', async () => {
  const {createCloudTransport} = await transportModule()
  const previous = globalThis.fetch
  let calls = 0
  globalThis.fetch = function () {
    assert.equal(this, globalThis); calls++
    return Promise.resolve(new Response('{}'))
  }
  try {
    const api = createCloudTransport({origin, now:()=>1000, tokenProvider:()=>token('synthetic')})
    await api.fetch('/api/v1/service-desk/quota')
    assert.equal(calls, 1)
  } finally { globalThis.fetch = previous }
})

test('clearAuth aborts the dispatched generation and fences a fetcher that returns late anyway', async () => {
  const {createCloudTransport} = await transportModule()
  const late = deferred(), requests = []
  let cancelled = 0, signins = 0
  const api = createCloudTransport({origin, now:()=>1000, tokenProvider:()=>token('owner-' + ++signins),
    fetcher: async (_url, options) => {requests.push(options); return requests.length === 1 ? late.promise : new Response('{}')}})
  const old = api.fetch('/api/v1/resident/chat', {method:'POST',body:'{"submission_id":"same-intent"}'})
    .then(() => null, error => error)
  await flush(); api.clearAuth()
  const aborted = requests[0].signal?.aborted
  late.resolve(new Response(new ReadableStream({cancel(){cancelled++}})))
  const outcome = await old
  assert.equal(aborted, true)
  assert.equal(outcome?.name, 'AbortError')
  assert.equal(cancelled, 1)
  assert.equal(requests[0].body, '{"submission_id":"same-intent"}')
  await api.fetch('/api/v1/service-desk/quota')
  assert.equal(requests.length, 2)
  assert.equal(requests[1].signal.aborted, false)
})

test('clearAuth also aborts a response body after headers without aborting the caller controller', async () => {
  const {createCloudTransport} = await transportModule()
  const caller = new AbortController()
  const api = createCloudTransport({origin, now:()=>1000, tokenProvider:()=>token('synthetic'),
    fetcher: async (_url, options) => new Response(new ReadableStream({
      start(controller){ options.signal?.addEventListener('abort', () => controller.error(new DOMException('stopped', 'AbortError'))) },
    }))})
  const response = await api.fetch('/_audio/v1/audio/resident-stream', {method:'POST',body:'{}',signal:caller.signal})
  const reader = response.body.getReader()
  const reading = reader.read().then(() => null, error => error)
  api.clearAuth()
  let timer
  const outcome = await Promise.race([reading, new Promise(resolve => {timer=setTimeout(()=>resolve(null),30)})])
  clearTimeout(timer)
  await reader.cancel().catch(()=>{})
  assert.equal(outcome?.name, 'AbortError')
  assert.equal(caller.signal.aborted, false)
})

test('late previous-generation 401 cannot evict an identical token reacquired for a new generation', async () => {
  const {createCloudTransport} = await transportModule()
  const late = deferred()
  let calls = 0, signins = 0
  const api = createCloudTransport({origin, now:()=>1000,
    tokenProvider:()=>{signins++; return token('same-valid-owner')},
    fetcher:async()=>++calls === 1 ? late.promise : new Response('{}')})
  const old = api.fetch('/api/v1/service-desk/quota').then(()=>null,error=>error)
  await flush(); api.clearAuth()
  await api.fetch('/api/v1/service-desk/quota')
  late.resolve(new Response('{}', {status:401}))
  const outcome = await old
  await api.fetch('/api/v1/service-desk/quota')
  assert.equal(outcome?.name, 'AbortError')
  assert.equal(signins, 2); assert.equal(calls, 3)
})

test('a caller cancelling one active request does not abort another request in the same identity', async () => {
  const {createCloudTransport} = await transportModule()
  const caller = new AbortController(), signals = []
  const api = createCloudTransport({origin, now:()=>1000, tokenProvider:()=>token('synthetic'),
    fetcher:async(_url, options)=>{
      signals.push(options.signal)
      return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('stop','AbortError'))))
    }})
  const first = api.fetch('/api/v1/resident/chat',{method:'POST',body:'{}',signal:caller.signal}).then(()=>null,error=>error)
  const second = api.fetch('/_audio/v1/audio/resident-stream',{method:'POST',body:'{}'}).then(()=>null,error=>error)
  await flush(); caller.abort()
  assert.equal((await first).name, 'AbortError')
  assert.equal(signals[0].aborted, true); assert.equal(signals[1].aborted, false)
  api.clearAuth()
  assert.equal((await second).name, 'AbortError'); assert.equal(signals.length, 2)
})

test('a late body with a never-finishing cancel cannot hold the old request open', async () => {
  const {createCloudTransport} = await transportModule()
  const late = deferred()
  let cancellations = 0
  const api = createCloudTransport({origin, now:()=>1000, tokenProvider:()=>token('synthetic'),fetcher:()=>late.promise})
  const old = api.fetch('/api/v1/service-desk/quota').then(()=>null,error=>error)
  await flush(); api.clearAuth()
  late.resolve(new Response(new ReadableStream({cancel(){cancellations++; return new Promise(()=>{})}})))
  let timer
  const outcome = await Promise.race([old,new Promise(resolve=>{timer=setTimeout(()=>resolve(null),30)})])
  clearTimeout(timer)
  assert.equal(outcome?.name,'AbortError'); assert.equal(cancellations,1)
})

test('a callback starting a new request during old-generation abort uses the fresh lifecycle', async () => {
  const {createCloudTransport} = await transportModule()
  let next, count = 0
  const api = createCloudTransport({origin, now:()=>1000, tokenProvider:()=>token('synthetic'),
    fetcher:async(_url, options)=>{
      if (++count === 1) {
        return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>{
          next=api.fetch('/api/v1/service-desk/quota')
          reject(new DOMException('stop','AbortError'))
        }))
      }
      assert.equal(options.signal.aborted,false)
      return new Response('{}')
    }})
  const old=api.fetch('/api/v1/service-desk/summary').then(()=>null,error=>error)
  await flush(); api.clearAuth()
  assert.equal((await old).name,'AbortError')
  assert.equal((await next).status,200); assert.equal(count,2)
})
