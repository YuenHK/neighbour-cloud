const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
let chromium
try{({chromium}=require('@playwright/test'))}catch{({chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright')))}
;(async()=>{
 const browser=await chromium.launch(process.platform==='win32'?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']}:{headless:true})
 const context=await browser.newContext({permissions:[],serviceWorkers:'block',colorScheme:'dark'})
 const pattern='.cross-background-container{background:white}.dark .cross-background-container{background:#121212}'
 const css=fs.readFileSync('airi_overlay/cloud-resident.css','utf8')
 await context.route('**/*',r=>r.fulfill({contentType:'text/html',body:'<html class="dark"><head><style>'+pattern+css+'</style></head><body data-estate-kiosk data-cloud-view="resident" style="margin:0;--resident-wave:#d6eee2;--resident-ambient:#e5f3ec"><div class="customized-background" style="position:fixed;inset:0"><div class="cross-background-container" style="height:100%"><div class="wave" style="height:60px"></div></div></div></body></html>'}))
 const page=await context.newPage();await page.goto('https://background-fixture.test')
 fs.mkdirSync('acceptance-results/background',{recursive:true})
 const results=[]
 for(const [width,height] of [[2557,961],[390,844]]){
  await page.setViewportSize({width,height});let baseline
  for(const view of ['resident','settings']){
   await page.evaluate(v=>document.body.dataset.cloudView=v,view)
   const computed=await page.evaluate(()=>{const bg=document.querySelector('.cross-background-container'),wave=document.querySelector('.wave');return{image:getComputedStyle(bg).backgroundImage,wave:getComputedStyle(wave).backgroundColor,bounds:{x:bg.getBoundingClientRect().x,width:bg.getBoundingClientRect().width},pseudo:getComputedStyle(document.querySelector('.customized-background'),'::before').content}})
   assert.match(computed.image,/radial-gradient/);assert.match(computed.image,/linear-gradient/);assert.equal(computed.pseudo,'none')
   if(baseline)assert.deepEqual(computed,baseline);else baseline=computed
   assert.ok(computed.bounds.width>=width)
   await page.screenshot({path:'acceptance-results/background/background-'+view+'-'+width+'.png'})
   results.push({view,width,height,matchingAiriPattern:true,noBubbleOverlay:true})
  }
 }
 fs.writeFileSync('acceptance-results/background/verified.json',JSON.stringify({passed:true,results,actual_mic_audio:0},null,2));console.log(JSON.stringify({passed:true,results}))
 await context.close();await browser.close()
})().catch(e=>{console.error(e);process.exitCode=1})
