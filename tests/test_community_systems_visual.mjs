import assert from 'node:assert/strict'
import { test } from 'node:test'
import { COMMUNITY_SYSTEMS, mountCommunitySystems } from '../deploy/cloud/web/community-systems.js'

class Element {
  constructor(document, tag) { this.ownerDocument = document; this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.style = { setProperty() {} }; this.listeners = {} }
  append(node) { this.children.push(node); node.parent = this }
  setAttribute(name, value) { this.attributes[name] = String(value) }
  removeAttribute(name) { delete this.attributes[name]; if(name.startsWith('data-'))delete this.dataset[name.slice(5)] }
  addEventListener(name, fn) { this.listeners[name] = fn }
  focus() { this.ownerDocument.focused = this }
  remove() { this.parent.children = this.parent.children.filter(node => node !== this) }
}
function fixture() {
  const document = { defaultView: { matchMedia() { return { matches: true } } }, createElement(tag) { return new Element(document, tag) }, createElementNS(_ns, tag) { return new Element(document, tag) } }
  return new Element(document, 'main')
}
function all(node) { return [node, ...node.children.flatMap(all)] }
function system(host, id) { return all(host).find(node => node.tagName === 'li' && node.dataset.system === id) }
function hasText(node, text) { return all(node).some(item => item.textContent === text) }

test('constellation has exactly nine independently identified work divisions and original neighbourhood core', () => {
  assert.equal(COMMUNITY_SYSTEMS.length, 9)
  assert.equal(new Set(COMMUNITY_SYSTEMS.map(item => item.id)).size, 9)
  assert.equal(COMMUNITY_SYSTEMS.find(item => item.id === 'aether').name, '埃涅特')
  const host = fixture()
  mountCommunitySystems(host)
  assert.equal(all(host).filter(node => node.tagName === 'li').length, 9)
  assert.equal(system(host, 'artemis').dataset.state, 'planned')
  assert.equal(system(host, 'apollo').dataset.state, 'loading')
  assert.equal(all(host).find(node => node.tagName === 'img').src, '/assets/brand/neighbour-house-apricot-v1.webp')
  assert.ok(hasText(host, '鄰伴'))
  assert.ok(hasText(host, '燈號反映本次軟件檢查；實機、影像準確度及規劃項目另作驗收。'))
})

test('updates follow explicit checks, retain other state and reflect repair flow on the matching connection', () => {
  const host = fixture()
  const mounted = mountCommunitySystems(host)
  mounted.update({ systems: { minerva: { state: 'ready', detail: '登入流程已載入' }, hades: { state: 'repairing', detail: '正在重接必要畫面' }, hephaestus: 'offline' } })
  assert.equal(system(host, 'minerva').dataset.state, 'ready')
  assert.ok(hasText(system(host, 'minerva'), '已就緒'))
  assert.ok(hasText(system(host, 'hades'), '正在修復'))
  assert.equal(system(host, 'hephaestus').dataset.state, 'offline')
  const connection = all(host).find(node => node.attributes.class === 'community-system-link' && node.attributes['data-system'] === 'hades')
  assert.equal(connection.dataset.state, 'repairing')
  mounted.update({ hades: 'error' })
  assert.ok(hasText(system(host, 'hades'), '需處理'))
  assert.equal(system(host, 'minerva').dataset.state, 'ready')
  assert.equal(system(host, 'artemis').dataset.state, 'planned')
})

test('invalid status never turns green, hostile detail remains bounded literal text and destroy is inert', () => {
  const host = fixture()
  const mounted = mountCommunitySystems(host, { compact: true })
  const hostile = '<img onerror=alert(1) src=x>'
  mounted.update({ eleuthia: { state: 'success', detail: hostile.repeat(20) } })
  assert.equal(system(host, 'eleuthia').dataset.state, 'loading')
  assert.equal(system(host, 'eleuthia').title.length, 180)
  assert.ok(system(host, 'eleuthia').title.startsWith(hostile))
  assert.equal(all(host).filter(node => node.tagName === 'img').length, 1)
  mounted.destroy()
  mounted.update({ apollo: 'ready' })
  assert.equal(host.children.length, 0)
})

test('multiple mounts have independent labels and do not make a network or permission request', () => {
  const a = fixture(), b = fixture()
  const aa = mountCommunitySystems(a), bb = mountCommunitySystems(b)
  assert.notEqual(aa.element.attributes['aria-labelledby'], bb.element.attributes['aria-labelledby'])
  aa.update({ minerva: 'ready' })
  assert.equal(system(b, 'minerva').dataset.state, 'loading')
  assert.throws(() => mountCommunitySystems(null), /host required/)
})

