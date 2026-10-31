const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const test = require('node:test')

class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.value = ''; this.disabled = false }
  append(...items) { for (const item of items) { item.remove?.(); this.children.push(item); item.parent = this } }
  insertBefore(item, before) { item.remove(); const at = before ? this.children.indexOf(before) : -1; this.children.splice(at < 0 ? this.children.length : at,0,item); item.parent = this }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this),1); this.parent = null }
  contains(item) { return this === item || this.children.some(child => child.contains?.(item)) }
  get firstChild() { return this.children[0] || null }
  matches(selector) { return selector.split(',').some(s => s === this.tag || (s === 'dialog[open]' && this.tag === 'dialog' && this.open) || (s === 'button:not([data-case-close])' && this.tag === 'button' && !this.dataset.caseClose)) }
  querySelectorAll(selector) { return this.children.flatMap(child => [ ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]) }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) || null }
  showModal() { this.open = true }
  close() { this.open = false; this.listeners.close?.() }
  focus() {}
  addEventListener(name, fn) { this.listeners[name] = fn }
  setAttribute() {}
}

function row(id, stamp) { return { id: id.repeat(32), kind: 'general', status: 'new', revision: 1, message: '公開測試', location: '', contact: '', created_at_ms: stamp } }
const flush = () => new Promise(resolve => setImmediate(resolve))

function harness() {
  const nodes = Object.fromEntries(['operatorKey','caseAlert','caseNewCount','caseActiveCount','caseClosedCount','serviceCases','caseStatus','casesPage','casesPrevious','casesNext'].map(id=>[id,new Element()]))
  nodes.operatorKey.value = 'synthetic'
  const events = {}, intervals = [], calls = []
  let tones = 0, answer = {items:[row('a',1)],counts:{new:1},has_more:false,latest_created_at_ms:1}, fail = false, audioFail = false
  const document = { activeElement:null, title:'管理', hidden:false, getElementById:id=>nodes[id], createElement:tag=>new Element(tag), addEventListener:(name,fn)=>{events[name]=fn} }
  class Audio {
    constructor() { this.state = 'suspended'; this.currentTime = 0; this.destination = {} }
    async resume() { this.state = 'running' }
    createOscillator() { if (audioFail) throw new Error('device unavailable'); return { frequency:{}, connect(){}, start(){tones++}, stop(){} } }
    createGain() { return {gain:{},connect(){}} }
  }
  const scope = {document, AudioContext:Audio, AbortSignal, queueMicrotask, setInterval:fn=>intervals.push(fn), fetch:async (url,options)=>{
    calls.push({url,options}); if (fail) throw new Error('offline')
    return {ok:true,json:async()=>answer}
  }}
  vm.runInNewContext(fs.readFileSync('edge_hub/static/service-workbench.js','utf8'),scope)
  return {nodes,events,intervals,calls,document,setAnswer:value=>{answer=value},setFail:value=>{fail=value},setAudioFail:value=>{audioFail=value},tones:()=>tones}
}

test('new cases update during typing and default sound needs no checkbox or staff name', async()=>{
  const h=harness(); await flush()
  const card=h.nodes.serviceCases.children[0], input=card.querySelectorAll('textarea')[0]
  input.value='未寫完'; input.listeners.input(); h.document.activeElement=input
  h.setAnswer({items:[row('a',1),row('b',2)],counts:{new:2},has_more:false,latest_created_at_ms:2})
  h.intervals[0](); await flush()
  assert.equal(h.nodes.serviceCases.children.length,2)
  assert.equal(h.nodes.serviceCases.children[0],card)
  assert.equal(input.value,'未寫完')
  assert.equal(h.tones(),0)
  await h.events.pointerdown(); await flush()
  assert.equal(h.tones(),1)
  h.intervals[0](); await flush(); assert.equal(h.tones(),1)
  h.document.activeElement=null
  card.querySelectorAll('button').find(button => button.textContent === '接手跟進').listeners.click(); await flush(); await flush()
  const edit=h.calls.find(call=>call.options.method==='PATCH')
  assert.equal(JSON.parse(edit.options.body).assignee,'管理團隊')
  assert.equal(JSON.parse(edit.options.body).note,'未寫完')
})

