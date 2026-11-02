// Own synthetic origin and fresh headless profile. No Google, real capture,
// playback, provider calls, credentials or production data are used.
const assert=require('node:assert/strict')
const fs=require('node:fs')
const path=require('node:path')
const {chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
const area=path.resolve('.runtime/cloud-host-20261029/private-deployment-20261030/cloud-asr-20261030/frontend13')
const fixture=JSON.parse(fs.readFileSync(path.join(area,'fixtures.json'),'utf8'))
const origin='https://isolated.neighbour.test'
const tokens=Object.fromEntries(['resident','staff'].map(role=>[role,'header.'+Buffer.from(JSON.stringify({role,exp:Math.floor(Date.now()/1000)+3600})).toString('base64url')+'.signature']))
const token=role=>tokens[role]

async function main(){
 const browser=await chromium.launch({headless:true,chromiumSandbox:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']})
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]})
 const unexpected=[],errors=[],attempts=[],turns=[],voices=[],writes=[]
 let first=true,modelFirst=true,revision=1,accessRequests=0
 let settings={revision:1,name:'鄰伴',greeting:'你好，慢慢傾。',persona:'',background:'mint'}
 await context.addInitScript(()=>{
  globalThis.__testNodes=0
  navigator.mediaDevices.getUserMedia=async()=>{throw Error('test denies capture')}
  const param=()=>({value:0,setValueAtTime(){},linearRampToValueAtTime(){},cancelScheduledValues(){}})
  const node=()=>({connect(){},disconnect(){},addEventListener(){},removeEventListener(){}})
  class SilentContext{
   constructor(){this.state='running';this.sampleRate=24000;this.currentTime=0;this.destination=node();this.audioWorklet={addModule:async()=>{}}}
   async resume(){} async suspend(){} async close(){this.state='closed'} addEventListener(){} removeEventListener(){}
   createGain(){return {...node(),gain:param()}}
   createAnalyser(){return {...node(),frequencyBinCount:512,fftSize:1024,getByteFrequencyData(x){x.fill(0)},getByteTimeDomainData(x){x.fill(128)},getFloatTimeDomainData(x){x.fill(0)}}}
   createBuffer(_channels,length,sampleRate){return {duration:length/sampleRate,sampleRate,getChannelData:()=>new Float32Array(length)}}
   createBufferSource(){return {...node(),start(){globalThis.__testNodes++;setTimeout(()=>this.onended?.(),10)},stop(){}}}
   createOscillator(){return {...node(),frequency:param(),start(){},stop(){}}}
   createMediaStreamSource(){throw Error('capture forbidden')}
  }
  globalThis.AudioContext=SilentContext;globalThis.webkitAudioContext=SilentContext
  globalThis.AudioWorkletNode=class{constructor(){Object.assign(this,node());this.port={postMessage(){},addEventListener(){},start(){},close(){}}}}
 })
 await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url())
  if(url.origin!==origin){
   if(url.hostname==='huggingface.co'||url.hostname.endsWith('.hf.co'))return route.abort()
   unexpected.push(url.origin+url.pathname);return route.abort()
  }
  if(url.pathname==='/api/v1/resident/access'){
   accessRequests++
   const body=req.postDataJSON()
   if(body.password&&body.password!=='synthetic-manager')return route.fulfill({status:401,json:{detail:'管理口令不正確。'}})
   const role=body.password?'staff':'resident'
   return route.fulfill({json:{token:token(role),role,expires_at_ms:Date.now()+3600000}})
  }
  if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/_audio/')){
   const auth=req.headers().authorization
   assert.ok([`Bearer ${token('resident')}`,`Bearer ${token('staff')}`].includes(auth))
   const role=auth===`Bearer ${token('staff')}`?'staff':'resident'
   if(url.pathname==='/api/v1/resident/session')return route.fulfill({json:{authenticated:true,role,storage_acceptance:false}})
   if(url.pathname==='/api/v1/resident/presentation')return route.fulfill({json:{name:settings.name,greeting:settings.greeting,background:settings.background,revision:settings.revision}})
   if(url.pathname==='/api/v1/resident/timing')return route.fulfill({json:{accepted:true}})
   if(url.pathname==='/api/v1/resident/chat'){
    const body=req.postDataJSON();attempts.push(body)
    if(first){first=false;return route.fulfill({status:503,json:{code:'service_maintenance',operation_outcome:'not_attempted'}})}
    turns.push(body);return route.fulfill({json:{object:'resident.plan',messages:body.messages,system_prompt:'公開隔離對話'}})
   }
   if(url.pathname==='/api/v1/resident/model/v1/chat/completions'){
    if(modelFirst){modelFirst=false;return route.fulfill({status:401,json:{detail:'expired synthetic session'}})}
    return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({choices:[{delta:{content:'你好，慢慢傾。'}}]})+'\n\ndata: [DONE]\n\n'})
   }
   if(url.pathname==='/_audio/v1/audio/resident-stream'){
    voices.push(req.postDataJSON());return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({audio:Buffer.alloc(512).toString('base64')})+'\n\ndata: {"done":true}\n\n'})
   }
   if(url.pathname.startsWith('/api/v1/service-desk/')&&role!=='staff')return route.fulfill({status:403,json:{detail:'staff only'}})
   if(url.pathname==='/api/v1/service-desk/presentation'){
    if(req.method()==='PUT'){const body=req.postDataJSON();assert.equal(body.expected_revision,settings.revision);delete body.expected_revision;settings={...body,revision:settings.revision+1};writes.push('settings')}
    return route.fulfill({json:settings})
   }
   if(url.pathname.startsWith('/api/v1/service-desk/requests')){
    if(req.method()==='PATCH'){assert.equal(req.postDataJSON().expected_revision,revision);revision++;writes.push('case');return route.fulfill({json:{}})}
    return route.fulfill({json:{items:[{id:'a'.repeat(32),case_number:1,kind:'general',status:revision>1?'acknowledged':'new',revision,message:'公開隔離個案',location:'',contact:'',created_at_ms:1}],counts:{new:1,acknowledged:0,resolved:0},has_more:false,latest_case_number:1}})
   }
   if(url.pathname==='/api/v1/service-desk/knowledge')return route.fulfill({json:{items:[]}})
   if(url.pathname==='/api/v1/service-desk/quota')return route.fulfill({json:{overview:{updated_at_ms:Date.now(),active_rows:[{id:'azure-voice',platform:'Microsoft Azure Speech F0',service:'廣東話朗讀',provider:{status:'not_reported'},guard:{counters:[{remaining:390000,limit:400000}],percent:97.5},operation:{state:'ready'}}]}}})
   if(url.pathname==='/api/v1/events')return route.fulfill({json:[]})
   if(url.pathname==='/api/v1/event-stats')return route.fulfill({json:{total:0,pending:0,confirmed:0,false_positive:0,resolved:0}})
   if(url.pathname==='/api/v1/governance/retention')return route.fulfill({json:{status:'ready'}})
   unexpected.push(req.method()+' '+url.pathname);return route.abort()
  }
  const item=fixture[url.pathname]
  if(item)return route.fulfill({headers:item.headers,body:item.file?fs.readFileSync(item.file):Buffer.from(item.body,'base64')})
  unexpected.push(url.pathname);return route.abort()
 })
 try{
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message))
  await page.goto(origin+'/')
  const resident=page.frameLocator('iframe')
  await resident.getByRole('textbox').first().waitFor({timeout:60000})
  assert.equal(await page.locator('#googleButton button').count(),0)
  for(const [index,text] of ['你好呀。','我今日整咗香蕉蛋糕。','頭先整咗乜嘢？'].entries()){
   await resident.getByRole('textbox').first().fill(text)
   await resident.getByRole('button',{name:'傳送',exact:true}).click()
   await page.waitForFunction(n=>{const child=document.querySelector('iframe')?.contentWindow;return child?.__testNodes>=n&&child.document.querySelector('textarea')?.value===''},index+1,{timeout:20000})
  }
  assert.deepEqual(attempts[0],attempts[1]);assert.equal(turns.length,3);assert.equal(turns[2].messages.length,5)
  assert.ok(voices.every(v=>v.voice==='zh-HK-HiuMaanNeural'&&v.model==='azure-hiumaan-f0'))
  await page.getByRole('button',{name:'管理工作台',exact:true}).click()
  await page.locator('#staffPassword').fill('wrong');await page.locator('#staffLoginForm button[type=submit]').click()
  await page.getByText('管理口令不正確。',{exact:true}).waitFor()
  assert.equal(await page.locator('iframe').count(),0)
  await page.locator('#staffPassword').fill('synthetic-manager');await page.locator('#staffLoginForm button[type=submit]').click()
  const staff=page.frameLocator('iframe')
  await staff.getByText('公開隔離個案',{exact:true}).waitFor()
  await staff.getByRole('button',{name:'接手跟進',exact:true}).click()
  await staff.getByText(/跟進中/).first().waitFor()
  await staff.getByRole('tab',{name:'數字人設定',exact:true}).click()
  await staff.locator('#presentationName').waitFor()
  await staff.locator('#presentationGreeting').fill('歡迎返嚟。')
  await staff.locator('#cloudPresentationForm button[type=submit]').click()
  await staff.getByText(/已儲存；下次開啟/).waitFor()
  const widths=await staff.locator('.service-tabs [role=tab]').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().width))
  assert.equal(widths.length,6);assert.ok(Math.max(...widths)-Math.min(...widths)<2)
  await staff.getByRole('tab',{name:'服務用量',exact:true}).click()
  await staff.getByText('估計可用 390,000',{exact:true}).waitFor()
  assert.equal(await staff.locator('.service-quota-table thead th').count(),3)
  assert.equal(await staff.locator('iframe').count(),0)
  assert.deepEqual(writes,['case','settings']);assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[])
  assert.equal(accessRequests,4)
  await page.screenshot({path:path.join(area,'quota-desktop.png')})
  await page.setViewportSize({width:390,height:844})
  await page.screenshot({path:path.join(area,'quota-mobile.png')})
  const mobile=await staff.locator('body').evaluate(body=>({width:body.clientWidth,scroll:body.scrollWidth}))
  assert.ok(mobile.scroll<=mobile.width+1)
  const proof={public_entry:true,no_Google:true,three_turns:3,context_messages:5,safe_maintenance_retry_same_intent:true,expired_resident_session_renewed:true,password_staff:true,settings_saved:true,equal_tabs:true,compact_quota:true,mobile_no_overflow:true,provider_calls:0,real_mic:false,real_audio:false,EP_actions:0}
  fs.writeFileSync(path.join(area,'PUBLIC-UI-VERIFIED.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof))
 }catch(error){console.error(JSON.stringify({errors,unexpected,turns:turns.length,voices:voices.length}));throw error}
 finally{await context.close();await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1})
