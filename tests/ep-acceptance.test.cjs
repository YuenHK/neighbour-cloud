const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-acceptance.js'), 'utf8')
const html = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-acceptance.html'), 'utf8')
const flush = () => new Promise(resolve => setImmediate(resolve))

async function fixture({ failConnect = false, pendingConnect = false, stage = 2, failPrepare = false, pairingActive = false, pendingStart = false, pendingActivate = false, failActivate = false } = {}) {
  const nodes = new Map()
  const calls = []
  const events = {}
  const pairing = { active: pairingActive }
  let poll
  let finishConnect
  let finishStart
  let finishActivate
  let timerId = 0
  let wallClock = 1000000
  const timers = new Map()
  const state = { devices: [{ id: 'ep-1', sn: 'SYNTHETIC-1' }, { id: 'ep-2', sn: 'SYNTHETIC-2' }],
    safety_hold: true, selected_id: null, connection: 'not_connected', elapsed_seconds: 0,
    acceptance_stage: stage, prepare_attempted: false, prepared_idle: false,
    short_press_session: 'a'.repeat(32), short_press_used: false, movement_enabled: false,
    short_press_max_ms: stage >= 5 ? 500 : 200 }
  function element() {
    return { value: '', checked: false, disabled: false, textContent: '', listeners: {},
      addEventListener(name, fn) { this.listeners[name] = fn },
      setAttribute() {}, setPointerCapture() {},
      replaceChildren() { this.value = '' },
      append(child) { if (!this.value) this.value = child.value } }
  }
  const pageHtml = stage >= 3 ? fs.readFileSync(path.join(__dirname,
    stage === 6 ? '../edge_hub/static/ep-idle-motor-acceptance.html'
      : stage === 5 ? '../edge_hub/static/ep-release-check-acceptance.html'
      : stage === 4 ? '../edge_hub/static/ep-short-press-acceptance.html' : '../edge_hub/static/ep-idle-acceptance.html'), 'utf8') : html
  for (const [, id] of pageHtml.matchAll(/id="([^"]+)"/g)) nodes.set(id, element())
  const context = vm.createContext({ AbortSignal,
    Date: class extends Date { static now() { return wallClock } },
    performance: { now: () => 1000 },
    crypto: { randomUUID: () => 'dddddddd-dddd-dddd-dddd-dddddddddddd' },
    setTimeout(fn, ms) { timers.set(++timerId, { fn, ms }); return timerId },
    clearTimeout(id) { timers.delete(id) },
    document: { body: { dataset: { acceptanceStage: String(stage) } },
      getElementById(id) { assert.ok(nodes.has(id), `missing real HTML id: ${id}`); return nodes.get(id) },
      createElement: element, addEventListener(name, fn) { events[`document:${name}`] = fn } },
    window: { addEventListener(name, fn) { events[name] = fn } },
    setInterval(fn) { poll = fn },
    async fetch(url, options) {
      const action = url.split('/').pop()
      const scope = url.includes('/manual-pairing/') ? 'manual-pairing' : 'acceptance'
      const body = options.body ? JSON.parse(options.body) : undefined
      calls.push({ action, body, options, scope })
      if (scope === 'manual-pairing') {
        if (action === 'end') pairing.active = false
        return { ok: true, json: async () => ({ ...pairing }) }
      }
      if (action === 'status' && state.statusRequestFails)
        return { ok: false, status: 503, json: async () => ({ detail: 'Synthetic unavailable status' }) }
      if (action === 'connect' || action === 'connect-auto') {
        state.selected_id = body.device_id
        state.acceptance_stage = body.stage || 2
        if (pendingConnect) await new Promise(resolve => { finishConnect = resolve })
        if (failConnect) {
          state.connection = 'not_connected'
          state.last_connection_error = { code: 'handshake_timeout' }
          return { ok: false, status: 503, json: async () => ({ detail: '機體編號不符' }) }
        }
        state.connection = 'connected'
        state.chassis_status_age_ms = 50
        state.chassis_motion_allowed = true
      }
      if (action === 'prepare') {
        state.prepare_attempted = true
        if (failPrepare) return { ok: false, json: async () => ({ detail: '保留舊停止鎖定' }) }
        state.prepared_idle = true
        state.elapsed_seconds = 0
        state.control ||= { state: 'idle', direction: 'stop', lease_active: false, software_stop_latched: false }
        state.movement_enabled = stage >= 4
        if (stage === 6) {
          state.rest_evidence_version = 'body-window-v5'
          state.motor_state = 'holding_zero'
          state.motor_stop_id = 'e'.repeat(32)
          state.wheel_rest_confirmed = true
          state.movement_enabled = false
        }
      }
      if (action === 'motor-release') {
        state.motor_state = 'released_reply'
        state.movement_enabled = !state.short_press_used
      }
      if (action === 'motor-activate') {
        if (pendingActivate) await new Promise(resolve => { finishActivate = resolve })
        if (failActivate) return { ok: false, json: async () => ({ detail: '電機模式未確認' }) }
        state.motor_state = 'engaged_reply'
        state.movement_enabled = false
      }
      if (action === 'short-press-start') {
        state.short_press_used = true
        state.movement_enabled = false
        state.control = { state: 'manual', direction: 'forward', lease_active: true, software_stop_latched: false }
        if (pendingStart) await new Promise(resolve => { finishStart = resolve })
      }
      if (action === 'short-press-release') {
        state.control = { state: 'safe_stop', direction: 'stop', lease_active: false, software_stop_latched: false, reason: 'operator_release' }
        state.short_press_stop_origin = body.source || 'release'
      }
      if (action === 'reset-stop') {
        state.control = { state: 'idle', software_stop_latched: false, lease_active: false }
        state.prepare_attempted = false
      }
      if (action === 'disconnect') { state.connection = 'not_connected'; state.selected_id = null }
      return { ok: true, json: async () => ({ ...state }) }
    } })
  vm.runInContext(source, context)
  await flush()
  return { nodes, calls, state, events,
    poll: async () => { await poll(); await flush() },
    submit: () => {
      // Simulate the user's explicit SN choice before submitting.
      nodes.get('device').value ||= 'ep-1'
      return nodes.get('acceptanceForm').listeners.submit({ preventDefault() {} })
    },
    submitWithoutChoice: () => nodes.get('acceptanceForm').listeners.submit({ preventDefault() {} }),
    disconnect: () => nodes.get('disconnect').listeners.click(),
    prepare: () => nodes.get('prepare').listeners.click(),
    reset: () => nodes.get('resetStop').listeners.click(),
    motorRelease: () => nodes.get('releaseMotor').listeners.click(),
    endPairing: () => nodes.get('endPairing').listeners.click(),
    press: async (extra = {}) => { nodes.get('shortPress').listeners.pointerdown({ button: 0, isTrusted: true, pointerId: 1, preventDefault() {}, ...extra }); await flush() },
    release: async () => { nodes.get('shortPress').listeners.pointerup(); await flush() },
    runTimers: async () => { for (const [id, timer] of [...timers]) { timers.delete(id); assert.equal(timer.ms, state.short_press_max_ms); timer.fn() }; await flush() },
    finishStart: () => finishStart(),
    finishActivate: () => finishActivate(),
    autoChange: async () => { nodes.get('autoConnect').listeners.change(); await flush(); await flush() },
    advanceAuto: async () => { wallClock += 6000; await poll(); await flush(); await flush() },
    finish: () => finishConnect() }
}

