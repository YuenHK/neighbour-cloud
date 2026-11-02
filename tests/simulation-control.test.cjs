const assert = require('node:assert/strict')
const test = require('node:test')
const { SimulationControl } = require('../edge_hub/static/simulation-control.js')

const status = { mode: 'simulation', connected: false, hardware_acceptance: false,
  direction: 'stop', software_stop_latched: false, lease_active: false, state: 'safe_stop' }
const token = 'simulation-test-token-not-production'

function pageRig(response) {
  const nodes = new Map()
  const calls = []
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { value: 'test-key', checked: true, textContent: '', listeners: {},
      addEventListener(name, callback) { this.listeners[name] = callback } })
    return nodes.get(id)
  }
  const document = { querySelector: node, querySelectorAll: () => [], addEventListener() {} }
  const source = require('node:fs').readFileSync(require.resolve('../edge_hub/static/simulation-control.js'), 'utf8')
  require('node:vm').runInNewContext(source, {
    document, window: { addEventListener() {} }, AbortController, setTimeout, clearTimeout,
    fetch: async (path, options) => { calls.push({ path, options }); return { ok: true, json: async () => response } },
  })
  return { node, calls }
}

test('stop and reset buttons reject partial or contradictory success snapshots', async () => {
  for (const reset of [false, true]) {
    const valid = { ...status, software_stop_latched: !reset, state: reset ? 'idle' : 'safe_stop' }
    for (const response of [null, {}, { ...valid, mode: 'dji-ep-sdk-unverified' },
      { ...valid, connected: true }, { ...valid, hardware_acceptance: true },
      { ...valid, software_stop_latched: reset }, { ...valid, software_stop_latched: 1 },
      { ...valid, state: 'fault' }, { ...valid, direction: 'forward' },
      { ...valid, lease_active: true }, { ...valid, lease_active: 0 },
      { ...valid, shutdown_requested: true, control_lifecycle_scope: lifecycleScope },
      { ...valid, shutdown_requested: false }]) {
      const { node, calls } = pageRig(response)
      await node(reset ? '#resetSimulationStop' : '#softwareStop').listeners.click()
      assert.match(node('#controlStatus').textContent, reset ? /未能重設/ : /停止鎖定未確認/)
      assert.equal(node('#confirmStationary').checked, true)
      assert.equal(calls.length, 1) // No retry, lease or movement after a bad acknowledgement.
      assert.match(calls[0].path, reset ? /reset-software-stop$/ : /\/software-stop$/)
    }
  }
})

test('validated stop and reset buttons keep simulation-only notices without automatic movement', async () => {
  for (const reset of [false, true]) {
    for (const lifecycle of [{}, { shutdown_requested: false, control_lifecycle_scope: lifecycleScope }]) {
      const state = { ...status, ...lifecycle, software_stop_latched: !reset, state: reset ? 'idle' : 'safe_stop' }
      const { node, calls } = pageRig(state)
      await node(reset ? '#resetSimulationStop' : '#softwareStop').listeners.click()
      assert.match(node('#controlStatus').textContent, reset ? /僅模擬停止鎖定已重設/ : /模擬軟件停止已鎖定/)
      assert.equal(node('#confirmStationary').checked, !reset)
      assert.equal(calls.length, 1)
      assert.equal(calls[0].options.keepalive, !reset)
    }
  }
})

test('reset button still requires explicit stationary confirmation', async () => {
  const { node, calls } = pageRig({ ...status, state: 'idle' })
  node('#confirmStationary').checked = false
  await node('#resetSimulationStop').listeners.click()
  assert.equal(calls.length, 0)
})

function rig(custom) {
  const calls = []
  const timers = new Map()
  let next = 0
  const control = new SimulationControl({
    key: () => 'test-key', now: () => 1000,
    later: callback => { timers.set(++next, callback); return next },
    cancel: id => timers.delete(id),
    request: async (path, body, key, keepalive) => {
      calls.push({ path, body, key, keepalive })
      if (custom) return custom(path, body)
      if (path === 'lease') return { mode: 'simulation', lease_token: token, server_time_ms: 1000 }
      return body?.direction ? { ...status, direction: body.direction } : status
    },
  })
  return { control, calls, timers }
}

test('never acquires or moves without an explicit arm and press', async () => {
  const { control, calls } = rig()
  assert.equal(await control.press('forward'), false)
  assert.equal(calls.length, 0)
  await control.arm()
  assert.deepEqual(calls.map(c => c.path), ['status'])
})

