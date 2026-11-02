// Chromium receives only synthetic pixels. No live Hub, EP, camera or audio.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))

async function main() {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe', args:['--mute-audio']})
  const context = await browser.newContext({serviceWorkers:'block', permissions:[]})
  const unexpected=[]
  await context.route('**/*', route => {
    const url=new URL(route.request().url())
    if(url.origin==='http://isolated.neighbour.test'&&url.pathname==='/')
      return route.fulfill({contentType:'text/html',body:'<title>Isolated photo regression</title>'})
    if(url.origin==='http://isolated.neighbour.test'&&url.pathname==='/api/v1/patrol/events/synthetic/photo')
      return route.fulfill({contentType:'image/jpeg',body:Buffer.from('synthetic pixels')})
    unexpected.push(url.href);return route.abort()
  })
  try {
    const page = await context.newPage()
    await page.goto('http://isolated.neighbour.test/')
    await page.addScriptTag({content:fs.readFileSync('edge_hub/static/latest-photo.js','utf8')})
    const result=await page.evaluate(async () => {
      const revoked=[],shown=[],jobs=[]
      const urls={createObjectURL:blob=>URL.createObjectURL(blob),revokeObjectURL:url=>{revoked.push(url);URL.revokeObjectURL(url)}}
      const first=URL.createObjectURL(new Blob(['synthetic first']))
      const view=new NeighbourLatestPhoto(first,(_,options)=>new Promise(resolve=>jobs.push({resolve,signal:options.signal})),urls)
      const apply=url=>shown.push(url)
      const response=label=>new Response(new Blob([label],{type:'image/jpeg'}))
      const left=view.load('/api/v1/patrol/events/synthetic/photo?side=left',{},apply)
      const right=view.load('/api/v1/patrol/events/synthetic/photo?side=right',{},apply)
      jobs[1].resolve(response('synthetic right'))
      await right
      jobs[0].resolve(response('synthetic left'))
      await left
      const newest=shown[0]
      const pending=view.load('/api/v1/patrol/events/synthetic/photo?side=event',{},apply)
      view.close()
      jobs[2].resolve(response('synthetic late'))
      await pending
      return {shown:shown.length,aborted:jobs[0].signal.aborted&&jobs[2].signal.aborted,
        revoked:revoked.length,latestReleased:revoked.includes(newest),closed:view.closed}
    })
    assert.deepEqual(result,{shown:1,aborted:true,revoked:2,latestReleased:true,closed:true})
    assert.equal(await page.evaluate(async()=>{
      const view=new NeighbourLatestPhoto(null)
      let shown=false
      const loaded=await view.load('/api/v1/patrol/events/synthetic/photo',{},url=>{shown=url.startsWith('blob:')})
      view.close()
      return loaded&&shown
    }),true)
    assert.deepEqual(unexpected,[])
    console.log(JSON.stringify({real_chromium:true,latest_photo_only:true,close_aborts:true,blob_urls_released:true,native_fetch_mock_origin:true,outside_requests:0,production_writes:0}))
  } finally {await context.close();await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
