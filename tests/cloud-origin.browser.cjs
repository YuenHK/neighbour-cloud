// Isolated browser engines, fake credentials and responses; no real API/audio.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
let playwright
try { playwright = require('@playwright/test') }
catch { playwright = require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright')) }
const origin = 'https://origin-fixture.test'
async function run(name) {
  const browser = await playwright[name].launch(name === 'chromium' && process.platform === 'win32'
    ? { headless:true, executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe', args:['--mute-audio'] }
    : {headless:true})
  const context = await browser.newContext({serviceWorkers:'block',permissions:[]})
  const rows = [], unexpected = []
  await context.route('**/*', async route => {
    const req=route.request(), url=new URL(req.url())
    if(url.origin!==origin){unexpected.push(url.href);return route.abort()}
    if(url.pathname==='/private/page')return route.fulfill({contentType:'text/html',headers:{'Referrer-Policy':'no-referrer'},body:'<title>Origin fixture</title>'})
    if(url.pathname==='/transport.js')return route.fulfill({contentType:'text/javascript',body:fs.readFileSync('airi_overlay/cloud-transport.js','utf8')})
    if(req.method()==='POST'){
      const headers=await req.allHeaders()
      rows.push({path:url.pathname,origin:headers.origin||null,referer:headers.referer||null})
      return route.fulfill({status:headers.origin===origin?200:403,json:{accepted:headers.origin===origin}})
    }
    unexpected.push(url.pathname);return route.abort()
  })
  try {
    const page=await context.newPage();await page.goto(origin+'/private/page?draft=synthetic-private')
    const result=await page.evaluate(async()=>{
      const {createCloudTransport}=await import('/transport.js')
      const transport=createCloudTransport({origin:location.origin,tokenProvider:()=>({token:'header.public-synthetic.signature',expiresAtMs:Date.now()+3600000})})
      const codes=[]
      for(const target of ['/api/v1/resident/chat','/api/v1/resident/transcription','/_audio/v1/audio/resident-stream']){
        const response=await transport.fetch(target,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
        codes.push(response.status)
      }
      transport.clearAuth();return codes
    })
    console.log(JSON.stringify({engine:name,statuses:result,headers:rows,real_provider_requests:0,mic_or_playback:0}))
    assert.deepEqual(result,[200,200,200]);assert.deepEqual(unexpected,[])
    assert.ok(rows.every(row=>row.origin===origin))
    assert.ok(rows.every(row=>row.referer===null||row.referer===origin+'/'))
    assert.ok(rows.every(row=>!String(row.referer).includes('private')))
  } finally {await context.close();await browser.close()}
}
;(async()=>{for(const name of ['chromium','webkit'])await run(name)})().catch(error=>{console.error(error);process.exitCode=1})
