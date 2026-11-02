const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-manual-pairing.js'), 'utf8')
const html = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-manual-pairing.html'), 'utf8')
const flush = () => new Promise(resolve => setImmediate(resolve))

async function fixture({ restored = false, denyWifi = false, acceptanceBusy = false } = {}) {
  const nodes = new Map()
  const calls = []
  const revoked = []
  let poll
  let blobCount = 0
  const state = { target: { id: 'ep-2', sn: 'SYNTHETIC-0930' }, active: restored,
    qr_revision: restored ? 'synthetic-restored' : '', ssid: 'Synthetic-Current',
    safety_hold: true, acceptance_busy: acceptanceBusy, pairing: 'idle', candidates: [] }
  const element = () => ({ value: '', textContent: '', hidden: false, disabled: false, open: false, listeners: {},
    addEventListener(name, fn) { this.listeners[name] = fn },
    removeAttribute(name) { delete this[name] },
    showModal() { this.open = true }, close() { this.open = false } })
  for (const [, id] of html.matchAll(/id="([^"]+)"/g)) nodes.set(id, element())
  nodes.get('zoom').hidden = true
  const context = vm.createContext({ AbortSignal, Blob, Uint8Array, atob,
    URL: { createObjectURL() { return `blob:synthetic-${++blobCount}` }, revokeObjectURL(url) { revoked.push(url) } },
    document: { getElementById(id) { assert.ok(nodes.has(id), `missing real HTML id: ${id}`); return nodes.get(id) } },
    setInterval(fn) { poll = fn },
    async fetch(url, options) {
      const action = url.split('/').pop()
      const body = options.body ? JSON.parse(options.body) : undefined
      calls.push({ action, body, options })
      if (action === 'qr' && options.method === 'POST') {
        if (denyWifi && body.password === undefined)
          return { ok: false, json: async () => ({ detail: 'Windows 未能讀取當前 Wi-Fi 帳密' }) }
        state.active = true
        state.qr_revision = 'synthetic-generated'
      }
      if (action === 'end') { state.active = false; state.qr_revision = '' }
      return { ok: true, json: async () => action === 'qr'
        ? { svg_base64: state.active ? 'PHN2Zy8+' : null, ssid: state.ssid, revision: state.qr_revision }
        : { ...state } }
    } })
  vm.runInContext(source, context)
  await flush()
  return { nodes, calls, state, revoked,
    poll: async () => { await poll(); await flush() },
    generate: async () => { nodes.get('generate').listeners.click(); await flush() },
    passwordGenerate: async () => { nodes.get('passwordForm').listeners.submit({ preventDefault() {} }); await flush() },
    end: async () => { await nodes.get('end').listeners.click(); await flush() } }
}

test('page load and polling only GET metadata; no WLAN read or QR POST', async () => {
  const f = await fixture()
  await f.poll()
  assert.ok(f.calls.every(call => call.options.method === 'GET' && call.action === 'status'))
  assert.equal(f.nodes.get('zoom').hidden, true)
  assert.equal(f.nodes.get('generate').disabled, false)
})

test('explicit generate targets 0930 and scan replies never request SDK connection or movement', async () => {
  const f = await fixture()
  await f.generate()
  assert.deepEqual(f.calls.find(call => call.options.method === 'POST').body, { device_id: 'ep-2' })
  assert.equal(f.nodes.get('zoom').hidden, false)
  f.state.pairing = 'joined_network'
  f.state.candidates = [{ ip: '192.168.99.42' }]
  await f.poll()
  await f.poll()
  assert.match(f.nodes.get('notice').textContent, /沒有自動連線/)
  assert.match(f.nodes.get('reply').textContent, /SN 尚未核對/)
  assert.ok(f.calls.every(call => ['status', 'qr'].includes(call.action)))
  const count = f.calls.length
  f.nodes.get('zoom').listeners.click()
  assert.equal(f.nodes.get('qrDialog').open, true)
  f.nodes.get('closeZoom').listeners.click()
  assert.equal(f.calls.length, count)
})

test('existing in-memory QR restores with GET only and end clears image memory', async () => {
  const f = await fixture({ restored: true })
  assert.equal(f.nodes.get('zoom').hidden, false)
  assert.ok(f.calls.every(call => call.options.method === 'GET'))
  await f.end()
  assert.equal(f.nodes.get('zoom').hidden, true)
  assert.equal(f.nodes.get('qrImage').src, undefined)
  assert.equal(f.revoked.length, 1)
  assert.equal(f.calls.filter(call => call.options.method === 'POST').length, 1)
  assert.equal(f.calls.find(call => call.options.method === 'POST').action, 'end')
})

test('Windows key denial never retries POST; optional hidden password is cleared from input', async () => {
  const f = await fixture({ denyWifi: true })
  await f.generate()
  await f.poll()
  assert.match(f.nodes.get('notice').textContent, /Windows/)
  assert.equal(f.nodes.get('manualPassword').open, true)
  assert.equal(f.calls.filter(call => call.options.method === 'POST').length, 1)
  f.nodes.get('wifiPassword').value = 'synthetic-hidden-only'
  await f.passwordGenerate()
  assert.equal(f.nodes.get('wifiPassword').value, '')
  assert.equal(f.nodes.get('zoom').hidden, false)
  assert.equal(f.calls.filter(call => call.options.method === 'POST').length, 2)
  assert.equal(f.nodes.get('notice').textContent.includes('synthetic-hidden-only'), false)
})

test('a pending acceptance session disables pairing instead of disconnecting or connecting automatically', async () => {
  const f = await fixture({ acceptanceBusy: true })
  assert.equal(f.nodes.get('generate').disabled, true)
  await f.generate()
  assert.ok(f.calls.every(call => call.options.method === 'GET'))
  assert.match(f.nodes.get('notice').textContent, /結束並斷線/)
})
