const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const test = require('node:test')

function harness() {
  const create = tag => ({ tag, children: [], attrs: {}, textContent: '', append(...nodes) { this.children.push(...nodes) }, replaceChildren(...nodes) { this.children = nodes }, setAttribute(key, value) { this.attrs[key] = value } })
  const context = { document: { createElement: create } }
  vm.runInNewContext(fs.readFileSync('edge_hub/static/api-quota.js', 'utf8'), context)
  return { api: context.ZhiweiQuota, root: create('tbody') }
}

test('readiness shows missing or stale dependencies without presenting cached success', () => {
  const { api, root } = harness()
  const checks = ['chat','speech','recognition','page'].map(id => ({id,ready:true}))
  api.readiness(root,{checks,checked_at_ms:1000},1000)
  assert.match(root.textContent,/Microsoft 語音服務：就緒/)
  checks[1].ready=false
  api.readiness(root,{checks,checked_at_ms:1000},1000)
  assert.match(root.textContent,/Microsoft 語音服務：需檢查/)
  api.readiness(root,{checks,checked_at_ms:1000},32000)
  assert.match(root.textContent,/未能確認/)
  api.readiness(root,{checks:[{id:'chat',ready:true}],checked_at_ms:32000},32000)
  assert.match(root.textContent,/未能確認/)
})

test('official and local remaining bars are separate, unknown official quota gets no bar', () => {
  const { api, root } = harness()
  api.render(root, [
    { platform: 'Tavily', service: '搜尋', provider: { status: 'stale', percent: 98.7, remaining: 987, limit: 1000 }, note: '官方記錄' },
    { platform: 'Google', service: '對話', provider: { status: 'not_reported', percent: null }, guard: { percent: 5, counters: [{ meter: 'gemini_chat_characters', remaining: 10000, limit: 200000 }] }, note: '官方未知' },
  ])
  const official = root.children[0].children[1]
  assert.equal(official.children.find(node => node.tag === 'progress').value, 98.7)
  assert.match(official.children[0].textContent, /上次記錄/)
  assert.equal(official.children.find(node => node.tag === 'progress').className, 'service-quota-stale')
  const google = root.children[1]
  assert.equal(google.children[1].children.some(node => node.tag === 'progress'), false)
  assert.equal(google.children[2].children.find(node => node.tag === 'progress').value, 5)
  assert.equal(google.children[2].children.at(-1).textContent, '不是平台官方餘額')
  api.render(root, [{ service: '<script>never execute</script>', platform: 'test', provider: { percent: null }, note: 'unknown' }])
  assert.equal(root.children.length, 1)
  assert.equal(root.children[0].children[0].children[0].textContent, '<script>never execute</script>')
})

test('invalid and missing percentages are never rendered as zero or full', () => {
  const { api } = harness()
  for (const value of [undefined, null, true, NaN, Infinity, -1, 101, '100'])
    assert.equal(api.percentage(value), null)
  assert.equal(api.percentage(0), 0)
  assert.equal(api.percentage(100), 100)
})

test('monthly voice and provider reset are labelled without inventing official remaining quota', () => {
  const { api, root } = harness()
  api.render(root, [{ platform: 'Azure F0', service: '曉曼', purpose: '居民回覆朗讀',
    provider: { status: 'not_reported', percent: null, allocation: '每月 500,000 計費字元' },
    guard: { interval: 'month', percent: 99.8, counters: [{ meter: 'azure_tts_characters', remaining: 399215, limit: 400000 }], period: '本機下次重設：2026-11-01 08:00（香港）' },
    reset_label: '官方資源精確重設日期未取得', note: '本機保守預留' }])
  const row = root.children[0]
  assert.equal(row.children[0].children.at(-1).textContent, '居民回覆朗讀')
  assert.equal(row.children[1].children.some(node => node.tag === 'progress'), false)
  assert.match(row.children[1].children.at(-1).textContent, /500,000/)
  assert.match(row.children[2].children.find(node => node.tag === 'progress').attrs['aria-label'], /每月/)
  assert.match(row.children[2].children[2].textContent, /計費字元/)
  assert.equal(row.children[3].children.at(-1).textContent, '本機下次重設：2026-11-01 08:00（香港）')
})

test('local resource bars show USED percentage and missing readings have no fabricated bar',()=>{
  const {api,root}=harness()
  api.resources(root,{metrics:{cpu:{percent:25},ram:{percent:60,used_bytes:6*1073741824,total_bytes:10*1073741824}}})
  assert.equal(root.children.length,3)
  assert.equal(root.children[0].children.find(x=>x.tag==='progress').value,25)
  assert.match(root.children[0].children[1].textContent,/已使用/)
  assert.equal(root.children[1].children.at(-1).textContent,'6.0／10.0 GB')
  assert.equal(root.children[2].children.some(x=>x.tag==='progress'),false)
  api.resources(root,{metrics:{cpu:{percent:0}}})
  assert.equal(root.children[0].children.find(x=>x.tag==='progress').value,0)
})
