const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const html = fs.readFileSync(path.join(__dirname, '../edge_hub/static/admin.html'), 'utf8')
const match = html.match(/\/\/ BEGIN REQUEST CLIENT([\s\S]*?)\/\/ END REQUEST CLIENT/)
assert.ok(match, 'exercise the exact client served by the management page')
const context = vm.createContext({ AbortController, setTimeout, clearTimeout })
vm.runInContext(match[1], context)
const client = context.ZhiweiAdminRequest

test('failed HTTP never masquerades as a successful JSON answer', async () => {
  await assert.rejects(client.json('/api/v1/faq/query', {}, 100, async () => ({
    ok: false, status: 503, json() { throw Error('must not decode error body') },
  })), /HTTP 503/)
})

test('deadline works even if fetch or body decoding ignores abort', async () => {
  let signal
  await assert.rejects(client.json('/health', {}, 10, async (_path, options) => {
    signal = options.signal
    return { ok: true, json: () => new Promise(() => {}) }
  }), /request_timeout/)
  assert.equal(signal.aborted, true)
})

test('same-origin requests disable redirects, ambient credentials and cache', async () => {
  let options
  const result = await client.json('/health', {}, 100, async (_path, opts) => {
    options = opts
    return { ok: true, json: async () => ({ status: 'ok' }) }
  })
  assert.equal(result.status, 'ok')
  assert.equal(options.redirect, 'error')
  assert.equal(options.credentials, 'omit')
  assert.equal(options.cache, 'no-store')
})

test('rejects external or protocol-relative targets before invoking fetch', async () => {
  for (const target of ['https://example.com', '//example.com', '/\\example.com']) {
    await assert.rejects(client.json(target, {}, 100, () => {
      throw Error('must not send operator credentials')
    }), /invalid_local_path/)
  }
})

test('workspace navigation removes obsolete demonstrations and duplicate tools', () => {
  assert.doesNotMatch(html, /href="http:\/\/127\.0\.0\.1:4173"/)
  assert.doesNotMatch(html, /href="\/simulation-control"/)
  assert.match(html, /管理工作台分區/)
  assert.doesNotMatch(html, /id="chatForm"|id="speechForm"|id="simulateLitter"/)
  assert.doesNotMatch(html, /onclick=.*(?:drive|motor)/)
})

function pageHarness(request, eventsOpen = true, pageSource = html) {
  const nodes = new Map()
  const document = {
    listeners: {}, addEventListener(name, handler) { this.listeners[name] = handler },
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {
        textContent: '', value: 'test-only', listeners: {}, open: selector === '#eventsPanel' ? eventsOpen : undefined, hidden: selector === '#eventsPanel' ? !eventsOpen : false,
        addEventListener(name, handler) { this.listeners[name] = handler },
        replaceChildren(...rows) { this.rows = rows },
      })
      return nodes.get(selector)
    },
    createElement() { return { textContent: '', appendChild() {}, addEventListener() {} } },
  }
  const page = vm.createContext({ AbortController, setTimeout, clearTimeout, document,
    setInterval() {}, fetch: request, performance: { now: () => 0 } })
  vm.runInContext(pageSource.match(/<script>([\s\S]*?)<\/script>/)[1], page)
  return { page, nodes, document }
}

const archived = fs.readFileSync(path.join(__dirname, '../docs/archive/ui-2026-10-26/admin-legacy.html'), 'utf8')
const flush = () => new Promise(resolve => setImmediate(resolve))
const emptyStats = { total: 0, pending: 0, confirmed: 0, false_positive: 0, resolved: 0 }

test('FAQ handler reports 503 and malformed success instead of displaying undefined', async () => {
  for (const response of [{ ok: false, status: 503 }, { ok: true, json: async () => ({}) }]) {
    const { nodes } = pageHarness(async path => path === '/api/v1/faq/query'
      ? response : { ok: false, status: 503 }, true, archived)
    await flush()
    await nodes.get('#faqForm').listeners.submit({ preventDefault() {} })
    assert.match(nodes.get('#faqResult').textContent, /FAQ 查詢失敗或逾時/)
    assert.doesNotMatch(nodes.get('#faqResult').textContent, /undefined/)
  }
})

test('event load failure marks stale rows and statistics as unverified', async () => {
  const { nodes } = pageHarness(async () => { throw Error('offline') })
  await flush()
  assert.match(nodes.get('#eventStatus').textContent, /目前列表不可視為最新/)
  assert.match(nodes.get('#stats').textContent, /不是零事件/)
})

test('report section does not poll until staff select it', async () => {
  let requests = 0
  const { nodes, document } = pageHarness(async (path) => {
    if (path.startsWith('/api/v1/event')) requests++
    return { ok: true, json: async () => path.endsWith('event-stats') ? emptyStats : [] }
  }, false)
  await flush()
  assert.equal(requests, 0)
  nodes.get('#eventsPanel').hidden = false
  document.listeners.worksectionchange()
  await flush()
  assert.equal(requests, 2)
})

test('overlapping event polls are coalesced while an earlier snapshot is pending', async () => {
  const pending = []
  const { page, nodes } = pageHarness(async path => {
    if (path === '/api/v1/events?limit=100' || path === '/api/v1/event-stats')
      return new Promise(resolve => pending.push(() => resolve({ ok: true,
        json: async () => path.endsWith('event-stats') ? emptyStats : [] })))
    return { ok: false, status: 503 }
  })
  await page.loadEvents()
  assert.equal(pending.length, 2)
  pending.forEach(resolve => resolve())
  await flush()
  assert.match(nodes.get('#eventStatus').textContent, /目前顯示 0 項現場回報/)
})

test('simulation event creation is explicitly marked as software validation', async () => {
  let payload
  const { page } = pageHarness(async (path, options) => {
    if (path === '/api/v1/events' && options.method === 'POST') payload = JSON.parse(options.body)
    return { ok: true, json: async () => path.endsWith('event-stats') ? emptyStats : [] }
  }, true, archived)
  await flush()
  await page.simulate('temperature_drill', 'notice')
  assert.equal(payload.details.is_test, true)
  assert.equal(payload.details.source, 'software_validation')
})


test('live workbench hides historical software demonstrations without deleting records', async () => {
  const rows = [
    { id: 'real-report', details: {}, type: 'leak_detected', severity: 'warning', status: 'pending' },
    { id: 'demo-report', details: { is_test: true }, type: 'litter_detected', severity: 'notice', status: 'pending' },
  ]
  const { nodes } = pageHarness(async path => ({ ok: true, json: async () => path.endsWith('event-stats') ? { ...emptyStats, total: 2, pending: 2 } : rows }))
  await flush()
  assert.equal(nodes.get('#events').rows.length, 1)
  assert.match(nodes.get('#eventStatus').textContent, /1 項現場回報/)
  assert.doesNotMatch(html, /method: 'DELETE'/)
})
