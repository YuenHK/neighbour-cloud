const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium, webkit } = require('playwright')
const web = path.resolve('deploy/cloud/web')
const area = path.resolve('.runtime/free-paths-20261105')
fs.mkdirSync(area, { recursive: true })
const origin = 'https://isolated.planner.test'
const full = fs.readFileSync(path.join(web, 'robots.html'), 'utf8')
const fragment = full.slice(full.indexOf('<section class="service-card patrol-planner">'))
const html = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>*{box-sizing:border-box}body{font:16px sans-serif;margin:16px;color:#16443b}button,input,select{font:inherit}button,input,select{border:1px solid #cadbd3;border-radius:10px;padding:10px}.service-card{background:#f4f8f5;padding:18px;border-radius:18px}</style><link rel="stylesheet" href="/planner.css">' + fragment + '<script type="module" src="/planner.js"></script>'

async function main() {
  const results = []
  for (const [engineName, engine] of [['chromium', chromium], ['webkit', webkit]]) {
    const browser = await engine.launch(engineName === 'chromium' && process.platform === 'win32'
      ? { headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--mute-audio'] }
      : { headless: true })
    try {
      for (const width of [390, 1280]) {
        const context = await browser.newContext({ viewport: { width, height: 900 }, permissions: [], serviceWorkers: 'block' })
        let stored = { revision: 0, map: null }, requests = 0, outside = 0, mutations = 0
        const errors = []
        await context.route('**/*', async route => {
          const url = new URL(route.request().url())
          if (url.origin !== origin) { outside++; return route.abort() }
          if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
          if (url.pathname === '/planner.js') return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(path.join(web, 'patrol-planner.js')) })
          if (url.pathname === '/planner.css') return route.fulfill({ contentType: 'text/css', body: fs.readFileSync(path.join(web, 'robots.css')) })
          if (url.pathname === '/cloud/admin-request.js') return route.fulfill({ contentType: 'text/javascript', body: 'export const cloudFetch=(...args)=>fetch(...args)' })
          if (url.pathname.startsWith('/api/v1/service-desk/patrol-planning')) {
            requests++
            if (url.pathname.endsWith('/offline-kit.zip')) return route.fulfill({ contentType: 'application/zip', body: Buffer.from('PK-isolated-fixture') })
            const data = route.request().postDataJSON()
            if (url.pathname.endsWith('/simulate')) return route.fulfill({ json: { path: [data.start, { x: data.goal.x, y: data.start.y }, data.goal], distance_m: 4, hardware_commands: 0, execution_enabled: false } })
            if (route.request().method() === 'PUT') {
              if (data.revision !== stored.revision) return route.fulfill({ status: 409, json: { detail: '版本衝突；草稿保留。' } })
              stored = { revision: stored.revision + 1, map: data.map }; mutations++
            }
            return route.fulfill({ json: stored })
          }
          throw Error('Unexpected isolated request ' + url.pathname)
        })
        const page = await context.newPage()
        page.on('pageerror', error => errors.push(error.message))
        await page.goto(origin)
        assert.equal(requests, 0, 'closed planner must not fetch')
        await page.locator('#patrolPlanning > summary').click()
        await page.waitForFunction(() => document.getElementById('patrolPlanStatus').textContent.includes('尚未儲存'))
        const floor = []
        for (let y = 0; y < 16; y++) for (let x = 0; x < 20; x++) floor.push({ x, y })
        await page.locator('#patrolMapImport').setInputFiles({ name: 'synthetic.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ format: 'neighbour-survey-map-v1', map: { name: '合成測試區', width: 20, height: 16, cell_cm: 50, clearance_cm: 35, floor, blocked: [] } })) })
        await page.waitForFunction(() => document.getElementById('patrolPlanStatus').textContent.includes('已匯入'))
        for (const [mode, x, y] of [['start', 2, 2], ['goal', 6, 6]]) {
          await page.locator('#patrolPaint').selectOption(mode)
          const box = await page.locator('#patrolMapCanvas').boundingBox()
          await page.mouse.click(box.x + box.width*(x+.5)/20, box.y + box.height*(y+.5)/16)
        }
        await page.locator('#patrolProfile').selectOption('s1')
        assert.match(await page.locator('#patrolProfileNotice').textContent(), /Lab.*SBus/)
        await page.locator('#patrolPlan').click()
        await page.waitForFunction(() => document.getElementById('patrolPlanStatus').textContent.includes('沒有連線或移動'))
        assert.equal(mutations, 0, 'simulate must not save')
        await page.locator('#patrolMapSave').click()
        await page.waitForFunction(() => document.getElementById('patrolPlanStatus').textContent.includes('第 1 版'))
        assert.equal(stored.map.name, '合成測試區')
        stored.revision++ // Another staff browser saves first.
        await page.locator('#patrolMapName').fill('本頁新草稿')
        await page.locator('#patrolMapSave').click()
        await page.waitForFunction(() => document.getElementById('patrolPlanStatus').textContent.includes('衝突'))
        assert.equal(await page.locator('#patrolMapName').inputValue(), '本頁新草稿')
        assert.equal(mutations, 1)
        await page.locator('summary', { hasText: 'S1 接入與定位準備' }).click()
        const download = page.waitForEvent('download')
        await page.locator('#patrolOfflineKit').click()
        assert.equal((await download).suggestedFilename(), 'neighbour-patrol-review-kit.zip')
        await page.waitForFunction(() => document.getElementById('patrolPlanStatus').textContent.includes('沒有開啟串口'))
        assert.equal(mutations, 1, 'downloading code must not change map or contact hardware')
        await page.screenshot({ path: path.join(area, `planner-${engineName}-${width}.png`), fullPage: true })
        const overflow = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(item => item.getBoundingClientRect().right > innerWidth+1).map(item => [item.tagName, item.id, item.className, item.getBoundingClientRect().width]))
        assert.deepEqual(overflow, [])
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
        assert.deepEqual(errors, [])
        assert.equal(outside, 0)
        await page.screenshot({ path: path.join(area, `planner-${engineName}-${width}.png`), fullPage: true })
        results.push({ engine: engineName, width, passed: true, outside, writes: mutations, real_hardware_commands: 0 })
        await context.close()
      }
    } finally { await browser.close() }
  }
  fs.writeFileSync(path.join(area, 'PLANNER-ISOLATED-UI.json'), JSON.stringify({ passed: true, results }, null, 2))
  console.log(JSON.stringify({ passed: true, cases: results.length }))
}
main().catch(error => { console.error(error); process.exitCode = 1 })
