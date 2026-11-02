const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-console.js'), 'utf8')
const context = vm.createContext({ setTimeout, clearTimeout })
vm.runInContext(source, context)
const EpControl = context.EpManualControl
const ready = { connection: 'connected', control: { direction: 'stop', lease_active: false,
  software_stop_latched: false, state: 'idle' } }
const lease = { mode: 'dji-ep-sdk-live', lease_token: 'synthetic-lease-token-only', server_time_ms: 1000 }

test('stop-latched state refuses readiness without issuing motor commands', async () => {
  const calls = []
  const control = new EpControl(async (...args) => { calls.push(args); return ready }, () => {}, () => 1000)
  await control.arm()
  assert.equal(control.armed, true)
  ready.control.software_stop_latched = true
  try {
    await assert.rejects(control.arm(), /尚未就緒/)
    assert.equal(control.armed, false)
  }
  finally { ready.control.software_stop_latched = false }
})

test('release while acquiring a lease sends only a late stop and no movement', async () => {
  const calls = []
  let resolveLease
  const control = new EpControl(async (action, body) => {
    calls.push([action, body])
    if (action === 'connection') return ready
    if (action === 'lease') return new Promise(resolve => { resolveLease = resolve })
    return { state: 'safe_stop', direction: 'stop', lease_active: false }
  }, () => {}, () => 1000)
  await control.arm()
  const pending = control.press('forward')
  await control.release(true)
  resolveLease(lease)
  await pending
  assert.deepEqual(calls.filter(([action]) => action === 'command').map(([, body]) => body.direction), ['stop'])
  assert.equal(control.armed, false)
})

test('holding uses bounded TTL and release revokes continuation; no automatic re-arm', async () => {
  const calls = []
  const control = new EpControl(async (action, body) => {
    calls.push([action, body])
    if (action === 'connection') return ready
    if (action === 'lease') return lease
    return { connected: true, state: body.direction === 'stop' ? 'safe_stop' : 'manual',
      direction: body.direction, lease_active: body.direction !== 'stop' }
  }, () => {}, () => 1000)
  await control.arm()
  await control.press('left')
  await control.release(true)
  const commands = calls.filter(([action]) => action === 'command').map(([, body]) => body)
  assert.deepEqual(commands.map(body => body.direction), ['left', 'stop'])
  assert.deepEqual(commands.map(body => body.seq), [0, 1])
  assert.ok(commands.every(body => body.ttl_ms === 300))
  assert.equal(control.timer, null)
  assert.equal(control.armed, false)
})

test('invalid lease cannot become a motor command or echoed credential', async () => {
  const calls = []
  const control = new EpControl(async (action, body) => {
    calls.push([action, body])
    return action === 'connection' ? ready : { ...lease, lease_token: '<invalid>' }
  }, () => {}, () => 1000)
  await control.arm()
  await control.press('forward')
  assert.equal(calls.some(([action]) => action === 'command'), false)
  assert.equal(control.armed, false)
})

test('failed motor command disarms, attempts stop once and never retries movement', async () => {
  const commands = []
  const control = new EpControl(async (action, body) => {
    if (action === 'connection') return ready
    if (action === 'lease') return lease
    commands.push(body.direction)
    if (body.direction !== 'stop') throw new Error('offline')
    return { state: 'safe_stop', direction: 'stop', lease_active: false }
  }, () => {}, () => 1000)
  await control.arm()
  await control.press('forward')
  assert.deepEqual(commands, ['forward', 'stop'])
  assert.equal(control.armed, false)
  assert.equal(control.timer, null)
})

