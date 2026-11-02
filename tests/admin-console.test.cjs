const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const html = fs.readFileSync(path.join(__dirname, '../docs/archive/ui-2026-10-26/admin-legacy.html'), 'utf8')

function harness(request) {
  const nodes = new Map()
  const document = {
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {
        value: '', textContent: '', disabled: false, listeners: {},
        addEventListener(name, handler) { this.listeners[name] = handler },
        replaceChildren(...rows) { this.rows = rows },
        pause() {}, load() {}, removeAttribute() { this.src = '' },
      })
      return nodes.get(selector)
    },
    createElement() { return { textContent: '' } },
  }
  const calls = []
  const context = vm.createContext({ document, AbortController, setTimeout, clearTimeout,
    Uint8Array, URL: { createObjectURL: () => 'blob:local-test', revokeObjectURL() {} },
    fetch: request, ZhiweiAdminRequest: { json: async (...args) => {
      calls.push(args)
      return request(...args)
    } } })
  vm.runInContext(html.match(/\/\/ BEGIN CONSOLE ASSISTANT([\s\S]*?)\/\/ END CONSOLE ASSISTANT/)[1], context)
  const submit = id => nodes.get(id).listeners.submit({ preventDefault() {} })
  return { nodes, calls, submit }
}

test('chat sends bounded context, no operator or memory credential, and reset clears it', async () => {
  const h = harness(async () => ({ choices: [{ message: { content: '<script>public answer</script>' } }] }))
  for (let i = 0; i < 12; i++) {
    if (!h.nodes.has('#chatInput')) h.nodes.set('#chatInput', { value: '' })
    h.nodes.get('#chatInput').value = `public question ${i}`
    await h.submit('#chatForm')
  }
  const [url, options] = h.calls.at(-1)
  assert.equal(url, '/v1/chat/completions')
  assert.equal(JSON.parse(options.body).messages.length, 21)
  assert.equal(Object.keys(options.headers).length, 2)
  assert.equal(h.nodes.get('#chatHistory').rows.length, 20)
  assert.equal(h.nodes.get('#chatHistory').rows.at(-1).textContent, '助理：<script>public answer</script>')
  h.nodes.get('#chatReset').listeners.click()
  h.nodes.get('#chatInput').value = 'new conversation'
  await h.submit('#chatForm')
  assert.equal(JSON.parse(h.calls.at(-1)[1].body).messages.length, 1)
})

test('pending submit cannot duplicate and failures preserve input without adding history', async () => {
  let reject
  const h = harness(() => new Promise((_, fail) => { reject = fail }))
  h.nodes.set('#chatInput', { value: 'retain this public question' })
  const pending = h.submit('#chatForm')
  await h.submit('#chatForm')
  assert.equal(h.calls.length, 1)
  reject(new Error('HTTP 403'))
  await pending
  assert.match(h.nodes.get('#chatStatus').textContent, /沒有儲存記憶/)
  assert.equal(h.nodes.get('#chatInput').value, 'retain this public question')
  assert.equal(h.nodes.get('#chatSend').disabled, false)
})

test('speech accepts WAV only and a failed regeneration removes old audio', async () => {
  let valid = true
  const bytes = Buffer.alloc(64)
  bytes.write('RIFF', 0)
  bytes.write('WAVE', 8)
  const h = harness(async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8765/v1/audio/speech')
    assert.equal(options.credentials, 'omit')
    assert.equal(options.redirect, 'error')
    return { ok: true, blob: async () => new Blob([bytes], { type: valid ? 'audio/wav' : 'text/html' }) }
  })
  h.nodes.set('#speechInput', { value: '本機公開語音測試' })
  await h.submit('#speechForm')
  assert.equal(h.nodes.get('#speechPlayer').src, 'blob:local-test')
  valid = false
  await h.submit('#speechForm')
  assert.equal(h.nodes.get('#speechPlayer').src, '')
  assert.match(h.nodes.get('#speechStatus').textContent, /失敗或逾時/)
  assert.equal(h.nodes.get('#speechGenerate').disabled, false)
})
