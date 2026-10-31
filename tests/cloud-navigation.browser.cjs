// Actual shell on a synthetic origin. No credentials, audio or resident data.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const {chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
const origin='https://navigation.neighbour.test'
const token=role=>'header.'+Buffer.from(JSON.stringify({role,exp:Math.floor(Date.now()/1000)+3600})).toString('base64url')+'.signature'
async function main(){
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']})
 const context=await browser.newContext({serviceWorkers:'block',permissions:[]})
 let waiting=false
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url())
  if(u.origin!==origin)return route.abort()
  if(u.pathname==='/login-config')return route.fulfill({json:{public_resident:true}})
  if(u.pathname==='/api/v1/resident/access'){
   const body=req.postDataJSON()
   if(body.password){waiting=true;await new Promise(r=>setTimeout(r,1000))}
   return route.fulfill({json:{token:token(body.password?'staff':'resident')}}).catch(()=>{})
  }
  if(u.pathname==='/api/v1/resident/session')return route.fulfill({json:{authenticated:true,role:req.headers().authorization.includes(token('staff'))?'staff':'resident',storage_acceptance:false}})
  if(u.pathname==='/cloud/resident'||u.pathname==='/cloud/admin')return route.fulfill({contentType:'text/html',body:u.pathname==='/cloud/admin'?'<h1>管理工作台測試</h1>':'<h1>居民服務台測試</h1>'})
  const files={'/':'deploy/cloud/web/index.html','/cloud/shell.js':'deploy/cloud/web/shell.js','/cloud/shell.css':'deploy/cloud/web/shell.css','/cloud/cloud-session.js':'airi_overlay/cloud-session.js','/cloud/cloud-frame.js':'airi_overlay/cloud-frame.js'}
  if(files[u.pathname])return route.fulfill({contentType:u.pathname.endsWith('.js')?'text/javascript':u.pathname.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(files[u.pathname])})
  return route.fulfill({status:404,body:''})
 })
 try{
  const page=await context.newPage();await page.goto(origin)
  await page.frameLocator('iframe').getByText('居民服務台測試').waitFor()
  await page.getByRole('button',{name:'管理工作台',exact:true}).click()
  await page.locator('#staffPassword').fill('synthetic-password')
  await page.locator('#staffLoginForm button[type=submit]').click()
  assert.equal(waiting,true)
  await page.getByRole('button',{name:'居民服務台',exact:true}).click()
  await page.frameLocator('iframe').getByText('居民服務台測試').waitFor({timeout:3000})
  await page.waitForTimeout(1200)
  await page.frameLocator('iframe').getByText('居民服務台測試').waitFor({timeout:1000})
  console.log(JSON.stringify({interrupted_staff_login_returns_to_resident:true,late_login_cannot_replace_resident:true,production_requests:0,hardware_used:false}))
 }finally{await context.close();await browser.close()}
}
main().catch(e=>{console.error(e.message);process.exitCode=1})
