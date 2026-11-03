// Full staff UI with synthetic cases/events and intercepted requests; no live Hub or EP.
const assert=require('node:assert/strict')
const fs=require('node:fs')
const path=require('node:path')
let chromium
try{({chromium}=require('@playwright/test'))}catch{({chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright')))}

async function main(){
 const browser=await chromium.launch(process.platform==='win32'?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']}:{headless:true})
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]})
 const unexpected=[],writes=[],errors=[]
 let state='new',revision=1,note=''
 const eventId='a'.repeat(32),caseId='b'.repeat(32)
 const eventStatus=()=>({new:'pending',acknowledged:'confirmed',resolved:'resolved'})[state]
 await context.addInitScript(()=>{
   Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:()=>Promise.reject(new Error('capture forbidden'))},configurable:true})
   window.AudioContext=class{constructor(){this.state='running';this.currentTime=0}resume(){}createOscillator(){return{frequency:{},connect(){},start(){},stop(){}}}createGain(){return{gain:{},connect(){}}}}
 })
 await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url())
   if(url.origin!=='https://isolated.neighbour.test'){unexpected.push(url.href);return route.abort()}
   if(url.pathname==='/admin')return route.fulfill({contentType:'text/html',body:fs.readFileSync('edge_hub/static/admin.html','utf8')})
   if(url.pathname==='/assets/service-shell.css')return route.fulfill({contentType:'text/css',body:fs.readFileSync('edge_hub/static/service-shell.css')})
   if(url.pathname.startsWith('/assets/service/')){
     const file=path.join('edge_hub/static',path.basename(url.pathname))
     if(fs.existsSync(file))return route.fulfill({contentType:file.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(file)})
   }
   if(url.pathname==='/api/v1/events/browse'&&request.method()==='GET')return route.fulfill({json:{events:[{id:eventId,type:'litter_detected',zone:'合成大堂',at_ms:1,severity:'notice',status:eventStatus(),evidence:'synthetic.jpg',details:{source:'ep_patrol_local',robot_sn:'SYNTHETIC'}}],matched_total:1,has_more:false,offset:0}})
   if(url.pathname==='/api/v1/event-stats')return route.fulfill({json:{total:1,pending:state==='new'?1:0,confirmed:state==='acknowledged'?1:0,resolved:state==='resolved'?1:0,false_positive:0}})
   if(url.pathname==='/api/v1/patrol/followups')return route.fulfill({json:{items:[{event_id:eventId,case_id:caseId,case_number:100001,revision,status:state,note,sync_pending:0}]}})
   if(url.pathname==='/api/v1/events/'+eventId&&request.method()==='PATCH'){
     const body=request.postDataJSON();writes.push({kind:'event',body})
     assert.equal(body.expected_revision,revision)
     state='acknowledged';revision++
     return route.fulfill({json:{status:'confirmed'}})
   }
   if(url.pathname==='/api/v1/service-desk/requests/'+caseId&&request.method()==='PATCH'){
     const body=request.postDataJSON();writes.push({kind:'case',body})
     assert.equal(body.expected_revision,revision)
     state=body.status;note=body.note;revision++
     return route.fulfill({json:{}})
   }
   if(url.pathname==='/api/v1/service-desk/requests')return route.fulfill({json:{items:[{id:caseId,case_number:100001,kind:'litter',status:state,revision,message:'合成巡查候選',location:'合成大堂',contact:'',created_at_ms:1,note,source_event_id:eventId,patrol_status:eventStatus(),patrol_sync_pending:false}],counts:{[state]:1},has_more:false,latest_case_number:100001}})
   if(url.pathname==='/api/v1/service-desk/knowledge')return route.fulfill({json:{items:[]}})
   if(url.pathname==='/api/v1/service-desk/summary')return route.fulfill({json:{counts:{new:state==='new'?1:0},pending_by_group:{requests:state==='new'?1:0,care:0},delivery_scope:'local_staff_workbench_only'}})
   if(url.pathname==='/api/v1/service-desk/quota')return route.fulfill({json:{overview:{rows:[]},chat:{}}})
   if(url.pathname==='/api/v1/service-desk/resources')return route.fulfill({json:{}})
   if(url.pathname==='/api/v1/service-desk/readiness')return route.fulfill({json:{}})
   unexpected.push(url.pathname);return route.abort()
 })
 try{
   const page=await context.newPage()
   page.on('pageerror',error=>errors.push(error.message))
   await page.goto('https://isolated.neighbour.test/admin#reports')
   const report=page.locator('[data-event-id]')
   await report.getByRole('button',{name:'核實並接手'}).click()
   await page.waitForFunction(()=>document.querySelector('[data-event-id]').innerText.includes('已確認'))
   await report.getByRole('link',{name:/個案 100001/}).click()
   const card=page.locator('[data-case-id]')
   await card.locator('.service-case-summary').getByText('跟進中',{exact:true}).waitFor()
   await card.getByRole('button',{name:'查看及跟進',exact:true}).click()
   await card.getByText('巡查回報 · 職員跟進',{exact:true}).waitFor()
   await card.getByRole('textbox',{name:'跟進內容／回覆居民'}).fill('合成測試：已清理完成')
   await card.getByRole('button',{name:'標記完成',exact:true}).click()
   await card.locator('dialog').waitFor({state:'hidden'})
   await card.getByRole('button',{name:'查看及跟進',exact:true}).click()
   await card.getByText('最新跟進：合成測試：已清理完成',{exact:true}).waitFor()
   await card.getByRole('link',{name:'查看現場回報及相片'}).click()
   await page.waitForFunction(()=>document.querySelector('[data-event-id]').innerText.includes('已完成'))
   await page.locator('#refreshEvents').click()
   assert.equal(await report.getByRole('button',{name:'核實並接手'}).isDisabled(),true)
   assert.equal(writes.length,2)
   assert.deepEqual(unexpected,[])
   assert.deepEqual(errors,[])
   console.log(JSON.stringify({real_chromium:true,event_to_case:true,case_to_event:true,revision_guard:true,progress_visible:true,outside_requests:0,production_writes:0,robot_requests:0}))
 }finally{await context.close();await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
