// Viewport and wrapping regression; synthetic same-origin HTTPS, no real devices/providers.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const {chromium,webkit}=require(path.resolve(process.env.NODE_PATH||'.experiments/optimization-lab-20261029/node/node_modules','playwright'))
const area=path.resolve('.runtime/viewport-fit-20261105'),base=path.resolve('deploy/cloud/web'),origin='https://viewport-fit.fixture.test'
fs.mkdirSync(area,{recursive:true})
const results=[],violations=[],outside=[],errors=[]
const csp="default-src 'none';script-src 'self';style-src 'self';connect-src 'self';img-src 'self' data:;frame-src 'self';base-uri 'none';object-src 'none'"
const headers={'Content-Security-Policy':csp}
const settle=page=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
async function frame(page,selector,within){
 return page.evaluate(({selector,within})=>{
  const frame=document.querySelector(within),r=frame.getBoundingClientRect()
  const items=[...document.querySelectorAll(selector)].filter(n=>n.getClientRects().length)
  const clipped=items.filter(n=>{const b=n.getBoundingClientRect();return b.left<r.left-2||b.right>r.right+2||b.top<r.top-2||b.bottom>r.bottom+2}).map(n=>n.className||n.id)
  const s=getComputedStyle(frame)
  return {clipped,scrollX:['auto','scroll'].includes(s.overflowX)&&frame.scrollWidth>frame.clientWidth+1,
   scrollY:['auto','scroll'].includes(s.overflowY)&&frame.scrollHeight>frame.clientHeight+1,
   pageOverflow:document.documentElement.scrollWidth>innerWidth+1||document.documentElement.scrollHeight>innerHeight+1}
 },{selector,within})
}
;(async()=>{
 for(const[engine,type]of[['chromium',chromium],['webkit',webkit]]){
  const browser=await type.launch(engine==='chromium'?{headless:true,executablePath:process.platform==='win32'?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined,args:['--mute-audio']}:{headless:true})
  try{
   for(const [width,height]of [[1920,912],[1536,728],[1280,720],[1024,600],[768,1024],[390,844],[320,568],[844,390]]){
    const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce',serviceWorkers:'block',permissions:[]})
    await context.addInitScript(()=>document.addEventListener('securitypolicyviolation',e=>console.error('CSP:'+e.effectiveDirective+':'+e.blockedURI)))
    context.on('page',p=>{p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(m.text().startsWith('CSP:'))violations.push(m.text())})})
    await context.route('**/*',async route=>{
     const u=new URL(route.request().url());if(u.origin!==origin){outside.push(u.href);return route.abort()}
     if(u.pathname==='/')return route.fulfill({headers,contentType:'text/html',body:fs.readFileSync(path.join(base,'index.html'),'utf8').replace('/cloud/shell.js','/harness.js')})
     if(u.pathname==='/boot')return route.fulfill({headers,contentType:'text/html',body:fs.readFileSync(path.join(base,'boot-wait.html'),'utf8').replace('/cloud/boot-wait.js','/boot-harness.js')})
     if(u.pathname==='/harness.js')return route.fulfill({contentType:'text/javascript',body:`import{createLaunchScreen}from'/cloud/launch-screen.js';import{prepareCommunityIntroduction}from'/cloud/community-about.js';document.body.setAttribute('data-led-navigation-open','');window.launch=createLaunchScreen(document,{});prepareCommunityIntroduction(document);document.getElementById('navigation').hidden=false;document.getElementById('staff').hidden=false;launch.start('resident');window.ready=true`})
     if(u.pathname==='/boot-harness.js')return route.fulfill({contentType:'text/javascript',body:`import{mountCommunitySystems}from'/cloud/community-systems.js';window.diagram=mountCommunitySystems(document.getElementById('bootSystems'),{compact:true});diagram.orbit();window.ready=true`})
     const file=u.pathname.startsWith('/assets/brand/')?path.join(base,'brand',path.basename(u.pathname)):/^\/cloud\/[a-z-]+\.(css|js)$/.test(u.pathname)?path.join(base,path.basename(u.pathname)):null
     if(file&&fs.existsSync(file))return route.fulfill({contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'image/png',body:fs.readFileSync(file)})
     outside.push(u.pathname);return route.abort()
    })
    try{
     const page=await context.newPage();await page.goto(origin);await page.waitForFunction(()=>window.ready);await settle(page)
     const loading=await frame(page,'#launchSystems .community-system-node,#launchSystems .community-systems-heading,#launchSystems .community-systems-legend,#launchSystems .community-systems-note,.launch-copy>*','#launchScreen')
     if(engine==='chromium'&&[1280,390].includes(width))await page.screenshot({path:path.join(area,`loading-${width}.png`),caret:'initial'})
     await page.locator('#platformIntro').click();await settle(page)
     const orbit=await frame(page,'#introSystems .community-system-node,#introSystems .community-systems-heading,#introSystems .community-systems-legend,#introSystems .community-systems-note,#closeCommunityIntroduction','#communityIntroduction')
     if(engine==='chromium'&&[1280,390].includes(width))await page.screenshot({path:path.join(area,`orbit-${width}.png`),caret:'initial'})
     await page.locator('#closeCommunityIntroduction').click();await settle(page)
     await page.evaluate(()=>{const credit=document.getElementById('modelCredit');credit.hidden=false;document.getElementById('modelCreditSource').textContent='Tda-Vroid-Miku - Miku v0.3 · Coatie（Koh-Tee）';document.getElementById('modelCreditNotice').textContent='角色模型由原作者提供，使用時保留署名。'})
     await page.locator('.privacy>summary').click();await settle(page)
     const privacy=await page.evaluate(()=>{const n=document.querySelector('.privacy>div'),r=n.getBoundingClientRect();return {whiteSpace:getComputedStyle(n).whiteSpace,horizontalOverflow:n.scrollWidth>n.clientWidth+1,verticalOverflow:n.scrollHeight>n.clientHeight+1,withinScreen:r.left>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1,notesVisible:document.querySelector('.privacy-notes').scrollWidth<=document.querySelector('.privacy-notes').clientWidth+1}})
     if(engine==='chromium'&&[1280,390].includes(width))await page.screenshot({path:path.join(area,`privacy-${width}.png`),caret:'initial'})
     const record={engine,width,height,loading,orbit,privacy};results.push(record)
     fs.writeFileSync(path.join(area,'VIEWPORT-DIAGNOSTIC.json'),JSON.stringify(results,null,2))
     assert.deepEqual(loading,{clipped:[],scrollX:false,scrollY:false,pageOverflow:false},`${engine} ${width}x${height} loading`)
     assert.deepEqual(orbit,{clipped:[],scrollX:false,scrollY:false,pageOverflow:false},`${engine} ${width}x${height} dialog`)
     assert.deepEqual(privacy,{whiteSpace:'normal',horizontalOverflow:false,verticalOverflow:false,withinScreen:true,notesVisible:true},`${engine} ${width}x${height} privacy`)
     await page.locator('.privacy-more>summary').click();await settle(page)
     assert.equal(await page.locator('.privacy>div').evaluate(n=>n.scrollWidth<=n.clientWidth+1),true)
     await page.locator('.privacy-more>summary').click()
     await page.locator('.privacy>summary').click();await page.locator('#platformIntro').click()
     await page.locator('#introSystems').getByRole('button',{name:'查看赫淮斯托斯 · 機械工坊',exact:true}).click();await settle(page)
     record.overview=await frame(page,'#introSystems .community-system-node,#introSystems .community-system-overview,#closeCommunityIntroduction','#communityIntroduction')
     assert.deepEqual(record.overview,{clipped:[],scrollX:false,scrollY:false,pageOverflow:false},`${engine} ${width}x${height} 3D details`)
     assert.equal(await page.locator('#introSystems .community-product__canvas').count(),1)
     if(engine==='chromium')await page.screenshot({path:path.join(area,`dialog-${width}.png`),caret:'initial'})
     if(width===1280){
      await page.setViewportSize({width:844,height:390});await settle(page)
      assert.deepEqual(await frame(page,'#introSystems .community-system-node,#introSystems .community-system-overview,#closeCommunityIntroduction','#communityIntroduction'),{clipped:[],scrollX:false,scrollY:false,pageOverflow:false},`${engine} resize open dialog`)
      await page.setViewportSize({width,height});await settle(page)
     }
     await page.goto(origin+'/boot');await page.waitForFunction(()=>window.ready);await settle(page)
     record.coldBoot=await frame(page,'body main>* ,#bootSystems .community-system-node','body')
     assert.deepEqual(record.coldBoot,{clipped:[],scrollX:false,scrollY:false,pageOverflow:false},`${engine} ${width}x${height} cold boot`)
     if(engine==='chromium'&&[1280,390].includes(width))await page.screenshot({path:path.join(area,`boot-${width}.png`),caret:'initial'})
    }finally{await context.close()}
   }
  }finally{await browser.close()}
 }
 assert.deepEqual(violations,[]);assert.deepEqual(outside,[]);assert.deepEqual(errors,[])
 const report={passed:true,results,violations,outside,errors,productionProvidersOrHardwareActions:0}
 fs.writeFileSync(path.join(area,'VIEWPORT-VERIFIED.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:true,scenarios:results.length,strictCSP:true,productionActions:0}))
})().catch(e=>{console.error(e);process.exitCode=1})
