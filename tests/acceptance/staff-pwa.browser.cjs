// Fresh, synthetic origin; notification API is a fixture, no real permission.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
let chromium
try { ({ chromium } = require('@playwright/test')) }
catch { ({ chromium } = require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))) }
;(async () => {
  const browser = await chromium.launch(process.platform === 'win32'
    ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true } : { headless: true })
  try {
  const context = await browser.newContext()
  const unexpected = [], errors = [], testRequests = [], subscriptions = []
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await context.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.origin !== 'https://staff-fixture.test') { unexpected.push(url.origin); return route.abort() }
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: '<meta charset="utf-8"><section id="panel-usage"></section><button type="button">求助查詢</button><script type="module" src="/cloud/admin/staff-notifications.js"></script>' })
    if (url.pathname === '/cloud/admin-request.js') return route.fulfill({ contentType: 'text/javascript', body: 'export const cloudFetch = (...a) => fetch(...a)' })
    if (url.pathname === '/cloud/admin/staff-notifications.js') return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync('deploy/cloud/web/staff-notifications.js', 'utf8') })
    if (url.pathname === '/api/v1/service-desk/notifications') {
      if (route.request().method() === 'POST') subscriptions.push('subscribed')
      return route.fulfill({ json: route.request().method() === 'GET' ? { public_key: Buffer.alloc(65, 4).toString('base64url') } : { subscription_id: 'a'.repeat(64) } })
    }
    if (url.pathname === '/api/v1/service-desk/notifications/' + 'a'.repeat(64)) return route.fulfill({ json: { removed: true } })
    if (url.pathname === '/api/v1/service-desk/notifications/' + 'a'.repeat(64) + '/test') {
      testRequests.push(route.request().method())
      return route.fulfill({ json: { accepted: true, state: 'push_service_accepted', retry_after_seconds: 60, device_delivery_confirmed: false } })
    }
    if (url.pathname.endsWith('/status')) return route.fulfill({ json: { registered: true, test_retry_after_seconds: testRequests.length ? 60 : 0 } })
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
    let permission=location.search.includes('alreadyGranted')?'granted':location.search.includes('denied')?'denied':'default'
    Object.defineProperty(window, 'Notification', { value: { get permission(){return permission}, requestPermission: async () => { window.mockRequests++; permission='granted';return permission } } })
  })
  await page.goto('https://staff-fixture.test/')
  await page.waitForFunction(()=>document.documentElement.dataset.staffNotifications==='permission-required')
  assert.equal(await page.locator('#panel-usage').innerHTML(),'')
  assert.equal(await page.getByRole('heading',{name:'手機工作提示'}).count(),0)
  assert.equal(await page.evaluate(() => window.mockRequests), 0)
  await page.getByRole('button',{name:'求助查詢'}).evaluate(button=>button.click())
  assert.equal(await page.evaluate(() => window.mockRequests), 0) // No synthetic permission activation.
  await page.getByRole('button',{name:'求助查詢'}).click()
  await page.waitForFunction(()=>document.documentElement.dataset.staffNotifications==='ready')
  assert.equal(await page.evaluate(() => window.mockRequests), 1)
  assert.equal(subscriptions.length, 1)
  await page.evaluate(()=>{window.dispatchEvent(new Event('online'));window.dispatchEvent(new Event('online'));localStorage.setItem('neighbour-push-preference','off')})
  assert.equal(subscriptions.length, 1)
  await page.goto('https://staff-fixture.test/?alreadyGranted=1')
  await page.waitForFunction(()=>document.documentElement.dataset.staffNotifications==='ready')
  assert.equal(await page.evaluate(() => window.mockRequests), 0)
  assert.equal(subscriptions.length, 2) // Latest user instruction makes the app default on; OS grant remains mandatory.
  await page.goto('https://staff-fixture.test/?denied=1')
  await page.getByRole('button',{name:'求助查詢'}).click()
  assert.equal(await page.evaluate(() => window.mockRequests), 0)
  assert.equal(subscriptions.length, 2)
  assert.deepEqual(testRequests, []) // No automatic test notification, old-case delivery or duplicate push.
  assert.deepEqual(unexpected, []); assert.deepEqual(errors, [])
  console.log(JSON.stringify({ passed: true, first_permission_trusted_interaction_only: true, default_restore_if_granted: true, denied_permission_respected: true, no_extra_card: true, no_automatic_test_push: true, real_notifications: false }))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
