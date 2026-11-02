const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

test('workspace tabs preserve drafts, support deep links and return to work on unknown hashes', () => {
  const panels = Object.fromEntries(['work', 'knowledge', 'usage', 'avatar'].map(key => [`panel-${key}`, { hidden: false, setAttribute(name,value) { this[name]=value } }]))
  let changed
  const listeners = {}
  const scrolls = []
  const tabs = ['work', 'care', 'reports', 'knowledge', 'usage', 'avatar'].map(key => ({ id: `tab-${key}`, attrs: { href: `#${key}`, 'aria-controls': `panel-${['care', 'reports'].includes(key) ? 'work' : key}` }, listeners: {}, getAttribute(name) { return this.attrs[name] }, setAttribute(name, value) { this.attrs[name] = value }, addEventListener(name, handler) { this.listeners[name] = handler }, focus() { this.focused = true } }))
  const draft = { value: '未儲存的職員備註' }
  const frame = { style: {}, contentWindow: {}, attrs: { 'data-src': 'http://127.0.0.1:4173/ui/estate-settings-entry.html' }, loads: 0, getAttribute(name) { return this.attrs[name] }, setAttribute(name, value) { this.attrs[name] = value; this.loads++ } }
  const location = { hash: '' }
  const document = { querySelectorAll: () => tabs, getElementById: id => id === 'airiSettingsFrame' ? frame : panels[id] || draft }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../edge_hub/static/workspace-navigation.js'), 'utf8'), { document, location, window: { scrollBy: value => scrolls.push(value.top), addEventListener: (name, handler) => { listeners[name] = handler; if (name === 'hashchange') changed = handler } } })
  assert.equal(panels['panel-work'].hidden, false)
  assert.equal(panels['panel-usage'].hidden, true)
  assert.equal(frame.loads, 0)
  location.hash = '#voiceSettingsForm'; changed()
  assert.equal(panels['panel-usage'].hidden, false)
  assert.equal(tabs[4].attrs['aria-selected'], 'true')
  location.hash = '#knowledge'; changed()
  assert.equal(panels['panel-knowledge'].hidden, false)
  assert.equal(draft.value, '未儲存的職員備註')
  tabs[3].listeners.keydown({ key: 'ArrowRight', preventDefault() {} })
  assert.equal(location.hash, '#usage')
  assert.equal(tabs[4].focused, true)
  location.hash = '#quotaHeading'; changed()
  assert.equal(panels['panel-usage'].hidden, false)
  assert.equal(panels['panel-knowledge'].hidden, true)
  assert.equal(tabs[4].attrs['aria-selected'], 'true')
  location.hash = '#care'; changed()
  assert.equal(panels['panel-work'].hidden, false)
  assert.equal(panels['panel-work']['aria-labelledby'], 'tab-care')
  assert.equal(tabs[1].attrs['aria-selected'], 'true')
  location.hash = '#eventsPanel'; changed()
  assert.equal(panels['panel-work'].hidden, false)
  assert.equal(tabs[2].attrs['aria-selected'], 'true')
  location.hash = '#old-unknown'; changed()
  assert.equal(panels['panel-work'].hidden, false)
  location.hash = '#settings'; changed()
  assert.equal(panels['panel-avatar'].hidden, false)
  assert.equal(tabs[5].attrs['aria-selected'], 'true')
  assert.equal(frame.attrs.src, 'http://127.0.0.1:4173/ui/estate-settings-entry.html')
  location.hash = '#work'; changed()
  location.hash = '#avatar'; changed()
  assert.equal(frame.loads, 1)
  for (const event of [
    { origin: 'https://unrelated.example', source: frame.contentWindow, data: { type: 'estate:settings-size', height: 900 } },
    { origin: 'http://127.0.0.1:4173', source: {}, data: { type: 'estate:settings-size', height: 900 } },
    { origin: 'http://127.0.0.1:4173', source: frame.contentWindow, data: { type: 'estate:settings-size', height: '900' } },
    { origin: 'http://127.0.0.1:4173', source: frame.contentWindow, data: { type: 'estate:settings-size', height: 999999 } },
  ]) listeners.message(event)
  assert.equal(frame.style.height, undefined)
  listeners.message({ origin: 'http://127.0.0.1:4173', source: frame.contentWindow, data: { type: 'estate:settings-size', height: 1240.5 } })
  assert.equal(frame.style.height, '1241px')
  const wheel = { origin: 'http://127.0.0.1:4173', source: frame.contentWindow, data: { type: 'estate:settings-wheel', deltaY: 320 } }
  listeners.message({ ...wheel, origin: 'https://unrelated.example' })
  listeners.message({ ...wheel, data: { ...wheel.data, deltaY: Infinity } })
  assert.deepEqual(scrolls, [])
  listeners.message(wheel)
  assert.deepEqual(scrolls, [320])
  location.hash = '#work'; changed()
  listeners.message(wheel)
  assert.deepEqual(scrolls, [320])
})

