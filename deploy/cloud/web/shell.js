import { createFrameBroker } from '/cloud/cloud-frame.js'
import { createCloudSession } from '/cloud/cloud-session.js'

const node = id => document.getElementById(id)
let frame, broker, expire, provider, role
let publicMode = false
let requestedArea = 'resident'
let opening = false
let navigationEpoch = 0
let navigationAbort = new AbortController()
function beginNavigation() {
  navigationEpoch++
  navigationAbort.abort()
  navigationAbort = new AbortController()
  opening = false
  session.clear()
}
function closeService() {
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
  frame.title = area === 'staff' ? '管理工作台' : '居民服務台'
  frame.allow = area === 'staff' ? "microphone 'none'; camera 'none'; autoplay 'self'" : "microphone 'self'; camera 'none'; autoplay 'self'"
  frame.referrerPolicy = 'no-referrer'
  frame.src = area === 'staff' ? '/cloud/admin' : '/cloud/resident?estate=1'
  broker = createFrameBroker({ origin: location.origin, frameWindow: () => frame?.contentWindow, tokenProvider: provider })
  window.addEventListener('message', broker.receive)
  node('service').replaceChildren(frame)
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
        if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 600 * (attempt + 1)))
      }
    }
    node('status').textContent = '暫時未能連接，請按上方「居民服務台」再試。'
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
  node('login').hidden = true
  node('staffLogin').hidden = false
  node('staffLoginStatus').textContent = ''
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
  finally { if (epoch === navigationEpoch) opening = false }
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
    await startResident()
  }
  else {
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
catch { node('status').textContent = '服務暫時未能載入，請稍後重整。' }
