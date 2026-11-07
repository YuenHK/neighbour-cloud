import { createFrameBroker } from '/cloud/cloud-frame.js'
import { createCloudSession } from '/cloud/cloud-session.js'
import { createLaunchScreen } from '/cloud/launch-screen.js'
import { preloadModules } from '/cloud/module-warmup.js'
import { placeModelCredit, preparePrivacy } from '/cloud/privacy.js'
import { StartupRepair } from '/cloud/startup-repair.js'
import { prepareCommunityIntroduction } from '/cloud/community-about.js'

const node = id => document.getElementById(id)
preparePrivacy(document)
installLedNavigation()
function installLedNavigation() {
  const header = node('platformHeader'), handle = node('ledNavigationToggle')
  const small = matchMedia('(max-aspect-ratio:1/1), (max-width:900px), (max-height:360px)')
  let hovering = false, pinned = false, swipe, ignoreClickUntil = 0
  const adaptive = () => small.matches && document.body.dataset.platformView !== 'staff'
  function update() {
    const open = adaptive() && (hovering || pinned || header.contains(document.activeElement))
    document.body.toggleAttribute('data-led-navigation-open', open)
    handle.setAttribute('aria-expanded', String(open))
    // A hidden drawer must not receive tab focus until its handle is opened.
    header.inert = adaptive() && !open
    const viewport = window.visualViewport
    const height = viewport && Math.abs(viewport.scale - 1) < .01 ? viewport.height : innerHeight
    document.body.style.setProperty('--resident-viewport-height', `${Math.max(1, height)}px`)
  }
  function outside(target) { return !header.contains(target) && !handle.contains(target) }
  function dismiss() {
    if (!adaptive()) return
    pinned = hovering = false
    if (header.contains(document.activeElement)) document.activeElement.blur()
    update()
  }
  for (const surface of [header, handle]) {
    surface.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') { hovering = true; update() } })
    surface.addEventListener('pointerleave', event => { if (outside(event.relatedTarget)) { hovering = false; update() } })
  }
  handle.addEventListener('click', () => {
    if (performance.now() < ignoreClickUntil) { ignoreClickUntil = 0; return }
    pinned = !pinned; if (!pinned) hovering = false; update()
  })
  handle.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch' || !adaptive()) return
    swipe = { id: event.pointerId, x: event.clientX, y: event.clientY }
  })
  handle.addEventListener('pointermove', event => {
    if (!swipe || event.pointerId !== swipe.id) return
    if (event.clientY - swipe.y >= 32 && Math.abs(event.clientX - swipe.x) < 48) {
      pinned = true; ignoreClickUntil = performance.now() + 500; update()
    }
  })
  handle.addEventListener('pointerup', () => { swipe = undefined })
  handle.addEventListener('pointercancel', () => { swipe = undefined; ignoreClickUntil = 0 })
  header.addEventListener('focusin', update)
  header.addEventListener('focusout', () => queueMicrotask(update))
  document.addEventListener('pointerdown', event => {
    if (!adaptive() || !outside(event.target)) return
    dismiss()
  })
  // Pointer events inside the service iframe do not bubble to this document.
  node('service').addEventListener('pointerenter', dismiss)
  window.addEventListener('blur', () => setTimeout(() => { if (document.activeElement?.tagName === 'IFRAME') dismiss() }, 0))
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !adaptive() || !document.body.hasAttribute('data-led-navigation-open')) return
    pinned = hovering = false
    handle.focus({ preventScroll: true })
    update()
  })
  small.addEventListener('change', () => { pinned = hovering = false; update() })
  window.visualViewport?.addEventListener('resize', update)
  window.addEventListener('resize', update)
  new MutationObserver(() => { pinned = hovering = false; update() })
    .observe(document.body, { attributes: true, attributeFilter: ['data-platform-view'] })
  update()
}
let frame, broker, expire, provider, role
let publicMode = false
let requestedArea = new URLSearchParams(location.search).get('workspace') === 'staff' ? 'staff' : 'resident'
let opening = false
let navigationEpoch = 0
let navigationAbort = new AbortController()
let currentArea = 'resident'
let startupTimer, startupTextReady = false
const startupRepair = new StartupRepair({ onState(key, state) {
  if (key !== 'frame' || !frame?.classList.contains('is-warming')) return
  launch.repairState('eleuthia', state)
  if (state === 'retrying') launch.repair('畫面暫時未能啟動，正在自動重新連接一次。', 'eleuthia')
  if (state === 'unavailable') launch.fail('自動重新連接仍未完成；原有資料保留，可以稍後再試。')
} })
const launch = createLaunchScreen(document, {
  onRetry() {
    startupRepair.reset()
    if (currentArea === 'staff' && provider && role === 'staff') show('staff')
    else { beginNavigation(); void startResident() }
  },
  onContinue() { reveal() },
})
prepareCommunityIntroduction(document, { snapshot: () => launch.snapshot() })
launch.start('resident')
void preloadModules(document, [...document.querySelectorAll('link[data-neighbour-warm]')].map(link => ({
  key: link.dataset.neighbourWarm, path: new URL(link.href).pathname,
})), { onState: (key, state) => launch.moduleState(key, state) })
function reveal() {
  if (!frame || !frame.classList.contains('is-warming')) return
  const showing = frame
  clearTimeout(startupTimer)
  showing.classList.remove('is-warming')
  showing.classList.add('is-revealing')
  launch.finish(() => {
    if (frame !== showing) return
    showing.classList.remove('is-revealing')
    showing.inert = false
    showing.removeAttribute('aria-hidden')
    if (currentArea === 'resident') showing.contentWindow.postMessage({ type: 'neighbour-resident-visible' }, location.origin)
  })
}
window.addEventListener('message', event => {
  if (event.origin !== location.origin || !frame || event.source !== frame.contentWindow) return
  if (event.data?.type === 'neighbour-model-credit' && currentArea === 'resident'
    && placeModelCredit(document, event.data.credit))
    frame.contentWindow.postMessage({ type: 'neighbour-model-credit-placed' }, location.origin)
  if (event.data?.type === 'neighbour-readiness' && currentArea === 'resident') {
    startupTextReady = event.data.textReady === true
    launch.checks(event.data)
    if (event.data.ready === true) reveal()
    else if (startupTextReady && ['action', 'failed'].some(state => Object.values(event.data.checks || {}).includes(state))) reveal()
  }
  if (event.data?.type === 'neighbour-service-stage' && currentArea === 'resident') {
    launch.phase('avatar')
  }
  if (event.data?.type === 'neighbour-service-stage' && currentArea === 'staff') launch.staffSettings()
  if (event.data?.type === 'neighbour-service-ready' && event.data.area === 'staff' && currentArea === 'staff') reveal()
  if (event.data?.type === 'neighbour-service-error') void repairStartupFrame()
})
function canRepairFrame() {
  if (!frame?.classList.contains('is-warming')) return false
  try {
    const idle = frame.contentWindow.__NEIGHBOUR_RESIDENT_IDLE__
    return typeof idle === 'function' ? idle() === true : !startupTextReady
  }
  catch { return false }
}
async function repairStartupFrame() {
  if (startupTextReady) { reveal(); return }
  const own = frame, epoch = navigationEpoch
  const retried = await startupRepair.run('frame', () => { show(currentArea); return true }, canRepairFrame)
  if (!retried && frame === own && epoch === navigationEpoch && frame?.classList.contains('is-warming')) launch.fail('載入仍未完成；未重新傳送任何對話或個案，可以稍後再試。')
}
function beginNavigation() {
  startupRepair.reset()
  clearTimeout(startupTimer)
  navigationEpoch++
  navigationAbort.abort()
  navigationAbort = new AbortController()
  opening = false
  session.clear()
}
function closeService() {
  clearTimeout(startupTimer)
  launch.hide()
  broker?.close()
  if (broker) window.removeEventListener('message', broker.receive)
  broker = undefined
  frame?.remove()
  frame = undefined
  provider = undefined
  clearTimeout(expire)
  node('navigation').hidden = !publicMode
  node('login').hidden = false
}
function show(area) {
  if (!provider || (area === 'staff' && role !== 'staff')) return
  broker?.close()
  if (broker) window.removeEventListener('message', broker.receive)
  frame?.remove()
  frame = document.createElement('iframe')
  currentArea = area
  document.body.dataset.platformView = area === 'staff' ? 'staff' : 'resident'
  clearTimeout(startupTimer)
  startupTextReady = false
  launch.start(area, 'interface')
  launch.connected()
  frame.className = 'is-warming'
  frame.inert = true
  frame.setAttribute('aria-hidden', 'true')
  frame.title = area === 'staff' ? '管理工作台' : '居民服務台'
  frame.allow = area === 'staff' ? "microphone 'none'; camera 'none'; autoplay 'self'" : "microphone 'self'; camera 'self'; autoplay 'self'"
  frame.referrerPolicy = 'no-referrer'
  frame.src = area === 'staff' ? '/cloud/admin' : '/cloud/resident?estate=1'
  broker = createFrameBroker({ origin: location.origin, frameWindow: () => frame?.contentWindow, tokenProvider: provider })
  window.addEventListener('message', broker.receive)
  node('service').replaceChildren(frame)
  startupTimer = setTimeout(() => { void repairStartupFrame() }, 25000)
  for (const name of ['resident', 'staff']) node(name).setAttribute('aria-current', String(name === area))
}
const session = createCloudSession({ origin: location.origin, onClear: closeService,
  onReady(tokenProvider) { provider = tokenProvider },
  onState(state) {
    const status = node('status')
    if (state.state === 'checking') status.textContent = '正在連接服務…'
    if (state.state === 'storage_acceptance') status.textContent = 'Google 登入已核對成功。平台仍在準備，未開放居民對話或正式資料操作。'
    if (state.state === 'unavailable') status.textContent = '暫時未能核對登入，請稍後再試。'
    if (state.state === 'signed_out') status.textContent = publicMode ? '正在準備服務台…' : '請用已核准的 Google 帳戶登入。'
    if (state.state === 'ready') {
      role = state.role
      node('login').hidden = true
      node('navigation').hidden = false
      node('staffLogin').hidden = true
      node('staff').hidden = !publicMode && role !== 'staff'
      node('signOut').hidden = publicMode || role !== 'staff'
      expire = setTimeout(() => publicMode && role === 'resident' ? void startResident() : session.clear(),
        Math.max(0, provider().expiresAtMs - Date.now() - 60000))
      show(requestedArea === 'staff' && role === 'staff' ? 'staff' : 'resident')
    }
  } })
