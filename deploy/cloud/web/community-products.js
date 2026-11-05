// Original small 3D illustrations: mesh faces are projected and shaded on a
// transparent canvas. No avatar files, external renderer or device access.
const PRODUCTS = Object.freeze({
  minerva: ['通訊與權限示意', '登入與安全控制分工；不代表已連接現場設備。'],
  hades: ['修復與備份示意', '安全復原分工；不會自行重設居民資料或免費額度。'],
  hephaestus: ['巡查機械人示意', '示意機體；S1、定位及自主行車仍待實機驗收。'],
  poseidon: ['水務觀察示意', '漏水與積水線索須由職員到場核實。'],
  demeter: ['社區環境示意', '回報流程已有；影像辨識仍待實景驗收。'],
  artemis: ['生態共處規劃', '未來構想；尚未實裝專門動物服務。'],
  eleuthia: ['數字人示意', '原創抽象角色，並非平台目前選用的模型。'],
  aether: ['感測器概念', '未來發展；不代表已安裝空氣感測器。'],
  apollo: ['社區知識示意', '屋苑資料、搜尋及明確保存的記憶，共同支援服務。'],
})
const PALETTE = Object.freeze({
  ivory: [228, 245, 255], blue: [77, 151, 204], cyan: [91, 216, 223],
  dark: [27, 61, 85], ink: [11, 38, 62], gold: [250, 191, 119],
  skin: [252, 215, 186], blush: [245, 155, 158], green: [132, 204, 177],
})
const TAU = Math.PI * 2
const add = (a, b) => a.map((v, i) => v + b[i])
const sub = (a, b) => a.map((v, i) => v - b[i])
const mul = (a, n) => a.map(v => v * n)
const dot = (a, b) => a.reduce((n, v, i) => n + v * b[i], 0)
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
function unit(a) { return mul(a, 1 / (Math.hypot(...a) || 1)) }
function rotateY([x, y, z], angle) { return [x * Math.cos(angle) + z * Math.sin(angle), y, z * Math.cos(angle) - x * Math.sin(angle)] }
function rotateZ([x, y, z], angle) { return [x * Math.cos(angle) - y * Math.sin(angle), x * Math.sin(angle) + y * Math.cos(angle), z] }

function mesh(vertices, faces, color, wave = false) { return { vertices, faces, color, wave } }
function box(center, size, color, wave = false) {
  const [x, y, z] = size.map(v => v / 2)
  return mesh([[-x,-y,-z],[x,-y,-z],[x,y,-z],[-x,y,-z],[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]].map(v => add(v, center)),
    [[0,3,2,1],[4,5,6,7],[0,1,5,4],[3,7,6,2],[1,2,6,5],[0,4,7,3]], color, wave)
}
function ellipsoid(center, radius, color, segments = 12, rings = 7, wave = false) {
  const vertices = [], faces = []
  for (let r = 0; r <= rings; r++) for (let s = 0; s < segments; s++) {
    const a = Math.PI * r / rings, b = TAU * s / segments
    vertices.push(add(center, [Math.sin(a) * Math.cos(b) * radius[0], Math.cos(a) * radius[1], Math.sin(a) * Math.sin(b) * radius[2]]))
  }
  for (let r = 0; r < rings; r++) for (let s = 0; s < segments; s++) {
    const next = (s + 1) % segments, a = r * segments, b = (r + 1) * segments
    if (r !== 0) faces.push([a + s, b + s, b + next])
    if (r !== rings - 1) faces.push([a + s, b + next, a + next])
  }
  return mesh(vertices, faces, color, wave)
}
function cylinder(a, b, radius, color, segments = 12, endRadius = radius, wave = false) {
  const direction = unit(sub(b, a)), axis = Math.abs(direction[1]) > .9 ? [1,0,0] : [0,1,0]
  const u = unit(cross(direction, axis)), v = cross(direction, u), vertices = [], faces = []
  for (const [center, rad] of [[a, radius], [b, endRadius]]) for (let i = 0; i < segments; i++) {
    const theta = TAU * i / segments
    vertices.push(add(center, add(mul(u, Math.cos(theta) * rad), mul(v, Math.sin(theta) * rad))))
  }
  for (let i = 0; i < segments; i++) {
    const n = (i + 1) % segments
    faces.push([i, n, n + segments, i + segments])
  }
  faces.push(Array.from({ length: segments }, (_, i) => segments - 1 - i), Array.from({ length: segments }, (_, i) => segments + i))
  return mesh(vertices, faces, color, wave)
}
function extrusion(points, depth, color) {
  const count = points.length
  const vertices = [-depth / 2, depth / 2].flatMap(z => points.map(([x, y]) => [x, y, z]))
  const faces = [Array.from({ length: count }, (_, i) => count - i - 1), Array.from({ length: count }, (_, i) => count + i)]
  for (let i = 0; i < count; i++) { const n = (i + 1) % count; faces.push([i, n, n + count, i + count]) }
  return mesh(vertices, faces, color)
}
function torus(center, major, minor, color, axis = 'y') {
  const vertices = [], faces = [], sides = 6, segments = 24
  for (let i = 0; i < segments; i++) for (let j = 0; j < sides; j++) {
    const a = TAU * i / segments, b = TAU * j / sides
    const point = [(major + minor * Math.cos(b)) * Math.cos(a), minor * Math.sin(b), (major + minor * Math.cos(b)) * Math.sin(a)]
    vertices.push(add(center, axis === 'z' ? [point[0], point[2], point[1]] : point))
  }
  for (let i = 0; i < segments; i++) for (let j = 0; j < sides; j++) faces.push([
    i * sides + j, ((i + 1) % segments) * sides + j,
    ((i + 1) % segments) * sides + (j + 1) % sides, i * sides + (j + 1) % sides,
  ])
  return mesh(vertices, faces, color)
}
function move(item, delta) { item.vertices = item.vertices.map(v => add(v, delta)); return item }
function turn(item, radians) { item.vertices = item.vertices.map(v => rotateZ(v, radians)); return item }

