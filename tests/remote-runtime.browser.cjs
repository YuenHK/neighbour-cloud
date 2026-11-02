// Native Chrome fetch/XHR, synthetic HTTPS origin, all network intercepted.
const assert=require('node:assert/strict')
const fs=require('node:fs')
const path=require('node:path')
const {chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
async function main(){
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']})
 const context=await browser.newContext({permissions:[],serviceWorkers:'block'})
 const calls=[],unexpected=[]
 const origin='https://synthetic.ngrok-free.dev'
 await context.addCookies([{name:'edge_session',value:'synthetic-only',url:origin,httpOnly:true,secure:true,sameSite:'Lax'}])
 await context.addInitScript(()=>{
  window.__socketUrls=[]
  window.WebSocket=class{constructor(url){window.__socketUrls.push(String(url))}}
  window.EventSource=class{constructor(url){window.__socketUrls.push(String(url))}}
  navigator.mediaDevices.getUserMedia=()=>Promise.reject(new Error('capture forbidden'))
 })
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url())
  if(url.origin!==origin && url.origin!=='https://external.invalid'){unexpected.push(url.href);return route.abort()}
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<meta charset="utf-8"><title>Isolated remote adapter</title><script>'+fs.readFileSync('edge_hub/static/remote-runtime.js','utf8')+'</script>'})
  calls.push({url:url.href,method:request.method(),cookie:request.headers().cookie||'',body:request.postData()})
  return route.fulfill({status:200,headers:{'Access-Control-Allow-Origin':origin},json:{ok:true}})
 })
 try{
  const page=await context.newPage();await page.goto(origin)
  const result=await page.evaluate(async()=>{
   await fetch('http://127.0.0.1:8000/api/v1/resident/chat',{method:'POST',credentials:'omit',body:'first-public-turn'})
   await fetch(new Request('http://localhost:8765/v1/audio/resident-stream',{method:'POST',body:'public-voice'}))
   await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.onload=resolve;xhr.onerror=reject;xhr.open('GET','http://127.0.0.1:8765/health');xhr.send()})
   await fetch('https://external.invalid/data',{credentials:'omit'})
   new WebSocket('ws://127.0.0.1:6121/ws')
   new EventSource('http://127.0.0.1:8000/ws/events')
   return {remote:window.__NEIGHBOUR_REMOTE__,sockets:window.__socketUrls}
  })
  assert.equal(result.remote,true)
  assert.deepEqual(calls.map(x=>new URL(x.url).pathname),['/api/v1/resident/chat','/_audio/v1/audio/resident-stream','/_audio/health','/data'])
  assert.equal(calls[0].body,'first-public-turn');assert.equal(calls[1].body,'public-voice')
  assert(calls.slice(0,3).every(x=>x.cookie.includes('edge_session=synthetic-only')))
  assert.equal(calls[3].cookie,'')
  assert.deepEqual(result.sockets,['wss://synthetic.ngrok-free.dev/_airi/ws','https://synthetic.ngrok-free.dev/ws/events'])
  assert.deepEqual(unexpected,[])
  console.log(JSON.stringify({native_fetch:true,native_xhr:true,post_body_preserved:true,edge_cookie_preserved:true,external_cookie_leaks:0,websocket_remapped:true,outside_requests:0,cloud_calls:0,ep_actions:0,microphone:0}))
 }finally{await context.close();await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