test('page load only reads passive connection status; no Wi-Fi read or connection POST', async () => {
  const calls = []
  const nodes = new Map()
  const page = vm.createContext({ setTimeout, clearTimeout, setInterval() {}, AbortController,
    window: { addEventListener() {} }, document: { hidden: false, addEventListener() {},
      querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, { value: '', dataset: {}, addEventListener() {} })
        return nodes.get(selector)
      }, querySelectorAll() { return [] } },
    fetch: async (url, options) => {
      calls.push([url, options.method])
      return { ok: true, json: async () => ({ connection: 'not_connected', pairing: 'idle' }) }
    } })
  vm.runInContext(source, page)
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(calls, [['/api/v1/robot/ep/connection', 'GET'], ['/api/v1/robot/ep/qr', 'GET']])
})

test('restored QR stays visible through blur and hidden page without storing credentials in browser', async () => {
  const nodes = new Map()
  const windowEvents = {}
  const documentEvents = {}
  const document = { hidden: false,
    addEventListener(name, handler) { documentEvents[name] = handler },
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, { value: '', dataset: {}, hidden: true,
        addEventListener() {}, removeAttribute() {} })
      return nodes.get(selector)
    }, querySelectorAll() { return [] } }
  const page = vm.createContext({ document, setTimeout, clearTimeout, setInterval() {}, AbortController,
    Blob, Uint8Array, atob, URL: { createObjectURL: () => 'blob:synthetic-only', revokeObjectURL() {} },
    window: { addEventListener(name, handler) { windowEvents[name] = handler } },
    fetch: async url => ({ ok: true, json: async () => url.endsWith('/qr')
      ? { svg_base64: 'PHN2Zy8+', ssid: 'Synthetic-EP', expires_in_seconds: null }
      : { connection: 'not_connected', pairing: 'idle' } }) })
  vm.runInContext(source, page)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(nodes.get('#epQr').hidden, false)
  windowEvents.blur()
  document.hidden = true
  documentEvents.visibilitychange()
  assert.equal(nodes.get('#epQr').hidden, false)
  assert.equal(nodes.get('#epQr').src, 'blob:synthetic-only')
  assert.equal(nodes.get('#qrCountdown').textContent, '持續顯示')
})

test('fresh scan auto-connects once without a lease, while repeated packets do not retry', async () => {
  const calls = []
  let poll
  let status = { connection: 'not_connected', pairing: 'waiting_for_scan', scan_id: 0 }
  const nodes = new Map()
  const page = vm.createContext({ setTimeout, clearTimeout, setInterval(handler) { poll = handler }, AbortController,
    window: { addEventListener() {} }, document: { hidden: false, addEventListener() {},
      querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, { value: '', dataset: {}, addEventListener() {} })
        return nodes.get(selector)
      }, querySelectorAll() { return [] } },
    fetch: async (url, options) => {
      calls.push([url, options.method, options.body])
      return { ok: true, json: async () => url.endsWith('/connect')
        ? { connection: 'connected', ip: '192.168.1.2', control: null }
        : url.endsWith('/qr') ? { svg_base64: null } : status }
    } })
  vm.runInContext(source, page)
  await new Promise(resolve => setImmediate(resolve))
  status = { connection: 'not_connected', pairing: 'joined_network', detected_ip: '192.168.1.2',
    scan_id: 1, scan_received_at_ms: Date.now(), auto_connect_suppressed_scan: 0 }
  await poll()
  await new Promise(resolve => setImmediate(resolve))
  await poll()
  await new Promise(resolve => setImmediate(resolve))
  const connects = calls.filter(([url]) => url.endsWith('/connect'))
  assert.equal(connects.length, 1)
  assert.equal(JSON.parse(connects[0][2]).ip, '192.168.1.2')
  assert.equal(calls.some(([url]) => /lease|command|prepare-control/.test(url)), false)
  status = { ...status, scan_id: 2, auto_connect_suppressed_scan: 2 }
  await poll()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.filter(([url]) => url.endsWith('/connect')).length, 1)
})

