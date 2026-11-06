const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
const {chromium,webkit}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
const origin='https://led.neighbour.test',results=[]
const html=fs.readFileSync('deploy/cloud/web/index.html','utf8').replace(/<script[^>]*src="\/cloud\/shell.js"[^>]*><\/script>/,'<script src="/qa-led.js"></script>')
const shell=fs.readFileSync('deploy/cloud/web/shell.js','utf8'),start=shell.indexOf('function installLedNavigation()'),end=shell.indexOf('\nlet frame,',start),navigation=shell.slice(start,end)
async function run(engine,type){
 const browser=await type.launch(engine==='chromium'?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']}:{headless:true})
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]});const errors=[],outside=[]
 await context.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.origin!==origin){outside.push(u.origin+u.pathname);return route.abort()}
  if(u.pathname==='/')return route.fulfill({contentType:'text/html',body:html})
  if(u.pathname==='/qa-led.js')return route.fulfill({contentType:'text/javascript',body:`const node=id=>document.getElementById(id);${navigation};document.getElementById('launchScreen').hidden=true;document.getElementById('navigation').hidden=false;document.getElementById('staff').hidden=false;document.getElementById('service').innerHTML='<iframe title="合成服務畫面" src="/frame"></iframe>';installLedNavigation();`})
  if(u.pathname==='/frame')return route.fulfill({contentType:'text/html',body:'<html><body style="margin:0;background:#ecf6f0"><button style="margin:250px 20px">合成服務畫面</button></body></html>'})
  const file=path.join('deploy/cloud/web',u.pathname.replace(/^\/cloud\//,'').replace(/^\/assets\//,''));if(fs.existsSync(file)&&fs.statSync(file).isFile())return route.fulfill({contentType:u.pathname.endsWith('.css')?'text/css':u.pathname.endsWith('.png')?'image/png':'image/webp',body:fs.readFileSync(file)})
  outside.push(u.pathname);return route.abort()
 })
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message))
 try{
  for(const [width,height,led] of [[256,768,true],[192,640,true],[128,384,true],[257,768,false],[256,769,false],[390,844,false],[1280,900,false]]){
   await page.setViewportSize({width,height});await page.mouse.move(width/2,height/2);await page.goto(origin);await page.locator('#service iframe').waitFor();await page.waitForTimeout(260)
   const handle=page.locator('#ledNavigationToggle'),header=page.locator('#platformHeader')
   assert.equal(await handle.isVisible(),led,`${engine} ${width}x${height}`)
   if(led){
    assert.ok((await header.boundingBox()).y+(await header.boundingBox()).height<=1)
    const frameHeight=await page.locator('#service iframe').evaluate(e=>e.getBoundingClientRect().height);assert.equal(frameHeight,height)
    await page.mouse.move(width/2,3);await page.waitForTimeout(260);assert.equal(await handle.getAttribute('aria-expanded'),'true')
    assert.ok((await header.boundingBox()).y>=-.5);assert.equal(await page.locator('#service iframe').evaluate(e=>e.getBoundingClientRect().height),height)
    await page.mouse.move(width/2,height-30);await page.waitForTimeout(260);assert.equal(await handle.getAttribute('aria-expanded'),'false')
    await handle.focus();await page.keyboard.press('Enter');await page.waitForTimeout(250);assert.equal(await handle.getAttribute('aria-expanded'),'true')
    await page.frameLocator('iframe').getByRole('button',{name:'合成服務畫面'}).click();await page.waitForTimeout(260);assert.equal(await handle.getAttribute('aria-expanded'),'false','content interaction dismisses overlay')
    await handle.focus();await page.keyboard.press('Enter');await page.keyboard.press('Escape');assert.equal(await handle.getAttribute('aria-expanded'),'false')
    await page.mouse.move(width/2,height-30);await page.screenshot({path:path.resolve(process.env.LED_SCREENSHOT_DIR||'.runtime/led-display-20261106',`${engine}-shell-${width}.png`)})
   }else assert.ok((await header.boundingBox()).y>=0)
   const geometry=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(geometry.scroll<=width+1,JSON.stringify(geometry))
   results.push({engine,width,height,led,no_reflow:true,no_horizontal_overflow:true})
  }
  assert.deepEqual(errors,[]);assert.deepEqual(outside,[])
 }finally{await context.close();await browser.close()}
}
;(async()=>{await run('chromium',chromium);await run('webkit',webkit);const result={passed:true,results,real_media_API_EP:0};if(process.env.LED_UI_RECEIPT)fs.writeFileSync(process.env.LED_UI_RECEIPT,JSON.stringify(result,null,2));console.log(JSON.stringify(result))})().catch(e=>{console.error(e);process.exitCode=1})
