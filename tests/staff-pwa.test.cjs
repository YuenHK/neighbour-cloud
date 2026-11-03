const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
test('push notification contains no incoming private text and opens only the staff entry', async () => {
  const listeners = {}, notifications = [], windows = []
  const self = { addEventListener: (name, handler) => { listeners[name] = handler }, registration: {
    showNotification: async (...args) => notifications.push(args),
  }, clients: { openWindow: async url => windows.push(url) } }
  vm.runInNewContext(fs.readFileSync('deploy/cloud/web/staff-sw.js', 'utf8'), { self })
  assert.equal(listeners.fetch, undefined)
  const promises = []
  listeners.push({ data: { json: () => ({ type: 'staff-update', address: 'PRIVATE ADDRESS', care: 'PRIVATE QUOTE', url: 'https://evil.example' }) }, waitUntil: p => promises.push(p) })
  await Promise.all(promises)
  assert.equal(notifications.length, 1)
  assert.equal(JSON.stringify(notifications).includes('PRIVATE'), false)
  assert.equal(notifications[0][1].tag, 'neighbour-workbench')
  listeners.notificationclick({ notification: { close() {} }, waitUntil: p => promises.push(p) })
  await Promise.all(promises)
  assert.deepEqual(windows, ['/?workspace=staff'])
})
test('staff PWA does not use an offline data cache', () => {
  const sw = fs.readFileSync('deploy/cloud/web/staff-sw.js', 'utf8')
  assert.equal(sw.includes('caches.'), false)
  const manifest = JSON.parse(fs.readFileSync('deploy/cloud/web/staff.webmanifest', 'utf8'))
  assert.equal(manifest.start_url, '/?workspace=staff')
  assert.equal(manifest.display, 'standalone')
})

test('notification worker updates immediately without fetching or caching staff data', async () => {
  const listeners = {}, calls = [], pending = []
  const self = { addEventListener: (name, handler) => { listeners[name] = handler },
    skipWaiting: async () => calls.push('skipWaiting'), clients: { claim: async () => calls.push('claim') } }
  vm.runInNewContext(fs.readFileSync('deploy/cloud/web/staff-sw.js', 'utf8'), { self })
  for (const name of ['install', 'activate']) listeners[name]({ waitUntil: promise => pending.push(promise) })
  await Promise.all(pending)
  assert.deepEqual(calls, ['skipWaiting', 'claim'])
  assert.equal(listeners.fetch, undefined)
})
