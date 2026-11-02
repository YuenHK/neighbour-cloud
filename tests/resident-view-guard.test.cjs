const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const test = require('node:test')
const source = fs.readFileSync(path.join(__dirname, '../airi_overlay/resident-view-guard.js'), 'utf8')
const guard = vm.createContext({})
vm.runInContext(source.replace('export function inspectResidentView', 'globalThis.inspectResidentView = function').replace('export function isCameraGesture', 'globalThis.isCameraGesture = function'), guard)

test('resident view blocks low angles and excessive closeups without modifying stored settings', () => {
  const normal = { renderer: 'vrm', camera: { x: 0, y: 1.65, z: -1.85 }, origin: { x: 0, y: 1.4, z: 0 }, height: 2, fov: 40 }
  const original = JSON.stringify(normal)
  assert.equal(guard.inspectResidentView(normal), 'safe')
  assert.equal(guard.inspectResidentView({ ...normal, camera: { x: 0, y: 0, z: -1 } }), 'low-angle')
  assert.equal(guard.inspectResidentView({ ...normal, camera: { x: 0, y: 1.4, z: -.2 } }), 'close-up')
  assert.equal(guard.inspectResidentView({ ...normal, fov: 5 }), 'close-up')
  assert.equal(guard.inspectResidentView({ ...normal, camera: { x: NaN, y: 1, z: -2 } }), 'invalid-view')
  assert.equal(guard.inspectResidentView({ renderer: 'live2d', scale: 2.5 }), 'close-up')
  assert.equal(guard.inspectResidentView({ renderer: 'live2d', scale: 1 }), 'safe')
  assert.equal(JSON.stringify(normal), original)
})

test('ordinary hover and clicks do not trigger the stop notice; camera drags do', () => {
  assert.equal(guard.isCameraGesture(undefined, { x: 30, y: 30 }), false)
  assert.equal(guard.isCameraGesture({ x: 10, y: 10 }, { x: 15, y: 15 }), false)
  assert.equal(guard.isCameraGesture({ x: 10, y: 10 }, { x: 30, y: 10 }), true)
})
