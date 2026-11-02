// Real Chromium, synthetic origin and fully intercepted network. No live Hub.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))

async function main() {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe', args:['--mute-audio']})
  const context = await browser.newContext({serviceWorkers:'block', permissions:[]})
  let broken=false, version=1, count=1
  const writes=[], unexpected=[]
  await context.addInitScript(() => {
    // Sound devices and permission prompts must never be used in regression tests.
    window.AudioContext = class { constructor(){this.state='running';this.currentTime=0} resume(){} createOscillator(){return {frequency:{},connect(){},start(){},stop(){}}} createGain(){return {gain:{},connect(){}}} }
    navigator.mediaDevices.getUserMedia=()=>Promise.reject(new Error('isolated test forbids capture'))
  })
  const ids=['operatorKey','caseAlert','caseNewCount','caseActiveCount','caseClosedCount','serviceCases','caseStatus','casesPage','casesPrevious','casesNext']
  const code=fs.readFileSync('edge_hub/static/service-workbench.js','utf8')
  await context.route('**/*', async route=>{
    const request=route.request(), url=new URL(request.url())
    if(url.origin!=='http://isolated.neighbour.test'){unexpected.push(url.origin);return route.abort()}
    if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<meta charset="utf-8">'+ids.map(id=>`<${id==='operatorKey'?'input':'div'} id="${id}"></${id==='operatorKey'?'input':'div'}>`).join('')+`<script>${code}</script>`})
    if(!url.pathname.startsWith('/api/v1/service-desk/requests')){unexpected.push(url.pathname);return route.abort()}
    if(request.method()==='PATCH'){writes.push(request.postDataJSON());version++;return route.fulfill({json:{}})}
    if(broken)return route.fulfill({status:503,json:{}})
    const items=Array.from({length:count},(_,i)=>({id:(i?'b':'a').repeat(32),kind:'general',status:'new',revision:version,message:'虛構測試個案',location:'',contact:'',created_at_ms:i+1}))
    return route.fulfill({json:{items,counts:{new:count},has_more:false,latest_case_number:100000+count}})
  })
  try {
    const page=await context.newPage()
    await page.clock.install()
    await page.goto('http://isolated.neighbour.test/')
    await page.getByText('虛構測試個案',{exact:true}).first().waitFor()
    await page.getByRole('button',{name:'查看及跟進',exact:true}).first().click()
    await page.getByRole('dialog').waitFor()
    const note=page.getByRole('textbox',{name:'跟進內容／回覆居民'}).first()
    await note.fill('未完成草稿')
    broken=true
    await page.clock.runFor(2100)
    await page.getByText(/以下不是最新狀態/).waitFor()
    assert.equal(await page.getByRole('button',{name:'接手跟進'}).first().isDisabled(),true)
    broken=false;count=2
    await page.clock.runFor(2100)
    await page.waitForFunction(()=>document.querySelectorAll('[data-case-id]').length===2)
    assert.equal(await note.inputValue(),'未完成草稿')
    assert.equal(await page.getByRole('button',{name:'接手跟進'}).first().isEnabled(),true)
    const card=page.locator('[data-case-id]').first()
    await card.locator('summary').click()
    await card.getByRole('textbox',{name:'位置／單位',exact:true}).fill('B座12樓A室')
    await card.getByRole('textbox',{name:'更正原因',exact:true}).fill('虛構更正')
    await card.getByRole('button',{name:'儲存更正'}).click()
    await page.waitForFunction(()=>document.querySelector('[data-case-id]').dataset.revision==='2')
    assert.equal(await page.getByRole('dialog').count(),0)
    assert.equal(writes.length,1)
    assert.equal(writes[0].location,'B座12樓A室')
    const pcmCode=fs.readFileSync('airi_overlay/resident-pcm.js','utf8')
    const pcm=await page.evaluate(async code=>{
      const module=await import('data:text/javascript;base64,'+btoa(unescape(encodeURIComponent(code))))
      const nodes=[]
      let controller, started=0
      const ctx={state:'running',currentTime:0,destination:{},resume:async()=>{},
        createBuffer(c,n,r){return {duration:n/r,getChannelData:()=>new Float32Array(n)}},
        createBufferSource(){const node={connect(){},disconnect(){},start(){},stop(){node.stopped=true}};nodes.push(node);return node}}
      const player=new module.ResidentPcm({context:ctx,started:()=>started++,fetcher:async()=>({ok:true,
        body:new ReadableStream({start(c){controller=c}})})})
      player.write('synthetic')
      await new Promise(resolve=>setTimeout(resolve,0))
      controller.enqueue(new TextEncoder().encode('data: '+JSON.stringify({audio:btoa('\0\0'.repeat(2048))})+'\n\n'))
      await new Promise(resolve=>setTimeout(resolve,0))
      const beforeDone=started===1
      player.cancel()
      controller.enqueue(new TextEncoder().encode('data: {"done":true}\n\n'));controller.close()
      await player.chain
      return {beforeDone, stopped:nodes[0]?.stopped===true}
    },pcmCode)
    assert.deepEqual(pcm,{beforeDone:true,stopped:true})
    assert.deepEqual(unexpected,[])
    console.log(JSON.stringify({real_chromium:true,pcm_first_chunk_before_end:true,pcm_cancel_stops:true,offline_fail_recover:true,draft_preserved:true,correction_mocked:true,outside_requests:unexpected.length,production_writes:0}))
  } finally {await context.close();await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
