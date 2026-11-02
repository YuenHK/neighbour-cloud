const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
async function moduleUnderTest() { return import('data:text/javascript;base64,' + fs.readFileSync('airi_overlay/cloud-readiness.js').toString('base64')) }
test('avatar alone never means conversation or microphone ready', async () => {
  const {createReadiness} = await moduleUnderTest(), calls = []
  const value = createReadiness(x => calls.push(x))
  value.update('avatar','ready')
  assert.equal(calls.at(-1).ready,false)
  assert.equal(calls.at(-1).textReady,false)
  value.update('interface','ready');value.update('runtime','ready')
  assert.equal(calls.at(-1).textReady,true)
  value.update('input','action')
  assert.equal(calls.at(-1).ready,false)
  value.update('input','ready')
  assert.equal(calls.at(-1).ready,true)
  value.close();value.update('runtime','failed')
  assert.equal(calls.at(-1).ready,true)
})