test('overview reuses nine nodes, lazily mounts one illustrative product and retains genuine checks', () => {
  const host = fixture(), calls = []
  const mounted = mountCommunitySystems(host, { productFactory(_host, options) {
    calls.push(['mount', options.system])
    return { setSystem(id) { calls.push(['system', id]) }, pause() { calls.push(['pause']) }, resume() { calls.push(['resume']) }, destroy() { calls.push(['destroy']) } }
  } })
  assert.deepEqual(calls, [])
  mounted.update({ apollo: 'error', artemis: 'planned', hephaestus: 'offline' })
  mounted.overview('hephaestus')
  assert.equal(mounted.element.dataset.presentation, 'overview')
  assert.equal(all(host).filter(node => node.tagName === 'li').length, 9)
  assert.deepEqual(calls[0], ['mount', 'hephaestus'])
  assert.ok(hasText(host, '管理及離機規劃已有；S1 接入、真實定位及自主行車待現場驗收。'))
  assert.equal(all(system(host, 'hephaestus')).find(node => node.tagName === 'button').attributes['aria-pressed'], 'true')
  mounted.overview('apollo')
  assert.deepEqual(calls.filter(item => item[0] === 'mount').length, 1)
  assert.ok(hasText(host, '本次檢查：需處理'))
  assert.equal(system(host, 'apollo').dataset.state, 'error')
  assert.equal(system(host, 'artemis').dataset.state, 'planned')
  mounted.orbit()
  assert.equal(mounted.element.dataset.presentation, 'orbit')
  assert.equal(calls.at(-1)[0], 'pause')
  mounted.overview('eleuthia'); mounted.pause(); mounted.resume()
  assert.equal(calls.at(-1)[0], 'resume')
  mounted.destroy(); mounted.destroy()
  assert.equal(calls.filter(item => item[0] === 'destroy').length, 1)
})

function timedFixture() {
  const host = fixture(), tasks = new Map()
  let time = 0, next = 0
  host.ownerDocument.defaultView = {
    matchMedia() { return { matches: false } }, performance: { now: () => time },
    setTimeout(fn, delay) { const id = ++next; tasks.set(id, { at: time + delay, fn }); return id },
    clearTimeout(id) { tasks.delete(id) },
  }
  return { host, tasks, advance(ms) {
    const end = time + ms
    while (true) {
      const item = [...tasks].filter(([, job]) => job.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
      if (!item) break
      time = item[1].at; tasks.delete(item[0]); item[1].fn()
    }
    time = end
  } }
}

test('short entrance advances only presentation, pauses cleanly and finishes without declaring services healthy', async () => {
  const { host, tasks, advance } = timedFixture()
  const mounted = mountCommunitySystems(host)
  mounted.update({ minerva: 'error', eleuthia: 'loading', artemis: 'planned' })
  assert.equal(mounted.element.dataset.presentation, 'entrance')
  advance(560)
  assert.equal(mounted.element.dataset.spotlight, 'hephaestus')
  mounted.pause(); advance(10000)
  assert.equal(mounted.element.dataset.spotlight, 'hephaestus')
  const done = mounted.whenIntroduced()
  mounted.resume(); advance(2200)
  assert.equal(await done, true)
  assert.equal(mounted.element.dataset.presentation, 'orbit')
  assert.equal(system(host, 'minerva').dataset.state, 'error')
  assert.equal(system(host, 'eleuthia').dataset.state, 'loading')
  assert.equal(system(host, 'artemis').dataset.state, 'planned')
  assert.equal(tasks.size, 0)
  mounted.orbit({ replay: true });assert.equal(mounted.element.dataset.presentation, 'entrance')
  const cancelled = mounted.whenIntroduced(); mounted.destroy()
  assert.equal(await cancelled, false);assert.equal(tasks.size, 0)
})

test('reduced motion skips the timed introduction and keyboard selection opens the matching detail', async () => {
  const host = fixture(), selected = []
  const mounted = mountCommunitySystems(host, { productFactory(_host, value) {
    selected.push(value.system)
    return { setSystem(id) { selected.push(id) }, pause() {}, resume() {}, destroy() {} }
  } })
  assert.equal(mounted.element.dataset.presentation, 'orbit')
  assert.equal(await mounted.whenIntroduced(), true)
  const button = all(system(host, 'minerva')).find(node => node.tagName === 'button')
  let prevented = false
  button.listeners.keydown({ key: 'End', preventDefault() { prevented = true } })
  assert.equal(prevented, true)
  assert.deepEqual(selected, ['apollo'])
  assert.equal(host.ownerDocument.focused.attributes['aria-label'], '查看阿波羅 · 知識與記憶')
})
