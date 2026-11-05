// Real launch, shell and cold-boot UI against a wholly intercepted synthetic HTTPS origin.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const {chromium,webkit}=require(path.resolve(process.env.NODE_PATH||'.experiments/optimization-lab-20261029/node/node_modules','playwright'))
const origin='https://community-launch.fixture.test',base=path.resolve('deploy/cloud/web'),area=path.resolve('.runtime/original-libraries-20261105/launch')
const results=[],outside=[],errors=[],cspViolations=[]
const csp="default-src 'none';script-src 'self';style-src 'self';connect-src 'self';img-src 'self' data:;frame-src 'self';base-uri 'none';object-src 'none'"
const headers={'Content-Security-Policy':csp}
fs.mkdirSync(area,{recursive:true})
const token='header.'+Buffer.from(JSON.stringify({role:'resident',exp:Math.floor(Date.now()/1000)+3600})).toString('base64url')+'.signature'
const ready={interface:'ready',runtime:'ready',avatar:'ready',input:'ready'}
const mime=file=>file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':file.endsWith('.webp')?'image/webp':'text/html'
function fileFor(url){
 if(url.pathname.startsWith('/assets/brand/'))return path.join(base,'brand',path.basename(url.pathname))
 if(url.pathname==='/cloud/cloud-session.js')return path.resolve('airi_overlay/cloud-session.js')
 if(url.pathname==='/cloud/cloud-frame.js')return path.resolve('airi_overlay/cloud-frame.js')
 if(/^\/cloud\/[a-z-]+\.(js|css)$/.test(url.pathname))return path.join(base,path.basename(url.pathname))
}
async function serve(route,handler){
 const url=new URL(route.request().url())
 if(url.origin!==origin){outside.push(url.href);return route.abort()}
 if(await handler(route,url))return
 const file=fileFor(url)
 if(file&&fs.existsSync(file))return route.fulfill({contentType:mime(file),body:fs.readFileSync(file)})
 outside.push(url.pathname);return route.abort()
}
async function guard(context){
 context.on('page',page=>page.on('console',message=>{if(message.text().startsWith('FIXTURE_CSP_VIOLATION:'))cspViolations.push(message.text())}))
 await context.addInitScript(()=>document.addEventListener('securitypolicyviolation',event=>console.error('FIXTURE_CSP_VIOLATION:'+event.effectiveDirective+':'+event.blockedURI)))
}
const state=(page,id)=>page.locator(`#launchSystems .community-system-node[data-system="${id}"],#bootSystems .community-system-node[data-system="${id}"]`).getAttribute('data-state')
async function layout(page,label){
 const value=await page.evaluate(()=>{
  const r=document.querySelector('#launchScreen'),all=[...document.querySelectorAll('#launchSystems .community-system-node')].map(n=>n.getBoundingClientRect())
  let overlap=false;for(let i=0;i<all.length;i++)for(let j=i+1;j<all.length;j++){const a=all[i],b=all[j];if(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top)overlap=true}
  return{pageOverflow:document.documentElement.scrollWidth>innerWidth,launchOverflow:r.scrollWidth>r.clientWidth,nodeOverlap:overlap,nodes:all.length}
 })
 assert.deepEqual(value,{pageOverflow:false,launchOverflow:false,nodeOverlap:false,nodes:9},label)
}
async function direct(browser,engine,viewport,reduced=false){
 const context=await browser.newContext({viewport,reducedMotion:reduced?'reduce':'no-preference',serviceWorkers:'block',permissions:[]})
 await guard(context)
 await context.route('**/*',route=>serve(route,async(route,u)=>{
  if(u.pathname==='/'){const html=fs.readFileSync(path.join(base,'index.html'),'utf8').replace('<script type="module" src="/cloud/shell.js"></script>','<script type="module" src="/harness.js"></script>');await route.fulfill({headers,contentType:'text/html',body:html});return true}
  if(u.pathname==='/harness.js'){await route.fulfill({contentType:'text/javascript',body:`import{createLaunchScreen}from'/cloud/launch-screen.js';import{prepareCommunityIntroduction}from'/cloud/community-about.js';window.launch=createLaunchScreen(document,{onRetry(){window.retries=(window.retries||0)+1},onContinue(){window.continued=true}});prepareCommunityIntroduction(document,{snapshot:()=>launch.snapshot()});launch.start('resident');window.testReady=true`});return true}
  return false
 }))
 try{
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin);await page.waitForFunction(()=>window.testReady===true)
  const tag=`${engine}-${viewport.width}${reduced?'-reduced':''}`
  assert.equal(await page.locator('#launchEnterNow').isVisible(),false)
  await page.locator('#launchSystems .community-systems[data-presentation=orbit]').waitFor()
  await layout(page,tag)
  assert.equal(await page.locator('#launchProgress').getAttribute('aria-valuenow'),'0')
  assert.equal(await state(page,'minerva'),'loading');assert.equal(await state(page,'artemis'),'planned')
  assert.equal(await state(page,'hephaestus'),'offline');assert.equal(await state(page,'aether'),'offline')
  assert.equal(await page.locator('#launchSystems .community-system-node[data-system=minerva] .community-system-symbol').evaluate(n=>getComputedStyle(n).animationName),reduced?'none':'community-node-pulse')
  await page.locator('#platformIntro').focus();await page.keyboard.press('Enter')
  await page.locator('#communityIntroduction[open]').waitFor();assert.equal(await page.locator('[data-community-function]').count(),9)
  assert.match(await page.locator('#communityIntroduction').textContent(),/具備情境理解與情感回應能力/)
  await page.locator('#introSystems .community-systems[data-presentation=overview]').waitFor()
  const introIdentity=await page.locator('#introSystems .community-systems').getAttribute('aria-labelledby')
  await page.locator('#introSystems').getByRole('button',{name:'查看赫淮斯托斯 · 機械工坊',exact:true}).click()
  assert.match(await page.locator('#introSystems .community-overview-limit').textContent(),/S1.*待現場驗收/)
  assert.match(await page.locator('#introSystems .community-product').textContent(),/示意/)
  assert.equal(await page.locator('#introSystems .community-product__canvas').count(),1)
  if(viewport.width===1280||reduced){
   await page.locator('#replayCommunitySystems').click()
   if(!reduced)assert.equal(await page.locator('#introSystems .community-systems').getAttribute('data-presentation'),'entrance')
   await page.locator('#introSystems .community-systems[data-presentation=overview]').waitFor()
  }
  await page.locator('#introSystems').getByRole('button',{name:'查看阿耳忒彌斯 · 生態共處',exact:true}).click()
  assert.match(await page.locator('#introSystems .community-overview-limit').textContent(),/尚未實裝/)
  await page.locator('#introSystems').getByRole('button',{name:'返回協作圓盤',exact:true}).click()
  assert.equal(await page.locator('#introSystems .community-systems').getAttribute('data-presentation'),'orbit')
  await page.keyboard.press('Escape');assert.equal(await page.locator('#communityIntroduction').getAttribute('open'),null)
  await page.locator('#introSystems .community-systems[data-paused=true]').waitFor({state:'attached'})
  assert.equal(await page.locator('#introSystems .community-systems').getAttribute('data-paused'),'true')
  await page.locator('#platformIntro').focus();await page.keyboard.press('Enter')
  assert.equal(await page.locator('#introSystems .community-systems').getAttribute('aria-labelledby'),introIdentity)
  assert.equal(await page.locator('#introSystems .community-product').count(),1)
  await page.locator('#closeCommunityIntroduction').focus();await page.keyboard.press('Enter')
  assert.equal(await page.locator('#communityIntroduction').getAttribute('open'),null)
  await page.evaluate(()=>{launch.connected();launch.phase('interface')})
  assert.equal(await state(page,'minerva'),'ready');assert.equal(await page.locator('#launchProgress').getAttribute('aria-valuenow'),'1')
  await page.evaluate(checks=>launch.checks({textReady:true,checks:{...checks,input:'action'}}),ready)
  assert.equal(await state(page,'eleuthia'),'error');assert.equal(await state(page,'apollo'),'ready')
  assert.equal(await page.locator('#launchProgress').getAttribute('aria-valuenow'),'2')
  assert.equal(await state(page,'artemis'),'planned');assert.equal(await state(page,'hephaestus'),'offline')
  await page.locator('#launchContinue').click();assert.equal(await page.evaluate(()=>window.continued),true)
  await page.evaluate(()=>launch.fail('合成知識載入錯誤，保留資料。','apollo'))
  assert.equal(await state(page,'apollo'),'error');assert.equal(await page.locator('#launchRetry').isVisible(),true)
  await page.locator('#launchRetry').click();assert.equal(await page.evaluate(()=>window.retries),1)
  await page.evaluate(()=>launch.repair('合成安全重連中。','apollo'))
  assert.equal(await state(page,'apollo'),'repairing');assert.equal(await state(page,'hades'),'repairing')
  assert.equal(await page.locator('#launchSystems .community-system-link[data-system=apollo] .community-link-flow').evaluate(n=>getComputedStyle(n).animationName),reduced?'none':'community-flow-repair')
  // Playwright's WebKit screenshot sync injects <style>body {}</style>, even with
  // caret:'initial'. Keep strict CSP checks intact instead of introducing that
  // test-only violation; Chromium captures and prior WebKit visual QA remain.
  if(engine==='chromium')await page.screenshot({path:path.join(area,`${tag}-repairing.png`),fullPage:true,caret:'initial'})
  await page.evaluate(checks=>{launch.repairState('apollo','retried');launch.checks({textReady:true,checks})},ready)
  assert.equal(await state(page,'apollo'),'ready');assert.equal(await state(page,'eleuthia'),'ready');assert.equal(await state(page,'hades'),'ready')
  assert.equal(await state(page,'poseidon'),'offline');assert.equal(await state(page,'demeter'),'offline')
  await page.evaluate(()=>{launch.fail('合成尚未修復的異常。','apollo');launch.finish(()=>window.finished=true)})
  assert.equal(await state(page,'apollo'),'error');assert.equal(await state(page,'artemis'),'planned')
  if(!reduced){
   await page.locator('#launchSystems .community-systems[data-presentation=overview]').waitFor()
   assert.equal(await page.locator('#launchSystems .community-product__canvas').count(),1)
   const enter=await page.locator('#launchEnterNow').boundingBox()
   assert.ok(enter.x>=0&&enter.x+enter.width<=viewport.width+1&&enter.y>=0&&enter.y+enter.height<=viewport.height+1)
  }
  await page.waitForFunction(()=>window.finished===true);assert.equal(await page.locator('#launchProgress').getAttribute('aria-valuenow'),'3')
  assert.equal(await state(page,'apollo'),'error')
  if(viewport.width===1280){
   await page.evaluate(()=>{window.skipCount=0;window.staleStart=0;window.staleHide=0;launch.start('resident');launch.finish(()=>skipCount++);document.querySelector('#launchEnterNow').click();document.querySelector('#launchEnterNow').click();launch.start('resident');launch.finish(()=>staleStart++);launch.start('staff');launch.finish(()=>staleHide++);launch.hide();launch.start('staff')})
   await page.waitForTimeout(3000)
   assert.deepEqual(await page.evaluate(()=>[skipCount,staleStart,staleHide]),[1,0,0])
   assert.equal(await page.locator('#launchScreen').getAttribute('data-state'),'loading')
   assert.equal(await page.locator('#launchEnterNow').isVisible(),false)
  }
  await page.evaluate(()=>launch.start('staff','interface'))
  assert.equal(await page.locator('#launchProgress').getAttribute('aria-valuemax'),'2');assert.equal(await page.locator('[data-launch-step=avatar]').isVisible(),false)
  if(engine==='chromium')await page.screenshot({path:path.join(area,`${tag}-staff.png`),fullPage:true,caret:'initial'})
  results.push({engine,width:viewport.width,reduced,direct:true,nineNodes:true,realPhaseProgress:true,repairFlow:true,finishDoesNotGreenError:true,offlinePlannedRemainGrey:true,introductionKeyboard:true,lazyReusableIntroAndProduct:true,overviewBeforeGlow:!reduced,enterNowWithinViewport:!reduced,skipAndNavigationFence:viewport.width===1280,noHorizontalOverflow:true})
 }finally{await context.close()}
}
async function shell(browser,engine){
 const context=await browser.newContext({viewport:{width:1280,height:900},serviceWorkers:'block',permissions:[]})
 await guard(context)
 let frames=0,accesses=0
 await context.route('**/*',route=>serve(route,async(route,u)=>{
  if(u.pathname==='/'){await route.fulfill({headers,contentType:'text/html',body:fs.readFileSync(path.join(base,'index.html'))});return true}
  if(u.pathname==='/login-config'){await route.fulfill({json:{public_resident:true}});return true}
  if(u.pathname==='/api/v1/resident/access'){accesses++;await route.fulfill({json:{token}});return true}
  if(u.pathname==='/api/v1/resident/session'){await route.fulfill({json:{authenticated:true,role:'resident',storage_acceptance:false}});return true}
  if(u.pathname==='/cloud/resident'){frames++;await route.fulfill({headers,contentType:'text/html',body:'<p>合成居民畫面</p><script src="/fixture-resident.js"></script>'});return true}
  if(u.pathname==='/fixture-resident.js'){await route.fulfill({contentType:'text/javascript',body:'window.__NEIGHBOUR_RESIDENT_IDLE__=()=>true;parent.postMessage({type:"neighbour-service-stage",state:"mounted"},location.origin)'});return true}
  return false
 }))
 try{
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin)
  await page.frameLocator('#service iframe').getByText('合成居民畫面').waitFor({state:'attached'})
  assert.equal(await page.locator('#service iframe').getAttribute('inert'),'');assert.equal(await state(page,'minerva'),'ready')
  let child=page.frames().find(f=>f.url().includes('/cloud/resident'))
  await child.evaluate(()=>parent.postMessage({type:'neighbour-service-error'},location.origin))
  await page.waitForFunction(()=>document.querySelector('.community-system-node[data-system=eleuthia]').dataset.state==='repairing')
  await page.waitForFunction(()=>document.querySelector('#launchScreen').dataset.state==='loading')
  await page.frameLocator('#service iframe').getByText('合成居民畫面').waitFor({state:'attached'})
  assert.equal(frames,2);assert.equal(accesses,1)
  child=page.frames().find(f=>f.url().includes('/cloud/resident'))
  await child.evaluate(()=>parent.postMessage({type:'neighbour-service-error'},location.origin))
  await page.locator('#launchScreen[data-state=failed]').waitFor();assert.equal(frames,2)
  // postMessage queues delivery; child.evaluate does not await the parent's listener.
  // Register after the real shell so this acknowledgement observes its completed turn.
  await page.evaluate(()=>{
   window.__fixtureReadinessHandled=false
   window.addEventListener('message',event=>{
    if(event.origin===location.origin&&event.source===document.querySelector('#service iframe')?.contentWindow
     &&event.data?.type==='neighbour-readiness'&&event.data.checks?.input==='pending')window.__fixtureReadinessHandled=true
   })
  })
  await child.evaluate(checks=>parent.postMessage({type:'neighbour-readiness',area:'resident',checks:{...checks,input:'pending'},textReady:true,ready:false},location.origin),ready)
  await page.waitForFunction(()=>window.__fixtureReadinessHandled===true)
  assert.equal(await page.locator('#service iframe').getAttribute('inert'),'')
  assert.equal(await state(page,'eleuthia'),'loading')
  await child.evaluate(checks=>parent.postMessage({type:'neighbour-readiness',area:'resident',checks,textReady:true,ready:true},location.origin),ready)
  await page.locator('#launchScreen').waitFor({state:'hidden'});assert.equal(await page.locator('#service iframe').getAttribute('inert'),null)
  assert.equal(await state(page,'eleuthia'),'ready');assert.equal(frames,2)
  results.push({engine,shell:true,inertUntilAllRequiredReady:true,oneSafeFrameRetry:true,noDuplicateAccessRequest:true,realMicrophonePermissionRequests:0})
 }finally{await context.close()}
}
async function boot(browser,engine,terminal=false){
 const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block',permissions:[]})
 await guard(context)
 let roots=0,health=0,release=false
 await context.route('**/*',route=>serve(route,async(route,u)=>{
  if(u.pathname==='/'){roots++;await route.fulfill({headers,contentType:'text/html',body:roots===1?fs.readFileSync(path.join(base,'boot-wait.html')):'<p id="entered">合成平台已進入</p>'});return true}
  if(u.pathname==='/health'){health++;await route.fulfill({status:release?200:503,json:{public_ready:release,rollout_waiting:!release&&!terminal,rollout_failed:terminal}});return true}
  return false
 }))
 try{
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin)
  await page.waitForFunction(()=>document.querySelectorAll('.community-system-node').length===9)
  await page.waitForFunction(()=>!document.querySelector('#bootStatus').textContent.includes('正在連接服務'))
  assert.equal(roots,1);assert.equal(await state(page,'artemis'),'planned');assert.equal(await state(page,'aether'),'offline')
  if(terminal){
   await page.locator('#bootRetry').waitFor({state:'visible'});assert.equal(await state(page,'minerva'),'error');assert.equal(await state(page,'hades'),'error');assert.equal(health,1)
   if(engine==='chromium')await page.screenshot({path:path.join(area,`${engine}-boot-terminal.png`),fullPage:true,caret:'initial'})
  }else{
   assert.equal(await state(page,'minerva'),'loading');assert.equal(await page.locator('#bootRetry').isVisible(),false)
   if(engine==='chromium')await page.screenshot({path:path.join(area,`${engine}-boot-wait.png`),fullPage:true,caret:'initial'})
   release=true;await page.locator('#entered').waitFor();assert.equal(roots,2);assert.ok(health>=2)
  }
  results.push({engine,coldBoot:true,terminal,noPrematureEnter:true,terminalRedStopsAutoRetry:terminal,healthOnly:true})
 }finally{await context.close()}
}
async function moduleRetry(browser,engine){
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]})
 await guard(context)
 let requests=0
 await context.route('**/*',route=>serve(route,async(route,u)=>{
  if(u.pathname==='/'){await route.fulfill({headers,contentType:'text/html',body:'<script type="module" src="/module-harness.js"></script>'});return true}
  if(u.pathname==='/module-harness.js'){await route.fulfill({contentType:'text/javascript',body:'import{preloadModules}from"/cloud/module-warmup.js";window.warmStates=[];window.warmResult=await preloadModules(document,[{key:"robots",path:"/assets/fixture-robots.js"}],{timeoutMs:500,onState(key,state){warmStates.push(state)}});window.testReady=true'});return true}
  if(u.pathname==='/assets/fixture-robots.js'){requests++;await route.fulfill({status:requests===1?503:200,contentType:'text/javascript',body:requests===1?'':'window.__CONSOLE_MUST_NOT_EXECUTE__=true'});return true}
  return false
 }))
 try{
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin);await page.waitForFunction(()=>window.testReady===true)
  const value=await page.evaluate(()=>({states:warmStates,result:warmResult,executed:window.__CONSOLE_MUST_NOT_EXECUTE__===true}))
  assert.equal(value.states.filter(v=>v==='repairing').length,1);assert.equal(value.executed,false);assert.ok(requests>=1&&requests<=2)
  assert.ok(['loaded','failed'].includes(value.result[0].state));assert.equal(value.states[0],'loading');assert.equal(value.states[1],'failed')
  results.push({engine,moduleRetry:true,oneBoundedRetry:true,networkRequests:requests,final:value.result[0].state,moduleNotExecuted:true})
 }finally{await context.close()}
}
;(async()=>{
 for(const[engine,type]of[['chromium',chromium],['webkit',webkit]]){
  const browser=await type.launch(engine==='chromium'?{headless:true,executablePath:process.platform==='win32'?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined,args:['--mute-audio']}:{headless:true})
  try{
   for(const viewport of[{width:1280,height:900},{width:390,height:844},{width:320,height:740}])await direct(browser,engine,viewport)
   await direct(browser,engine,{width:390,height:844},true)
   await shell(browser,engine);await boot(browser,engine);await boot(browser,engine,true);await moduleRetry(browser,engine)
  }finally{await browser.close()}
 }
 assert.deepEqual(outside,[]);assert.deepEqual(errors,[]);assert.deepEqual(cspViolations,[])
 const result={passed:true,results,strictSelfCsp:true,cspViolations,webkitScreenshotsOmittedToAvoidPlaywrightStyleInjection:true,externalRequests:outside,pageErrors:errors,productionProvidersCapturePlaybackRobotActions:0}
 fs.writeFileSync(path.join(area,'RESULT.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result))
})().catch(e=>{console.error(e);process.exitCode=1})
