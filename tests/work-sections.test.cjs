const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const test = require('node:test')

test('flat request care and report routes keep draft DOM and update category', () => {
  let change
  const events=[]
  const tabs=['requests','care','reports'].map(key=>({dataset:{workSection:key},attrs:{href:key==='requests'?'#work':`#${key}`},listeners:{},setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]},addEventListener(k,v){this.listeners[k]=v},focus(){}}))
  const nodes={caseWorkspace:{setAttribute(k,v){this[k]=v}},eventsPanel:{},caseHeading:{},draft:{value:'未儲存跟進'}}
  const location={hash:'#work'}
  const scope={location,document:{querySelectorAll:()=>tabs,getElementById:id=>nodes[id],dispatchEvent:event=>events.push(event.detail)},CustomEvent:class{constructor(name,options){this.detail=options.detail}},window:{addEventListener:(_,handler)=>{change=handler}}}
  vm.runInNewContext(fs.readFileSync('edge_hub/static/work-sections.js','utf8'),scope)
  assert.equal(nodes.eventsPanel.hidden,true)
  location.hash='#care';change()
  assert.equal(scope.ZhiweiWorkSection,'care')
  assert.equal(nodes.caseHeading.textContent,'關懷跟進')
  assert.equal(nodes.caseWorkspace.hidden,false)
  location.hash='#reports';change()
  assert.equal(nodes.caseWorkspace.hidden,true)
  assert.equal(nodes.eventsPanel.hidden,false)
  assert.equal(nodes.draft.value,'未儲存跟進')
  assert.deepEqual(events,['requests','care','reports'])
})