test('arming rejects missing, active or contradictory stopped-state metadata', async () => {
  for (const fields of [{ state: undefined }, { state: null }, { state: 'fault' }, { state: 'manual' },
    { state: 'unknown' }, { direction: undefined }, { direction: 'forward' }, { direction: null },
    { lease_active: undefined }, { lease_active: true }, { lease_active: 0 }, { lease_active: 'false' }]) {
    const { control, calls, timers } = rig(() => ({ ...status, ...fields }))
    const notices = []
    control.notify = text => notices.push(text)
    await assert.rejects(control.arm(), /simulation_not_ready/)
    assert.equal(control.armed, false)
    assert.equal(control.holding, false)
    assert.equal(control.lease, null)
    assert.equal(timers.size, 0)
    assert.deepEqual(calls.map(call => call.path), ['status'])
    assert.deepEqual(notices, [])
    assert.equal(await control.press('forward'), false)
    assert.equal(calls.length, 1)
  }
})

test('arming a stopped idle or safe-stop snapshot never itself acquires a lease', async () => {
  for (const state of ['idle', 'safe_stop']) {
    const { control, calls, timers } = rig(() => ({ ...status, state }))
    assert.equal(await control.arm(), true)
    assert.equal(control.armed, true)
    assert.equal(control.holding, false)
    assert.equal(control.lease, null)
    assert.equal(timers.size, 0)
    assert.deepEqual(calls.map(call => call.path), ['status'])
  }
})

test('press uses bounded TTL and sequence; release cancels renewal and sends stop', async () => {
  const { control, calls, timers } = rig()
  await control.arm()
  await control.press('forward')
  assert.equal(calls[2].body.ttl_ms, 300)
  assert.equal(calls[2].body.seq, 0)
  assert.equal(timers.size, 1)
  await control.stop()
  assert.equal(timers.size, 0)
  assert.equal(calls.at(-1).body.direction, 'stop')
  assert.equal(calls.at(-1).body.seq, 1)
  assert.equal(control.holding, false)
})

test('invalid lease response is never stored or echoed in a command or retry', async () => {
  for (const fields of [{ lease_token: 'x'.repeat(129) }, { lease_token: 'x'.repeat(19) },
    { lease_token: '私'.repeat(20) }, { lease_token: 'x'.repeat(20) + '\n' },
    { lease_token: 'x'.repeat(20) + '\u0000' }, { lease_token: 'x'.repeat(20) + '=' },
    { lease_token: 'x'.repeat(20) + ' ' }, { lease_token: 123 },
    { server_time_ms: -1 }, { server_time_ms: NaN }, { server_time_ms: Infinity },
    { server_time_ms: 1.5 }, { server_time_ms: '1000' },
    { server_time_ms: Number.MAX_SAFE_INTEGER + 1 }, { mode: 'dji-ep-sdk-unverified' }]) {
    const { control, calls, timers } = rig(path => path === 'lease'
      ? { mode: 'simulation', lease_token: token, server_time_ms: 1000, ...fields } : status)
    await control.arm()
    assert.equal(await control.press('forward'), false)
    assert.equal(control.armed, false)
    assert.equal(control.holding, false)
    assert.equal(control.acquiring, false)
    assert.equal(control.lease, null)
    assert.equal(control.credential, null)
    assert.equal(timers.size, 0)
    assert.deepEqual(calls.map(call => call.path), ['status', 'lease'])
  }
})

test('cancelled pending invalid lease cannot echo a token in a release command', async () => {
  let resolveLease
  const { control, calls, timers } = rig(path => path === 'lease'
    ? new Promise(resolve => { resolveLease = resolve }) : status)
  await control.arm()
  const pending = control.press('left')
  await control.stop({ disarm: true })
  resolveLease({ mode: 'simulation', lease_token: 'x'.repeat(20) + '\n', server_time_ms: 1000 })
  assert.equal(await pending, false)
  assert.equal(control.armed, false)
  assert.equal(control.lease, null)
  assert.equal(timers.size, 0)
  assert.deepEqual(calls.map(call => call.path), ['status', 'lease'])
})

test('URL-safe token length boundaries permit explicit simulation press and stop', async () => {
  for (const leaseToken of ['x'.repeat(20), 'x'.repeat(128), 'aB_0-9'.repeat(5)]) {
    const { control, calls, timers } = rig((path, body) => path === 'lease'
      ? { mode: 'simulation', lease_token: leaseToken, server_time_ms: 1000 }
      : body?.direction ? { ...status, direction: body.direction } : status)
    await control.arm()
    assert.equal(await control.press('right'), true)
    assert.equal(calls[2].body.lease_token, leaseToken)
    await control.stop()
    assert.equal(calls.at(-1).body.direction, 'stop')
    assert.equal(control.lease, null)
    assert.equal(timers.size, 0)
  }
})