test('real page IDs work and page load/polling never connect or request Wi-Fi', async () => {
  const f = await fixture()
  await f.poll()
  assert.ok(f.calls.every(call => call.action === 'status' && call.options.method === 'GET'))
  assert.equal(f.nodes.get('connect').disabled, true)
  assert.equal(f.nodes.get('device').value, '')
  assert.equal(f.nodes.get('disconnect').disabled, true)
})

test('stationary confirmation and explicit submission start exactly one selected connection', async () => {
  const f = await fixture()
  await f.submit()
  assert.equal(f.calls.some(call => call.action === 'connect'), false)
  f.nodes.get('stationary').checked = true
  f.nodes.get('device').value = 'ep-2'
  await f.submit()
  await f.poll()
  await f.submit()
  const requests = f.calls.filter(call => call.action === 'connect')
  assert.equal(requests.length, 1)
  assert.deepEqual(requests[0].body, { device_id: 'ep-2', confirmed_stationary: true })
  assert.equal(f.nodes.get('device').disabled, true)
  assert.equal(f.nodes.get('connect').disabled, true)
  assert.equal(f.nodes.get('disconnect').disabled, false)
  assert.ok(f.calls.every(call => ['status', 'connect'].includes(call.action)))
})

test('timer reaching two minutes requires human observation and never records an automatic pass', async () => {
  const f = await fixture()
  f.nodes.get('stationary').checked = true
  await f.submit()
  f.state.elapsed_seconds = 120
  await f.poll()
  assert.match(f.nodes.get('status').textContent, /記錄有沒有飄移/)
  assert.equal(f.calls.filter(call => call.options.method === 'POST').length, 1)
  await f.disconnect()
  assert.equal(f.nodes.get('connect').disabled, false)
})

