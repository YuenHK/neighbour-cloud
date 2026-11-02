const assert = require('node:assert/strict')
const test = require('node:test')

test('production preview serves built assets without build plugins and keeps retired pages retired', async () => {
  const { default: config } = await import('../scripts/stage_preview.config.mjs')
  assert.equal(config.preview.strictPort, true)
  assert.equal(config.preview.host, '127.0.0.1')
  assert.equal(config.plugins.length, 1)
  let middleware
  config.plugins[0].configurePreviewServer({ middlewares: { use(handler) { middleware = handler } } })
  let passed = false
  middleware({ url: '/settings/models' }, {}, () => { passed = true })
  assert.equal(passed, true)
  let result
  middleware({ url: '/ui/estate-timer-check.html?old=true' }, {
    writeHead(code, headers) { result = { code, headers } }, end() {},
  }, () => assert.fail('retired page must not reach static files'))
  assert.equal(result.code, 307)
  assert.equal(result.headers['Cache-Control'], 'no-store')
})
