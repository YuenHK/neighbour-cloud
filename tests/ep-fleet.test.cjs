const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const manual = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-console.js'), 'utf8')
const fleet = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-fleet.js'), 'utf8')
const flush = () => new Promise(resolve => setImmediate(resolve))

async function fixture({ remembered = false, safetyHold = false, manualOnly = false, hardwareOnly = false } = {}) {
  const calls = []
  const discoveryCalls = []
  const nodes = new Map()
  const created = []
  const events = {}
  let timer = 0
  let pollHandler
  let revision = 'synthetic-revision-1'
  let expired = false
  let gimbalStopPending = false
  let resolveGimbalStop
  function element(tag = 'div') {
    const node = { tagName: tag.toUpperCase(), dataset: {}, value: '', textContent: '', hidden: false,
      className: '', children: [], listeners: {}, classList: { toggle() {} },
      addEventListener(name, handler) { this.listeners[name] = handler },
      append(...items) { this.children.push(...items) },
      replaceChildren(...items) { this.children = items },
      setAttribute() {}, setPointerCapture() {}, showModal() { this.open = true }, close() { this.open = false } }
    node.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 })
    created.push(node)
    return node
  }
  const directions = ['forward', 'backward', 'left', 'right', 'turn_left', 'turn_right'].map((direction) => {
    const node = element('button')
    node.dataset.epDirection = direction
    return node
  })
  const states = new Map(['ep-1', 'ep-2'].map((id, index) => [id, {
    id, name: `EP 0${index + 1}`, sn: `TEST-SN-0${index + 1}`, ip: `192.168.99.${index + 1}`, connection: remembered ? 'not_connected' : 'connected', remembered,
    battery_percent: 50 + index, follow_enabled: true, speed_level: 1, control: null }]))
  const context = vm.createContext({ Blob, Uint8Array, atob, AbortController, AbortSignal,
    DOMParser: class { parseFromString() { return { querySelector: () => ({ value: 'synthetic-refreshed-local-token' }) } } },
    setTimeout() { return ++timer }, clearTimeout() {}, setInterval(handler, ms) { if (ms === 800) pollHandler = handler },
    URL: { createObjectURL: () => 'blob:synthetic', revokeObjectURL() {} },
    window: { addEventListener(name, handler) { events[name] = handler } },
    fetch: async (url, options) => {
      if (url.endsWith('/discovery')) { discoveryCalls.push(url); return { ok: true, json: async () => ({ enabled: true }) } }
      const body = options.body ? JSON.parse(options.body) : null
      calls.push({ url, method: options.method, body })
      if (url.includes('/frame.jpg?')) return { ok: true, status: 200,
        headers: { get(name) { return name === 'X-Frame-Key' ? 'synthetic-1' : '0' } },
        blob: async () => new Blob(['synthetic JPEG'], { type: 'image/jpeg' }) }
      if (url === '/robots') {
        expired = false
        return { ok: true, text: async () => '<input id="epKey" value="synthetic-refreshed-local-token">' }
      }
      if (expired) return { ok: false, status: 403, json: async () => ({ detail: 'synthetic-expired-token' }) }
      let result
      const match = url.match(/devices\/(ep-[12])\/(.*)$/)
      if (url.endsWith('/fleet')) result = { devices: [...states.values()], qr_revision: safetyHold ? '' : revision,
        safety_hold: safetyHold, manual_only: manualOnly, notice: safetyHold ? 'EP 暫停使用' : '' }
      else if (url.endsWith('/qr')) result = safetyHold || manualOnly ? { safety_hold: safetyHold, svg_base64: null }
        : { svg_base64: 'PHN2Zy8+', ssid: 'Synthetic Wi-Fi', revision }
      else if (match) {
        const [, id, action] = match
        const state = states.get(id)
        if (action === 'gimbal-stop' && gimbalStopPending) {
          await new Promise(resolve => { resolveGimbalStop = resolve })
        }
        if (action === 'speed') state.speed_level = body.level
        if (action === 'gimbal-follow') {
          state.follow_enabled = body.enabled
          state.drive_mode = body.enabled ? 'chassis_lead' : 'free'
        }
        if (action === 'connect') state.connection = 'connected'
        if (action === 'prepare-control') state.control = { state: 'idle', direction: 'stop', lease_active: false, software_stop_latched: false }
        if (action === 'lease') result = { mode: 'dji-ep-sdk-live', lease_token: `synthetic-lease-token-${id}`, server_time_ms: Date.now() }
        else if (action === 'gimbal-start') result = { generation: 42, server_time_ms: Date.now() }
        else if (action === 'command') result = { connected: true, direction: body.direction,
          state: body.direction === 'stop' ? 'safe_stop' : 'manual', lease_active: body.direction !== 'stop' }
        else if (action === 'video-frame') result = { jpeg_base64: null, video_enabled: true }
        else result = state
      }
      return { ok: true, json: async () => result }
    } })
  vm.runInContext(manual, context)
  context.document = { body: { dataset: { epUi: 'fleet', hardwareOnly: String(hardwareOnly) } }, hidden: false,
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, element())
      return nodes.get(id)
    }, querySelectorAll() { return directions }, createElement: element,
    addEventListener(name, handler) { events[name] = handler } }
  context.document.documentElement = { async requestFullscreen() {
    context.document.fullscreenElement = this
    events.fullscreenchange()
  } }
  context.document.exitFullscreen = async () => {
    context.document.fullscreenElement = null
    events.fullscreenchange()
  }
  vm.runInContext(fleet, context)
  await flush()
  return { calls, discoveryCalls, nodes, created, events, directions,
    addSaved(id, online = false) { states.set(id, { id, sn: `TEST-SN-${id}`, remembered: true, connection: online ? 'connected' : 'not_connected' }) },
    setOnline(id, value = true) { states.get(id).connection = value ? 'connected' : 'not_connected' },
    holdGimbalStop() { gimbalStopPending = true },
    finishGimbalStop() { gimbalStopPending = false; resolveGimbalStop() },
    changeQr() { revision = 'synthetic-revision-2' }, expire() { expired = true },
    async poll() { await pollHandler(); await flush() }, async monitor() {
    nodes.get('monitorEp').listeners.click()
    await flush()
  }, async select(id) {
    const button = created.find(node => node.className === 'select-ep' && node.textContent === `操作 TEST-SN-0${id}`)
    assert.ok(button)
    button.listeners.click()
    await flush()
  } }
}

