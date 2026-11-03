const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path')
const { chromium } = require(path.resolve(process.env.NODE_PATH || '.experiments/optimization-lab-20261029/node/node_modules', 'playwright'))
const origin = 'https://launch-motion.fixture.test', outside = [], results = []
async function main() {
  const browser = await chromium.launch({ headless:true, executablePath:process.platform==='win32'?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined, args:['--mute-audio'] })
  try {
    for (const options of [{viewport:{width:1280,height:900}}, {viewport:{width:390,height:844}}, {viewport:{width:390,height:844},reducedMotion:'reduce'}]) {
      const context = await browser.newContext({ ...options, serviceWorkers:'block', permissions:[] })
      await context.route('**/*', route => {
        const url = new URL(route.request().url())
        if (url.origin !== origin) { outside.push(url.origin); return route.abort() }
        if (url.pathname === '/') {
          const html = fs.readFileSync('deploy/cloud/web/index.html','utf8').replace(/<script[^>]+src="\/cloud\/shell.js"[^>]*><\/script>/,'').replace('</body>','<script type="module" src="/harness.js"></script></body>')
          return route.fulfill({contentType:'text/html',body:html})
        }
        if (url.pathname === '/harness.js') return route.fulfill({contentType:'text/javascript',body:"import {createLaunchScreen} from '/cloud/launch-screen.js';window.launch=createLaunchScreen(document,{onRetry(){},onContinue(){}});launch.start('resident');window.testReady=true"})
        const routes = {'/cloud/shell.css':'shell.css','/cloud/launch-screen.css':'launch-screen.css','/cloud/launch-screen.js':'launch-screen.js','/cloud/mascot.css':'mascot.css','/assets/brand/neighbour-house-apricot-v1.webp':'brand/neighbour-house-apricot-v1.webp','/assets/brand/icon-192.png':'brand/icon-192.png','/assets/brand/favicon-32.png':'brand/favicon-32.png','/assets/brand/apple-touch-icon-180.png':'brand/apple-touch-icon-180.png'}
        const file = routes[url.pathname]
        if (!file) { outside.push(url.pathname); return route.abort() }
        return route.fulfill({contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':file.endsWith('.webp')?'image/webp':'image/png',body:fs.readFileSync(path.join('deploy/cloud/web',file))})
      })
      const page = await context.newPage(), errors=[]
      page.on('pageerror', error=>errors.push(error.message))
      await page.goto(origin); await page.waitForFunction(()=>window.testReady===true)
      const mascot=page.locator('.launch-mascot')
      const initial=await mascot.evaluate(n=>({transform:getComputedStyle(n).transform,left:getComputedStyle(n).left,animation:getComputedStyle(n).animationName}))
      if (options.reducedMotion === 'reduce') assert.equal(initial.animation,'none')
      else await page.waitForFunction(value=>getComputedStyle(document.querySelector('.launch-mascot')).transform!==value,initial.transform)
      assert.equal(await page.locator('#launchProgress').getAttribute('aria-valuenow'),'0')
      await page.evaluate(()=>launch.phase('avatar'))
      assert.equal(await page.locator('#launchProgress').getAttribute('aria-valuenow'),'2')
      if (options.reducedMotion !== 'reduce') await page.waitForFunction(value=>getComputedStyle(document.querySelector('.launch-mascot')).left!==value,initial.left)
      const layout=await page.locator('.launch-progress').boundingBox()
      assert.ok(layout.x>=0 && layout.x+layout.width<=options.viewport.width+1)
      assert.ok(layout.y>=0 && layout.y+layout.height<=options.viewport.height+1)
      await page.evaluate(()=>launch.fail('合成網絡故障，原資料保留。'))
      assert.equal(await mascot.evaluate(n=>getComputedStyle(n).animationName),'none')
      assert.deepEqual(errors,[])
      results.push({width:options.viewport.width,reduced:options.reducedMotion==='reduce',animated:initial.animation!=='none',real_phase_progress:true,failure_paused:true,within_viewport:true})
      await context.close()
    }
    assert.deepEqual(outside,[])
    console.log(JSON.stringify({passed:true,results,provider_mic_audio_EP:0}))
  } finally { await browser.close() }
}
main().catch(error=>{console.error(error);process.exitCode=1})
