// Full workbench UI on an intercepted origin. No real stores, sound or hardware.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
let chromium
try{({chromium}=require('@playwright/test'))}catch{({chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright')))}
;(async()=>{
 const browser=await chromium.launch(process.platform==='win32'?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']}:{headless:true})
 const context=await browser.newContext({permissions:[],serviceWorkers:'block',viewport:{width:1280,height:900}})
 const origin='https://filter-fixture.test',unexpected=[],errors=[],queries=[]
 const cases=Array.from({length:63},(_,i)=>({id:(i+1).toString(16).padStart(32,'0'),case_number:i+1,kind:'water',
   status:i<60?'resolved':'new',revision:1,message:'公開合成漏水 '+(i+1),location:'1樓1室',unit:'1樓1室',contact:'',
   created_at_ms:1793635200000+i,updated_at_ms:1793635300000-i}))
 const care={...cases[0],id:'f'.repeat(32),case_number:64,kind:'human_support',message:'公開合成關懷',status:'new'}
 await context.addInitScript(()=>{
   window.AudioContext=class{constructor(){this.state='running';this.currentTime=0}resume(){}createOscillator(){return{frequency:{},connect(){},start(){},stop(){}}}createGain(){return{gain:{},connect(){}}}}
   Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:()=>{throw Error('microphone forbidden')}}})
 })
 await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url()),p=url.searchParams
   if(url.origin!==origin||request.method()!=='GET'){unexpected.push(url.href);return route.abort()}
   if(url.pathname==='/admin')return route.fulfill({contentType:'text/html',body:fs.readFileSync('edge_hub/static/admin.html','utf8')})
   if(url.pathname==='/assets/service-shell.css')return route.fulfill({contentType:'text/css',body:fs.readFileSync('edge_hub/static/service-shell.css')})
   if(url.pathname.startsWith('/assets/service/')){
     const file=path.join('edge_hub/static',path.basename(url.pathname))
     if(fs.existsSync(file))return route.fulfill({contentType:file.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(file)})
   }
   if(url.pathname==='/api/v1/service-desk/requests'){
     queries.push(Object.fromEntries(p));let rows=p.get('group')==='care'?[care]:[...cases]
     if(p.get('state')==='new')rows=rows.filter(r=>r.status==='new')
     if(p.get('state')==='resolved')rows=rows.filter(r=>r.status==='resolved')
     if(p.get('q'))rows=rows.filter(r=>String(r.case_number)===p.get('q')||r.message.includes(p.get('q')))
     rows.sort((a,b)=>p.get('sort')==='created_asc'?a.created_at_ms-b.created_at_ms:b.created_at_ms-a.created_at_ms)
     const total=rows.length,offset=Number(p.get('offset')||0),limit=Number(p.get('limit')||50)
     return route.fulfill({json:{items:rows.slice(offset,offset+limit),matched_total:total,offset,has_more:offset+limit<total,
       counts:{new:3,resolved:60},latest_case_number:64}})
   }
   if(url.pathname==='/api/v1/events/browse'){
     queries.push(Object.fromEntries(p));const offset=Number(p.get('offset')||0)
     return route.fulfill({json:{events:[],matched_total:0,has_more:false,offset}})
   }
   if(url.pathname==='/api/v1/event-stats')return route.fulfill({json:{total:0,pending:0,resolved:0,confirmed:0,false_positive:0}})
   if(url.pathname==='/api/v1/patrol/followups')return route.fulfill({json:{items:[]}})
   if(url.pathname==='/api/v1/service-desk/summary')return route.fulfill({json:{counts:{new:3},pending_by_group:{requests:3,care:1}}})
   if(url.pathname==='/api/v1/service-desk/knowledge')return route.fulfill({json:{items:[]}})
   if(url.pathname==='/api/v1/service-desk/quota')return route.fulfill({json:{overview:{rows:[]},chat:{}}})
   if(url.pathname==='/api/v1/service-desk/resources')return route.fulfill({json:{}})
   if(url.pathname==='/api/v1/service-desk/readiness')return route.fulfill({json:{}})
   unexpected.push(url.pathname);return route.abort()
 })
 try{
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin+'/admin#work')
   const filters=page.locator('#caseFilters'),cards=page.locator('#serviceCases>article')
   await page.locator('#casesPage').filter({hasText:'63'}).waitFor()
   assert.match(await cards.first().innerText(),/#63/)
   await page.locator('#casesNext').click();await page.locator('#casesPage').filter({hasText:'第 2 頁'}).waitFor()
   await filters.getByRole('button',{name:'等待接手',exact:true}).click()
   await page.waitForFunction(()=>document.querySelectorAll('#serviceCases>article').length===3)
   assert.match(await page.locator('#casesPage').innerText(),/第 1 頁/)
   await filters.getByRole('searchbox').fill('62');await filters.getByRole('button',{name:'搜尋',exact:true}).click()
   await page.waitForFunction(()=>document.querySelectorAll('#serviceCases>article').length===1)
   assert.match(await cards.first().innerText(),/#62/)
   await page.getByRole('tab',{name:'關懷',exact:true}).click()
   await page.waitForFunction(()=>document.querySelector('#serviceCases').innerText.includes('#64'))
   assert.equal(await filters.getByRole('searchbox').inputValue(),'')
   await filters.getByRole('button',{name:'已完成',exact:true}).click()
   await page.getByRole('tab',{name:'求助查詢',exact:true}).click()
   await page.waitForFunction(()=>document.querySelector('#serviceCases').innerText.includes('#62'))
   assert.equal(await filters.getByRole('searchbox').inputValue(),'62')
   assert.equal(await filters.getByRole('button',{name:'等待接手',exact:true}).getAttribute('aria-pressed'),'true')
   await filters.getByText('按日期範圍檢索',{exact:true}).click()
   await filters.getByLabel('日期依據').selectOption('updated')
   await filters.getByLabel('由',{exact:true}).fill('2026-11-04')
   await filters.getByLabel('至（包括當日）',{exact:true}).fill('2026-11-03')
   const count=queries.length;await filters.getByRole('button',{name:'搜尋',exact:true}).click()
   assert.match(await filters.getByRole('alert').innerText(),/開始日期不可/);assert.equal(queries.length,count)
   await filters.getByLabel('由',{exact:true}).fill('2026-11-01');await filters.getByRole('button',{name:'搜尋',exact:true}).click()
   await page.waitForFunction(()=>document.querySelector('#caseStatus').textContent.includes('已更新'))
   assert.ok(queries.some(q=>q.date_field==='updated'&&q.date_to==='2026-11-03'))
   await filters.getByRole('button',{name:'清除篩選',exact:true}).click()
   await filters.getByLabel('排序',{exact:true}).selectOption('created_asc')
   await page.waitForFunction(()=>document.querySelector('#serviceCases>article').innerText.includes('#1 ·'))
   await page.getByRole('tab',{name:'現場回報',exact:true}).click()
   const reports=page.locator('#eventFilters')
   await reports.getByRole('button',{name:'已確認',exact:true}).click()
   await page.waitForFunction(()=>document.querySelector('#eventStatus').textContent.includes('本頁顯示'))
   assert.ok(queries.some(q=>q.state==='confirmed'&&q.live_only==='true'))
   for(const width of [390,1280]){
     await page.setViewportSize({width,height:844})
     const box=await reports.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1)
   }
   assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[])
   console.log(JSON.stringify({passed:true,three_sections:true,server_pagination:true,scope_preserved:true,date_validation:true,mobile_layout:true,production_writes:0,microphone:0,audio:0}))
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1})