test('fleet load never starts a camera, prepares controls or acquires leases', async () => {
  const f = await fixture()
  assert.ok(f.calls.every(call => call.method === 'GET'))
  assert.equal(f.nodes.get('devicesView').hidden, false)
  assert.equal(f.nodes.get('driveControls').hidden, true)
  assert.deepEqual(f.created.filter(node => node.tagName === 'H3').map(node => node.textContent), ['TEST-SN-01', 'TEST-SN-02'])
})

test('cloud hardware-only console never creates QR or enables unavailable patrol on load', async () => {
  const f = await fixture({hardwareOnly:true, manualOnly:false})
  await f.poll()
  assert.ok(f.calls.every(call=>call.method==='GET'))
  assert.equal(f.discoveryCalls.length,0)
  assert.equal(f.nodes.get('patrolToggle').disabled,true)
  assert.match(f.nodes.get('patrolStatus').textContent,/尚未接通雲端/)
})

test('page requests background discovery but never requests motion or warning on load', async () => {
  const f = await fixture()
  assert.equal(f.discoveryCalls.length, 0) // Common shell owns the one discovery heartbeat.
  await f.monitor()
  assert.ok(f.calls.some(call => call.url.includes('/frame.jpg?')))
  assert.equal(f.calls.some(call => /\/manual-warning$|\/infrared-warning$|\/lease$|\/command$/.test(call.url)), false)
})

