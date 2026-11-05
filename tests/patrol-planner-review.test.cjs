const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

const SOURCE = fs.readFileSync('deploy/cloud/web/patrol-planner.js', 'utf8')
  .replace(/^import \{ cloudFetch \} from '[^']+'\s*\n/, '')
const floor = name => ({ name, width: 4, height: 4, cell_cm: 50, clearance_cm: 35,
  floor: [], blocked: [] })
const reply = value => ({ ok: true, json: async () => value })
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)) }

function ui(fetch) {
  const elements = new Map()
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', textContent: '', open: false, width: 640, height: 512, listeners: new Map(),
      addEventListener(event, handler) { this.listeners.set(event, handler) },
      getContext() { return { clearRect() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {} } },
    })
    return elements.get(id)
  }
  get('patrolMapName').value = 'old draft'
  get('patrolCellSize').value = '50'
  get('patrolProfile').value = 'simulation'
  const context = { document: { getElementById: get }, cloudFetch: fetch, AbortSignal,
    URL, Blob, setTimeout, clearTimeout, confirm: () => true }
  vm.runInNewContext(SOURCE, context, { filename: 'patrol-planner.js' })
  return { get, dispatch(id, event, value = {}) { return get(id).listeners.get(event)(value) } }
}

test('edits during successful PUT stay visibly unsaved rather than falsely saved', async () => {
  let resolveSave, captured
  const app = ui(async (url, options) => {
    if (!options.method) return reply({ revision: 1, map: floor('saved draft') })
    assert.equal(options.method, 'PUT')
    captured = JSON.parse(options.body)
    return new Promise(resolve => { resolveSave = resolve })
  })
  app.get('patrolPlanning').open = true
  app.dispatch('patrolPlanning', 'toggle')
  await flush()
  app.dispatch('patrolMapSave', 'click')
  await flush()
  assert.equal(captured.map.name, 'saved draft')
  app.get('patrolMapName').value = 'newer unsaved draft'
  app.dispatch('patrolMapName', 'input')
  resolveSave(reply({ revision: 2 }))
  await flush()
  assert.equal(app.get('patrolMapName').value, 'newer unsaved draft')
  assert.match(app.get('patrolPlanStatus').textContent, /未儲存|草稿/)
})

test('late file reading cannot overwrite newer staff map edits', async () => {
  let resolveFile
  const app = ui(() => assert.fail('file import must not contact a service'))
  const file = { size: 100, text: () => new Promise(resolve => { resolveFile = resolve }) }
  app.dispatch('patrolMapImport', 'change', { target: { files: [file] } })
  await flush()
  app.get('patrolMapName').value = 'newer staff edit'
  app.dispatch('patrolMapName', 'input')
  resolveFile(JSON.stringify({ format: 'neighbour-survey-map-v1', map: floor('late imported map') }))
  await flush()
  assert.equal(app.get('patrolMapName').value, 'newer staff edit')
  assert.match(app.get('patrolPlanStatus').textContent, /草稿|修改|套用/)
})
