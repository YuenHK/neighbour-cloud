const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const html = fs.readFileSync(path.join(__dirname, '../edge_hub/static/admin.html'), 'utf8')

test('live management script is valid and technical diagnostics are retired', () => {
  assert.doesNotThrow(() => new vm.Script(html.match(/<script>([\s\S]*?)<\/script>/)[1]))
  assert.doesNotMatch(html, /ZhiweiAdminStatus|system-status|vision\/status|loadHealth|voiceSettingsForm|searchSettingsForm/)
})

test('management initializes using only nodes still present and never loads secret or voice settings', async () => {
  const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], {
    value: match[1] === 'operatorKey' ? 'synthetic-key' : '', textContent: '', disabled: false,
    listeners: {}, addEventListener(name, handler) { this.listeners[name] = handler },
    replaceChildren(...items) { this.children = items }, add(item) { this.children.push(item) },
  }]))
  const calls = []
  const context = { document: { getElementById: id => nodes.get(id) || null, addEventListener() {} }, window: { addEventListener() {} }, queueMicrotask,
    crypto: require('node:crypto').webcrypto, AbortSignal, Option: class {}, setInterval() {},
    ZhiweiQuota: { render(root) { assert.ok(root) }, resources(root) { assert.ok(root) } },
    fetch: async (url, options) => {
      calls.push({ url, method: options.method })
      return { ok: true, json: async () => url.endsWith('/knowledge') ? { items: [] } : { overview: { rows: [], updated_at_ms: Date.now() }, chat: {} } }
    },
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../edge_hub/static/estate-management.js'), 'utf8'), context)
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(calls.map(call => call.url).sort(), ['/api/v1/service-desk/knowledge', '/api/v1/service-desk/quota', '/api/v1/service-desk/resources'])
  assert.ok(calls.every(call => call.method === 'GET'))
  assert.match(nodes.get('quotaStatus').textContent, /已核對/)
  assert.ok(nodes.get('knowledgeForm').listeners.submit)
  assert.ok(nodes.get('residentMemoriesForm').listeners.submit)
})