test('infrared hold starts only from human press and release sends the same fenced press id', async () => {
  const f = await fixture()
  assert.equal(f.calls.some(c => c.url.endsWith('/infrared-warning')), false)
  await f.monitor()
  await f.select(2)
  const button = f.nodes.get('infraredWarning')
  const pending = button.listeners.pointerdown({ type: 'pointerdown', button: 0, pointerId: 7, preventDefault() {} })
  button.listeners.pointerup()
  await pending
  await flush()
  const calls = f.calls.filter(c => c.url.endsWith('/infrared-warning'))
  assert.deepEqual(calls.map(c => c.body.active), [true, false])
  assert.equal(calls[0].body.press_id, calls[1].body.press_id)
  assert.ok(calls.every(c => c.url.includes('/ep-2/')))
  assert.equal(f.calls.some(c => /\/command$|\/lease$|\/prepare-control$/.test(c.url)), false)
})

test('six saved robots use compact cards, online first; offline removal requires two clicks', async () => {
  const f = await fixture({ remembered: true })
  for (let i = 3; i <= 6; i++) f.addSaved(`ep-${i}`, i === 4)
  await f.poll()
  const list = f.nodes.get('deviceList')
  assert.equal(list.dataset.density, 'compact')
  assert.equal(list.children.length, 6)
  assert.match(list.children[0].className, /is-online/)
  const onlineRemove = list.children[0].children.find(node => node.className === 'forget-ep')
  assert.equal(onlineRemove.disabled, true)
  const offline = list.children.find(card => /is-offline/.test(card.className))
  const remove = offline.children.find(node => node.className === 'forget-ep')
  await remove.listeners.click()
  assert.equal(f.calls.filter(call => call.method === 'DELETE').length, 0)
  await remove.listeners.click()
  assert.equal(f.calls.filter(call => call.method === 'DELETE').length, 1)
  assert.equal(f.calls.some(call => /\/disconnect$/.test(call.url)), false)
})

test('incident hold displays paused robots and never auto-generates QR or reconnects', async () => {
  const f = await fixture({ remembered: true, safetyHold: true })
  await f.poll()
  assert.ok(f.calls.every(call => call.method === 'GET'))
  assert.equal(f.nodes.get('makeQr').disabled, true)
  assert.equal(f.nodes.get('manualWifiQr').disabled, true)
  assert.match(f.nodes.get('pairStatus').textContent, /控制故障/)
  assert.match(f.nodes.get('fleetNotice').textContent, /暫停/)
  assert.equal(f.nodes.get('monitorEp').disabled, true)
  assert.equal(f.nodes.get('monitorEp').hidden, true)
  assert.equal(f.nodes.get('addEp').hidden, true)
  assert.equal(f.nodes.get('pairingView').hidden, true)
})

test('manual service never pairs or connects on load; only a human connect click dispatches connect', async () => {
  const f = await fixture({ remembered: true, manualOnly: true })
  await f.poll()
  assert.ok(f.calls.every(call => call.method === 'GET'))
  const connect = f.created.find(node => node.tagName === 'BUTTON' && node.textContent === '連線')
  assert.ok(connect && !connect.disabled)
  connect.listeners.click()
  await flush()
  assert.deepEqual(f.calls.filter(call => call.method === 'POST').map(call => call.url.split('/').at(-1)), ['connect'])
})

test('another tab updating QR refreshes the displayed code without reconnecting or moving', async () => {
  const f = await fixture()
  f.changeQr()
  await f.poll()
  assert.equal(f.calls.filter(call => call.url.endsWith('/qr')).length, 2)
  assert.ok(f.calls.every(call => call.method === 'GET'))
})

test('after service restart a stale capability refreshes in RAM and read-only polling recovers automatically', async () => {
  const f = await fixture()
  f.expire()
  await f.poll()
  assert.equal(f.calls.filter(call => call.url === '/robots').length, 1)
  assert.equal(f.nodes.get('epKey').value, 'synthetic-refreshed-local-token')
  assert.equal(f.nodes.get('fleetNotice').textContent, '')
  assert.equal(f.nodes.get('driveControls').hidden, true)
})

