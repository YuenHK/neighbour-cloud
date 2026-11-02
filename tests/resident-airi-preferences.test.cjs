const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
const test = require('node:test')
const moduleAt = name => import(pathToFileURL(path.resolve('airi_overlay', name)))

test('published shorter context keeps recent complete turns and reset still removes identity', async () => {
  const { ResidentSession } = await moduleAt('resident-session.js')
  const requests = []
  const current = new ResidentSession(async body => { requests.push(body); return '公開合成回覆' }, { maxMessages: 4, maxCharacters: 2000 })
  for (let i = 0; i < 8; i++) await current.send(`公開問題${i}`)
  assert.ok(requests.every(body => body.messages.length <= 4 && body.messages[0].role === 'user'))
  assert.equal(requests.at(-1).messages.at(-1).content, '公開問題7')
  assert.equal(requests.at(-1).messages[0].content, '公開問題6')
  current.profile = '合成稱呼'
  current.reset()
  assert.equal(current.profile, '')
  assert.deepEqual(current.history, [])
  assert.throws(() => new ResidentSession(() => {}, { maxMessages: 100 }), /invalid_resident_context/)
})

test('saved two-minute handover expires on wall clock and cannot exceed original privacy ceiling', async () => {
  const { ResidentIdle } = await moduleAt('resident-idle.js')
  let now = 0, expired = 0, scheduled
  const idle = new ResidentIdle(() => expired++, { timeoutMs: 120000, now: () => now,
    setTimer: (_fn, delay) => { scheduled = delay; return 1 }, clearTimer() {} })
  idle.touch()
  assert.equal(scheduled, 120000)
  now = 119999
  idle.check()
  assert.equal(expired, 0)
  now = 120000
  idle.check()
  assert.equal(expired, 1)
  idle.check()
  assert.equal(expired, 1)
  assert.throws(() => new ResidentIdle(() => {}, { timeoutMs: 240000 }), /invalid_resident_idle/)
})