function person() {
  const c = PALETTE, items = [
    box([-.25,-1.08,0], [.25,.75,.29], c.ivory), box([.25,-1.08,0], [.25,.75,.29], c.ivory),
    ellipsoid([-.25,-1.46,.1], [.23,.13,.34], c.blue, 10, 5), ellipsoid([.25,-1.46,.1], [.23,.13,.34], c.blue, 10, 5),
    cylinder([0,-.75,0], [0,.4,0], .55, c.blue, 10, .37),
    cylinder([0,.33,0], [0,.48,0], .34, c.ivory, 12),
    cylinder([0,.43,0], [0,.63,0], .15, c.skin, 10),
    ellipsoid([0,1.05,-.08], [.55,.59,.42], c.dark, 14, 8),
    ellipsoid([0,1.05,.14], [.46,.5,.39], c.skin, 14, 8),
    ellipsoid([-.4,1.52,-.07], [.2,.19,.18], c.dark, 10, 5),
    ellipsoid([.4,1.52,-.07], [.2,.19,.18], c.dark, 10, 5),
    ellipsoid([-.17,1.12,.49], [.055,.077,.04], c.ink, 8, 5),
    ellipsoid([.17,1.12,.49], [.055,.077,.04], c.ink, 8, 5),
    ellipsoid([-.3,.96,.45], [.08,.04,.025], c.blush, 8, 4),
    ellipsoid([.3,.96,.45], [.08,.04,.025], c.blush, 8, 4),
    ellipsoid([0,.85,.49], [.09,.037,.025], c.blush, 8, 4),
    cylinder([-.39,.32,0], [-.68,-.23,.02], .12, c.ivory, 10),
    ellipsoid([-.7,-.28,.04], [.13,.16,.13], c.skin, 8, 5),
    cylinder([.38,.33,0], [.69,.68,0], .12, c.ivory, 10, .1, true),
    cylinder([.69,.68,0], [.76,1.05,0], .1, c.ivory, 10, .085, true),
    ellipsoid([.77,1.16,.02], [.14,.18,.11], c.skin, 10, 5, true),
    box([0,-.03,.47], [.3,.29,.04], c.cyan),
    box([0,-.03,.5], [.12,.12,.025], c.ivory),
  ]
  return items
}
function robot() {
  const c = PALETTE, items = [
    box([0,-.66,0], [1.65,.57,1.03], c.blue), box([0,-.3,.02], [1.35,.2,.9], c.ivory),
    cylinder([0,-.2,0], [0,.47,0], .17, c.dark),
    box([0,.62,.06], [1.08,.63,.66], c.ivory), box([0,.61,.42], [.78,.33,.06], c.dark),
    cylinder([0,.62,.42], [0,.62,.52], .14, c.cyan, 14),
    cylinder([0,.62,.52], [0,.62,.55], .075, c.ink, 12),
    cylinder([.4,.97,-.12], [.4,1.45,-.12], .035, c.blue, 8), ellipsoid([.4,1.47,-.12], [.085,.085,.085], c.gold, 8, 5),
    box([0,-.62,.56], [.58,.13,.04], c.cyan),
  ]
  for (const x of [-.88, .88]) for (const z of [-.36,.36]) {
    const sign = Math.sign(x)
    items.push(cylinder([x,-.92,z], [x + sign * .19,-.92,z], .28, c.dark, 14),
      cylinder([x + sign * .195,-.92,z], [x + sign * .215,-.92,z], .13, c.cyan, 12))
  }
  return items
}
function sensor() {
  const c = PALETTE, items = [
    cylinder([0,-1.4,0], [0,-1.2,0], .76, c.blue, 16),
    cylinder([0,-1.22,0], [0,.85,0], .47, c.ivory, 12, .41),
    cylinder([0,.85,0], [0,1.1,0], .48, c.blue, 12, .35),
    cylinder([0,1.1,0], [0,1.5,0], .04, c.cyan, 8), ellipsoid([0,1.55,0], [.1,.1,.1], c.gold, 8, 5),
    box([0,.22,.445], [.44,.59,.03], c.dark), box([0,.26,.47], [.27,.17,.02], c.cyan),
  ]
  for (let i = 0; i < 4; i++) items.push(box([0,-.4 - i * .15,.45], [.44,.035,.025], c.blue))
  items.push(torus([0,1.23,0], .42, .025, c.cyan), torus([0,1.37,0], .62, .018, c.blue))
  return items
}
function books() {
  const c = PALETTE, items = []
  for (const [x, color, height] of [[-.72,c.blue,2],[-.24,c.cyan,2.35],[.25,c.gold,1.82],[.7,c.ivory,2.12]]) {
    items.push(box([x,-1.3 + height / 2,0], [.37,height,.85], color), box([x + .02,-1.3 + height / 2,.44], [.25,height - .2,.04], c.ivory))
    for (let i = 0; i < 3; i++) items.push(box([x,-.3 + i * .1,.48], [.2,.025,.025], c.dark))
  }
  items.push(box([0,-1.39,0], [2.1,.13,1.05], c.dark))
  return items
}
function water() {
  const c = PALETTE, items = [
    cylinder([-.65,-.95,0], [-.65,.8,0], .22, c.ivory, 12),
    cylinder([-.65,.8,0], [.65,.8,0], .22, c.blue, 12),
    cylinder([.65,.8,0], [.65,.36,0], .22, c.ivory, 12),
    cylinder([-.65,.15,-.28], [-.65,.15,.4], .08, c.gold, 10), torus([-.65,.15,.43], .32, .055, c.gold, 'z'),
    cylinder([.65,-.35,0], [.65,.1,0], .16, c.cyan, 12, .025),
    ellipsoid([.65,-.4,0], [.19,.23,.19], c.cyan, 12, 7),
    cylinder([0,-1.5,0], [0,-1.38,0], 1.02, c.blue, 20), torus([0,-1.34,0], .74, .025, c.cyan),
  ]
  return items
}
function recycle() {
  const c = PALETTE, items = [
    cylinder([0,-1.3,0], [0,.58,0], .62, c.blue, 8, .76),
    box([0,.67,0], [1.67,.18,1.5], c.ivory), box([0,.88,0], [.58,.18,.26], c.cyan),
  ]
  const arrow = [[-.14,-.26],[-.14,.12],[-.32,.12],[0,.48],[.32,.12],[.14,.12],[.14,-.26]]
  for (let i = 0; i < 3; i++) {
    const symbol = extrusion(arrow, .045, c.green)
    turn(symbol, i * TAU / 3)
    move(symbol, [0,-.28,.72]); items.push(symbol)
  }
  return items
}
function shield() {
  const c = PALETTE, items = [extrusion([[-.95,1.08],[0,1.45],[.95,1.08],[.84,-.5],[0,-1.36],[-.84,-.5]], .34, c.blue)]
  items.push(move(extrusion([[-.72,.95],[0,1.2],[.72,.95],[.62,-.38],[0,-1.04],[-.62,-.38]], .04, c.dark), [0,0,.2]))
  items.push(move(turn(box([0,0,0], [.15,.57,.06], c.cyan), .75), [-.22,-.05,.25]),
    move(turn(box([0,0,0], [.15,1.03,.06], c.cyan), -.68), [.17,.11,.25]))
  return items
}
function recovery() {
  const c = PALETTE, items = []
  for (const y of [-1.12,-.5,.12]) {
    items.push(cylinder([0,y,0], [0,y + .43,0], .72, c.blue, 18),
      cylinder([0,y + .43,0], [0,y + .49,0], .73, c.ivory, 18), box([.22,y + .2,.68], [.17,.09,.03], c.cyan))
  }
  items.push(torus([0,.98,0], .54, .075, c.cyan, 'z'), move(extrusion([[0,0],[.4,.1],[.16,.39]], .12, c.gold), [.35,1.2,0]))
  return items
}
function paw() {
  const c = PALETTE, items = [ellipsoid([0,-.45,0], [.75,.66,.28], c.blue, 12, 7)]
  for (const [x,y] of [[-.8,.37],[-.31,.88],[.31,.88],[.8,.37]]) items.push(ellipsoid([x,y,0], [.26,.38,.26], c.ivory, 10, 6))
  items.push(torus([0,-1.4,0], .92, .025, c.cyan))
  return items
}
const SCENES = { minerva: shield, hades: recovery, hephaestus: robot, poseidon: water, demeter: recycle, artemis: paw, eleuthia: person, aether: sensor, apollo: books }

