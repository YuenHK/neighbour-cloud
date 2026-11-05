import { mountCommunityProduct } from './community-products.js'
// Original neighbourhood constellation. Presentation time never changes service checks.
export const COMMUNITY_SYSTEMS = Object.freeze([
  { id: 'minerva', name: '密涅瓦', code: 'MINERVA', role: '權限與通訊', icon: 'shield' },
  { id: 'hades', name: '黑底斯', code: 'HADES', role: '故障隔離與復原', icon: 'restore' },
  { id: 'hephaestus', name: '赫淮斯托斯', code: 'HEPHAESTUS', role: '機械工坊', icon: 'gear' },
  { id: 'poseidon', name: '波塞頓', code: 'POSEIDON', role: '水務觀察', icon: 'water' },
  { id: 'demeter', name: '得墨忒耳', code: 'DEMETER', role: '社區環境', icon: 'leaf' },
  { id: 'artemis', name: '阿耳忒彌斯', code: 'ARTEMIS', role: '生態共處', icon: 'paw' },
  { id: 'eleuthia', name: '艾莉提亞', code: 'ELEUTHIA', role: '居民關懷', icon: 'heart' },
  { id: 'aether', name: '埃涅特', code: 'AETHER', role: '煙霧與空氣觀察', icon: 'air' },
  { id: 'apollo', name: '阿波羅', code: 'APOLLO', role: '知識與記憶', icon: 'book' },
].map(item => Object.freeze(item)))

const STATES = Object.freeze({
  loading: ['處理中', '◌'], ready: ['已就緒', '✓'], error: ['需處理', '!'],
  repairing: ['正在修復', '↻'], offline: ['待現場驗收', '◇'], planned: ['規劃中', '–'],
})
const ICONS = Object.freeze({
  shield: ['M16 3 27 7v9c0 7-11 13-11 13S5 23 5 16V7Z', 'm11 16 4 4 7-8'],
  restore: ['M7 10a11 11 0 1 1-2 12', 'M7 3v8h8', 'M16 10v7l5 3'],
  gear: ['m13 3 6 0 1 4 4 2 4-1 3 5-3 3v4l3 3-3 5-4-1-4 2-1 4h-6l-1-4-4-2-4 1-3-5 3-3v-4l-3-3 3-5 4 1 4-2Z', 'M21 17a5 5 0 1 1-10 0 5 5 0 0 1 10 0'],
  water: ['M16 2S5 15 5 21a11 11 0 0 0 22 0C27 15 16 2 16 2Z', 'M11 21c0 4 4 6 7 4'],
  leaf: ['M27 4C12 1 3 8 6 20c4 13 22 9 21-16Z', 'M5 28 22 11', 'm12 13 1 7 8 1'],
  paw: ['M10 20c-9 9 0 13 6 9 7 4 15 0 6-9-4-5-8-5-12 0Z', 'M9 10c0 3-4 4-5 0s1-7 3-5Z', 'M15 7c0 4-4 4-5 0s1-7 3-5Z', 'M22 7c-1 4-5 4-5 0s3-7 4-5Z', 'M28 11c-1 4-5 3-5 0s3-6 5-4Z'],
  heart: ['M16 27 4 15C-3 6 9-2 16 7c7-9 19-1 12 8Z', 'M10 16h4l2-4 3 8 2-4h5'],
  air: ['M7 19a7 7 0 0 1 1-14 9 9 0 0 1 16 5c8-1 9 10 2 11', 'M4 24h17m-9 5h14', 'm25 21 3 3-3 3'],
  book: ['M16 8C12 4 6 4 2 6v21c4-2 10-2 14 2 4-4 10-4 14-2V6c-4-2-10-2-14 2Z', 'M16 8v21', 'M6 11h5m-5 5h5m10-5h5m-5 5h5'],
})
const NS = 'http://www.w3.org/2000/svg'
let sequence = 0
const EXPLANATIONS = Object.freeze({
  minerva: ['讓合適的人收到訊息、接手工作及安全操作。', '職員登入、工作提示及軟件保護已有；實機停止效果待現場核實。'],
  hades: ['把出錯部分分開處理，在保留資料的前提下嘗試安全重連。', '已有有限次數重試及備份復原流程；不會清除資料、用量或自行重送對話。'],
  hephaestus: ['機械人、巡查工作與數字人角色模型的協作工坊。', '管理及離機規劃已有；S1 接入、真實定位及自主行車待現場驗收。'],
  poseidon: ['從居民回報及現場線索，了解哪裏需要處理漏水或積水。', '居民回報流程已有；影像判斷須由職員核實，準確度待實景測試。'],
  demeter: ['整理垃圾、清潔與公共地方異常，讓需要更早被看見。', '回報流程已有；巡查辨識仍待實景驗收。'],
  artemis: ['為動物受困、寵物與社區生態需要預留的服務分工。', '未來發展：專門動物服務尚未實裝。'],
  eleuthia: ['親切聆聽居民，了解生活與情緒需要，協助職員及早跟進。', '對話、初步支援及關懷分流已有；並非醫療診斷，實際支援由職員跟進。'],
  aether: ['整理煙霧及火警候選線索，交給職員核實。', '影像辨識待實景驗收；空氣感測器屬未來發展，不能代替消防設備。'],
  apollo: ['把屋苑知識、搜尋與記憶連起來，讓對話前後相連。', '已有查詢、本輪上下文及明確長期記憶；沿用原有保存與交接規則。'],
})

