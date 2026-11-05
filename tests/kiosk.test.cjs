const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const source = fs.readFileSync(path.join(__dirname, '../deploy/cloud/web/kiosk.js'), 'utf8')
const modulePromise = import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))

function browser(options = {}) {
  const calls = { permissions: [], media: 0, audio: 0, full: 0 }
  const win = { location: { origin: 'https://neighbour.test' }, isSecureContext: true,
    navigator: { mediaDevices: { getUserMedia() { calls.media++; throw Error('must not open device') } },
      permissions: { async query({ name }) { calls.permissions.push(name); return { state: name === 'camera' ? 'prompt' : 'granted' } } } },
    AudioContext: function () { calls.audio++; throw Error('must not play') }, WebAssembly: {},
    document: { documentElement: { async requestFullscreen() { calls.full++ } } },
    matchMedia: () => ({ matches: false }), ...options }
  return { win, calls }
}

test('kiosk check reads permission state only, without devices, audio or full screen', async () => {
  const { kioskReadiness } = await modulePromise
  const { win, calls } = browser()
  const value = await kioskReadiness(win)
  assert.deepEqual(calls, { permissions: ['microphone', 'camera'], media: 0, audio: 0, full: 0 })
  assert.equal(value.hardwareTested, false)
  assert.equal(value.readsOnly, true)
  assert.equal(value.residentUrl, '/?workspace=resident')
  assert.equal(value.rows.find(row => row.label === '咪高峰權限').ok, true)
  assert.equal(value.rows.find(row => row.label === '鏡頭權限').ok, false)
})

test('queries same-origin top portal rather than media-denied staff iframe', async () => {
  const { kioskReadiness } = await modulePromise
  const top = browser(), child = browser({ isSecureContext: false })
  child.win.top = top.win
  const value = await kioskReadiness(child.win)
  assert.equal(value.rows[0].ok, true)
  assert.equal(child.calls.permissions.length, 0)
  assert.equal(top.calls.permissions.length, 2)
})

test('cross-origin top is not used and unsupported Safari permission query is honest', async () => {
  const { kioskReadiness } = await modulePromise
  const { win, calls } = browser()
  win.top = { location: { origin: 'https://other.test' }, navigator: { permissions: { query() { throw Error('cross-origin') } } } }
  win.navigator.permissions.query = async () => { throw new TypeError('not supported') }
  const value = await kioskReadiness(win)
  assert.equal(value.rows.find(row => row.label === '鏡頭權限').text, '未能讀取，請在居民頁確認')
  assert.equal(calls.media, 0)
})

test('insecure or media-less browser never queries permissions or claims media readiness', async () => {
  const { kioskReadiness } = await modulePromise
  const { win, calls } = browser({ isSecureContext: false })
  const value = await kioskReadiness(win)
  assert.equal(value.rows[0].ok, false)
  assert.equal(value.rows[1].ok, false)
  assert.deepEqual(calls.permissions, [])
})

test('hanging permission inspection stops within a bounded wait', async () => {
  const { kioskReadiness } = await modulePromise
  const { win } = browser()
  win.navigator.permissions.query = () => new Promise(() => {})
  const started = Date.now()
  const value = await kioskReadiness(win)
  assert.ok(Date.now() - started < 2500)
  assert.equal(value.rows[2].ok, false)
  assert.match(value.rows[2].text, /未能讀取/)
})

test('mount is passive; only explicit buttons inspect or enter fullscreen and rapid checks coalesce', async () => {
  const { mountKiosk } = await modulePromise
  const { win, calls } = browser()
  function node() {
    return { listeners: {}, textContent: '', dataset: {}, addEventListener(key, fn) { this.listeners[key] = fn },
      replaceChildren(...items) { this.children = items } }
  }
  const nodes = Object.fromEntries(['kioskCheck', 'kioskFullscreen', 'kioskChecks', 'kioskStatus'].map(key => [key, node()]))
  const doc = { getElementById: key => nodes[key], createElement: () => node() }
  mountKiosk(doc, win)
  assert.deepEqual(calls, { permissions: [], media: 0, audio: 0, full: 0 })
  const pending = nodes.kioskCheck.listeners.click()
  await nodes.kioskCheck.listeners.click()
  await pending
  assert.equal(calls.permissions.length, 2)
  assert.equal(nodes.kioskChecks.children.length, 14)
  await nodes.kioskFullscreen.listeners.click()
  assert.equal(calls.full, 1)
  assert.equal(calls.media + calls.audio, 0)
  assert.match(nodes.kioskStatus.textContent, /已進入全螢幕/)
})

test('fullscreen rejected or unavailable preserves original page and explains next step', async () => {
  const { mountKiosk } = await modulePromise
  const { win } = browser()
  const nodes = Object.fromEntries(['kioskCheck', 'kioskFullscreen', 'kioskChecks', 'kioskStatus'].map(key => [key, { listeners: {}, addEventListener(k, fn) { this.listeners[k] = fn } }]))
  mountKiosk({ getElementById: key => nodes[key] }, win)
  win.document.documentElement.requestFullscreen = async () => { throw Error('not permitted') }
  await nodes.kioskFullscreen.listeners.click()
  assert.match(nodes.kioskStatus.textContent, /原有畫面保留/)
  delete win.document.documentElement.requestFullscreen
  await nodes.kioskFullscreen.listeners.click()
  assert.match(nodes.kioskStatus.textContent, /加入主畫面/)
})
