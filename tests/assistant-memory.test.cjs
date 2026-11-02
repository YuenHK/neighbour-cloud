const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const test = require('node:test')
const source = fs.readFileSync(path.join(__dirname, '../airi_overlay/assistant-memory.js'), 'utf8')

test('paired credential is RAM-only and sent only to the exact local chat endpoint', async () => {
  const calls = []
  const listeners = {}
  const opener = { postMessage(data, origin) { calls.push({ data, origin }) } }
  const win = { opener, addEventListener(type, handler) { listeners[type] = handler },
    async fetch(input, init) { const request = input instanceof Request ? input : new Request(input, init); calls.push(request); return {} } }
  let now = 1000
  const context = vm.createContext({ window: win, location: { href: 'http://127.0.0.1:4173/' },
    Request, Headers, URL, Date: { now: () => now }, console: { info() {} } })
  vm.runInContext(source.replace('export function', 'function') + '\ninstallAssistantMemory()', context)
  assert.equal(calls[0].origin, 'http://127.0.0.1:8000')
  const data = { type: 'zhiwei-memory-capability', token: 'x'.repeat(43), expiresIn: 28800 }
  listeners.message({ origin: 'https://evil.example', source: opener, data })
  await win.fetch('http://127.0.0.1:8000/v1/chat/completions', { method: 'POST', body: '{}' })
  assert.equal(calls.at(-1).headers.has('X-Assistant-Memory-Token'), false)
  listeners.message({ origin: 'http://127.0.0.1:8000', source: {}, data })
  await win.fetch('http://127.0.0.1:8000/v1/chat/completions', { method: 'POST', body: '{}' })
  assert.equal(calls.at(-1).headers.has('X-Assistant-Memory-Token'), false)
  listeners.message({ origin: 'http://127.0.0.1:8000', source: opener, data })
  assert.equal(calls.at(-1).data.type, 'zhiwei-memory-accepted')
  await win.fetch('http://127.0.0.1:8000/v1/chat/completions', { method: 'POST', body: '{}' })
  assert.equal(calls.at(-1).headers.get('X-Assistant-Memory-Token'), data.token)
  assert.equal(calls.at(-1).redirect, 'error')
  assert.equal(calls.at(-1).credentials, 'omit')
  for (const url of ['http://127.0.0.1:8000/api/v1/robot/command', 'https://cloud.example/v1/chat/completions',
    'http://127.0.0.1:8765/v1/audio/speech', 'http://127.0.0.1:8000/v1/chat/completions/else']) {
    await win.fetch(url, { method: 'POST', body: '{}' })
    assert.equal(calls.at(-1).headers.has('X-Assistant-Memory-Token'), false)
  }
  now += 28800001
  await assert.rejects(win.fetch('http://127.0.0.1:8000/v1/chat/completions', { method: 'POST', body: '{}' }), /授權已到期/)
})

test('memory UI is explicit, safe text rendering, no capture or credential persistence', () => {
  const js = fs.readFileSync(path.join(__dirname, '../edge_hub/static/assistant-memory.js'), 'utf8')
  const html = fs.readFileSync(path.join(__dirname, '../edge_hub/static/assistant-memory.html'), 'utf8')
  assert.doesNotThrow(() => new vm.Script(js))
  assert.doesNotMatch(js + source, /localStorage|sessionStorage|innerHTML|getUserMedia|\.play\(/)
  assert.match(js, /event.source !== popup/)
  assert.match(js, /redirect: 'error'/)
  assert.match(js, /window.confirm/)
  assert.match(html, /不自動保存整段聊天/)
  assert.doesNotMatch(html, /<style|style=|<video|<audio/)
  assert.match(js, /zhiwei-memory-accepted/)
  assert.match(js, /正在等待 AIRI 確認/)
  assert.match(js, /\|\| issued/)
})

test('management page needs a matching child acknowledgement, not just a sent token', async () => {
  const js = fs.readFileSync(path.join(__dirname, '../edge_hub/static/assistant-memory.js'), 'utf8')
  const nodes = new Map()
  const listeners = {}
  const sent = []
  let issued = 0
  const popup = { postMessage(message, origin) { sent.push({ message, origin }) } }
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, { value: selector === '#memoryKey' ? 'unit-test-only' : '',
      textContent: '', addEventListener(type, callback) { this[type] = callback } })
    return nodes.get(selector)
  }
  const sandbox = vm.createContext({ document: { querySelector: node }, AbortController,
    window: { open: () => popup, addEventListener: (name, cb) => { listeners[name] = cb },
      removeEventListener: name => { delete listeners[name] } },
    setTimeout: () => 1, clearTimeout() {},
    fetch: async () => { issued++; return { ok: true, json: async () => ({token:'x'.repeat(43),expires_in_seconds:28800}) } } })
  vm.runInContext(js, sandbox)
  node('#pairMemory').click()
  const ready = listeners.message
  await ready({ origin: 'https://evil.example', source: popup, data: {type:'zhiwei-memory-ready'} })
  assert.equal(issued, 0)
  await ready({ origin: 'http://127.0.0.1:4173', source: popup, data: {type:'zhiwei-memory-ready'} })
  assert.equal(issued, 1)
  assert.equal(sent.length, 1)
  assert.match(node('#memoryStatus').textContent, /等待 AIRI 確認/)
  await ready({ origin: 'http://127.0.0.1:4173', source: popup, data: {type:'zhiwei-memory-ready'} })
  assert.equal(issued, 1)
  await ready({ origin: 'http://127.0.0.1:4173', source: {}, data: {type:'zhiwei-memory-accepted'} })
  assert.match(node('#memoryStatus').textContent, /等待 AIRI 確認/)
  await ready({ origin: 'http://127.0.0.1:4173', source: popup, data: {type:'zhiwei-memory-accepted'} })
  assert.match(node('#memoryStatus').textContent, /AIRI 已確認記憶配對/)
  assert.equal(listeners.message, undefined)
})
