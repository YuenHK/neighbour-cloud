// Fresh, synthetic origin; notification API is a fixture, no real permission.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
let chromium
try { ({ chromium } = require('@playwright/test')) }
catch { ({ chromium } = require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))) }
;(async () => {
  const browser = await chromium.launch(process.platform === 'win32'
    ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true } : { headless: true })
  const context = await browser.newContext()
  const unexpected = [], errors = []
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await context.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.origin !== 'https://staff-fixture.test') { unexpected.push(url.origin); return route.abort() }
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<section id="panel-usage"></section><script type="module" src="/cloud/admin/staff-notifications.js"></script>' })
    if (url.pathname === '/cloud/admin-request.js') return route.fulfill({ contentType: 'text/javascript', body: 'export const cloudFetch = (...a) => fetch(...a)' })
    if (url.pathname === '/cloud/admin/staff-notifications.js') return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync('deploy/cloud/web/staff-notifications.js', 'utf8') })
    if (url.pathname === '/api/v1/service-desk/notifications') return route.fulfill({ json: route.request().method() === 'GET' ? { public_key: Buffer.alloc(65, 4).toString('base64url') } : { subscription_id: 'a'.repeat(64) } })
    if (url.pathname === '/api/v1/service-desk/notifications/' + 'a'.repeat(64)) return route.fulfill({ json: { removed: true } })
    unexpected.push(url.pathname); return route.abort()
  })
  await context.addInitScript(() => {
    window.mockRequests = 0
    const subscription = { toJSON: () => ({ endpoint: 'https://fcm.googleapis.com/fcm/send/synthetic', keys: { p256dh: 'mock', auth: 'mock' } }), unsubscribe: async () => true }
    let current
    const registration = { pushManager: { getSubscription: async () => current,
      subscribe: async () => { current = subscription; return subscription } } }
    Object.defineProperty(navigator, 'serviceWorker', { value: { register: async () => registration, ready: Promise.resolve(registration) } })
    window.PushManager = class {}
    Object.defineProperty(window, 'Notification', { value: { requestPermission: async () => { window.mockRequests++; return 'granted' } } })
  })
  await page.goto('https://staff-fixture.test/')
  const button = page.getByRole('button', { name: '開啟工作提示' })
  await button.waitFor()
  assert.equal(await page.evaluate(() => window.mockRequests), 0)
  await button.click()
  await page.getByRole('button', { name: '關閉工作提示' }).waitFor()
  assert.equal(await page.evaluate(() => window.mockRequests), 1)
  await page.getByRole('button', { name: '關閉工作提示' }).click()
  await button.waitFor()
  assert.deepEqual(unexpected, []); assert.deepEqual(errors, [])
  console.log(JSON.stringify({ passed: true, opt_in_only: true, unsubscribe: true, real_notifications: false }))
  await browser.close()
})().catch(error => { console.error(error); process.exitCode = 1 })