test('embedded settings forwards wheel remainder while preserving editor scrolling and browser zoom', () => {
  let wheel
  const messages = []
  class Element {
    constructor(values = {}) { Object.assign(this, { scrollTop: 0, scrollHeight: 100, clientHeight: 100, overflowY: 'visible' }, values) }
  }
  const document = { head: { append() {} }, createElement: () => ({ dataset: {} }), body: new Element(), documentElement: new Element() }
  const window = { self: {}, top: {}, innerHeight: 700, parent: { postMessage: (data, origin) => messages.push({ data, origin }) }, addEventListener: (type, fn) => { if (type === 'wheel') wheel = fn } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../airi_overlay/settings-entry.js'), 'utf8'), { document, window, location: { pathname: '/settings' }, HTMLElement: Element, getComputedStyle: node => node })
  function event(extra = {}) { return { deltaY: 60, deltaMode: 0, composedPath: () => [], preventDefault() { this.prevented = true }, ...extra } }
  const down = event(); wheel(down)
  assert.equal(down.prevented, true)
  assert.equal(messages[0].data.deltaY, 60)
  assert.equal(messages[0].origin, 'http://127.0.0.1:8000')
  const editor = new Element({ overflowY: 'auto', scrollHeight: 500, scrollTop: 10 })
  wheel(event({ composedPath: () => [editor] }))
  wheel(event({ ctrlKey: true }))
  assert.equal(messages.length, 1)
  editor.scrollTop = 400
  wheel(event({ composedPath: () => [editor], deltaMode: 1, deltaY: 3 }))
  assert.equal(messages[1].data.deltaY, 48)
})

test('preview server retires diagnostic pages without intercepting the resident entry or operational APIs', () => {
  const ts = require('../.vendor/airi/node_modules/typescript')
  const source = fs.readFileSync(path.join(__dirname, '../airi_overlay/retired-pages.ts'), 'utf8')
  const sandbox = { exports: {} }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, sandbox)
  let middleware
  sandbox.exports.retiredPages().configurePreviewServer({ middlewares: { use: handler => { middleware = handler } } })
  for (const url of ['/ui/estate-timer-before-check.html', '/ui/estate-timer-check.html?old=1']) {
    let status; let headers; let ended = false
    middleware({ url }, { writeHead: (code, value) => { status = code; headers = value }, end: () => { ended = true } }, () => assert.fail('retired page continued'))
    assert.equal(status, 307)
    assert.equal(headers.Location, 'http://127.0.0.1:8000/admin#settings')
    assert.equal(ended, true)
  }
  for (const url of ['/ui/estate-resident-entry.html?estate=1', '/assets/active.js', '/api/v1/robot/status']) {
    let continued = false
    middleware({ url }, {}, () => { continued = true })
    assert.equal(continued, true)
  }
})
