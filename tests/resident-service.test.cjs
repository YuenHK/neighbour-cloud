const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-session.js'), 'utf8')
function session(request) {
  const sandbox = vm.createContext({ AbortController, crypto: require('node:crypto').webcrypto })
  vm.runInContext(source.replace('export class ResidentSession', 'globalThis.ResidentSession = class ResidentSession'), sandbox)
  return new sandbox.ResidentSession(request)
}

test('cancel waiting preserves history, resident identity and retry intent while fencing late output', async()=>{
 let finish
 const calls=[]
 let pending=true
 const current=session(async(body,signal)=>{
  calls.push({body,signal})
  return pending ? new Promise(resolve=>{finish=resolve}) : '新回覆'
 })
 current.history=[{role:'user',content:'之前問題'},{role:'assistant',content:'之前答案'}]
 current.profile='公開測試'
 const identity=current.sessionId
 const old=current.send('等待問題')
 const intent=calls[0].body.submission_id
 current.cancelPending()
 assert.equal(calls[0].signal.aborted,true)
 assert.equal(current.profile,'公開測試');assert.equal(current.history.length,2)
 assert.equal(current.sessionId,identity);assert.equal(current.busy,false)
 pending=false
 assert.equal(await current.send('等待問題'),'新回覆')
 assert.equal(calls[1].body.submission_id,intent)
 finish('不應顯示的舊回覆')
 assert.equal(await old,null)
 assert.equal(current.history.length,4)
 assert.match(fs.readFileSync(path.join(__dirname,'../airi_overlay/resident-service-panel.vue'),'utf8'),/v-if="busy"[^>]+cancelWaiting/)
})

test('resident turns stay bounded and only carry text conversation plus the chosen style', async () => {
  const calls = []
  const current = session(async (body) => { calls.push(body); return '公開合成回覆' })
  for (let index = 0; index < 18; index++) await current.send(`公開問題 ${index}`)
  assert.equal(calls.at(-1).messages.length, 35)
  assert.equal(calls.at(-1).messages[0].content, '公開問題 0')
  assert.equal(calls.at(-1).messages[0].role, 'user')
  assert.equal(calls.at(-1).messages.at(-1).content, '公開問題 17')
  assert.deepEqual(Object.keys(calls.at(-1)).sort(), ['messages', 'profile', 'session_id', 'stream', 'style', 'submission_id'])
  assert.equal(calls.at(-1).stream, true)
  assert.equal(current.history.at(-1).role, 'assistant')
})

test('reset aborts the previous resident and fences an ignored abort and late reply', async () => {
  let finishOld
  let finishNew
  const signals = []
  const current = session((body, signal) => {
    signals.push(signal)
    return new Promise(resolve => { if (body.messages[0].content === '舊居民') finishOld = resolve; else finishNew = resolve })
  })
  const old = current.send('舊居民')
  const oldSession = current.sessionId
  current.reset()
  assert.notEqual(current.sessionId, oldSession)
  assert.equal(signals[0].aborted, true)
  const next = current.send('新居民')
  finishOld('舊居民的遲到回覆')
  assert.equal(await old, null)
  assert.equal(current.busy, true)
  assert.equal(current.history.length, 0)
  finishNew('新居民的回覆')
  assert.equal(await next, '新居民的回覆')
  assert.doesNotMatch(JSON.stringify(current.history), /舊居民/)
})

test('double send cannot duplicate a request and a failure does not become a saved turn', async () => {
  let reject
  let calls = 0
  const current = session(() => { calls++; return new Promise((_, fail) => { reject = fail }) })
  const first = current.send('公開待發問題')
  await assert.rejects(current.send('重複問題'), /resident_busy_or_invalid/)
  assert.equal(calls, 1)
  reject(new Error('synthetic network failure'))
  await assert.rejects(first)
  assert.equal(current.history.length, 0)
  assert.equal(current.busy, false)
})