test('connection errors survive status polling and never cause a retry', async () => {
  const f = await fixture({ failConnect: true })
  f.nodes.get('stationary').checked = true
  await f.submit()
  await f.poll()
  assert.match(f.nodes.get('status').textContent, /機體編號不符/)
  assert.equal(f.calls.filter(call => call.action === 'connect').length, 1)
  assert.equal(f.nodes.get('connect').disabled, true)
})

test('leaving while connecting sends one cancellation, without issuing a control command', async () => {
  const f = await fixture({ pendingConnect: true })
  f.nodes.get('stationary').checked = true
  const pending = f.submit()
  await flush()
  f.events.pagehide()
  await flush()
  const cancel = f.calls.filter(call => call.action === 'disconnect')
  assert.equal(cancel.length, 1)
  assert.equal(cancel[0].options.keepalive, true)
  f.finish()
  await pending
  assert.ok(f.calls.every(call => ['status', 'connect', 'disconnect'].includes(call.action)))
})

test('stage three never prepares on load or connect, and requires its own recenter confirmation', async () => {
  const f = await fixture({ stage: 3 })
  assert.ok(f.calls.every(call => call.action === 'status'))
  f.nodes.get('stationary').checked = true
  await f.submit()
  assert.equal(f.calls.filter(call => call.action === 'prepare').length, 0)
  assert.equal(f.calls.find(call => call.action === 'connect').body.stage, 3)
  assert.match(f.nodes.get('status').textContent, /尚未準備/)
  await f.prepare()
  assert.equal(f.calls.filter(call => call.action === 'prepare').length, 0)
  f.nodes.get('prepareConfirm').checked = true
  f.state.chassis_motion_allowed = false
  await f.poll()
  await f.prepare()
  assert.equal(f.calls.filter(call => call.action === 'prepare').length, 0)
  f.state.chassis_motion_allowed = true
  await f.poll()
  await f.prepare()
  await f.prepare()
  assert.equal(f.calls.filter(call => call.action === 'prepare').length, 1)
  assert.deepEqual(f.calls.find(call => call.action === 'prepare').body, { confirmed_gimbal_recenter: true })
  assert.equal(f.nodes.get('prepare').disabled, true)
  assert.ok(f.calls.every(call => ['status', 'connect', 'prepare'].includes(call.action)))
})

test('stage three preparation failure stays visible and cannot automatically retry or unlock', async () => {
  const f = await fixture({ stage: 3, failPrepare: true })
  f.nodes.get('stationary').checked = true
  await f.submit()
  f.nodes.get('prepareConfirm').checked = true
  await f.prepare()
  await f.poll()
  await f.prepare()
  assert.match(f.nodes.get('status').textContent, /舊停止鎖定/)
  assert.equal(f.calls.filter(call => call.action === 'prepare').length, 1)
  assert.equal(f.nodes.get('prepare').disabled, true)
  assert.ok(f.calls.every(call => ['status', 'connect', 'prepare'].includes(call.action)))
})