function append(document, parent, tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text !== undefined) node.textContent = text
  parent.append(node)
  return node
}

function svgNode(document, tag, attributes) {
  const node = document.createElementNS(NS, tag)
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value))
  return node
}

function icon(document, name) {
  const node = svgNode(document, 'svg', { viewBox: '0 0 34 34', 'aria-hidden': 'true', fill: 'none' })
  for (const path of ICONS[name]) node.append(svgNode(document, 'path', { d: path }))
  return node
}

// Fit the complete card, including actions and legends. Measure untransformed
// layout so changing the scale cannot trigger a resize feedback loop.
function fitViewportCard(card) {
  const window = card?.ownerDocument?.defaultView
  const parent = card?.parentElement
  if (!window || !parent || typeof window.ResizeObserver !== 'function') return null
  let closed = false, frame = null
  function refresh() {
    if (closed || !parent.clientWidth || !parent.clientHeight || !card.offsetHeight) return
    const style = window.getComputedStyle(parent)
    const width = parent.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
    const height = parent.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)
    const scale = Math.max(.1, Math.min(1, width / Math.max(card.offsetWidth, card.scrollWidth), height / Math.max(card.offsetHeight, card.scrollHeight)))
    card.style.setProperty('--viewport-scale', scale.toFixed(5))
  }
  function schedule() {
    if (closed || frame !== null) return
    frame = window.requestAnimationFrame(() => { frame = null; refresh() })
  }
  const observer = new window.ResizeObserver(schedule)
  observer.observe(parent); observer.observe(card)
  window.addEventListener('resize', schedule)
  window.visualViewport?.addEventListener('resize', schedule)
  refresh()
  return { refresh, destroy() {
    closed = true; observer.disconnect()
    if (frame !== null) window.cancelAnimationFrame(frame)
    window.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('resize', schedule)
  } }
}

