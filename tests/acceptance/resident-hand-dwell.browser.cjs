// Actual DOM/rAF in both browsers; synthetic landmarks only, no camera or robot.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
const {chromium,webkit}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
const origin='https://resident-hand-fixture.test'
;(async()=>{
 const results=[]
 for(const [name,type] of Object.entries({chromium,webkit})){
  const browser=await type.launch({headless:true,...(name==='chromium'?{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{})})
  try{
   const page=await browser.newPage({viewport:{width:960,height:720}}),outside=[],errors=[]
   page.on('pageerror',error=>errors.push(error.message))
   await page.route('**/*',route=>{
    const url=new URL(route.request().url())
    if(url.origin!==origin){outside.push(url.href);return route.abort()}
    if(url.pathname==='/resident-hand.js')return route.fulfill({contentType:'text/javascript',body:fs.readFileSync('airi_overlay/resident-hand.js')})
    if(url.pathname==='/resident-panel.css')return route.fulfill({contentType:'text/css',body:fs.readFileSync('airi_overlay/resident-panel.css')})
    if(url.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/resident-panel.css"><section class="resident-assistant-panel"><button id="allowed" data-hand-action="next" style="position:fixed;left:100px;top:200px;width:150px;height:60px">下一位</button><button id="disabled" data-hand-action="send" disabled style="position:fixed;left:300px;top:200px;width:150px;height:60px">傳送</button></section><button id="forbidden" data-hand-action="move" style="position:fixed;left:500px;top:200px;width:150px;height:60px">非居民控制</button>'})
    return route.abort()
   })
   await page.goto(origin)
   await page.evaluate(async()=>{
    const {ResidentHandPointer}=await import('/resident-hand.js')
    window.hand=new ResidentHandPointer();window.clicks={allowed:0,disabled:0,forbidden:0}
    for(const id of Object.keys(window.clicks))document.getElementById(id).onclick=()=>window.clicks[id]++
    window.pointAt=(sx,sy)=>{
     const x=1-(.12+.76*sx/innerWidth),y=.12+.76*sy/innerHeight,p=Array.from({length:21},()=>({x,y}))
     p[0]={x,y:y+.1}
     for(const [tip,pip,mcp,i] of [[8,6,5,0],[12,10,9,1],[16,14,13,2],[20,18,17,3]]){
      const px=x+(i-1.5)*.05;p[mcp]={x:px,y:y-.025};p[pip]={x:px,y:y-.1};p[tip]={x:px,y:y-.2}
     }
     p[4]={x:x+.2,y};return p // Open palm, no pinch.
    }
    window.hold=(x,y)=>{clearInterval(window.samples);window.hand.clear();window.hand.update(window.pointAt(x,y));window.samples=setInterval(()=>window.hand.update(window.pointAt(x,y)),50)}
    window.release=()=>{clearInterval(window.samples);window.hand.clear()}
    window.hold(175,230)
   })
   await page.waitForFunction(()=>Number(document.querySelector('.resident-hand-cursor').style.getPropertyValue('--hand-progress'))>.35)
   const midway=await page.evaluate(()=>({progress:Number(document.querySelector('.resident-hand-cursor').style.getPropertyValue('--hand-progress')),clicks:window.clicks.allowed}))
   assert.ok(midway.progress<1&&midway.clicks===0)
   await page.waitForFunction(()=>window.clicks.allowed===1)
   await page.waitForTimeout(450);assert.equal(await page.evaluate(()=>window.clicks.allowed),1)
   const closed=await page.evaluate(async()=>{
    window.release();const points=window.pointAt(175,230)
    for(const index of [8,12,16,20])points[index]={x:points[0].x,y:points[0].y-.01}
    points[4]={...points[8]};window.hand.update(points)
    await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)
    return document.querySelector('.resident-hand-cursor').hidden
   })
   assert.equal(closed,true,'A closed fist must pause even when fingertips look pinched')
   await page.evaluate(()=>{window.release();window.hand.update(window.pointAt(175,230))})
   await page.waitForTimeout(550)
   assert.equal(await page.locator('.resident-hand-cursor').isHidden(),true)
   assert.equal(await page.evaluate(()=>window.clicks.allowed),1)
   for(const x of [375,575]){
    await page.evaluate(x=>window.hold(x,230),x);await page.waitForTimeout(2200)
    assert.equal(await page.evaluate(()=>document.querySelector('.resident-hand-cursor').dataset.state),'moving')
   }
   assert.deepEqual(await page.evaluate(()=>window.clicks),{allowed:1,disabled:0,forbidden:0})
   const motion=await page.evaluate(async()=>{
    window.release();window.hold(175,400)
    await new Promise(resolve=>setTimeout(resolve,60));clearInterval(window.samples)
    window.hand.update(window.pointAt(575,400));const xs=[]
    for(let i=0;i<6;i++){await new Promise(requestAnimationFrame);xs.push(new DOMMatrix(document.querySelector('.resident-hand-cursor').style.transform).m41)}
    window.release();window.hand.dispose();return xs
   })
   assert.ok(motion.some((x,i)=>i>0&&x>motion[i-1]+1));assert.ok(motion.every(x=>x>=175&&x<=575))
   assert.deepEqual(outside,[]);assert.deepEqual(errors,[])
   results.push({browser:name,two_second_open_hand_click_once:true,visible_progress:true,stale_disabled_and_nonresident_blocked:true,interpolated_render_frames:motion.length})
  }finally{await browser.close()}
 }
 console.log(JSON.stringify({passed:true,results,real_camera_audio_robot_or_API:0}))
})().catch(error=>{console.error(error);process.exitCode=1})