test('ordinary stop is shown on connect and clears only after local confirmation without preparing', async () => {
  const f = await fixture({ stage: 3 })
  f.nodes.get('stationary').checked = true
  f.state.control = { state: 'safe_stop', software_stop_latched: true, lease_active: false }
  await f.submit()
  assert.equal(f.nodes.get('resetPanel').hidden, false)
  assert.equal(f.nodes.get('prepare').disabled, true)
  assert.equal(f.calls.some(call => call.action === 'reset-stop'), false)
  await f.reset()
  assert.equal(f.calls.some(call => call.action === 'reset-stop'), false)
  f.nodes.get('resetStationary').checked = true
  await f.reset()
  assert.equal(f.calls.filter(call => call.action === 'reset-stop').length, 1)
  assert.equal(f.calls.some(call => call.action === 'prepare'), false)
  assert.equal(f.nodes.get('resetPanel').hidden, true)
  assert.equal(f.nodes.get('prepare').disabled, false)
  assert.equal(f.state.elapsed_seconds, 0)
})

test('fault cannot be reset through the page even with a checked confirmation', async () => {
  const f = await fixture({ stage: 3 })
  f.nodes.get('stationary').checked = true
  f.state.control = { state: 'fault', software_stop_latched: true, lease_active: false }
  await f.submit()
  assert.equal(f.nodes.get('resetStop').disabled, true)
  assert.equal(f.nodes.get('prepare').disabled, true)
  f.nodes.get('resetStationary').checked = true
  await f.reset()
  assert.equal(f.calls.some(call => call.action === 'reset-stop'), false)
  assert.match(f.nodes.get('resetNotice').textContent, /故障鎖定/)
})

test('even with stationary confirmation no connection occurs until a SN is explicitly selected', async () => {
  const f = await fixture({ stage: 3 })
  f.nodes.get('stationary').checked = true
  await f.submitWithoutChoice()
  await f.poll()
  assert.equal(f.nodes.get('device').value, '')
  assert.equal(f.calls.some(call => call.action === 'connect'), false)
  f.nodes.get('device').value = 'ep-2'
  await f.nodes.get('device').listeners.change()
  await flush()
  assert.equal(f.nodes.get('connect').disabled, false)
  await f.submitWithoutChoice()
  assert.equal(f.calls.find(call => call.action === 'connect').body.device_id, 'ep-2')
})

test('active pairing has its own visible end button and does not offer an unusable connection', async () => {
  const f = await fixture({ stage: 3, pairingActive: true })
  f.nodes.get('device').value = 'ep-2'
  f.nodes.get('stationary').checked = true
  await f.poll()
  assert.equal(f.nodes.get('pairingGate').hidden, false)
  assert.equal(f.nodes.get('endPairing').disabled, false)
  assert.equal(f.nodes.get('connect').disabled, true)
  assert.equal(f.nodes.get('disconnect').disabled, true)
  await f.submitWithoutChoice()
  assert.equal(f.calls.some(call => call.options.method === 'POST'), false)
  await f.endPairing()
  assert.equal(f.nodes.get('pairingGate').hidden, true)
  assert.equal(f.nodes.get('connect').disabled, false)
  const posts = f.calls.filter(call => call.options.method === 'POST')
  assert.equal(posts.length, 1)
  assert.equal(posts[0].scope, 'manual-pairing')
  assert.equal(posts[0].action, 'end')
  assert.equal(f.calls.some(call => call.action === 'connect'), false)
})

async function shortFixture(options = {}) {
  const f = await fixture({ stage: 4, ...options })
  f.nodes.get('stationary').checked = true
  await f.submit()
  f.nodes.get('prepareConfirm').checked = true
  await f.prepare()
  return f
}

test('stage four load/connect/prepare never moves; explicit clear-path hold and release are one-shot', async () => {
  const f = await shortFixture()
  assert.equal(f.calls.some(call => call.action.startsWith('short-press')), false)
  assert.equal(f.nodes.get('shortPress').disabled, true)
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.press()
  await f.release()
  await f.poll()
  await f.press()
  assert.equal(f.calls.filter(call => call.action === 'short-press-start').length, 1)
  assert.equal(f.calls.filter(call => call.action === 'short-press-release').length, 1)
  assert.equal(f.nodes.get('shortPress').disabled, true)
  assert.match(f.nodes.get('shortResult').textContent, /現場確認/)
  assert.equal(f.calls.some(call => ['lease', 'command', 'speed'].includes(call.action)), false)
})