test('release while lease is pending cannot produce a late movement', async () => {
  let resolveLease
  const { control, calls } = rig(path => path === 'lease'
    ? new Promise(resolve => { resolveLease = resolve }) : status)
  await control.arm()
  const pending = control.press('forward')
  await control.stop({ disarm: true })
  resolveLease({ mode: 'simulation', lease_token: token, server_time_ms: 1000 })
  await pending
  assert.ok(calls.filter(c => c.path === 'command').every(c => c.body.direction === 'stop'))
  assert.equal(control.armed, false)
})

test('real transport or a latched stop cannot arm', async () => {
  for (const bad of [{ ...status, mode: 'dji-ep-sdk-unverified' },
    { ...status, connected: true }, { ...status, software_stop_latched: true }]) {
    const { control, calls } = rig(() => bad)
    await assert.rejects(control.arm())
    assert.equal(control.armed, false)
    assert.equal(calls.length, 1)
  }
})

const lifecycleScope = 'host shutdown intent only; not worker exit or hardware stop proof'

test('explicit open lifecycle metadata preserves bounded simulation controls', async () => {
  const { control, calls, timers } = rig((path, body) => {
    if (path === 'lease') return { mode: 'simulation', lease_token: token, server_time_ms: 1000 }
    return { ...status, direction: body?.direction || 'stop',
      shutdown_requested: false, control_lifecycle_scope: lifecycleScope }
  })
  await control.arm()
  await control.press('forward')
  assert.equal(timers.size, 1)
  assert.equal(calls.at(-1).body.ttl_ms, 300)
  await control.stop({ disarm: true })
  assert.equal(timers.size, 0)
})

test('shutdown and partial or invalid lifecycle status cannot arm or request leases', async () => {
  for (const fields of [{ shutdown_requested: true, control_lifecycle_scope: lifecycleScope },
    { shutdown_requested: false }, { control_lifecycle_scope: lifecycleScope },
    ...[0, 1, null, undefined, 'false'].map(value => ({ shutdown_requested: value, control_lifecycle_scope: lifecycleScope })),
    { shutdown_requested: false, control_lifecycle_scope: 'private scope' }]) {
    const { control, calls } = rig(() => ({ ...status, ...fields }))
    await assert.rejects(control.arm(), /^Error: simulation_not_ready$/)
    assert.equal(control.armed, false)
    assert.equal(await control.press('forward'), false)
    assert.deepEqual(calls.map(call => call.path), ['status'])
  }
})

test('shutdown observed during renewal disarms, cancels timer and never auto-resumes', async () => {
  for (const fields of [{ shutdown_requested: true, control_lifecycle_scope: lifecycleScope },
    { shutdown_requested: false }, { shutdown_requested: false, control_lifecycle_scope: 'bad scope' }]) {
    let closing = false
    const { control, calls, timers } = rig((path, body) => {
      if (path === 'lease') return { mode: 'simulation', lease_token: token, server_time_ms: 1000 }
      return { ...status, direction: body?.direction || 'stop',
        ...(closing && body?.direction !== 'stop' ? fields : {}) }
    })
    await control.arm()
    await control.press('forward')
    assert.equal(timers.size, 1)
    closing = true
    await control.cycle(control.epoch, 'forward')
    assert.equal(control.armed, false)
    assert.equal(control.holding, false)
    assert.equal(control.lease, null)
    assert.equal(control.credential, null)
    assert.equal(timers.size, 0)
    assert.equal(calls.at(-1).body.direction, 'stop')
    const count = calls.length
    await control.press('forward')
    assert.equal(calls.length, count)
  }
})

test('command failure disarms, requests stop and never schedules retry', async () => {
  const { control, calls, timers } = rig((path, body) => {
    if (path === 'lease') return { mode: 'simulation', lease_token: token, server_time_ms: 1000 }
    if (body?.direction === 'forward') throw new Error('network failure')
    return status
  })
  await control.arm()
  await control.press('forward')
  assert.equal(control.armed, false)
  assert.equal(timers.size, 0)
  assert.equal(calls.at(-1).body.direction, 'stop')
})