function draw(context, objects, width, height, angle, time) {
  context.clearRect(0, 0, width, height)
  const cx = width / 2, cy = height * .49, scale = Math.min(width, height) * .25
  const polygons = [], light = unit([-.4,.8,1])
  const transform = point => {
    const [x,y,z] = rotateY(point, angle)
    return [x,y * .99 + z * .14,z * .99 - y * .14]
  }
  const project = ([x,y,z]) => { const perspective = 5 / (5 - z); return [cx + x * scale * perspective, cy - y * scale * perspective] }
  context.save()
  context.strokeStyle = 'rgba(115,203,237,.18)'; context.lineWidth = 1
  for (const size of [1,.78,.52]) {
    context.beginPath(); context.ellipse(cx, cy + scale * 1.73, scale * 1.55 * size, scale * .32 * size, 0, 0, TAU); context.stroke()
  }
  context.restore()
  for (const object of objects) {
    const vertices = object.vertices.map(point => {
      if (object.wave) point = add(rotateZ(sub(point, [.38,.33,0]), Math.sin(time * 2.4) * .17), [.38,.33,0])
      return transform(point)
    })
    for (const face of object.faces) {
      const points = face.map(index => vertices[index]), normal = unit(cross(sub(points[1], points[0]), sub(points[2], points[0])))
      // A two-sided soft material keeps the stylised low-poly illustration
      // readable while the full geometry turns, including rear views.
      const brightness = .43 + .57 * Math.max(0, Math.abs(dot(normal, light)))
      polygons.push({ points: points.map(project), depth: points.reduce((total,p) => total + p[2],0) / points.length,
        color: object.color.map(v => Math.min(255, Math.round(v * brightness))) })
    }
  }
  polygons.sort((a,b) => a.depth - b.depth)
  context.lineJoin = 'round'
  for (const polygon of polygons) {
    context.beginPath(); polygon.points.forEach(([x,y],i) => i ? context.lineTo(x,y) : context.moveTo(x,y)); context.closePath()
    context.fillStyle = `rgb(${polygon.color.join(',')})`; context.fill()
    context.strokeStyle = 'rgba(164,228,255,.08)'; context.lineWidth = .45; context.stroke()
  }
}