test('QR zoom opens and closes a dialog without any connection action', async () => {
  const nodes = new Map()
  const calls = []
  const page = vm.createContext({ setTimeout, clearTimeout, setInterval() {}, AbortController, Blob, Uint8Array, atob,
    URL: { createObjectURL: () => 'blob:synthetic-zoom', revokeObjectURL() {} },
    window: { addEventListener() {} }, document: { hidden: false, addEventListener() {},
      querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, { value: '', dataset: {}, listeners: {},
          addEventListener(name, handler) { this.listeners[name] = handler },
          showModal() { this.open = true }, close() { this.open = false } })
        return nodes.get(selector)
      }, querySelectorAll() { return [] } },
    fetch: async (url, options) => {
      calls.push([url, options.method])
      return { ok: true, json: async () => url.endsWith('/qr')
        ? { svg_base64: 'PHN2Zy8+', ssid: 'Synthetic-EP', expires_in_seconds: null }
        : { connection: 'not_connected' } }
    } })
  vm.runInContext(source, page)
  await new Promise(resolve => setImmediate(resolve))
  nodes.get('#zoomQr').listeners.click()
  assert.equal(nodes.get('#qrDialog').open, true)
  assert.equal(nodes.get('#qrZoomImage').src, 'blob:synthetic-zoom')
  nodes.get('#closeQrDialog').listeners.click()
  assert.equal(nodes.get('#qrDialog').open, false)
  assert.ok(calls.every(([, method]) => method === 'GET'))
})

test('first direction press prepares internally and sends movement without a separate arm action', async () => {
  const calls = []
  const control = new EpControl(async (action, body) => {
    calls.push([action, body])
    if (action === 'prepare-control') return {}
    if (action === 'connection') return ready
    if (action === 'lease') return lease
    return { connected: true, direction: body.direction, state: body.direction === 'stop' ? 'safe_stop' : 'manual',
      lease_active: body.direction !== 'stop' }
  }, () => {}, () => 1000)
  await control.press('forward')
  await control.release()
  assert.deepEqual(calls.map(([action]) => action), ['prepare-control', 'connection', 'lease', 'command', 'command'])
  assert.deepEqual(calls.filter(([action]) => action === 'command').map(([, body]) => body.direction), ['forward', 'stop'])
  assert.equal(control.timer, null)
})

test('release during internal preparation cannot produce a delayed movement or lease', async () => {
  const calls = []
  let finishPreparation
  const control = new EpControl(async (action, body) => {
    calls.push([action, body])
    if (action === 'prepare-control') return new Promise(resolve => { finishPreparation = resolve })
    throw new Error('must not request a lease or move after release')
  }, () => {}, () => 1000)
  const pending = control.press('right')
  await control.release(true)
  finishPreparation({})
  await pending
  assert.deepEqual(calls.map(([action]) => action), ['prepare-control'])
  assert.equal(control.holding, false)
  assert.equal(control.timer, null)
})

test('connected page enables direction buttons but performs no preparation, lease or motor request', async () => {
  const calls = []
  const nodes = new Map()
  const buttons = ['forward', 'backward', 'left', 'right', 'turn_left', 'turn_right'].map(direction => ({
    disabled: true, dataset: { epDirection: direction }, addEventListener() {} }))
  const page = vm.createContext({ setTimeout, clearTimeout, setInterval() {}, AbortController,
    window: { addEventListener() {} }, document: { hidden: false, addEventListener() {},
      querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, { value: '', dataset: {}, addEventListener() {} })
        return nodes.get(selector)
      }, querySelectorAll() { return buttons } },
    fetch: async (url, options) => {
      calls.push([url, options.method])
      return { ok: true, json: async () => url.endsWith('/qr') ? { svg_base64: null }
        : { connection: 'connected', ip: '192.168.1.2', control: null } }
    } })
  vm.runInContext(source, page)
  await new Promise(resolve => setImmediate(resolve))
  assert.ok(buttons.every(button => !button.disabled))
  assert.ok(calls.every(([, method]) => method === 'GET'))
  assert.equal(calls.some(([url]) => /prepare-control|lease|command/.test(url)), false)
})
