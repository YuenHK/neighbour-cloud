const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const script = fs.readFileSync(path.join(__dirname, '../edge_hub/static/ep-preparation.js'), 'utf8')
const context = vm.createContext({ AbortController, setTimeout, clearTimeout })
vm.runInContext(script, context)
const client = context.ZhiweiEpPreparation
const fixture = () => ({ schema: 'ep-offline-preparation-v1', target_model: 'EP',
  scope: 'offline_preparation_not_hardware_acceptance', connection: 'not_connected',
  motion_enabled: false, video_enabled: false, audio_enabled: false,
  hardware_acceptance: false, autonomous_navigation: false,
  sdk_timeout_scope: 'host_timer_not_hardware_watchdog',
  sdk_report_state: 'blocked_native_wheel_abi' })

test('preparation never claims an EP link, privacy acceptance or ability to drive', () => {
  const text = client.format(fixture())
  assert.match(text, /EP 實機未接通/)
  assert.match(text, /人手控制／聲畫全部停用/)
  assert.match(text, /SDK wheel 與本機 Python 不符/)
})

test('inconsistent true, missing or coerced capability cannot activate UI', () => {
  for (const key of ['motion_enabled', 'video_enabled', 'audio_enabled',
    'hardware_acceptance', 'autonomous_navigation']) {
    for (const value of [true, 0, 'false', undefined, null])
      assert.throws(() => client.format({ ...fixture(), [key]: value }), /inconsistent/)
  }
  assert.throws(() => client.format({ ...fixture(), connection: 'connected' }), /inconsistent/)
})

test('only one fixed read-only local endpoint is contacted with an ephemeral key', async () => {
  const calls = []
  await client.read('test-only', async (url, options) => {
    calls.push({ url, options })
    return { ok: true, json: async () => fixture() }
  })
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v1/robot/ep/preparation')
  assert.equal(calls[0].options.method, 'GET')
  assert.equal(calls[0].options.redirect, 'error')
  assert.equal(calls[0].options.credentials, 'omit')
  assert.equal(calls[0].options.headers['X-Operator-Key'], 'test-only')
})

test('deadline includes a hung body and aborts without retry', async () => {
  let attempts = 0
  let signal
  await assert.rejects(client.read('test-only', async (_url, options) => {
    attempts++
    signal = options.signal
    return { ok: true, json: () => new Promise(() => {}) }
  }, 10), /ep_preparation_timeout/)
  assert.equal(attempts, 1)
  assert.equal(signal.aborted, true)
})

test('missing key and HTTP refusal cannot become a successful snapshot', async () => {
  await assert.rejects(client.read('', () => { throw Error('must not fetch') }), /key_required/)
  await assert.rejects(client.read('test-only', async () => ({ ok: false, status: 403 })), /unavailable/)
})

test('no connect, motion, AV or persistence APIs are present in preparation client', () => {
  assert.doesNotMatch(script, /localStorage|sessionStorage|getUserMedia|WebSocket|\.play\(|method: 'POST'/)
  assert.doesNotMatch(script, /\/command|\/lease|\/connect|\/audio|\/video/)
})

test('adapted import evidence is not original wheel support or hardware acceptance', () => {
  const text = client.format({ ...fixture(), adapted_runtime_report_state: 'reported_offline_pass' })
  assert.match(text, /專案適配版離機匯入／合成解碼報告已核對/)
  assert.match(text, /非原版 wheel，非實機驗收/)
  assert.match(text, /人手控制／聲畫全部停用/)
})
