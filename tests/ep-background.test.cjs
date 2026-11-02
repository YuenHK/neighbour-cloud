const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync(require('node:path').join(__dirname, '../edge_hub/static/ep-background.js'), 'utf8')

test('every page including a hidden resident tab renews only discovery without a key', async () => {
  const calls = []
  let tick
  const context = vm.createContext({ AbortSignal, document: { hidden: true },
    setInterval(fn) { tick = fn },
    fetch: async (url, options) => { calls.push({ url, options }); return { ok: true } },
  })
  vm.runInContext(source, context)
  await context.EpDiscoveryReady
  tick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.length, 2)
  assert.ok(calls.every(call => call.url === '/api/v1/robot/ep/discovery' && call.options.method === 'POST'))
  assert.ok(calls.every(call => !call.options.headers && call.options.credentials === 'omit'))
  vm.runInContext(source, context)
  assert.equal(calls.length, 2) // Loading the common shell twice does not duplicate work.
})
