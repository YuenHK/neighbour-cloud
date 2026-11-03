// Real IndexedDB, synthetic notification sink; no permission, push service or private data.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
let chromium
try { ({ chromium } = require('@playwright/test')) }
catch { ({ chromium } = require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))) }
;(async () => {
  const browser = await chromium.launch(process.platform === 'win32'
    ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true } : { headless: true })
  try {
    const context = await browser.newContext({ serviceWorkers: 'block' })
    const page = await context.newPage(), outside = []
    await context.route('**/*', route => {
      if (route.request().url() !== 'https://push-dedup.test/') { outside.push(route.request().url()); return route.abort() }
      return route.fulfill({ contentType: 'text/html', body: '<title>Synthetic push storage test</title>' })
    })
    await page.goto('https://push-dedup.test/')
    const result = await page.evaluate(async code => {
      const shown = []
      function worker(fail = false) {
        const handlers = {}, fake = { indexedDB,
          addEventListener: (type, callback) => { handlers[type] = callback },
          registration: { showNotification: async (...args) => {
            if (fail) throw new Error('synthetic display failure')
            shown.push(args)
          } }, clients: { openWindow: async () => {} } }
        new Function('self', code)(fake)
        return async (id, type = 'staff-update') => {
          let pending
          handlers.push({ data: { json: () => ({ type, notification_id: id, address: 'PRIVATE-DO-NOT-SHOW' }) }, waitUntil: promise => { pending = promise } })
          await pending
        }
      }
      const one = worker(), two = worker()
      await Promise.all([one('a'.repeat(64)), two('a'.repeat(64))])
      const concurrent = shown.length
      await worker()('a'.repeat(64)) // Fresh worker, same durable database.
      const restart = shown.length
      await worker()('b'.repeat(64), 'staff-test')
      const testTitle = shown.at(-1)[0], testTag = shown.at(-1)[1].tag
      await worker()('invalid')
      let failed = false
      try { await worker(true)('c'.repeat(64)) } catch { failed = true }
      await worker()('c'.repeat(64))
      const retry = shown.length
      const send = worker()
      for (let i = 0; i < 130; i++) await send((i + 1000).toString(16).padStart(64, '0'))
      const rows = await new Promise((resolve, reject) => {
        const request = indexedDB.open('neighbour-notification-dedup', 1)
        request.onsuccess = () => {
          const db = request.result, read = db.transaction('seen').objectStore('seen').getAll()
          read.onsuccess = () => { db.close(); resolve(read.result) }
          read.onerror = reject
        }
        request.onerror = reject
      })
      return { concurrent, restart, testTitle, testTag, failed, retry, stored: rows.length,
        technicalOnly: rows.every(row => Object.keys(row).sort().join(',') === 'at,id'),
        noPrivateText: !JSON.stringify(shown).includes('PRIVATE-DO-NOT-SHOW'),
        noRenotify: shown.every(row => row[1].renotify === false) }
    }, fs.readFileSync('deploy/cloud/web/staff-sw.js', 'utf8'))
    assert.equal(result.concurrent, 1); assert.equal(result.restart, 1)
    assert.equal(result.testTitle, '鄰伴・測試工作提示'); assert.equal(result.testTag, 'neighbour-workbench-test')
    assert.equal(result.failed, true); assert.equal(result.retry, 3)
    assert.equal(result.stored, 128); assert(result.technicalOnly && result.noPrivateText && result.noRenotify)
    assert.deepEqual(outside, [])
    console.log(JSON.stringify({ passed: true, ...result, real_notifications: 0, real_permissions: 0 }))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