async function access(body) {
  const response = await fetch('/api/v1/resident/access', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    cache: 'no-store', credentials: 'omit', redirect: 'error',
    signal: AbortSignal.any([navigationAbort.signal, AbortSignal.timeout(12000)]) })
  if (!response.ok) throw new Error(response.status === 401 ? '管理口令不正確。' : '暫時未能連接，請稍後再試。')
  const data = await response.json()
  if (typeof data.token !== 'string') throw new Error('服務連接未完成。')
  return data.token
}
async function startResident() {
  if (opening) return
  const epoch = navigationEpoch
  opening = true
  requestedArea = 'resident'
  launch.start('resident')
  currentArea = 'resident'
  document.body.dataset.platformView = 'resident'
  node('login').hidden = true
  node('staffLogin').hidden = true
  node('staffPassword').value = ''
  node('loginHint').textContent = '你好，正在為你準備數字人。'
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const value = await access({})
        if (epoch !== navigationEpoch) return
        const result = await session.accept(value)
        if (epoch !== navigationEpoch) return
        if (result.state !== 'ready') throw new Error('服務連接未完成。')
        return
      }
      catch {
        if (epoch !== navigationEpoch) return
        node('status').textContent = '正在重新連接服務，請稍候…'
        if (attempt < 2) {
          launch.repair('服務連接未完成，正在安全重連；不會重送對話或個案。', 'minerva')
          await new Promise(resolve => setTimeout(resolve, 600 * (attempt + 1)))
        }
      }
    }
    node('status').textContent = '暫時未能連接，請按上方「居民服務台」再試。'
    launch.fail('暫時未能連接，可以按「重新連接」再試。')
  }
  finally { if (epoch === navigationEpoch) opening = false }
}
node('resident').onclick = () => {
  if (publicMode) { beginNavigation(); void startResident() }
  else show('resident')
}
node('staff').onclick = () => {
  if (role === 'staff' && provider) { show('staff'); return }
  if (!publicMode) return
  beginNavigation()
  document.body.dataset.platformView = 'staff'
  node('login').hidden = true
  node('staffLogin').hidden = false
  node('staffLoginStatus').textContent = ''
  node('staffSubmit').disabled = false
  node('staffSubmit').textContent = '進入管理工作台'
  node('staffPassword').focus()
}
node('cancelStaffLogin').onclick = () => { beginNavigation(); void startResident() }
node('staffLoginForm').onsubmit = async (event) => {
  event.preventDefault()
  if (opening) return
  const epoch = navigationEpoch
  const password = node('staffPassword').value
  node('staffPassword').value = ''
  opening = true
  node('staffSubmit').disabled = true
  node('staffSubmit').textContent = '正在核對…'
  requestedArea = 'staff'
  node('staffLoginStatus').textContent = '正在進入…'
  try {
    const value = await access({ password })
    if (epoch !== navigationEpoch) return
    const result = await session.accept(value)
    if (epoch !== navigationEpoch) return
    if (result.state !== 'ready' || result.role !== 'staff') throw new Error('暫時未能進入管理工作台。')
  }
  catch (error) {
    if (epoch !== navigationEpoch) return
    node('login').hidden = true
    node('staffLogin').hidden = false
    node('staffLoginStatus').textContent = error.message
  }
  finally {
    if (epoch === navigationEpoch) {
      opening = false
      node('staffSubmit').disabled = false
      node('staffSubmit').textContent = '進入管理工作台'
    }
  }
}
node('signOut').onclick = () => {
  if (publicMode) void startResident()
  else { session.clear(); google.accounts.id.disableAutoSelect() }
}
window.addEventListener('pagehide', () => session.clear(), { once: true })
try {
  const response = await fetch('/login-config', { cache: 'no-store', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(10000) })
  if (!response.ok) throw new Error('login_unavailable')
  const config = await response.json()
  publicMode = config.public_resident === true
  if (publicMode) {
    node('navigation').hidden = false
    node('staff').hidden = false
    node('signOut').hidden = true
    if (requestedArea === 'staff') { launch.hide(); node('staff').onclick() }
    else await startResident()
  }
  else {
  launch.hide()
  node('login').hidden = false
  node('loginHint').textContent = '請先用已核准的 Google 帳戶登入。'
  await new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.onload = resolve
    script.onerror = reject
    document.head.append(script)
  })
  google.accounts.id.initialize({ client_id: config.client_id, callback: response => void session.accept(response.credential), auto_select: false, ux_mode: 'popup' })
  google.accounts.id.renderButton(node('googleButton'), { theme: 'outline', size: 'large', text: 'signin_with' })
  node('status').textContent = '請用已核准的 Google 帳戶登入。'
  }
}
catch { node('status').textContent = '服務暫時未能載入，請稍後重整。'; launch.fail('服務暫時未能載入，可以重新連接。') }