test('failed refresh recovers automatically without replacing a focused draft', async()=>{
  const h=harness(); await flush()
  const button=h.nodes.serviceCases.children[0].querySelectorAll('button')[0]
  h.setFail(true); h.intervals[0](); await flush(); assert.equal(button.disabled,true)
  h.setFail(false); h.intervals[0](); await flush(); assert.equal(button.disabled,false)
  assert.match(h.nodes.caseStatus.textContent,/已更新/)
})

test('newer revision preserves draft and prevents stale edit until focus leaves', async()=>{
  const h=harness(); await flush()
  const old=h.nodes.serviceCases.children[0], input=old.querySelectorAll('textarea')[0]
  input.value='草稿'; input.listeners.input(); h.document.activeElement=input
  h.setAnswer({items:[{...row('a',1),revision:2,note:'另一同事已更新'}],counts:{new:1},has_more:false,latest_created_at_ms:1})
  h.intervals[0](); await flush()
  assert.equal(h.nodes.serviceCases.children[0],old)
  assert.equal(old.querySelectorAll('button')[0].disabled,true)
  h.document.activeElement=null; h.nodes.serviceCases.listeners.focusout(); await flush()
  const updated=h.nodes.serviceCases.children[0]
  assert.equal(h.nodes.serviceCases.children.length,1)
  assert.notEqual(updated,old)
  assert.equal(updated.querySelectorAll('textarea')[0].value,'草稿')
  assert.equal(updated.dataset.revision,'2')
})

test('global case cursor announces another category even at the same timestamp', async()=>{
  const h=harness(); await flush()
  await h.events.pointerdown(); await flush()
  h.setAnswer({items:[row('a',1)],counts:{new:1},has_more:false,latest_created_at_ms:1,latest_case_number:100001})
  h.intervals[0](); await flush()
  assert.equal(h.tones(),0)
  h.setAnswer({items:[row('a',1)],counts:{new:1},has_more:false,latest_created_at_ms:1,latest_case_number:100002})
  h.intervals[0](); await flush()
  assert.equal(h.tones(),1)
  h.intervals[0](); await flush()
  assert.equal(h.tones(),1)
})

test('an unavailable speaker cannot prevent new cases appearing', async()=>{
  const h=harness(); await flush()
  await h.events.pointerdown(); await flush(); h.setAudioFail(true)
  h.setAnswer({items:[row('a',1),row('b',2)],counts:{new:2},has_more:false,latest_created_at_ms:2})
  h.intervals[0](); await flush()
  assert.equal(h.nodes.serviceCases.children.length,2)
  assert.match(h.nodes.caseStatus.textContent,/已更新/)
})

test('staff correction sends only verified fields and keeps polling draft', async()=>{
  const h=harness(); await flush()
  const card=h.nodes.serviceCases.children[0]
  const inputs=card.querySelectorAll('input')
  inputs[0].value='B座12樓A室'; inputs[0].listeners.input()
  inputs[2].value='居民更正單位'; inputs[2].listeners.input()
  h.document.activeElement=inputs[0]
  h.intervals[0](); await flush()
  assert.equal(h.nodes.serviceCases.children[0],card)
  assert.equal(inputs[0].value,'B座12樓A室')
  h.document.activeElement=null
  const save=card.querySelectorAll('button').find(button=>button.textContent==='儲存更正')
  save.listeners.click(); await flush(); await flush()
  const edit=h.calls.find(call=>call.options.method==='PATCH')
  assert.ok(edit.url.endsWith('/details'))
  const body=JSON.parse(edit.options.body)
  assert.equal(body.location,'B座12樓A室')
  assert.equal(body.reason,'居民更正單位')
  assert.equal(body.expected_revision,1)
  assert.equal(body.status,undefined)
})

test('staff correction needs a reason before any write', async()=>{
  const h=harness(); await flush()
  const save=h.nodes.serviceCases.children[0].querySelectorAll('button').find(button=>button.textContent==='儲存更正')
  save.listeners.click(); await flush()
  assert.ok(!h.calls.some(call=>call.options.method==='PATCH'))
  assert.match(h.nodes.caseStatus.textContent,/更正原因/)
})
