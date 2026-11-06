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

test('resource author search and VRoid provenance survive merging with an existing shared file', async () => {
  const { mergeModelChoices } = await loaded
  const source = { id:'123', source:'https://hub.vroid.com/en/characters/1/models/123' }
  const rows = [
    {id:'shared-id',name:'Existing.vrm',format:'vrm',sha256:'abc',platform:'平台共享'},
    {id:'vroid:123',name:'Original',format:'vrm',sha256:'abc',platform:'VRoid Hub',aliases:['Creator Name'],vroid:source},
  ]
  const result = mergeModelChoices(rows)
  assert.equal(result.length,1)
  assert.deepEqual(result[0].aliases,['Existing.vrm','Original','Creator Name'])
  assert.equal(result[0].vroid,source)
})

test('a reviewed application model reuses local or shared bytes and retains original application-only terms', async () => {
  const { mergeModelChoices } = await loaded
  const reviewed = {id:'tsukuyomi-official-spats',application_only:true,notice:'Keep original author terms'}
  const model = {id:'current-model',type:'file'}
  const rows = [
    {id:'current-model',name:'Existing.vrm',format:'vrm',sha256:'abc',platform:'此裝置',model},
    {id:'reviewed:tsukuyomi',name:'Tsukuyomi',format:'vrm',sha256:'abc',platform:'Tsukuyomi 官方',reviewed},
    {id:'cloud-vrm-abc',name:'Shared.vrm',format:'vrm',sha256:'abc',platform:'平台共享',sharedId:'cloud-vrm-abc'},
  ]
  const result=mergeModelChoices(rows,'current-model')
  assert.equal(result.length,1);assert.equal(result[0].model,model)
  assert.equal(result[0].reviewed,reviewed);assert.equal(result[0].sharedId,'cloud-vrm-abc')
  assert.deepEqual(result[0].platforms,['此裝置','Tsukuyomi 官方','平台共享'])
})

test('newest admitted or imported content sorts first across sources without changing current selection', async () => {
  const { mergeModelChoices, newestModelChoices } = await loaded
  const rows = [
    { id: 'selected-old', name: 'Old', platform: '官方', format: 'live2d-zip', sha256: 'old', addedAt: 100 },
    { id: 'new-vrm', name: 'New', platform: 'VRoid', format: 'vrm', sha256: 'new', addedAt: 300 },
    { id: 'shared-new', name: 'Newest upload', platform: '平台共享', format: 'live2d-zip', sha256: 'upload', addedAt: 500 },
    { id: 'local-copy', name: 'New local import', platform: '此裝置', format: 'vrm', sha256: 'new', addedAt: 700 },
    { id: 'unknown', name: 'Unknown date', platform: '官方', format: 'vrm' },
  ]
  const original = structuredClone(rows)
  const merged = mergeModelChoices(rows, 'selected-old')
  const sorted = newestModelChoices(merged)
  assert.deepEqual(sorted.map(row => row.id), ['new-vrm', 'shared-new', 'selected-old', 'unknown'])
  assert.equal(sorted[0].addedAt, 700)
  assert.deepEqual(rows, original)
  assert.equal(merged[0].id, 'selected-old')
  assert.deepEqual(newestModelChoices(merged).map(row => row.id), sorted.map(row => row.id))
})

test('missing or invalid dates remain last and ties retain their stable original order', async () => {
  const { newestModelChoices } = await loaded
  const rows = [{ id: 'missing' }, { id: 'future', addedAt: Infinity }, { id: 'bad', addedAt: '99999' },
    { id: 'one', addedAt: 100 }, { id: 'two', addedAt: 100 }, { id: 'negative', addedAt: -10 }]
  const original = rows.slice()
  assert.deepEqual(newestModelChoices(rows).map(row => row.id), ['one', 'two', 'missing', 'future', 'bad', 'negative'])
  assert.deepEqual(rows, original)
})