export function mountCommunityProduct(host, { system = 'eleuthia' } = {}) {
  if (!host?.ownerDocument || typeof host.append !== 'function') throw new TypeError('community product host required')
  const document = host.ownerDocument, window = document.defaultView || globalThis
  const element = document.createElement('section')
  element.className = 'community-product'
  Object.assign(element.style, { width: '100%', minWidth: '0', textAlign: 'center' })
  const canvas = document.createElement('canvas')
  canvas.className = 'community-product__canvas'
  canvas.setAttribute('role', 'img')
  Object.assign(canvas.style, { display: 'block', width: '100%', height: '280px', minHeight: '160px', maxHeight: '46vh' })
  const label = document.createElement('strong'), note = document.createElement('p')
  label.className = 'community-product__label'; note.className = 'community-product__note'
  Object.assign(label.style, { display: 'block', color: '#e8f5ff', fontSize: '15px', lineHeight: '1.6' })
  Object.assign(note.style, { margin: '5px auto 0', maxWidth: '34em', color: '#abc1d5', fontSize: '11px', lineHeight: '1.7', padding: '0 12px' })
  element.append(canvas, label, note); host.append(element)
  const context = canvas.getContext?.('2d')
  const motion = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  let current, objects, frame = null, paused = false, destroyed = false, inView = true, elapsed = 0, prior = null, lastDraw = -Infinity
  let width = 320, height = 280
  const active = () => !destroyed && !paused && inView && document.hidden !== true && host.isConnected !== false && element.isConnected !== false
  function render() {
    if (!context || destroyed) return
    context.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
    draw(context, objects, width, height, -.28 + (motion?.matches ? 0 : elapsed * .18), motion?.matches ? 0 : elapsed)
  }
  function stop() { if (frame !== null) window.cancelAnimationFrame?.(frame); frame = null; prior = null }
  function tick(stamp) {
    frame = null
    if (!active() || motion?.matches) { prior = null; return }
    if (prior !== null) elapsed += Math.min(Math.max(stamp - prior, 0), 60) / 1000
    prior = stamp
    if (stamp - lastDraw >= 32) { render(); lastDraw = stamp }
    frame = window.requestAnimationFrame?.(tick) ?? null
  }
  function sync() {
    stop()
    if (!active()) return
    render()
    if (!motion?.matches && context) frame = window.requestAnimationFrame?.(tick) ?? null
  }
  function resize() {
    if (destroyed) return
    const rect = canvas.getBoundingClientRect()
    width = Math.max(1, Math.min(960, rect.width || 320)); height = Math.max(1, Math.min(640, rect.height || 280))
    const ratio = Math.max(1, Math.min(2, window.devicePixelRatio || 1))
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio)
    render()
  }
  function setSystem(id) {
    if (destroyed) return
    current = Object.hasOwn(PRODUCTS, id) ? id : 'eleuthia'
    objects = SCENES[current]()
    const [title, description] = PRODUCTS[current]
    element.dataset.system = current; canvas.setAttribute('aria-label', title + '。' + description)
    label.textContent = title; note.textContent = description
    elapsed = 0; lastDraw = -Infinity; sync()
  }
  setSystem(system); resize()
  const observer = window.ResizeObserver ? new window.ResizeObserver(resize) : null
  observer?.observe(canvas)
  const intersection = window.IntersectionObserver ? new window.IntersectionObserver(entries => {
    inView = entries.some(entry => entry.isIntersecting); sync()
  }) : null
  intersection?.observe(element)
  const visibility = () => sync()
  document.addEventListener('visibilitychange', visibility)
  if (motion?.addEventListener) motion.addEventListener('change', visibility)
  else motion?.addListener?.(visibility)
  return {
    element, setSystem,
    pause() { if (!destroyed) { paused = true; stop() } },
    resume() { if (!destroyed) { paused = false; resize(); sync() } },
    destroy() {
      if (destroyed) return
      destroyed = true; stop(); observer?.disconnect(); intersection?.disconnect()
      document.removeEventListener('visibilitychange', visibility)
      if (motion?.removeEventListener) motion.removeEventListener('change', visibility)
      else motion?.removeListener?.(visibility)
      element.remove(); objects = []
    },
  }
}
