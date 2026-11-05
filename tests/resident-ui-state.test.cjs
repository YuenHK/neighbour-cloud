const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const load = () => import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync('airi_overlay/resident-ui-state.js')).toString('base64'))

test('preparing speech never claims the resident can already hear audio', async () => {
  const { residentUiPhase } = await load()
  assert.equal(residentUiPhase({ busy: true, streaming: true, preparingSpeech: true, speaking: false }), 'preparing')
  assert.equal(residentUiPhase({ busy: true, preparingSpeech: true, speaking: true }), 'speaking')
})
test('a preserved failure is not painted ready when network waiting ends', async () => {
  const { residentUiPhase } = await load()
  for (const status of ['剛才未能完成回覆，內容仍保留，可以再傳送一次。', '語音暫時未能完成朗讀，文字已保留。', '已停止等候，內容已保留。'])
    assert.equal(residentUiPhase({ busy: false, status }), 'attention')
  assert.equal(residentUiPhase({ busy: true, streaming: false }), 'thinking')
  assert.equal(residentUiPhase({ busy: true, streaming: true }), 'replying')
  assert.equal(residentUiPhase({ busy: false, status: '我喺度，你慢慢講。' }), 'ready')
})