test('holding stage four beyond 200ms sends one stop without a renewal loop', async () => {
  const f = await shortFixture()
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.runTimers()
  await f.release()
  assert.equal(f.calls.filter(call => call.action === 'short-press-start').length, 1)
  assert.equal(f.calls.filter(call => call.action === 'short-press-release').length, 1)
})

test('release while start response is pending sends stop and cannot resume when response arrives', async () => {
  const f = await shortFixture({ pendingStart: true })
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.release()
  f.finishStart()
  await flush()
  await f.press()
  assert.equal(f.calls.filter(call => call.action === 'short-press-start').length, 1)
  assert.equal(f.calls.filter(call => call.action === 'short-press-release').length, 1)
})

test('blur during stage four cancels the short press and does not request movement again', async () => {
  const f = await shortFixture()
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  f.events.blur()
  await flush()
  assert.equal(f.calls.filter(call => call.action === 'short-press-release').length, 1)
  assert.equal(f.calls.filter(call => call.action === 'short-press-start').length, 1)
})

test('an old trusted press queued by a busy browser is rejected instead of moving later', async () => {
  const f = await shortFixture()
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press({ timeStamp: 500 })
  assert.equal(f.calls.some(call => call.action.startsWith('short-press')), false)
  assert.match(f.nodes.get('shortResult').textContent, /過期/)
})

test('stage five records an early human release separately and never sends a second pulse', async () => {
  const f = await shortFixture({ stage: 5 })
  assert.equal(f.calls.some(call => call.action.startsWith('short-press')), false)
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.release()
  await f.runTimers()
  assert.equal(f.calls.filter(call => call.action === 'short-press-start').length, 1)
  const release = f.calls.filter(call => call.action === 'short-press-release')
  assert.equal(release.length, 1)
  assert.equal(release[0].body.source, 'release')
  assert.match(f.nodes.get('shortResult').textContent, /由按鍵放開/)
})

test('stage five 500ms protection is labelled limit rather than a successful human release', async () => {
  const f = await shortFixture({ stage: 5 })
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.runTimers()
  await f.release()
  assert.equal(f.calls.find(call => call.action === 'short-press-release').body.source, 'limit')
  assert.match(f.nodes.get('shortResult').textContent, /上限停止/)
  assert.doesNotMatch(f.nodes.get('shortResult').textContent, /由按鍵放開/)
  assert.equal(f.calls.filter(call => call.action === 'short-press-start').length, 1)
})

async function motorFixture(options = {}) {
  const f = await fixture({ ...options, stage: 6 })
  assert.ok(f.calls.every(call => call.options.method === 'GET'))
  f.nodes.get('stationary').checked = true
  await f.submit()
  f.nodes.get('prepareConfirm').checked = true
  await f.prepare()
  return f
}

test('stage six release requires a new local rest confirmation and does not enable or move', async () => {
  const f = await motorFixture()
  assert.equal(f.nodes.get('shortPress').disabled, true)
  await f.motorRelease()
  assert.equal(f.calls.some(call => call.action === 'motor-release'), false)
  f.nodes.get('motorStationary').checked = true
  await f.motorRelease()
  assert.equal(f.nodes.get('motorStationary').checked, false)
  assert.equal(f.calls.filter(call => call.action === 'motor-release').length, 1)
  assert.equal(f.calls.some(call => ['motor-activate', 'short-press-start'].includes(call.action)), false)
})

