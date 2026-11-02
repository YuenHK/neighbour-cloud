const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const ts = require('../.vendor/airi/node_modules/typescript')
const colorModule = require('../.vendor/airi/packages/stage-layouts/node_modules/colorjs.io')
const Color = colorModule.default || colorModule
const file = fs.readFileSync(path.join(__dirname, '../.vendor/airi/packages/stage-layouts/src/composables/theme-color.ts'), 'utf8')
const source = file.slice(file.indexOf('export function useThemeColor('), file.indexOf('export function useBackgroundThemeColor(')).replace('export function ', 'function ')
function harness(producer, extra = {}) {
  const changes = []
  const meta = { isConnected: true, setAttribute: (key, value) => changes.push([key, value]) }
  const context = vm.createContext({ Color, document: { querySelector: () => meta }, window: {}, ...extra })
  vm.runInContext(ts.transpileModule(source + '\nglobalThis.useThemeColor = useThemeColor', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { ...context.useThemeColor(producer), changes, meta }
}
test('empty, invalid and unresolved CSS references cannot crash the page or replace the last color', async () => {
  for (const input of ['', '   ', 'var(--not-ready)', 'not-a-color', undefined]) {
    const h = harness(() => input)
    await assert.doesNotReject(h.updateThemeColor())
    assert.equal(h.changes.length, 0)
  }
})
test('real ColorJS converts a ready background and handles a temporarily detached element', async () => {
  let reference = ''
  const h = harness(async () => reference)
  await h.updateThemeColor()
  reference = 'rgb(33 105 93)'
  await h.updateThemeColor()
  assert.equal(h.changes.length, 1)
  assert.equal(h.changes[0][1], '#21695d')
  h.meta.isConnected = false
  await h.updateThemeColor()
  assert.equal(h.changes.length, 1)
})
test('optional theme metadata tolerates rejected sampling and no DOM or meta element', async () => {
  const h = harness(async () => { throw new Error('widget unmounted while sampling') })
  await assert.doesNotReject(h.updateThemeColor())
  for (const extra of [{ window: undefined }, { document: undefined }, { document: { querySelector: () => null } }]) {
    const h = harness(() => { throw new Error('must not sample') }, extra)
    await assert.doesNotReject(h.updateThemeColor())
  }
})
test('a late sample from the old background cannot overwrite the current background', async () => {
  let finish
  let call = 0
  const h = harness(() => ++call === 1 ? new Promise(resolve => { finish = resolve }) : '#21695d')
  const old = h.updateThemeColor()
  await h.updateThemeColor()
  finish('#ffffff')
  await old
  assert.equal(h.changes.length, 1)
  assert.equal(h.changes[0][1], '#21695d')
})
