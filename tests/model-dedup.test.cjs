const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs')
const loaded = import('data:text/javascript;base64,' + fs.readFileSync('airi_overlay/model-dedup.js').toString('base64'))
test('same content reuses an existing import; same filename with different bytes is distinct', async () => {
  const { fileDigest, findSameModel } = await loaded
  const one = new File(['real-model-one'], 'same.zip'), copy = new File(['real-model-one'], 'renamed.zip'), different = new File(['different-data'], 'same.zip')
  const row = { id: 'legacy-id', type: 'file', format: 'live2d-zip', file: one }
  assert.equal(await findSameModel([row], row.format, copy, await fileDigest(copy)), row)
  assert.equal(await findSameModel([row], row.format, different, await fileDigest(different)), undefined)
  assert.equal(await findSameModel([row], 'vrm', copy, await fileDigest(copy)), undefined)
})
test('merged cards preserve current identity, every source filter, aliases and all originals', async () => {
  const { mergeModelChoices } = await loaded
  const a = { id: 'gallery:mao', name: 'Mao', platform: '官方', sha256: 'abc', format: 'live2d-zip', gallery: { id: 'mao' } }
  const b = { id: 'first-import', name: 'mao.zip', platform: '此裝置', sha256: 'abc', format: 'live2d-zip', model: { id: 'first-import' } }
  const current = { ...b, id: 'current-import', model: { id: 'current-import' } }
  const shared = { ...b, id: 'cloud-live2d-abc', platform: '平台共享', model: undefined, sharedId: 'cloud-live2d-abc' }
  const rows = [a, b, current, shared], before = structuredClone(rows)
  const result = mergeModelChoices(rows, 'current-import')
  assert.equal(result.length, 1)
  assert.equal(result[0].id, 'current-import')
  assert.equal(result[0].model.id, 'current-import')
  assert.deepEqual(result[0].platforms, ['官方', '此裝置', '平台共享'])
  assert.deepEqual(result[0].aliases, ['Mao', 'mao.zip'])
  assert.deepEqual(rows, before)
  assert.equal(mergeModelChoices([a, { ...b, sha256: 'different' }]).length, 2)
})
test('a file is hashed once and unreadable files are retained rather than falsely merged', async () => {
  const { fileDigest, findSameModel } = await loaded
  let reads = 0
  const file = { size: 1, arrayBuffer() { reads++; return Promise.resolve(new Uint8Array([1]).buffer) } }
  assert.equal(await fileDigest(file), await fileDigest(file)); assert.equal(reads, 1)
  assert.equal(await findSameModel([{ type:'file', format:'vrm', file:{size:1,arrayBuffer:async()=>{throw Error('unreadable')}} }], 'vrm', file, await fileDigest(file)), undefined)
})
