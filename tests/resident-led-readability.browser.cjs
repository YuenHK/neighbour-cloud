const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const {chromium}=require(path.resolve('.experiments/optimization-lab-20261029/node/node_modules/playwright'))
const original=fs.readFileSync('airi_overlay/resident-service-panel.vue','utf8').split('<style scoped>')[1].split('</style>')[0]
const external=fs.readFileSync(process.env.NEIGHBOUR_LED_BASELINE_CSS||'airi_overlay/resident-panel.css','utf8')
const html=`<html><style>html,body,#app{height:100%;margin:0;min-width:0}.estate-resident-layout{height:100%;display:grid}.resident-assistant-panel{position:relative!important;display:flex!important;flex-direction:column;inset:auto!important}.resident-conversation-state{display:flex}.resident-state-copy{display:flex;flex-direction:column}</style><style>${original}</style><style>${external}</style><body data-cloud-view="resident" data-estate-kiosk><div id="app"><div class="estate-resident-layout"><div class="estate-avatar-canvas"></div><section class="resident-assistant-panel"><header><div><h2>你好，慢慢傾。</h2></div><div class="resident-heading-actions"><button class="resident-camera-toggle" aria-label="鏡頭">◉</button><button class="resident-end">下一位</button></div></header><div class="resident-transcript"><div class="resident-greeting">查資料、傾偈、跟進事情，直接同我講就得。</div><div class="resident-bubble"><span>鄰伴</span><p>${'分類垃圾可以分資源回收、廚餘同一般垃圾。'.repeat(16)}</p></div></div><div class="resident-panel-notices"><div class="resident-conversation-state"><div class="resident-state-copy"><span>我喺度，你慢慢講。</span></div></div><p class="resident-panel-status">可以直接講，或者打字同我傾。</p></div><form><textarea aria-label="訊息" placeholder="直接講，或者喺度打字…"></textarea><div class="resident-panel-actions"><button type="button" data-hand-action="microphone">正在聆聽・暫停</button><button class="primary" type="button">傳送</button></div></form></section></div></div></body></html>`
async function main(){
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--mute-audio']});const checks=[]
 try{
  for(const viewport of [{width:256,height:768},{width:192,height:640},{width:128,height:384},{width:512,height:1536},{width:800,height:2400}]){
   const context=await browser.newContext({viewport,permissions:[],serviceWorkers:'block'});let requests=0
   await context.route('**/*',route=>{requests++;assert.equal(new URL(route.request().url()).origin,'https://isolated.neighbour.test');return route.fulfill({contentType:'text/html; charset=utf-8',body:html})})
   const page=await context.newPage();await page.goto('https://isolated.neighbour.test')
   const result=await page.evaluate(()=>{const panel=document.querySelector('.resident-assistant-panel'),h=panel.querySelector('h2'),px=e=>parseFloat(getComputedStyle(e).fontSize),box=e=>{const b=e.getBoundingClientRect();return [b.left,b.top,b.right,b.bottom]};return {greeting:px(h),text:Array.from(panel.querySelectorAll('.resident-greeting,.resident-bubble p,.resident-bubble span,.resident-state-copy span,.resident-panel-status,textarea,button')).map(e=>({text:e.getAttribute('aria-label')||e.textContent.slice(0,35),px:px(e),box:box(e)})),width:document.documentElement.scrollWidth,panel:box(panel),transcript:panel.querySelector('.resident-transcript').clientHeight,scroll:panel.querySelector('.resident-transcript').scrollHeight}})
   assert.ok(result.greeting>=(viewport.width<=180?16:18))
   assert.ok(result.text.every(r=>r.px>=result.greeting-.2),'every readable LED text needs greeting size: '+JSON.stringify(result))
   assert.ok(result.width<=viewport.width+1)
   assert.ok(result.text.filter(x=>x.text==='鏡頭'||x.text==='下一位'||x.text==='正在聆聽・暫停'||x.text==='傳送').every(x=>x.box[0]>=0&&x.box[2]<=viewport.width+1&&x.box[1]>=0&&x.box[3]<=viewport.height+1),JSON.stringify(result))
   assert.ok(result.transcript>12&&result.scroll>result.transcript,'long large text remains scrollable without pushing controls away: '+JSON.stringify({viewport,...result}))
   checks.push({viewport,...result});assert.equal(requests,1);await context.close()
  }
  console.log(JSON.stringify({passed:true,checks,provider_media_EP:0}))
 }finally{await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1})