test('stage six distinguishes holding from actual release receipt and never starts a timer on prepare', async () => {
  const f = await motorFixture()
  assert.match(f.nodes.get('motorStatus').textContent, /零速保持，尚未釋放/)
  assert.match(f.nodes.get('releaseObservation').textContent, /尚未收到本輪釋放成功回覆/)
  f.state.motor_state = 'released_reply'
  f.state.motor_release_receipt = { acknowledged_at_ms: 1000000, physical_effect_verified: false }
  f.state.released_observation_seconds = 123
  await f.poll()
  assert.match(f.nodes.get('releaseObservation').textContent, /123 \/ 120 秒/)
  assert.match(f.nodes.get('releaseObservation').textContent, /不代表實體驗收通過/)
  assert.equal(f.calls.some(call => ['motor-release', 'motor-activate', 'short-press-start'].includes(call.action)), false)
})

test('stage six v5 body diagnostics explain the real gate without treating old encoder comparator as a fault', async () => {
  const f = await motorFixture()
  f.state.rest_evidence_version = 'body-window-v5'
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics = { reason: 'waiting_body_telemetry',
    encoder_comparator: { reason: 'encoder_drift_since_rest' } }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /底盤位置、姿態、速度/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  f.state.wheel_rest_confirmed = true
  await f.poll()
  assert.equal(f.nodes.get('releaseMotor').disabled, false)
  assert.equal(f.calls.some(call => ['motor-release', 'motor-activate', 'short-press-start'].includes(call.action)), false)
})

test('stage six distinguishes a pending newest spike from a permanent stop fault', async () => {
  const f = await motorFixture()
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics = { reason: 'wheel_spike_unresolved', rpm_blocker: { at_latest_sample: true } }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /等下一筆輪速資料/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  f.state.wheel_rest_confirmed = true
  f.state.esc_diagnostics = { reason: 'body_and_wheels_stationary' }
  await f.poll()
  assert.equal(f.nodes.get('releaseMotor').disabled, false)
  assert.equal(f.calls.some(call => call.action === 'motor-release'), false)
})

