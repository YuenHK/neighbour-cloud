import assert from 'node:assert/strict'
import { test } from 'node:test'
import { validateFreeSkeletalBundle, validateSkeletalTexture } from '../airi_overlay/free-skeletal-loader.js'

const doc = () => ({ skeleton: { spine: '3.8.99' }, bones: [{ name: 'root' }, { name: 'mouth', parent: 'root' }],
  slots: [{ name: 'body', bone: 'root', attachment: 'body' }],
  skins: { default: { body: { body: { path: 'body', width: 8, height: 8 } } } },
  animations: { wave: { bones: { root: { rotate: [{ time: 0, angle: 0 }, { time: 0.2, angle: 20 }] } } } } })
const atlas = 'original.png\nsize: 8,8\nformat: RGBA8888\nfilter: Linear,Linear\nrepeat: none\nbody\n  bounds: 0,0,8,8\n'
function bundle(change) {
  const json = doc()
  change?.(json)
  return { format: 'rigby-json-zip/v1', skeletonText: JSON.stringify(json), atlasText: atlas,
    pages: { 'original.png': new Blob(['placeholder'], { type: 'image/png' }) } }
}

test('free JSON/PNG fixture is a distinct explicit format with a real local texture reference', () => {
  assert.deepEqual(validateFreeSkeletalBundle(bundle()).textureNames, ['original.png'])
  assert.throws(() => validateFreeSkeletalBundle({ ...bundle(), format: 'spine-zip' }))
})

const invalid = [
  ['self cycle', json => json.bones[0].parent = 'root'],
  ['missing bone', json => json.bones[1].parent = 'unknown'],
  ['string coordinate', json => json.bones[1].x = 'NaN'],
  ['numeric overflow', json => json.bones[1].x = 1e20],
  ['negative width', json => json.skins.default.body.body.width = -1],
  ['remote texture', json => json.skins.default.body.body.path = 'https://outside.invalid/PRIVATE'],
  ['missing region', json => json.skins.default.body.body.path = 'missing'],
  ['linked mesh', json => json.skins.default.body.body.type = 'linkedmesh'],
  ['weighted or invalid mesh', json => Object.assign(json.skins.default.body.body, { type: 'mesh', uvs: [0, 0, 1, 0, 1, 1], triangles: [0, 1, 9], vertices: [0, 0, 1, 0, 1, 1] })],
  ['backward timeline', json => json.animations.wave.bones.root.rotate.push({ time: -1, angle: 0 })],
  ['unknown timeline target', json => json.animations.wave.bones.unknown = {}],
  ['event execution unsupported', json => json.animations.wave.events = [{ name: 'run' }]],
  ['constraints unsupported', json => json.ik = [{ name: 'target' }]],
  ['unsupported format', json => json.skeleton.spine = '4.1.0'],
]
for (const [name, change] of invalid)
  test(`free importer rejects ${name}`, () => assert.throws(() => validateFreeSkeletalBundle(bundle(change))))

test('reject absent pages, external atlas names, giant atlas and disguised scripts before rendering', async () => {
  assert.throws(() => validateFreeSkeletalBundle({ ...bundle(), pages: {} }))
  assert.throws(() => validateFreeSkeletalBundle({ ...bundle(), atlasText: atlas.replace('original.png', 'https://outside.invalid/x.png') }))
  assert.throws(() => validateFreeSkeletalBundle({ ...bundle(), atlasText: atlas.replace('size: 8,8', 'size: 99999,99999') }))
  assert.throws(() => validateFreeSkeletalBundle({ ...bundle(), skeletonText: '{"skeleton":{"spine":"3.8"},"__proto__":{}}' }))
  assert.throws(() => validateFreeSkeletalBundle({ ...bundle(), skeletonText: ' ' .repeat(3 * 1024 * 1024 + 1) }))
  await assert.rejects(validateSkeletalTexture(new Blob(['<svg onload="run()"/>'], { type: 'image/png' })))
})

test('PNG dimensions are checked before an image decoder allocates pixels', async () => {
  const bytes = new Uint8Array(24)
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10], 0)
  bytes.set([73, 72, 68, 82], 12)
  const view = new DataView(bytes.buffer)
  view.setUint32(16, 8)
  view.setUint32(20, 8)
  assert.deepEqual(await validateSkeletalTexture(new Blob([bytes]), 8, 8), { width: 8, height: 8 })
  await assert.rejects(validateSkeletalTexture(new Blob([bytes]), 16, 16))
  view.setUint32(16, 99999)
  await assert.rejects(validateSkeletalTexture(new Blob([bytes])))
})
