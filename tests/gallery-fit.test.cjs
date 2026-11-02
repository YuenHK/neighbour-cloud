const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const source = fs.readFileSync(path.resolve('airi_overlay/gallery-fit.js'), 'utf8')
const load = () => import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
test('native framing remains exactly the same object', async () => {
  const { galleryFraming } = await load(), fallback = { scale: 2, x: 3, y: 4 }
  assert.equal(galleryFraming({}, { width: 500, height: 800 }, fallback), fallback)
})
test('reviewed off-centre visible geometry fits with padding and survives resizing', async () => {
  const { galleryFraming } = await load()
  const model = { internalModel: { width: 1000, height: 2000,
    settings: { json: { Neighbour: { fit: 'visible-contain-v1' } } },
    coreModel: { getDrawableCount: () => 2, getDrawableOpacity: i => i === 0 ? 1 : 0 },
    getDrawableVertices: () => [600, 800, 1000, 1200], localTransform: { apply: p => p } } }
  assert.deepEqual(galleryFraming(model, { width: 400, height: 800 }, {}), { scale: .9, x: -70, y: 400 })
  assert.deepEqual(galleryFraming(model, { width: 800, height: 400 }, {}), { scale: .9, x: 130, y: 200 })
})
test('empty geometry falls back without producing Infinity', async () => {
  const { galleryFraming } = await load(), fallback = { scale: 1 }
  const model = { internalModel: { settings: { json: { Neighbour: { fit: 'visible-contain-v1' } } }, coreModel: { getDrawableCount: () => 0 } } }
  assert.equal(galleryFraming(model, { width: 400, height: 500 }, fallback), fallback)
})
test('reviewed legacy mouth responds to the existing speech parameter without renaming files', async () => {
  const { installGalleryMouthAlias } = await load()
  const core = { getModel: () => ({ parameters: { ids: ['PARAM_MOUTH_OPEN_Y'] } }), getParameterIndex: id => id }
  const model = { internalModel: { settings: { json: { Neighbour: { fit: 'visible-contain-v1' } } }, coreModel: core } }
  installGalleryMouthAlias(model)
  assert.equal(core.getParameterIndex('ParamMouthOpenY'), 'PARAM_MOUTH_OPEN_Y')
  assert.equal(core.getParameterIndex('Other'), 'Other')
  const once = core.getParameterIndex
  installGalleryMouthAlias(model)
  assert.equal(core.getParameterIndex, once)
})