test('offline robots are red and disabled; background online changes enable green controls without refresh', async () => {
  const f = await fixture({ remembered: true })
  assert.equal(f.nodes.get('pairingView').hidden, false)
  assert.equal(f.nodes.get('devicesView').hidden, false)
  assert.equal(f.nodes.get('fleetCount').textContent, '2 台已加入 · 0 台已連線')
  const buttons = f.created.filter(node => node.tagName === 'BUTTON' && node.textContent === '離線')
  assert.equal(buttons.length, 2)
  assert.ok(buttons.every(button => button.disabled))
  buttons[1].listeners.click()
  await flush()
  assert.equal(f.calls.some(call => call.method === 'POST'), false)
  f.setOnline('ep-2')
  await f.poll()
  assert.equal(f.nodes.get('fleetCount').textContent, '2 台已加入 · 1 台已連線')
  const cards = f.nodes.get('deviceList').children
  assert.match(cards[0].className, /is-online/)
  assert.match(cards[1].className, /is-offline/)
  assert.equal(cards[0].children.find(node => node.tagName === 'BUTTON').disabled, false)
})

test('credential recovery never replays a POST preparation or movement command', async () => {
  const f = await fixture()
  await f.monitor()
  await f.select(1)
  f.expire()
  f.events.keydown({ key: 'w', target: { tagName: 'SECTION' }, preventDefault() {} })
  await flush()
  assert.equal(f.calls.filter(call => call.url.endsWith('/prepare-control')).length, 1)
  assert.equal(f.calls.some(call => /\/command$|\/lease$/.test(call.url)), false)
})

test('split view starts only video and selecting a robot does not move it', async () => {
  const f = await fixture()
  await f.monitor()
  assert.deepEqual(f.calls.filter(call => call.url.endsWith('/video-start')).map(call => call.url), [
    '/api/v1/robot/ep/devices/ep-1/video-start', '/api/v1/robot/ep/devices/ep-2/video-start'])
  await f.select(2)
  assert.equal(f.nodes.get('driveControlLabel').textContent, '操作 TEST-SN-02')
  assert.equal(f.calls.some(call => /lease|command|prepare-control/.test(call.url)), false)
})

test('W hold and release targets selected EP 02; switching cannot renew EP 02 movement', async () => {
  const f = await fixture()
  await f.monitor()
  await f.select(2)
  f.events.keydown({ key: 'w', target: { tagName: 'BUTTON' }, preventDefault() {} })
  await flush()
  f.events.keyup({ key: 'w' })
  await flush()
  await f.select(1)
  const commands = f.calls.filter(call => call.url.endsWith('/command'))
  assert.deepEqual(commands.map(call => [call.url, call.body.direction]), [
    ['/api/v1/robot/ep/devices/ep-2/command', 'forward'], ['/api/v1/robot/ep/devices/ep-2/command', 'stop']])
  assert.ok(commands.every(call => call.body.ttl_ms === 300))
  assert.equal(f.nodes.get('driveControlLabel').textContent, '操作 TEST-SN-01')
})

test('closing view while holding sends stop to that EP and stops both cameras', async () => {
  const f = await fixture()
  await f.monitor()
  await f.select(1)
  f.directions[0].listeners.pointerdown({ button: 0, pointerId: 1, preventDefault() {} })
  await flush()
  f.nodes.get('closeDrive').listeners.click()
  await flush()
  const commands = f.calls.filter(call => call.url.endsWith('/command'))
  assert.deepEqual(commands.map(call => call.body.direction), ['forward', 'stop'])
  assert.ok(commands.every(call => call.url.includes('/ep-1/')))
  assert.equal(f.calls.filter(call => call.url.endsWith('/video-stop')).length, 2)
  assert.equal(f.nodes.get('driveControls').hidden, true)
})