export function mountCommunitySystems(host, { compact = false, label = '鄰伴 · 九大協作子功能', productFactory = mountCommunityProduct } = {}) {
  if (!host?.ownerDocument || typeof host.append !== 'function') throw new TypeError('community systems host required')
  const document = host.ownerDocument
  const root = append(document, host, 'section', `community-systems${compact ? ' community-systems--compact' : ''}`)
  const own = `community-systems-${++sequence}`
  root.setAttribute('aria-labelledby', `${own}-heading`)
  const heading = append(document, root, 'h2', 'community-systems-heading', label)
  heading.id = `${own}-heading`
  const spotlight = append(document, root, 'p', 'community-systems-spotlight')
  spotlight.setAttribute('aria-hidden', 'true')
  const spotlightName = append(document, spotlight, 'strong', '')
  const spotlightRole = append(document, spotlight, 'span', '')
  const spotlightStatus = append(document, spotlight, 'span', 'community-spotlight-state')
  const scene = append(document, root, 'div', 'community-systems-scene')
  const links = svgNode(document, 'svg', { class: 'community-system-links', viewBox: '0 0 940 720', 'aria-hidden': 'true', focusable: 'false' })
  scene.append(links)
  for (const radius of [106, 138, 190]) links.append(svgNode(document, 'circle', { class: 'community-orbit', cx: 470, cy: 360, r: radius }))
  const center = append(document, scene, 'div', 'community-systems-core')
  const halo = append(document, center, 'span', 'community-core-halo')
  halo.setAttribute('aria-hidden', 'true')
  const platform = append(document, center, 'span', 'community-core-platform')
  platform.setAttribute('aria-hidden', 'true')
  append(document, platform, 'span', 'community-core-disc')
  const mascot = append(document, center, 'img', 'community-core-mascot')
  mascot.src = '/assets/brand/neighbour-house-apricot-v1.webp'
  mascot.alt = ''
  mascot.width = 100
  mascot.height = 100
  mascot.decoding = 'async'
  append(document, center, 'strong', 'community-core-name', '鄰伴')
  append(document, center, 'span', 'community-core-caption', '一起照顧社區')
  const list = append(document, scene, 'ul', 'community-systems-nodes')
  const refs = new Map()
  for (const [index, system] of COMMUNITY_SYSTEMS.entries()) {
    const angle = (-90 + index * 40) * Math.PI / 180
    const x = 470 + Math.cos(angle) * 365
    const y = 360 + Math.sin(angle) * 300
    const line = svgNode(document, 'g', { class: 'community-system-link', 'data-system': system.id, 'data-state': 'loading' })
    line.style.setProperty('--system-order', index)
    const path = `M470 360 Q${470 + Math.cos(angle - .22) * 190} ${360 + Math.sin(angle - .22) * 130} ${x.toFixed(2)} ${y.toFixed(2)}`
    line.append(svgNode(document, 'path', { class: 'community-link-base', d: path, pathLength: 1 }))
    line.append(svgNode(document, 'path', { class: 'community-link-flow', d: path }))
    links.append(line)
    const node = append(document, list, 'li', 'community-system-node')
    node.dataset.system = system.id
    node.style.setProperty('--system-order', index)
    node.style.setProperty('--system-x', `${x / 9.4}%`)
    node.style.setProperty('--system-y', `${y / 7.2}%`)
    node.style.setProperty('--system-from-x', `${(470 - x) / 9.4}cqw`)
    node.style.setProperty('--system-from-y', `${(360 - y) / 9.4}cqw`)
    const symbol = append(document, node, 'span', 'community-system-symbol')
    symbol.append(icon(document, system.icon))
    append(document, node, 'span', 'community-system-code', system.code)
    append(document, node, 'strong', 'community-system-name', system.name)
    append(document, node, 'span', 'community-system-role', system.role)
    const status = append(document, node, 'span', 'community-system-status')
    const mark = append(document, status, 'span', 'community-system-status-mark')
    mark.setAttribute('aria-hidden', 'true')
    const statusText = append(document, status, 'span', '')
    const detail = append(document, node, 'span', 'community-system-detail')
    const select = append(document, node, 'button', 'community-system-select')
    select.type = 'button'
    select.setAttribute('aria-label', `查看${system.name} · ${system.role}`)
    select.setAttribute('aria-pressed', 'false')
    select.addEventListener('click', () => overview(system.id))
    select.addEventListener('keydown', event => {
      const moves = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }
      if (!(event.key in moves) && !['Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 8 : (index + moves[event.key] + 9) % 9
      overview(COMMUNITY_SYSTEMS[next].id)
      refs.get(COMMUNITY_SYSTEMS[next].id).select.focus()
    })
    refs.set(system.id, { node, line, statusText, mark, detail, select, state: system.id === 'artemis' ? 'planned' : 'loading' })
  }
  const overviewPanel = append(document, scene, 'div', 'community-system-overview')
  overviewPanel.hidden = true
  overviewPanel.setAttribute('aria-labelledby', `${own}-detail`)
  append(document, overviewPanel, 'p', 'community-overview-eyebrow', '九個分工 · 一個社區')
  const detailCode = append(document, overviewPanel, 'p', 'community-overview-code')
  const detailTitle = append(document, overviewPanel, 'h3', 'community-overview-title')
  detailTitle.id = `${own}-detail`
  const detailRole = append(document, overviewPanel, 'p', 'community-overview-role')
  const detailPurpose = append(document, overviewPanel, 'p', 'community-overview-purpose')
  const detailStatus = append(document, overviewPanel, 'p', 'community-overview-status')
  const productHost = append(document, overviewPanel, 'div', 'community-product-host')
  const detailLimit = append(document, overviewPanel, 'p', 'community-overview-limit')
  const back = append(document, overviewPanel, 'button', 'community-overview-back', '返回協作圓盤')
  back.type = 'button'
  back.addEventListener('click', () => orbit())
  const legend = append(document, root, 'p', 'community-systems-legend')
  for (const [state, text] of [['ready', '就緒'], ['loading', '處理中'], ['error', '異常'], ['repairing', '修復中'], ['planned', '規劃／待驗收']]) {
    const item = append(document, legend, 'span', '')
    item.dataset.state = state
    append(document, item, 'i', '')?.setAttribute('aria-hidden', 'true')
    append(document, item, 'span', '', text)
  }
  append(document, root, 'p', 'community-systems-note', '燈號反映本次軟件檢查；實機、影像準確度及規劃項目另作驗收。')
  const view = document.defaultView
  const reduced = view?.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  const schedule = view?.setTimeout?.bind(view) || globalThis.setTimeout
  const cancel = view?.clearTimeout?.bind(view) || globalThis.clearTimeout
  const now = () => view?.performance?.now?.() ?? Date.now()
  let destroyed = false, paused = false, product, selected = 'eleuthia', introTimer, introDue = 0, introDelay = 0, introIndex = -1
  let introduced = true, introWaiters = [], motion = []
  function finishIntroduction() {
    cancel(introTimer); introTimer = undefined
    introduced = true
    root.removeAttribute('data-spotlight')
    for (const ref of refs.values()) ref.node.removeAttribute('data-spotlight')
    if (root.dataset.presentation === 'entrance') root.dataset.presentation = 'orbit'
    spotlight.hidden = true
    for (const resolve of introWaiters.splice(0)) resolve(!destroyed)
  }
  function introTick() {
    if (destroyed || paused || root.dataset.presentation !== 'entrance') return
    introIndex++
    if (introIndex >= COMMUNITY_SYSTEMS.length) { finishIntroduction(); return }
    const current = COMMUNITY_SYSTEMS[introIndex]
    root.dataset.spotlight = current.id
    for (const [id, ref] of refs) ref.node.dataset.spotlight = String(id === current.id)
    spotlightName.textContent = current.name
    spotlightRole.textContent = current.role
    spotlightStatus.textContent = STATES[refs.get(current.id).state][0]
    introDelay = 280; introDue = now() + introDelay
    introTimer = schedule(introTick, introDelay)
    introTimer?.unref?.()
  }
  function beginIntroduction() {
    finishIntroduction()
    root.dataset.presentation = reduced ? 'orbit' : 'entrance'
    if (reduced) return
    introduced = false; introIndex = -1; spotlight.hidden = false
    introTick()
  }
  function selection() {
    const current = COMMUNITY_SYSTEMS.find(item => item.id === selected)
    const ref = refs.get(selected)
    detailCode.textContent = current.code
    detailTitle.textContent = current.name
    detailRole.textContent = current.role
    detailPurpose.textContent = EXPLANATIONS[selected][0]
    detailLimit.textContent = EXPLANATIONS[selected][1]
    detailStatus.textContent = `本次檢查：${STATES[ref.state][0]}${ref.detail.textContent ? ` · ${ref.detail.textContent}` : ''}`
    detailStatus.dataset.state = ref.state
    for (const [id, item] of refs) {
      item.node.dataset.selected = String(id === selected)
      item.select.setAttribute('aria-pressed', String(id === selected))
    }
  }
  function animateLayout(previous) {
    if (reduced || paused) return
    for (const item of motion) item.cancel?.()
    motion = []
    for (const [id, ref] of refs) {
      const before = previous.get(id), after = ref.node.getBoundingClientRect?.()
      if (!before || !after || !after.width || typeof ref.node.animate !== 'function') continue
      motion.push(ref.node.animate([
        { transform: `translate(${before.left - after.left}px,${before.top - after.top}px) scale(${before.width / after.width},${before.height / after.height})`, transformOrigin: 'top left' },
        { transform: 'none', transformOrigin: 'top left' },
      ], { duration: 650, easing: 'cubic-bezier(.22,.8,.25,1)' }))
    }
  }
  function overview(id = selected) {
    if (destroyed) return
    if (refs.has(id)) selected = id
    const previous = new Map([...refs].map(([key, ref]) => [key, ref.node.getBoundingClientRect?.()]))
    const changed = root.dataset.presentation !== 'overview'
    finishIntroduction()
    root.dataset.presentation = 'overview'
    overviewPanel.hidden = false
    selection()
    if (!product) product = productFactory(productHost, { system: selected })
    else product.setSystem(selected)
    if (paused) product.pause()
    else product.resume()
    if (changed) animateLayout(previous)
    fit?.refresh()
  }
  function orbit({ replay = false } = {}) {
    if (destroyed) return
    product?.pause()
    for (const item of motion) item.cancel?.()
    motion = []
    overviewPanel.hidden = true
    root.dataset.presentation = 'orbit'
    if (replay && !paused) beginIntroduction()
    else finishIntroduction()
    fit?.refresh()
  }
  function pause() {
    if (destroyed || paused) return
    paused = true
    root.dataset.paused = 'true'
    if (!introduced) { introDelay = Math.max(0, introDue - now()); cancel(introTimer) }
    for (const item of motion) item.pause?.()
    product?.pause()
  }
  function resume() {
    fit?.refresh()
    if (destroyed || !paused) return
    paused = false
    root.removeAttribute('data-paused')
    for (const item of motion) item.play?.()
    if (!introduced && root.dataset.presentation === 'entrance') {
      introDue = now() + introDelay
      introTimer = schedule(introTick, introDelay)
      introTimer?.unref?.()
    }
    if (root.dataset.presentation === 'overview') product?.resume()
  }
  function update(snapshot = {}) {
    if (destroyed) return
    const incoming = snapshot?.systems ?? snapshot
    for (const [id, ref] of refs) {
      const value = incoming?.[id]
      if (value !== undefined) {
        const proposed = typeof value === 'string' ? value : value?.state
        ref.state = Object.hasOwn(STATES, proposed) ? proposed : 'loading'
        const text = typeof value?.detail === 'string' ? value.detail.slice(0, 180) : ''
        ref.detail.textContent = text
        ref.node.title = text
        ref.detail.hidden = !text
      }
      const [text, symbol] = STATES[ref.state]
      ref.node.dataset.state = ref.state
      ref.line.dataset.state = ref.state
      ref.statusText.textContent = text
      ref.mark.textContent = symbol
    }
    if (root.dataset.presentation === 'overview') selection()
    if (root.dataset.spotlight) spotlightStatus.textContent = STATES[refs.get(root.dataset.spotlight).state][0]
    fit?.refresh()
  }
  const fit = fitViewportCard(root.closest?.('[data-viewport-fit]'))
  update()
  beginIntroduction()
  return {
    element: root,
    update,
    overview, orbit, pause, resume,
    whenIntroduced() { return introduced || destroyed ? Promise.resolve(!destroyed) : new Promise(resolve => introWaiters.push(resolve)) },
    destroy() { if (destroyed) return; destroyed = true; fit?.destroy(); finishIntroduction(); product?.destroy(); for (const item of motion) item.cancel?.(); root.remove(); refs.clear() },
  }
}