test('invalid replies never appear as successful resident messages', async () => {
  for (const answer of [undefined, '', { text: 'invalid' }, 'x'.repeat(4001)]) {
    const current = session(async () => answer)
    await assert.rejects(current.send('公開問題'), /resident_reply_invalid/)
    assert.equal(current.history.length, 0)
  }
})

test('resident view has a distinct chat endpoint and never uses the private chat orchestrator', () => {
  const panel = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-service-panel.vue'), 'utf8')
  const api = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-api.js'), 'utf8')
  assert.match(panel, /residentApi.chat\(/)
  assert.match(api, /\/api\/v1\/resident\/chat/)
  assert.doesNotMatch(panel + api, /useChatOrchestratorStore|localStorage|indexedDB|sessionStorage|X-Operator-Key|X-Assistant-Memory-Token/)
  assert.match(panel, /session.reset\(\)/)
  assert.match(panel, /speechIntent\?\.cancel/)
})

test('unknown submission result reuses the same intent but changed content gets a new one', async () => {
  const ids = []
  const current = session(async (body) => { ids.push(body.submission_id); throw new Error('unknown result') })
  await assert.rejects(current.send('幫我通知管理處：測試大堂漏水'))
  await assert.rejects(current.send('幫我通知管理處：測試大堂漏水'))
  await assert.rejects(current.send('另一個問題'))
  assert.equal(ids[0], ids[1])
  assert.notEqual(ids[1], ids[2])
})

test('late streaming tokens after reset never render or speak for the next resident', async () => {
  let delta
  let finish
  const shown = []
  const current = session((body, signal, emit) => { delta = emit; return new Promise(resolve => { finish = resolve }) })
  const pending = current.send('公開問題', 'voice', text => shown.push(text))
  delta('第一句。')
  current.reset()
  delta('不應播放的遲到文字')
  finish('完整答案')
  assert.equal(await pending, null)
  assert.deepEqual(shown, ['第一句。'])
})

function streamReader() {
  const sandbox = vm.createContext({ TextDecoder })
  const text = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-response.js'), 'utf8')
  vm.runInContext(text.replace('export async function readResidentReply', 'globalThis.readResidentReply = async function')
    .replace('export function createResidentTextFilter', 'globalThis.createResidentTextFilter = function')
    .replace('export function residentPlainText', 'globalThis.residentPlainText = function')
    .replace('export function residentSpeechText', 'globalThis.residentSpeechText = function')
    .replace('export function residentMessageParts', 'globalThis.residentMessageParts = function'), sandbox)
  return sandbox
}

test('actual cloud panel without a native speech host keeps three-turn context, uses fixed Gemma and HiuMaan, then clears the visitor', async () => {
  const ts = require('../.vendor/airi/node_modules/typescript')
  const vue = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-service-panel.vue'), 'utf8')
  const script = vue.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const reader = streamReader(), calls = [], mounted = [], handshake = [], visitorEvents = []
  const now = { value: 100 }
  let finishInput
  const context = { state: 'running', currentTime: 0, destination: {}, nodes: [], resume: async () => {},
    createBuffer: (_channels, length, rate) => ({ duration: length / rate, getChannelData: () => new Float32Array(length) }),
    createBufferSource() { const node = { connect() {}, disconnect() {}, start() {}, stop() { node.stopped = true } }; this.nodes.push(node); return node } }
  const sandbox = vm.createContext({
    __NEIGHBOUR_CLOUD__: true,
    __NEIGHBOUR_CLOUD_TRANSPORT__: { fetch: async (url, init) => {
      const body = JSON.parse(init.body); calls.push({ url, body, headers: init.headers, signal: init.signal })
      if (url === '/api/v1/resident/transcription') return new Promise(resolve => { finishInput = resolve })
      if (url === '/api/v1/resident/chat') return new Response(JSON.stringify({ object: 'resident.plan', system_prompt: '親切香港好鄰居', messages: body.messages }), { headers: { 'Content-Type': 'application/json' } })
      if (url.endsWith('chat/completions')) return new Response('data: '+JSON.stringify({ choices: [{ delta: { content: '公開溫柔回覆。' } }] })+'\n\ndata: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
      if (url.endsWith('resident-stream')) return new Response('data: '+JSON.stringify({ audio: Buffer.alloc(2048).toString('base64') })+'\n\ndata: {"done":true}\n\n')
      if (url === '/api/v1/resident/timing') return new Response('{}')
      assert.fail('unexpected path: ' + url)
    } },
    fetch: () => { assert.fail('cloud panel must never use raw Notebook/provider fetch') },
    location: { origin: 'https://neighbour.example' }, performance: { now: () => now.value }, Date: { now: () => now.value },
    AbortController, AbortSignal, TextDecoder, Blob, DOMException, Event, btoa, atob, crypto: require('node:crypto').webcrypto,
    setTimeout: () => 1, clearTimeout() {}, ref: value => ({ value }),
    defineProps() {}, defineEmits: () => () => {}, defineExpose() {},
    nextTick: async callback => callback?.(), watch() {}, onMounted: callback => mounted.push(callback), onUnmounted() {},
    storeToRefs: () => ({ nowSpeaking: { value: false } }), useSpeakingStore: () => ({}), useAudioContext: () => ({ audioContext: context }),
    useLLM: () => ({ stream: () => assert.fail('cloud must not call the native provider selection') }), residentGesture() {},
    useAiriCardStore: () => ({ systemPrompt: '已有角色設定' }), useConsciousnessStore: () => ({ activeProvider: '', activeModel: '' }),
    useSpeechStore: () => ({ activeSpeechProvider: 'unrelated-old-provider', activeSpeechVoiceId: 'old-local-voice' }),
    useProvidersStore: () => ({ getProviderConfig: () => ({}) }),
    useSpeechRuntimeStore: () => ({ isHost: () => false, openIntent: () => assert.fail('cloud must not fall back to local voice') }),
    useSpeechOutputControlStore: () => ({ requestStopSpeaking() {} }),
    window: { addEventListener() {}, removeEventListener() {}, dispatchEvent: event => visitorEvents.push(event.type), parent: { postMessage: (...args) => handshake.push(args) } },
    document: { addEventListener() {}, removeEventListener() {} },
    readResidentReply: reader.readResidentReply, residentPlainText: reader.residentPlainText,
    residentSpeechText: reader.residentSpeechText, createResidentTextFilter: reader.createResidentTextFilter,
  })
  for (const file of ['resident-session.js', 'resident-idle.js', 'resident-pcm.js', 'resident-api.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../airi_overlay/' + file), 'utf8').replaceAll('export class ', 'class ').replace('export function createResidentApi', 'function createResidentApi'), sandbox)
  }
  vm.runInContext(ts.transpileModule(script + '\nglobalThis.panel = {sendMessage,transcribeAudio,session,checkIdle,draft,messages,get player(){return pcmPlayer}}', { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, sandbox)
  mounted.forEach(callback => callback())
  for (const text of ['今日同阿媽整蛋糕', '整咗香蕉味', '頭先同邊個整']) {
    await sandbox.panel.sendMessage(text)
    assert.ok(sandbox.panel.player)
    await sandbox.panel.player.chain
  }
  const chats = calls.filter(c => c.url === '/api/v1/resident/chat')
  const models = calls.filter(c => c.url.endsWith('chat/completions'))
  const voices = calls.filter(c => c.url.endsWith('resident-stream'))
  assert.deepEqual(chats.map(c => c.body.messages.length), [1, 3, 5])
  assert.equal(models.length, 3); assert.equal(voices.length, 3)
  assert.ok(models.every((c, i) => c.body.model === 'gemma-4-26b-a4b-it' && c.headers['X-Resident-Turn'] === chats[i].body.submission_id))
  assert.ok(voices.every(c => c.body.model === 'azure-hiumaan-f0' && c.body.voice === 'zh-HK-HiuMaanNeural' && c.body.speed === 1))
  assert.equal(handshake[0][1], 'https://neighbour.example')
  const replacedInput = sandbox.panel.transcribeAudio(new Blob([new Uint8Array(8044)],{type:'audio/wav'}))
  await new Promise(resolve=>setImmediate(resolve))
  const replaced = calls.filter(c=>c.url === '/api/v1/resident/transcription').at(-1)
  await sandbox.panel.sendMessage('改用文字繼續傾')
  await sandbox.panel.player.chain
  assert.equal(replaced.signal.aborted,true)
  finishInput(new Response(JSON.stringify({text:'唔應插入文字對話的舊錄音',engine:'cloudflare-whisper-free',model:'@cf/openai/whisper-large-v3-turbo'})))
  await assert.rejects(replacedInput)
  assert.doesNotMatch(JSON.stringify(sandbox.panel.session.history),/唔應插入/)
  const oldSession = sandbox.panel.session.sessionId
  const oldInput = sandbox.panel.transcribeAudio(new Blob([new Uint8Array(8044)],{type:'audio/wav'}))
  await new Promise(resolve=>setImmediate(resolve))
  const input = calls.filter(c=>c.url === '/api/v1/resident/transcription').at(-1)
  assert.equal(input.body.session_id,oldSession)
  sandbox.panel.draft.value = '未送出的舊居民內容'
  now.value += 180000; sandbox.panel.checkIdle()
  assert.deepEqual(visitorEvents, ['resident-conversation-ready', 'estate:resident-session-ended'])
  assert.equal(input.signal.aborted,true)
  finishInput(new Response(JSON.stringify({text:'不屬於新居民的辨識',engine:'cloudflare-whisper-free',model:'@cf/openai/whisper-large-v3-turbo'})))
  await assert.rejects(oldInput)
  assert.equal(sandbox.panel.session.history.length, 0)
  assert.equal(sandbox.panel.messages.value.length, 0)
  assert.equal(sandbox.panel.draft.value, '')
  assert.ok(context.nodes.every(node => node.stopped))
})

test('resident action and delay tags never leak across any network split or into speech', () => {
  const reader = streamReader()
  const raw = '<|ACT {"emotion":"neutral"}|><|DELAY 1|> 唔係唔係，慢慢講。 <|ACT {"emotion":"curious"}|>'
  for (let split = 0; split <= raw.length; split++) {
    const filter = reader.createResidentTextFilter()
    const chunks = [filter.push(raw.slice(0, split)), filter.push(raw.slice(split)), filter.finish()]
    assert.equal(chunks.join(''), ' 唔係唔係，慢慢講。 ')
    assert.ok(chunks.every(text => !text.includes('<|') && !text.includes('emotion')))
  }
  const filter = reader.createResidentTextFilter()
  let result = ''
  for (const letter of raw) result += filter.push(letter)
  result += filter.finish()
  assert.equal(result, ' 唔係唔係，慢慢講。 ')
  assert.equal(reader.residentSpeechText(raw), ' 唔係唔係，慢慢講。 ')
  assert.equal(Array.from(reader.residentMessageParts(raw), part => part.text).join(''), ' 唔係唔係，慢慢講。 ')
  assert.equal(reader.residentPlainText('你好。<|ACT {"emotion":'), '你好。')
  assert.equal(reader.residentPlainText('2 < 3；5 > 4'), '2 < 3；5 > 4')
})

test('network UTF-8 fragments produce deltas before completion without breaking Chinese characters', async () => {
  const reader = streamReader()
  let finish
  const wire = new ReadableStream({ start(controller) { finish = controller } })
  const seen = []
  const pending = reader.readResidentReply(new Response(wire, { headers: { 'Content-Type': 'text/event-stream' } }), text => seen.push(text), new AbortController().signal)
  const encoder = new TextEncoder()
  const event = encoder.encode(`data: ${JSON.stringify({ choices: [{ delta: { content: '你好，' } }] })}\r\n\r\n`)
  for (const byte of event) finish.enqueue(Uint8Array.of(byte))
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(seen, ['你好，'])
  finish.enqueue(encoder.encode(`data: ${JSON.stringify({ choices: [{ delta: { content: '有咩幫到你？' } }] })}\n\ndata: [DONE]\n\n`))
  finish.close()
  assert.equal(await pending, '你好，有咩幫到你？')
  assert.equal(reader.residentSpeechText('你好，**歡迎**。'), '你好，歡迎。')
  assert.equal(reader.residentSpeechText('綜合家庭服務：https://www.swd.gov.hk/tc/pubsvc/family/cat_family/ifs/ 。'), '綜合家庭服務： 。')
})

test('truncated stream is rejected rather than committing a partial reply', async () => {
  const reader = streamReader()
  const bytes = `data: ${JSON.stringify({ choices: [{ delta: { content: '未完成' } }] })}\n\n`
  const response = new Response(bytes, { headers: { 'Content-Type': 'text/event-stream' } })
  await assert.rejects(reader.readResidentReply(response, () => {}, new AbortController().signal), /incomplete/)
})

test('resident landing loads the avatar directly and tolerates its ready message arriving early', () => {
  const page = fs.readFileSync(path.join(__dirname, '../edge_hub/static/resident.html'), 'utf8')
  assert.match(page, /src="http:\/\/127\.0\.0\.1:4173\/ui\/estate-resident-entry\.html\?estate=1"/)
  assert.doesNotMatch(page, /<form|startAssistant|estate-information|human-help/)
  let message
  const posts = []
  const nodes = {
    residentAssistant: { contentWindow: { postMessage: (...args) => posts.push(args) }, addEventListener() {} },
    assistantLoadStatus: { hidden: false }, assistantFallback: { hidden: true },
  }
  const sandbox = vm.createContext({ document: { getElementById: id => nodes[id] },
    window: { addEventListener: (event, callback) => { message = callback } }, setTimeout() {} })
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../edge_hub/static/resident.js'), 'utf8'), sandbox)
  assert.equal(posts[0][0].type, 'estate-assistant-check')
  message({ origin: 'http://wrong-origin', source: nodes.residentAssistant.contentWindow, data: { type: 'estate-assistant-ready' } })
  assert.equal(nodes.assistantLoadStatus.hidden, false)
  message({ origin: 'http://127.0.0.1:4173', source: nodes.residentAssistant.contentWindow, data: { type: 'estate-assistant-ready' } })
  assert.equal(nodes.assistantLoadStatus.hidden, true)
})

test('named memory scope survives turns and resets for the next resident', async () => {
  const bodies = []
  const current = session(async (body) => { bodies.push(body); return '合成回覆' })
  await current.send('我叫阿明')
  await current.send('記住：我喜歡晨早散步')
  assert.equal(bodies[1].profile, '阿明')
  current.reset()
  await current.send('你好')
  assert.equal(bodies[2].profile, '')
})

test('source links render as data without accepting executable URL schemes', () => {
  const reader = streamReader()
  const parts = reader.residentMessageParts('來源：[官方](https://example.org/info)，[不執行](javascript:alert)')
  assert.equal(parts.filter(part => part.url).length, 1)
  assert.equal(parts.find(part => part.url).url, 'https://example.org/info')
})


test('fresh resident shell restores root before routing and preserves query and hash', () => {
  const script = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-entry.js'), 'utf8')
  const calls = []
  const history = { state: { preserved: true }, replaceState: (...args) => calls.push(args) }
  vm.runInNewContext(script, { location: { pathname: '/ui/estate-resident-entry.html', search: '?estate=1', hash: '#welcome' }, history })
  assert.equal(calls[0][2], '/?estate=1#welcome')
  assert.equal(calls[0][0], history.state)
  calls.length = 0
  vm.runInNewContext(script, { location: { pathname: '/', search: '', hash: '' }, history })
  assert.equal(calls.length, 0)
})


function idleHarness(expire) {
  let now = 100
  let task
  const context = vm.createContext({})
  const source = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-idle.js'), 'utf8')
  vm.runInContext(source.replace('export class ResidentIdle', 'globalThis.ResidentIdle = class ResidentIdle'), context)
  const idle = new context.ResidentIdle(expire, { now: () => now, setTimer: (callback, delay) => { task = { callback, delay }; return 1 }, clearTimer: () => { task = undefined } })
  return { idle, advance: ms => { now += ms }, fire: () => task?.callback(), delay: () => task?.delay }
}

test('three minutes of inactivity expire once, renew on a query and detect a suspended tab', () => {
  let expired = 0
  const h = idleHarness(() => expired++)
  h.idle.touch()
  assert.equal(h.delay(), 180000)
  h.advance(179999)
  h.idle.check()
  assert.equal(expired, 0)
  h.idle.touch()
  h.advance(179999)
  h.fire()
  assert.equal(expired, 0)
  h.advance(1)
  h.fire()
  assert.equal(expired, 1)
  h.idle.check()
  assert.equal(expired, 1)
  h.idle.touch()
  h.advance(600000)
  h.idle.check()
  assert.equal(expired, 2)
  h.idle.touch()
  h.idle.stop()
  h.advance(180000)
  h.fire()
  assert.equal(expired, 2)
})

test('idle expiry aborts old resident, clears identity and starts a fresh query without reloading', async () => {
  let finish
  const bodies = []
  const current = session((body) => { bodies.push(body); return body.messages.at(-1).content === '新居民查詢' ? Promise.resolve('新回覆') : new Promise(resolve => { finish = resolve }) })
  const old = current.send('我叫測試街坊')
  const h = idleHarness(() => current.reset())
  h.idle.touch()
  h.advance(180000)
  h.fire()
  assert.equal(current.profile, '')
  assert.equal(current.controller, null)
  assert.equal(current.intent, null)
  assert.equal(current.history.length, 0)
  assert.equal(await current.send('新居民查詢'), '新回覆')
  assert.equal(bodies.at(-1).profile, '')
  assert.equal(bodies.at(-1).messages.length, 1)
  finish('舊居民遲到回覆')
  assert.equal(await old, null)
  assert.equal(current.history.length, 2)
})


test('actual resident panel expires draft, profile and pending speech without reloading', async () => {
  const ts = require('../.vendor/airi/node_modules/typescript')
  const vue = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-service-panel.vue'), 'utf8')
  const script = vue.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const now = { value: 10 }
  const timers = new Map()
  let sequence = 0
  const events = []
  const mounted = []
  let cancelled = 0
  let finish
  let nativePlan = false
  const nativeCalls = []
  const nativeSelection = { activeProvider: 'native-test', activeModel: 'native-model' }
  const sandbox = vm.createContext({
    AbortController, AbortSignal, Event, crypto: require('node:crypto').webcrypto,
    Date: { now: () => now.value },
    setTimeout: (callback, delay) => { const id = ++sequence; timers.set(id, { callback, due: now.value + delay }); return id },
    clearTimeout: id => timers.delete(id), ref: value => ({ value }),
    defineProps: () => {}, defineEmits: () => (...args) => events.push(args), defineExpose: () => {},
    nextTick: async callback => callback?.(), watch: () => {}, onMounted: callback => mounted.push(callback), onUnmounted: () => {},
    storeToRefs: () => ({ nowSpeaking: { value: false } }), useSpeakingStore: () => ({}), useAudioContext: () => ({audioContext:undefined}),
    ResidentTiming: class { mark() {} report() { return Promise.resolve() } }, ResidentPcm: class {}, residentGesture() {},
    useLLM: () => ({ async stream(model, provider, messages, options) {
      nativeCalls.push({ model, provider, messages, options })
      await options.onStreamEvent({ type: 'text-delta', text: '<|AC' })
      await options.onStreamEvent({ type: 'text-delta', text: 'T {"emotion":"neutral"}|><|DELAY 1|>' })
      await options.onStreamEvent({ type: 'text-delta', text: 'AIRI選定模型的公開回覆。<|ACT {"emotion":' })
      await options.onStreamEvent({ type: 'text-delta', text: '"curious"}|>' })
    } }), useAiriCardStore: () => ({ systemPrompt: 'AIRI已選角色設定' }),
    useConsciousnessStore: () => nativeSelection,
    useSpeechStore: () => ({ activeSpeechProvider: 'openai-compatible-audio-speech', activeSpeechVoiceId: 'resident-yue' }),
    useProvidersStore: () => ({ getProviderConfig: () => ({ baseUrl: 'http://127.0.0.1:8765/v1/' }), getProviderInstance: async id => ({ id }) }),
    useSpeechRuntimeStore: () => ({ isHost: () => true, openIntent: () => ({ cancel: () => cancelled++, writeLiteral() {}, end() {} }) }),
    useSpeechOutputControlStore: () => ({ requestStopSpeaking() {} }),
    window: { addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, parent: { postMessage() {} } },
    document: { addEventListener() {}, removeEventListener() {} },
    fetch: async (url, options) => url.includes('8765/health')
      ? { ok: true, json: async () => ({ tts_cloud_last_error: { at_ms: now.value, reason: 'rate_limited' } }) }
      : nativePlan ? { ok: true, headers: { get: () => 'application/json' }, clone: () => ({ json: async () => ({
        object: 'resident.plan', messages: JSON.parse(options.body).messages, system_prompt: JSON.parse(options.body).airi_system_prompt,
      }) }) } : { answer: await new Promise(resolve => { finish = resolve }) },
    readResidentReply: async response => response.answer,
    createResidentTextFilter: streamReader().createResidentTextFilter,
    residentPlainText: streamReader().residentPlainText,
    residentSpeechText: text => text,
  })
  vm.runInContext(source.replace('export class ResidentSession', 'globalThis.ResidentSession = class ResidentSession'), sandbox)
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-api.js'), 'utf8').replace('export function createResidentApi', 'function createResidentApi'), sandbox)
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-idle.js'), 'utf8').replace('export class ResidentIdle', 'globalThis.ResidentIdle = class ResidentIdle'), sandbox)
  vm.runInContext(ts.transpileModule(script + '\nglobalThis.panel = { sendMessage, draft, messages, busy, session, beginSpeech, checkIdle, status, cancelWaiting }', { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, sandbox)
  mounted.forEach(callback => callback())
  sandbox.panel.draft.value = '舊居民未送出資料'
  const pending = sandbox.panel.sendMessage('我叫測試街坊', false)
  sandbox.panel.beginSpeech()
  assert.equal(sandbox.panel.busy.value, true)
  now.value += 180000
  sandbox.panel.checkIdle()
  assert.equal(sandbox.panel.draft.value, '')
  assert.equal(sandbox.panel.messages.value.length, 0)
  assert.equal(sandbox.panel.session.profile, '')
  assert.equal(sandbox.panel.busy.value, false)
  assert.equal(cancelled, 1)
  assert.ok(events.some(event => event[0] === 'endSession'))
  finish('舊居民的遲到回覆')
  await pending
  assert.equal(sandbox.panel.messages.value.length, 0)
  sandbox.panel.beginSpeech()
  const healthCheck = [...timers.values()].find(timer => timer.due === now.value + 1000)
  await healthCheck.callback()
  assert.match(sandbox.panel.status.value, /Google.*額度限制/)
  assert.equal(cancelled, 2)
  nativePlan = true
  await sandbox.panel.sendMessage('公開測試，使用 AIRI 的選擇', false)
  assert.equal(nativeCalls[0].model, 'native-model')
  assert.equal(nativeCalls[0].provider.id, 'native-test')
  assert.ok(nativeCalls[0].messages[0].content.startsWith('AIRI已選角色設定\n'))
  assert.match(nativeCalls[0].messages[0].content, /不輸出 ACT、DELAY/)
  assert.equal(nativeCalls[0].options.supportsTools, false)
  nativeSelection.activeProvider = 'another-native-provider'
  nativeSelection.activeModel = 'another-native-model'
  await sandbox.panel.sendMessage('轉換後仍記得上一句嗎', false)
  assert.equal(nativeCalls[1].provider.id, 'another-native-provider')
  assert.equal(nativeCalls[1].model, 'another-native-model')
  assert.equal(nativeCalls[1].messages[1].content, '公開測試，使用 AIRI 的選擇')
  nativePlan = false
  const savedHistory = JSON.stringify(sandbox.panel.session.history)
  const savedIdentity = sandbox.panel.session.sessionId
  sandbox.panel.session.profile = '公開街坊'
  const waiting = sandbox.panel.sendMessage('等待中的公開問題', false)
  sandbox.panel.draft.value = '等候時修改的草稿'
  const waitingTimer = [...timers.values()].find(timer => timer.due === now.value + 4000)
  waitingTimer.callback()
  assert.match(sandbox.panel.status.value, /我仲喺度整理/)
  sandbox.panel.cancelWaiting()
  assert.equal(sandbox.panel.busy.value, false)
  assert.equal(sandbox.panel.draft.value, '等候時修改的草稿')
  assert.equal(sandbox.panel.session.profile, '公開街坊')
  assert.equal(sandbox.panel.session.sessionId, savedIdentity)
  assert.equal(JSON.stringify(sandbox.panel.messages.value), savedHistory)
  assert.match(sandbox.panel.status.value, /已送達的個案仍會由職員跟進/)
  finish('取消後遲到的答案')
  await waiting
  assert.equal(JSON.stringify(sandbox.panel.messages.value), savedHistory)
  assert.equal(sandbox.panel.draft.value, '等候時修改的草稿')
  const index = fs.readFileSync(path.join(__dirname, '../airi_overlay/voice-stage.ts.txt'), 'utf8')
  assert.match(index, /function resetResidentInput\(\) \{[\s\S]*?voiceTurn.reset\(\)[\s\S]*?enabled.value = true/)
})


test('default browser timers keep the Window receiver on mount, reset and unmount', () => {
  const context = vm.createContext({})
  vm.runInContext(`
    globalThis.clock = 1
    globalThis.tasks = new Map()
    globalThis.expired = 0
    globalThis.sequence = 0
    Date.now = () => clock
    globalThis.setTimeout = function (callback, delay) {
      if (this !== globalThis) throw new TypeError('Illegal invocation')
      const id = ++sequence
      tasks.set(id, { callback, delay })
      return id
    }
    globalThis.clearTimeout = function (id) {
      if (this !== globalThis) throw new TypeError('Illegal invocation')
      tasks.delete(id)
    }
  `, context)
  const idle = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-idle.js'), 'utf8')
  vm.runInContext(idle.replace('export class ResidentIdle', 'globalThis.ResidentIdle = class ResidentIdle'), context)
  vm.runInContext(`
    const idle = new ResidentIdle(() => expired++)
    idle.touch()
    if (tasks.size !== 1) throw new Error('mount did not arm exactly one timer')
    idle.touch()
    if (tasks.size !== 1) throw new Error('activity duplicated timers')
    clock += 180000
    tasks.values().next().value.callback()
    if (expired !== 1 || tasks.size !== 0) throw new Error('expiry failed to clean up')
    idle.touch()
    idle.stop()
    if (tasks.size !== 0) throw new Error('unmount retained a timer')
  `, context)
})