test('clicking a split pane switches target and stops previous hold without moving new EP', async () => {
  const f = await fixture()
  await f.monitor()
  await f.select(1)
  f.events.keydown({ key: 'w', target: { tagName: 'SECTION' }, preventDefault() {} })
  await flush()
  const panes = f.created.filter(node => node.className === 'view-tile')
  panes[1].listeners.click({ target: { closest: () => null } })
  await flush()
  assert.equal(f.nodes.get('driveControlLabel').textContent, '操作 TEST-SN-02')
  const commands = f.calls.filter(call => call.url.endsWith('/command'))
  assert.deepEqual(commands.map(call => [call.url, call.body.direction]), [
    ['/api/v1/robot/ep/devices/ep-1/command', 'forward'], ['/api/v1/robot/ep/devices/ep-1/command', 'stop']])
  const previous = f.calls.length
  panes[0].listeners.click({ target: { closest: () => ({ tagName: 'BUTTON' }) } })
  await flush()
  assert.equal(f.nodes.get('driveControlLabel').textContent, '操作 TEST-SN-02')
  assert.equal(f.calls.length, previous)
})

test('fullscreen is reversible and never sends movement', async () => {
  const f = await fixture()
  await f.monitor()
  f.nodes.get('fullScreenViews').listeners.click()
  await flush()
  assert.equal(f.nodes.get('fullScreenViews').textContent, '退出全螢幕')
  f.nodes.get('fullScreenViews').listeners.click()
  await flush()
  assert.equal(f.nodes.get('fullScreenViews').textContent, '全螢幕')
  assert.equal(f.calls.some(call => /\/command$|\/lease$/.test(call.url)), false)
})

test('changing speed releases movement before applying the selected robots level', async () => {
  const f = await fixture()
  await f.monitor()
  await f.select(2)
  f.events.keydown({ key: 'w', target: { tagName: 'SECTION' }, preventDefault() {} })
  await flush()
  f.nodes.get('speedLevel').value = '4'
  f.nodes.get('speedLevel').listeners.change()
  await flush()
  const sequence = f.calls.filter(call => call.url.endsWith('/command') || call.url.endsWith('/speed'))
  assert.deepEqual(sequence.map(call => call.body.direction || call.body.level), ['forward', 'stop', 4])
  assert.ok(sequence.every(call => call.url.includes('/ep-2/')))
  assert.equal(f.nodes.get('speedValue').textContent, '0.60 m/s')
})

test('cursor targets only selected unfollowed gimbal; leaving or switching cancels it', async () => {
  const f = await fixture()
  await f.monitor()
  await f.select(1)
  f.nodes.get('followSelected').listeners.click()
  await flush()
  assert.equal(f.nodes.get('followSelected').textContent, '跟隨：關')
  const panes = f.created.filter(node => node.className === 'view-tile')
  panes[0].listeners.pointerenter({ clientX: 100, clientY: 0, target: { closest: () => null } })
  await flush()
  const target = f.calls.find(call => call.url.endsWith('/gimbal-target'))
  assert.equal(target.url, '/api/v1/robot/ep/devices/ep-1/gimbal-target')
  assert.equal(target.body.yaw, 60)
  assert.equal(target.body.pitch, 25)
  await f.select(2)
  assert.equal(f.calls.filter(call => call.url.endsWith('/gimbal-stop')).length, 1)
  assert.equal(f.calls.some(call => /\/command$|\/lease$/.test(call.url)), false)
})

test('a slow gimbal-stop cannot delay cancelling chassis movement when switching EP', async () => {
  const f = await fixture()
  await f.monitor()
  await f.select(1)
  f.nodes.get('followSelected').listeners.click()
  await flush()
  const panes = f.created.filter(node => node.className === 'view-tile')
  panes[0].listeners.pointerenter({ clientX: 100, clientY: 0, target: { closest: () => null } })
  await flush()
  f.events.keydown({ key: 'w', target: { tagName: 'SECTION' }, preventDefault() {} })
  await flush()
  f.holdGimbalStop()
  panes[1].listeners.click({ target: { closest: () => null } })
  await flush()
  assert.deepEqual(f.calls.filter(call => call.url.endsWith('/command')).map(call => call.body.direction), ['forward', 'stop'])
  f.finishGimbalStop()
  await flush()
  assert.equal(f.nodes.get('driveControlLabel').textContent, '操作 TEST-SN-02')
})