async function stopResponseRig(response) {
  const result = rig((path, body) => {
    if (path === 'lease') return { mode: 'simulation', lease_token: token, server_time_ms: 1000 }
    if (body?.direction === 'stop') return response
    return { ...status, direction: body?.direction || 'stop' }
  })
  await result.control.arm()
  await result.control.press('forward')
  result.messages = []
  result.control.notify = message => result.messages.push(message)
  return result
}

test('HTTP success with inconsistent stop state is never a stop acknowledgement', async () => {
  for (const response of [null, {}, { ...status, direction: 'forward' },
    { ...status, mode: 'dji-ep-sdk-unverified' }, { ...status, connected: true },
    { ...status, hardware_acceptance: true }, { ...status, software_stop_latched: true },
    { ...status, state: 'fault' }, { ...status, state: 'idle' },
    { ...status, shutdown_requested: true, control_lifecycle_scope: lifecycleScope }]) {
    const { control, timers, messages } = await stopResponseRig(response)
    await control.stop()
    assert.equal(control.armed, false)
    assert.equal(control.holding, false)
    assert.equal(control.stopping, false)
    assert.equal(control.lease, null)
    assert.equal(control.credential, null)
    assert.equal(timers.size, 0)
    assert.match(messages.join(''), /未收到停止確認/)
    assert.doesNotMatch(messages.join(''), /已確認模擬停止/)
  }
})

test('stop acknowledgement requires explicit revoked lease and safe-stop state', async () => {
  for (const fields of [{ lease_active: true }, { lease_active: 0 }, { lease_active: 'false' },
    { lease_active: undefined }, { lease_active: null }, { state: undefined }, { state: 'stop' }]) {
    const { control, messages } = await stopResponseRig({ ...status, ...fields })
    await control.stop()
    assert.equal(control.armed, false)
    assert.match(messages.join(''), /未收到停止確認/)
    assert.doesNotMatch(messages.join(''), /已確認模擬停止/)
  }
})

test('validated simulated stop is acknowledged without claiming physical safety', async () => {
  for (const response of [status, { ...status, shutdown_requested: false, control_lifecycle_scope: lifecycleScope }]) {
    const { control, timers, messages } = await stopResponseRig(response)
    await control.stop()
    assert.equal(control.armed, true) // Normal pointer release still permits a new explicit press.
    assert.equal(control.lease, null)
    assert.equal(timers.size, 0)
    assert.deepEqual(messages, ['已確認模擬停止；不是實體急停驗收。'])
  }
})

test('lifecycle stop uses captured credential and keepalive, with no persistence', async () => {
  const { control, calls } = rig()
  await control.arm()
  await control.press('left')
  control.key = () => 'changed-key'
  await control.stop({ disarm: true, keepalive: true })
  assert.equal(calls.at(-1).key, 'test-key')
  assert.equal(calls.at(-1).keepalive, true)
  assert.equal(control.credential, null)
})

test('pending command cannot renew after release or a second pointer', async () => {
  let resolveCommand
  const { control, calls, timers } = rig((path, body) => {
    if (path === 'lease') return { mode: 'simulation', lease_token: token, server_time_ms: 1000 }
    if (body?.direction === 'forward') return new Promise(resolve => { resolveCommand = resolve })
    return status
  })
  await control.arm()
  const pending = control.press('forward')
  await Promise.resolve()
  assert.equal(await control.press('right'), false)
  await control.stop({ disarm: true })
  resolveCommand({ ...status, direction: 'forward' })
  await pending
  assert.equal(timers.size, 0)
  assert.equal(calls.filter(c => c.body?.direction === 'forward').length, 1)
})

test('window abandon cancels a pending arm response', async () => {
  let resolveStatus
  const { control } = rig(() => new Promise(resolve => { resolveStatus = resolve }))
  const pending = control.arm()
  await control.stop({ disarm: true })
  resolveStatus(status)
  assert.equal(await pending, false)
  assert.equal(control.armed, false)
})

test('page lifecycle wiring uses simulation endpoints without credential persistence', () => {
  const fs = require('node:fs')
  const source = fs.readFileSync(require.resolve('../edge_hub/static/simulation-control.js'), 'utf8')
  for (const name of ['pointerup', 'pointercancel', 'pointerleave', 'lostpointercapture',
    'blur', 'pagehide', 'beforeunload', 'offline', 'visibilitychange']) assert.ok(source.includes(name))
  assert.ok(source.includes('/api/v1/robot/simulation/'))
  assert.doesNotMatch(source, /localStorage|sessionStorage|sendBeacon|keydown/)
})