test('stage six never labels unknown motor mode as zero holding', async () => {
  const f = await motorFixture()
  f.state.motor_state = 'unknown'
  f.state.control.state = 'fault'
  f.state.control.software_stop_latched = true
  f.state.movement_enabled = false
  await f.poll()
  assert.match(f.nodes.get('motorStatus').textContent, /電機模式未確認/)
  assert.doesNotMatch(f.nodes.get('motorStatus').textContent, /零速保持/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  assert.equal(f.nodes.get('shortPress').disabled, true)
})

test('stage six lost status clears stale readiness and checkbox changes cannot re-enable motion', async () => {
  const f = await motorFixture()
  f.nodes.get('motorStationary').checked = true
  await f.motorRelease()
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  assert.equal(f.nodes.get('shortPress').disabled, false)
  f.state.statusRequestFails = true
  await f.poll()
  f.nodes.get('clearPath').listeners.change()
  assert.equal(f.nodes.get('shortPress').disabled, true)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  assert.equal(f.nodes.get('prepare').disabled, true)
  assert.match(f.nodes.get('motorStatus').textContent, /電機狀態未確認/)
  assert.equal(f.calls.some(call => ['motor-activate', 'short-press-start'].includes(call.action)), false)
})

test('stage six old worker cannot release or move through the new page even if its own gate passes', async () => {
  const f = await motorFixture()
  f.state.rest_evidence_version = 'snapshot-window-v3'
  f.state.wheel_rest_confirmed = true
  f.state.movement_enabled = true
  f.nodes.get('clearPath').checked = true
  await f.poll()
  assert.match(f.nodes.get('motorStatus').textContent, /仍用舊判定/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  assert.equal(f.nodes.get('shortPress').disabled, true)
  f.nodes.get('clearPath').listeners.change()
  assert.equal(f.nodes.get('shortPress').disabled, true)
  assert.equal(f.calls.some(call => ['motor-release', 'motor-activate', 'short-press-start'].includes(call.action)), false)
})

test('stage six re-enables only on explicit hold, then sends start once and clears rest confirmation', async () => {
  const f = await motorFixture()
  f.nodes.get('motorStationary').checked = true
  await f.motorRelease()
  f.nodes.get('motorStationary').checked = true
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.release()
  const actions = f.calls.filter(call => call.options.method === 'POST').map(call => call.action)
  assert.deepEqual(actions, ['connect', 'prepare', 'motor-release', 'motor-activate', 'short-press-start', 'short-press-release'])
  assert.equal(f.nodes.get('motorStationary').checked, false)
  assert.equal(f.calls.find(call => call.action === 'motor-activate').body.issued_at_ms,
    f.calls.find(call => call.action === 'short-press-start').body.issued_at_ms)
})

test('stage six release during enable waits fences start, even after enable completes', async () => {
  const f = await motorFixture({ pendingActivate: true })
  f.nodes.get('motorStationary').checked = true
  await f.motorRelease()
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.release()
  f.finishActivate()
  await flush()
  assert.equal(f.calls.filter(call => call.action === 'motor-activate').length, 1)
  assert.equal(f.calls.some(call => call.action === 'short-press-start'), false)
  assert.equal(f.calls.filter(call => call.action === 'short-press-release').length, 1)
})

test('stage six enable failure never sends movement or retries', async () => {
  const f = await motorFixture({ failActivate: true })
  f.nodes.get('motorStationary').checked = true
  await f.motorRelease()
  f.nodes.get('clearPath').checked = true
  f.nodes.get('clearPath').listeners.change()
  await f.press()
  await f.press()
  assert.equal(f.calls.filter(call => call.action === 'motor-activate').length, 1)
  assert.equal(f.calls.some(call => call.action === 'short-press-start'), false)
})

test('stage six a new stop invalidates any checkbox checked before it', async () => {
  const f = await motorFixture()
  f.nodes.get('motorStationary').checked = true
  f.state.motor_stop_id = 'f'.repeat(32)
  await f.poll()
  assert.equal(f.nodes.get('motorStationary').checked, false)
  await f.motorRelease()
  assert.equal(f.calls.some(call => call.action === 'motor-release'), false)
})

test('stage six explains the blocked wheel gate without issuing release or movement', async () => {
  const f = await motorFixture()
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics = { reason: 'sequence_not_advancing', speeds_rpm: [0, 0, 0, 0] }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /序號未持續更新/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  assert.equal(f.calls.some(call => ['motor-release', 'motor-activate', 'short-press-start'].includes(call.action)), false)
})

test('stage six shows the encoder rest requirement and still requires local confirmation', async () => {
  const f = await motorFixture()
  f.state.wheel_rest_confirmed = true
  f.state.esc_diagnostics = { reason: 'collecting_rest_samples', speeds_rpm: [4, -4, -3, 1] }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /至少 2 秒的停穩回報證據/)
  await f.motorRelease()
  assert.equal(f.calls.some(call => call.action === 'motor-release'), false)
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics.reason = 'encoder_changed'
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /編碼器角度仍有變化/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
})

test('auto connect needs explicit opt-in and stationary choice, then stops at connection without preparing', async () => {
  const f = await fixture({ stage: 6 })
  assert.ok(f.calls.every(call => call.options.method === 'GET'))
  f.nodes.get('device').value = 'ep-2'
  f.nodes.get('autoConnect').checked = true
  await f.autoChange()
  assert.equal(f.calls.some(call => call.action === 'connect-auto'), false)
  f.nodes.get('stationary').checked = true
  f.nodes.get('stationary').listeners.change()
  await flush()
  await flush()
  assert.equal(f.calls.filter(call => call.action === 'connect-auto').length, 1)
  assert.equal(f.calls.find(call => call.action === 'connect-auto').body.device_id, 'ep-2')
  assert.equal(f.nodes.get('autoConnect').checked, false)
  assert.equal(f.calls.some(call => ['prepare', 'reset-stop', 'motor-release', 'motor-activate', 'short-press-start'].includes(call.action)), false)
  f.state.connection = 'not_connected'
  await f.advanceAuto()
  assert.equal(f.calls.filter(call => call.action === 'connect-auto').length, 1)
})

test('auto handshake retries are spaced and stop after three attempts', async () => {
  const f = await fixture({ stage: 6, failConnect: true })
  f.nodes.get('device').value = 'ep-2'
  f.nodes.get('stationary').checked = true
  f.nodes.get('autoConnect').checked = true
  await f.autoChange()
  await f.poll()
  assert.equal(f.calls.filter(call => call.action === 'connect-auto').length, 1)
  await f.advanceAuto()
  await f.advanceAuto()
  await f.advanceAuto()
  assert.equal(f.calls.filter(call => call.action === 'connect-auto').length, 3)
  assert.equal(f.nodes.get('autoConnect').checked, false)
  assert.equal(f.calls.some(call => call.action === 'disconnect' || call.action === 'prepare'), false)
})

test('turning auto off while connection is pending cannot schedule another attempt', async () => {
  const f = await fixture({ stage: 6, failConnect: true, pendingConnect: true })
  f.nodes.get('device').value = 'ep-2'
  f.nodes.get('stationary').checked = true
  f.nodes.get('autoConnect').checked = true
  await f.autoChange()
  f.nodes.get('autoConnect').checked = false
  await f.autoChange()
  f.finish()
  await flush()
  await f.advanceAuto()
  assert.equal(f.calls.filter(call => call.action === 'connect-auto').length, 1)
})

test('auto never retries a failed identity or an already prepared session', async () => {
  const f = await fixture({ stage: 6, failConnect: true })
  f.nodes.get('device').value = 'ep-2'
  f.nodes.get('stationary').checked = true
  f.nodes.get('autoConnect').checked = true
  await f.autoChange()
  f.state.last_connection_error = { code: 'identity_mismatch' }
  await f.advanceAuto()
  assert.equal(f.calls.filter(call => call.action === 'connect-auto').length, 1)
  assert.equal(f.nodes.get('autoConnect').checked, false)
})

test('unresolved RPM spike remains blocked and raw RPM is not relabelled as zero', async () => {
  const f = await motorFixture()
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics = { reason: 'rpm_unresolved_spike', speeds_rpm: [0, -6, -15, 0] }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /尖峰尚未/)
  assert.match(f.nodes.get('wheelStatus').textContent, /-15/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  assert.equal(f.calls.some(call => call.action === 'motor-release'), false)
})

test('v2 separates a historical confirmed excursion from a normal current center without unlocking', async () => {
  const f = await motorFixture()
  f.state.rest_evidence_version = 'snapshot-window-v2'
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics = {
    reason: 'encoder_drift_since_rest', encoder_center_within_reference: true,
    first_block_evidence: { kind: 'sustained_reference_excursion', offset_counts: 5 },
  }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /先前曾確認持續偏離/)
  assert.match(f.nodes.get('wheelStatus').textContent, /目前中心已回到附近/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  assert.equal(f.calls.some(call => call.action === 'motor-release'), false)
})

test('v3 unknown RPM history does not enable release until a complete new window passes', async () => {
  const f = await motorFixture()
  f.state.rest_evidence_version = 'snapshot-window-v3'
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics = {
    reason: 'rebuilding_after_signal_anomaly', signal_recovery_pending: true,
    first_signal_anomaly: { kind: 'rpm_quality', max_abs_rpm: 19 }, signal_recoveries: 0,
  }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /重建完整/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
  f.state.wheel_rest_confirmed = true
  f.state.esc_diagnostics.signal_recovery_pending = false
  f.state.esc_diagnostics.signal_recoveries = 1
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /先前訊號異常已保留/)
  assert.match(f.nodes.get('wheelStatus').textContent, /目前完整新窗口合格/)
  await f.motorRelease()
  assert.equal(f.calls.some(call => call.action === 'motor-release'), false)
})

test('v3 hard encoder block is retained even if signal quality has recovered', async () => {
  const f = await motorFixture()
  f.state.rest_evidence_version = 'snapshot-window-v3'
  f.state.wheel_rest_confirmed = false
  f.state.esc_diagnostics = {
    first_signal_anomaly: { kind: 'rpm_quality', max_abs_rpm: 19 }, signal_recoveries: 1,
    first_block_evidence: { kind: 'sustained_reference_excursion', offset_counts: 5 },
    encoder_center_within_reference: true,
  }
  await f.poll()
  assert.match(f.nodes.get('wheelStatus').textContent, /阻擋保留/)
  assert.equal(f.nodes.get('releaseMotor').disabled, true)
})
