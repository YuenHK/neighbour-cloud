// All URLs are intercepted, including localhost. Native fetch, fake AudioContext.
const assert=require('node:assert/strict')
const fs=require('node:fs')
const path=require('node:path')
const {chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
async function main(){
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']})
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]})
 const unexpected=[],synthesis=[]
 await context.route('**/*',route=>{
  const request=route.request(),url=new URL(request.url())
  if(url.href==='http://127.0.0.1:4173/isolated-native-pcm')return route.fulfill({contentType:'text/html',body:'<title>Isolated PCM</title>'})
  if(url.href==='http://127.0.0.1:8765/v1/audio/resident-stream'){
   const headers={'Access-Control-Allow-Origin':'http://127.0.0.1:4173','Access-Control-Allow-Methods':'POST,OPTIONS','Access-Control-Allow-Headers':'content-type'}
   if(request.method()==='OPTIONS')return route.fulfill({status:204,headers})
   const body=request.postDataJSON();synthesis.push(body)
   if(!body.input.trim())return route.fulfill({status:400,headers,contentType:'application/json',body:'{}'})
   return route.fulfill({headers,contentType:'text/event-stream',body:'data: '+JSON.stringify({audio:Buffer.alloc(4096).toString('base64')})+'\n\ndata: {"done":true}\n\n'})
  }
  unexpected.push(url.href);return route.abort()
 })
 try{
  const page=await context.newPage()
  await page.goto('http://127.0.0.1:4173/isolated-native-pcm')
  const result=await page.evaluate(async code=>{
   const {ResidentPcm}=await import('data:text/javascript;base64,'+btoa(unescape(encodeURIComponent(code))))
   let started=0,failed=0
   const nodes=[]
   const audio={state:'running',currentTime:0,destination:{},resume:async()=>{},
    createBuffer:(channels,count,rate)=>({duration:count/rate,getChannelData:()=>new Float32Array(count)}),
    createBufferSource:()=>{const node={connect(){},disconnect(){},start(){},stop(){node.stopped=true}};nodes.push(node);return node}}
   const player=new ResidentPcm({context:audio,started:()=>started++,failed:()=>failed++})
   player.write('公開虛構句子');player.write('\n\n');player.write('  \t ');player.write('下一段仍然朗讀。');player.end();await player.chain
   player.cancel()
   return {started,failed,stopped:nodes.every(node=>node.stopped===true),scheduled:nodes.length}
  },fs.readFileSync('airi_overlay/resident-pcm.js','utf8'))
  assert.deepEqual(result,{started:1,failed:0,stopped:true,scheduled:2})
  assert.equal(synthesis.length,2)
  assert.ok(synthesis.every(body=>body.input.trim()))
  assert.equal(synthesis[0].voice,'zh-HK-HiuMaanNeural')
  assert.deepEqual(unexpected,[])
  console.log(JSON.stringify({native_browser_fetch:true,pcm_scheduled:true,cancelled:true,voice:'zh-HK-HiuMaanNeural',outside_requests:0,actual_synthesis:0,playback:0}))
 }finally{await context.close();await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
