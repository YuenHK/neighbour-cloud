// Real shell, isolated synthetic origin. No actual providers or capture.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const {chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
const origin='https://startup.neighbour.test'
const token='header.'+Buffer.from(JSON.stringify({role:'resident',exp:Math.floor(Date.now()/1000)+3600})).toString('base64url')+'.signature'
async function main(){
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']})
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]})
 await context.route('**/*',async route=>{
  const u=new URL(route.request().url());assert.equal(u.origin,origin)
  if(u.pathname==='/login-config')return route.fulfill({json:{public_resident:true}})
  if(u.pathname==='/api/v1/resident/access')return route.fulfill({json:{token}})
  if(u.pathname==='/api/v1/resident/session')return route.fulfill({json:{authenticated:true,role:'resident',storage_acceptance:false}})
  if(u.pathname==='/cloud/resident')return route.fulfill({contentType:'text/html',body:'<p>合成居民畫面</p><script>parent.postMessage({type:"neighbour-service-stage",state:"mounted"},location.origin);parent.postMessage({type:"estate-assistant-ready"},location.origin)</script>'})
  const files={'/':'deploy/cloud/web/index.html','/cloud/launch-screen.js':'deploy/cloud/web/launch-screen.js','/cloud/launch-screen.css':'deploy/cloud/web/launch-screen.css','/cloud/shell.js':'deploy/cloud/web/shell.js','/cloud/shell.css':'deploy/cloud/web/shell.css','/cloud/cloud-session.js':'airi_overlay/cloud-session.js','/cloud/cloud-frame.js':'airi_overlay/cloud-frame.js'}
  if(files[u.pathname])return route.fulfill({contentType:u.pathname.endsWith('.js')?'text/javascript':u.pathname.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(files[u.pathname])})
  throw Error('Unexpected '+u.pathname)
 })
 try{
  const page=await context.newPage();await page.goto(origin)
  await page.frameLocator('iframe').getByText('合成居民畫面').waitFor({state:'attached'})
  assert.equal(await page.locator('#launchScreen').isVisible(),true)
  assert.equal(await page.locator('#service iframe').getAttribute('inert'),'')
  const child=page.frames().find(frame=>frame.url().includes('/cloud/resident'))
  await child.evaluate(()=>parent.postMessage({type:'neighbour-readiness',area:'resident',checks:{interface:'ready',runtime:'ready',avatar:'ready',input:'pending'},textReady:true,ready:false},location.origin))
  await page.getByText(/仍在核對：語音收音/).waitFor()
  assert.equal(await page.locator('#launchScreen').isVisible(),true)
  await child.evaluate(()=>parent.postMessage({type:'neighbour-readiness',area:'resident',checks:{interface:'ready',runtime:'ready',avatar:'ready',input:'ready'},textReady:true,ready:true},location.origin))
  await page.locator('#launchScreen').waitFor({state:'hidden'})
  assert.equal(await page.locator('#service iframe').getAttribute('inert'),null)
  console.log(JSON.stringify({avatar_alone_does_not_reveal:true,input_pending_keeps_launch:true,all_checks_reveal:true,production_requests:0}))
 }finally{await context.close();await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
