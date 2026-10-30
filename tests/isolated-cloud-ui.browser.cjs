// Owned, synthetic test origin with every request intercepted. This never
// controls the user's Chrome profile, signs into Google, records or plays audio.
const assert=require('node:assert/strict')
const fs=require('node:fs')
const path=require('node:path')
const {chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
const origin='https://isolated.neighbour.test'
const area=path.resolve('.runtime/cloud-host-20261029/private-deployment-20261030/cloud-asr-20261030/ui-browser-check')
const fixture=JSON.parse(fs.readFileSync(path.join(area,'fixtures.json'),'utf8'))

async function main(){
 const browser=await chromium.launch({headless:true,chromiumSandbox:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']})
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]})
 const unexpected=[],modelDownloads=[],turns=[],voices=[],writes=[],errors=[],consoleErrors=[]
 let stage=true,caseRevision=1,caseStatus='new'
 const jwt='header.'+Buffer.from(JSON.stringify({exp:Math.floor(Date.now()/1000)+3600})).toString('base64url')+'.signature'
 await context.addInitScript(()=>{
  globalThis.__testNodes=0
  globalThis.__testCaptureDenied=0
  navigator.mediaDevices.getUserMedia=async()=>{globalThis.__testCaptureDenied++;throw Error('isolated test denies real capture')}
  const param=()=>({value:0,setValueAtTime(){},linearRampToValueAtTime(){},cancelScheduledValues(){}})
  const node=()=>({connect(){},disconnect(){},addEventListener(){},removeEventListener(){}})
  class SilentContext{
   constructor(){this.state='running';this.sampleRate=24000;this.currentTime=0;this.destination=node();this.audioWorklet={addModule:async()=>{}}}
   async resume(){} async suspend(){} async close(){this.state='closed'}
   addEventListener(){} removeEventListener(){}
   createGain(){return {...node(),gain:param()}}
   createAnalyser(){return {...node(),frequencyBinCount:512,fftSize:1024,getByteFrequencyData(x){x.fill(0)},getByteTimeDomainData(x){x.fill(128)},getFloatTimeDomainData(x){x.fill(0)}}}
   createBuffer(channels,length,sampleRate){return {duration:length/sampleRate,sampleRate,getChannelData:()=>new Float32Array(length)}}
   createBufferSource(){return {...node(),start(){globalThis.__testNodes++;setTimeout(()=>this.onended?.(),10)},stop(){}}}
   createOscillator(){return {...node(),frequency:param(),start(){},stop(){}}}
   createMediaStreamSource(){throw Error('real capture forbidden')}
  }
  globalThis.AudioContext=SilentContext
  globalThis.webkitAudioContext=SilentContext
  globalThis.AudioWorkletNode=class{constructor(){Object.assign(this,node());this.port={postMessage(){},addEventListener(){},start(){},close(){}}}}
 })
 await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url())
  if(url.origin==='https://accounts.google.com'&&url.pathname==='/gsi/client')
   return route.fulfill({contentType:'text/javascript',body:`globalThis.google={accounts:{id:{initialize(value){this.value=value},renderButton(target){const b=document.createElement('button');b.textContent='隔離測試登入';b.onclick=()=>this.value.callback({credential:${JSON.stringify(jwt)}});target.append(b)},disableAutoSelect(){}}}}`})
  if(url.origin!==origin){
   if(url.hostname==='huggingface.co'||url.hostname.endsWith('.hf.co'))modelDownloads.push(url.hostname)
   else unexpected.push(url.origin+url.pathname)
   return route.abort()
  }
  const body=req.postDataJSON?.bind(req)
  if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/v1/')||url.pathname.startsWith('/_audio/')){
   assert.equal(req.headers().authorization,'Bearer '+jwt)
   assert.equal(req.headers()['x-operator-key'],undefined)
   if(url.pathname==='/api/v1/resident/session')return route.fulfill({json:{authenticated:true,role:'staff',storage_acceptance:stage}})
   if(url.pathname==='/api/v1/resident/timing')return route.fulfill({json:{accepted:true}})
   if(url.pathname==='/api/v1/resident/chat'){
    const value=body();turns.push(value)
    return route.fulfill({json:{object:'resident.plan',system_prompt:'公開隔離對話',messages:value.messages}})
   }
   if(url.pathname==='/api/v1/resident/model/v1/chat/completions')return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({choices:[{delta:{content:'你好，慢慢傾。'}}]})+'\n\ndata: [DONE]\n\n'})
   if(url.pathname==='/v1/audio/resident-stream'||url.pathname==='/_audio/v1/audio/resident-stream'){
    voices.push(body())
    return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({audio:Buffer.alloc(512).toString('base64')})+'\n\ndata: {"done":true}\n\n'})
   }
   if(url.pathname.startsWith('/api/v1/service-desk/requests')){
    if(req.method()==='PATCH'){writes.push(body());caseRevision++;caseStatus=body().status;return route.fulfill({json:{}})}
    return route.fulfill({json:{items:[{id:'a'.repeat(32),case_number:1,kind:'general',status:caseStatus,revision:caseRevision,message:'公開隔離個案',location:'',contact:'',created_at_ms:1}],counts:{new:caseStatus==='new'?1:0,acknowledged:caseStatus==='acknowledged'?1:0,resolved:0},has_more:false,latest_case_number:1}})
   }
   if(url.pathname==='/api/v1/service-desk/knowledge')return route.fulfill({json:{items:[]}})
   if(url.pathname==='/api/v1/service-desk/quota')return route.fulfill({json:{overview:{active_rows:[],rows:[],updated_at_ms:Date.now()}}})
   if(url.pathname==='/api/v1/events')return route.fulfill({json:[]})
   if(url.pathname==='/api/v1/event-stats')return route.fulfill({json:{total:0,pending:0,confirmed:0,false_positive:0,resolved:0}})
   unexpected.push(req.method()+' '+url.pathname);return route.abort()
  }
  if(fixture[url.pathname]){
   const entry=fixture[url.pathname]
   return route.fulfill({status:stage&&['/cloud/resident','/cloud/admin'].includes(url.pathname)?423:200,
    headers:stage?entry.stageHeaders:entry.headers,body:entry.file?fs.readFileSync(entry.file):Buffer.from(entry.body,'base64')})
  }
  unexpected.push(url.pathname);return route.abort()
 })
 try{
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text().slice(0,800))})
  await page.goto(origin+'/')
  await page.getByRole('button',{name:'隔離測試登入'}).click()
  await page.getByText(/Google 登入已核對成功/).waitFor()
  assert.equal(await page.locator('iframe').count(),0)
  assert.equal(await page.evaluate(()=>globalThis.__testCaptureDenied),0)
  stage=false;await page.reload();await page.getByRole('button',{name:'隔離測試登入'}).click()
  await page.getByRole('button',{name:'管理工作台',exact:true}).waitFor()
  // Inspect actual resident bundle with media devices stubbed and all network mocked.
  const resident=page.frameLocator('iframe')
  await Promise.race([
   resident.getByRole('textbox').first().waitFor({timeout:60000}),
   resident.getByText('畫面暫時未能顯示，請重新進入居民服務台。',{exact:true}).waitFor({timeout:60000}).then(()=>{throw Error('resident_render_error')})
  ])
  for(const [index,text] of ['你好呀。','我今日整咗香蕉蛋糕。','頭先講過整咗乜嘢？'].entries()){
   await resident.getByRole('textbox').first().fill(text)
   await resident.getByRole('button',{name:'傳送',exact:true}).click()
   await page.waitForFunction(expected=>{
    const child=document.querySelector('iframe')?.contentWindow
    return child?.__testNodes>=expected&&child.document.querySelector('textarea')?.value===''
   },index+1,{timeout:15000})
  }
  assert.equal(turns.length,3);assert.equal(turns[2].messages.length,5)
  assert.ok(voices.length>=3)
  assert.ok(voices.every(row=>row.model==='azure-hiumaan-f0'&&row.voice==='zh-HK-HiuMaanNeural'&&row.speed===1))
  await page.waitForFunction(()=>{
   const child=document.querySelector('iframe')?.contentWindow
   const start=child?.document.querySelector('#app')?._vnode
   const seen=new Set()
   function loaded(vnode){
    if(!vnode||typeof vnode!=='object'||seen.has(vnode))return false
    seen.add(vnode)
    const component=vnode.component
    if(component?.exposed?.initialModelWidth?.value>100&&component.exposed.initialModelHeight?.value>100)return true
    if(component&&loaded(component.subTree))return true
    return Array.isArray(vnode.children)&&vnode.children.some(loaded)
   }
   return loaded(start)
  },null,{timeout:30000})
  await resident.locator('canvas').first().waitFor()
  assert.doesNotMatch(await resident.locator('body').innerText(),/畫面暫時未能顯示|Something went wrong/)
  await page.screenshot({path:path.join(area,'resident-isolated.png')})
  await page.getByRole('button',{name:'管理工作台',exact:true}).click()
  const staff=page.frameLocator('iframe')
  await staff.getByText('公開隔離個案',{exact:true}).waitFor()
  await staff.getByRole('button',{name:'接手跟進',exact:true}).click()
  await staff.getByText(/跟進中/).first().waitFor()
  assert.equal(writes.length,1);assert.equal(writes[0].expected_revision,1)
  await staff.getByRole('tab',{name:'屋苑資料',exact:true}).click()
  await staff.getByRole('textbox',{name:'題目',exact:true}).waitFor()
  await page.getByRole('button',{name:'登出',exact:true}).click()
  assert.equal(await page.locator('iframe').count(),0)
  assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[])
  const proof={real_isolated_chromium:true,stage_never_mounts_media:true,avatar_model_dimensions_verified:true,three_text_turns:true,full_context_messages:5,hiuMaan_zero_pcm_mocked:voices.length,staff_update_mocked:writes.length,external_network_requests:0,real_microphone_or_audio:false,production_data_writes:0,ep_operations:0}
  fs.writeFileSync(path.join(area,'RESULT.json'),JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify(proof))
 }catch(error){
  const frames=[]
  for(const page of context.pages())for(const frame of page.frames())frames.push({url:frame.url(),body:await frame.locator('body').innerText({timeout:1000}).catch(()=>''),html:await frame.locator('head').innerHTML({timeout:1000}).catch(()=>'')})
  fs.writeFileSync(path.join(area,'errors.json'),JSON.stringify({errors,consoleErrors,unexpected,modelDownloads,turns:turns.length,voices:voices.length,frames},null,2));throw error
 }
 finally{await context.close();await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
