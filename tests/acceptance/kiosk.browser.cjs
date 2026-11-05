const assert = require('node:assert/strict')
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const { chromium, webkit } = require('playwright')
const root = path.resolve(__dirname, '../..')
const web = path.join(root, 'deploy/cloud/web')
const html = '<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><title>Kiosk isolated fixture</title><link rel="stylesheet" href="/kiosk.css"><style>body{font:16px sans-serif;margin:16px}button,a{font:inherit}section{padding:16px;border:1px solid #ddd;border-radius:16px}*{box-sizing:border-box}</style>' + fs.readFileSync(path.join(web, 'kiosk.html'), 'utf8') + '<script type="module" src="/kiosk.js"></script>'

async function main() {
  const server = http.createServer((req, res) => {
    const name = req.url === '/kiosk.js' ? 'kiosk.js' : req.url === '/kiosk.css' ? 'kiosk.css' : ''
    res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html')
    res.end(name ? fs.readFileSync(path.join(web, name)) : html)
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = 'http://127.0.0.1:' + server.address().port
  const results = []
  try {
    for (const [name, engine] of [['chromium', chromium], ['webkit', webkit]]) {
      const browser = await engine.launch(name === 'chromium' && process.platform === 'win32'
        ? { headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--mute-audio'] }
        : { headless: true })
      try {
        for (const width of [390, 1280]) {
          const context = await browser.newContext({ viewport: { width, height: 844 }, reducedMotion: 'reduce' })
          let outside = 0
          await context.route('**/*', route => {
            if (new URL(route.request().url()).origin !== origin) { outside++; return route.abort() }
            return route.continue()
          })
          await context.addInitScript(() => {
            window.kioskCalls = { query: 0, media: 0, audio: 0, full: 0 }
            Object.defineProperty(navigator, 'permissions', { configurable: true, value: { query: async ({ name }) => { window.kioskCalls.query++; return { state: name === 'camera' ? 'prompt' : 'granted' } } } })
            Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: () => { window.kioskCalls.media++; throw Error('real device prohibited') } } })
            window.AudioContext = function () { window.kioskCalls.audio++; throw Error('audio prohibited') }
            Element.prototype.requestFullscreen = async function () { window.kioskCalls.full++ }
          })
          const page = await context.newPage()
          const errors = []
          page.on('pageerror', error => errors.push(error.message))
          await page.goto(origin, { waitUntil: 'load' })
          assert.equal(await page.evaluate(() => window.kioskCalls.query), 0)
          await page.locator('summary').click()
          await page.locator('#kioskCheck').click()
          await page.waitForFunction(() => !document.getElementById('kioskChecks').hidden)
          assert.equal(await page.locator('#kioskChecks dt').count(), 7)
          await page.locator('#kioskFullscreen').click()
          assert.deepEqual(await page.evaluate(() => window.kioskCalls), { query: 2, media: 0, audio: 0, full: 1 })
          assert.equal(await page.locator('#kioskOpenResident').getAttribute('href'), '/?workspace=resident')
          assert.equal(await page.locator('#kioskOpenResident').getAttribute('target'), '_top')
          const geometry = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
            overflow: [...document.querySelectorAll('*')].filter(node => node.getBoundingClientRect().right > innerWidth)
              .map(node => ({ tag: node.tagName, id: node.id, right: node.getBoundingClientRect().right })),
            content: [...document.querySelectorAll('*')].filter(node => node.scrollWidth > node.clientWidth+2)
              .map(node => ({ tag: node.tagName, id: node.id, client: node.clientWidth, scroll: node.scrollWidth })) }))
          assert.ok(geometry.scroll <= geometry.width, name+':'+JSON.stringify(geometry))
          for (const id of ['kioskCheck', 'kioskFullscreen', 'kioskOpenResident']) {
            assert.ok((await page.locator('#' + id).boundingBox()).height >= 44)
          }
          assert.deepEqual(errors, [])
          assert.equal(outside, 0)
          results.push({ engine: name, width, passed: true, media_audio_requests: 0, external_requests: 0 })
          await context.close()
        }
      }
      finally { await browser.close() }
    }
  }
  finally { await new Promise(resolve => server.close(resolve)) }
  console.log(JSON.stringify({ passed: true, scenarios: results, real_devices_used: false }))
}
main().catch(error => { console.error(error); process.exitCode = 1 })
