import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mountCommunityProduct } from '../deploy/cloud/web/community-products.js'

function fixture({ reduced = false, ratio = 1 } = {}) {
  const frames = new Map(), events = new Map(), observers = []
  let sequence = 0, clock = 0
  const context = {
    paths: [], paints: 0, save() {}, restore() {}, ellipse() {}, stroke() {}, fill() {}, closePath() {},
    setTransform(...args) { this.transform = args }, clearRect() { this.paths = []; this.paints++ },
    beginPath() { this.current = [] }, moveTo(x,y) { this.current.push([x,y]); this.paths.push(this.current) },
    lineTo(x,y) { this.current.push([x,y]) },
  }
  const motion = { matches: reduced, handlers: new Set(), addEventListener(_type, fn) { this.handlers.add(fn) }, removeEventListener(_type,fn) { this.handlers.delete(fn) } }
  const observerClass = class {
    constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this) }
    observe(element) { this.element = element }
    disconnect() { this.disconnected = true }
  }
  const window = {
    devicePixelRatio: ratio, matchMedia() { return motion }, ResizeObserver: observerClass, IntersectionObserver: observerClass,
    requestAnimationFrame(callback) { const id = ++sequence; frames.set(id,callback); return id },
    cancelAnimationFrame(id) { frames.delete(id) },
  }
  const document = {
    hidden: false, defaultView: window,
    addEventListener(type,fn) { events.set(type,fn) }, removeEventListener(type,fn) { if(events.get(type) === fn) events.delete(type) },
    createElement(tag) {
      return {
        tag, ownerDocument: document, isConnected: true, children: [], style: {}, dataset: {}, attributes: {},
        append(...nodes) { this.children.push(...nodes); for(const node of nodes) node.parent=this },
        setAttribute(key,value) { this.attributes[key]=String(value) },
        getContext() { assert.equal(tag,'canvas'); return context },
        getBoundingClientRect() { return { width: 380, height: 280 } },
        remove() { this.isConnected=false; this.parent.children=this.parent.children.filter(node=>node!==this) },
      }
    },
  }
  const host=document.createElement('main')
  const step = (advance = 40) => {
    clock+=advance
    const pending=[...frames]; frames.clear(); for(const [,callback] of pending) callback(clock)
  }
  return { host, context, frames, events, observers, motion, document, step }
}

test('import needs no browser globals; products are original mesh illustrations with honest labels', () => {
  assert.throws(()=>mountCommunityProduct(null),/host required/)
  const f=fixture(), product=mountCommunityProduct(f.host)
  assert.equal(product.element.dataset.system,'eleuthia')
  assert.equal(product.element.children[1].textContent,'數字人示意')
  assert.ok(product.element.children[2].textContent.includes('並非平台目前選用的模型'))
  assert.ok(f.context.paths.length > 100,'individual mesh faces projected, not a rotating bitmap')
  for(const id of ['minerva','hades','hephaestus','poseidon','demeter','artemis','eleuthia','aether','apollo']) {
    product.setSystem(id)
    assert.equal(product.element.dataset.system,id)
    assert.ok(f.context.paths.length>12)
    assert.ok(f.context.paths.flat().every(point=>point.every(Number.isFinite)))
  }
  product.setSystem('aether')
  assert.equal(product.element.children[1].textContent,'感測器概念')
  assert.ok(product.element.children[2].textContent.includes('未來發展'))
  product.setSystem('hephaestus')
  assert.ok(product.element.children[2].textContent.includes('仍待實機驗收'))
  product.setSystem('<img src=x onerror=alert(1)>')
  assert.equal(product.element.dataset.system,'eleuthia')
  product.destroy()
})

test('actual face projections change at different angles, while reduced motion is a static mesh', () => {
  const f=fixture(), product=mountCommunityProduct(f.host,{system:'hephaestus'})
  const first=JSON.stringify(f.context.paths)
  for(let i=0;i<28;i++) f.step()
  assert.notEqual(JSON.stringify(f.context.paths),first)
  assert.equal(f.frames.size,1)
  product.destroy()
  const s=fixture({reduced:true}), still=mountCommunityProduct(s.host)
  const snapshot=JSON.stringify(s.context.paths), paints=s.context.paints
  for(let i=0;i<20;i++)s.step()
  assert.equal(JSON.stringify(s.context.paths),snapshot)
  assert.equal(s.context.paints,paints)
  assert.equal(s.frames.size,0)
  s.motion.matches=false; for(const handler of s.motion.handlers) handler()
  assert.equal(s.frames.size,1)
  s.motion.matches=true; for(const handler of s.motion.handlers) handler()
  assert.equal(s.frames.size,0)
  still.destroy()
})

test('pause, hidden document, offscreen and disconnected host stop animation, and destroy releases observers', () => {
  const f=fixture(), product=mountCommunityProduct(f.host)
  product.pause(); assert.equal(f.frames.size,0)
  product.resume(); assert.equal(f.frames.size,1)
  f.document.hidden=true; f.events.get('visibilitychange')(); assert.equal(f.frames.size,0)
  product.resume(); assert.equal(f.frames.size,0)
  f.document.hidden=false; f.events.get('visibilitychange')(); assert.equal(f.frames.size,1)
  const intersection=f.observers[1]
  intersection.callback([{isIntersecting:false}]); assert.equal(f.frames.size,0)
  intersection.callback([{isIntersecting:true}]); assert.equal(f.frames.size,1)
  f.host.isConnected=false; f.step(); assert.equal(f.frames.size,0)
  f.host.isConnected=true; product.resume(); assert.equal(f.frames.size,1)
  product.destroy(); product.destroy(); product.resume(); product.setSystem('apollo')
  assert.equal(f.frames.size,0)
  assert.equal(f.host.children.length,0)
  assert.ok(f.observers.every(observer=>observer.disconnected))
  assert.equal(f.events.size,0)
  assert.equal(f.motion.handlers.size,0)
})

test('high density devices have a bounded canvas allocation and no-context devices keep the text explanation', () => {
  const f=fixture({ratio:8}), product=mountCommunityProduct(f.host)
  const canvas=product.element.children[0]
  assert.equal(canvas.width,760)
  assert.equal(canvas.height,560)
  assert.deepEqual(f.context.transform,[2,0,0,2,0,0])
  product.destroy()
  const n=fixture(), create=n.document.createElement
  n.document.createElement=tag=>{const node=create(tag); if(tag==='canvas')node.getContext=()=>null; return node}
  const fallback=mountCommunityProduct(n.host,{system:'apollo'})
  assert.equal(fallback.element.children[1].textContent,'社區知識示意')
  assert.equal(n.frames.size,0)
  fallback.destroy()
})
