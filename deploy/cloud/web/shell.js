import { createFrameBroker } from '/cloud/cloud-frame.js'
import { createCloudSession } from '/cloud/cloud-session.js'

const node = id => document.getElementById(id)
let frame, broker, expire, provider, role
function closeService() {
  broker?.close()
  if (broker) window.removeEventListener('message', broker.receive)
  broker = undefined
  frame?.remove()
  frame = undefined
  provider = undefined
  clearTimeout(expire)
  node('navigation').hidden = true
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
    if (state.state === 'checking') status.textContent = '正在核對登入…'
    if (state.state === 'storage_acceptance') status.textContent = 'Google 登入已核對成功。平台仍在準備，未開放居民對話或正式資料操作。'
    if (state.state === 'unavailable') status.textContent = '暫時未能核對登入，請稍後再試。'
    if (state.state === 'signed_out') status.textContent = '請用已核准的 Google 帳戶登入。'
    if (state.state === 'ready') {
      role = state.role
      node('login').hidden = true
      node('navigation').hidden = false
      node('staff').hidden = role !== 'staff'
      expire = setTimeout(() => session.clear(), Math.max(0, provider().expiresAtMs - Date.now() - 60000))
      show('resident')
    }
  } })
node('resident').onclick = () => show('resident')
node('staff').onclick = () => show('staff')
node('signOut').onclick = () => { session.clear(); google.accounts.id.disableAutoSelect() }
window.addEventListener('pagehide', () => session.clear(), { once: true })
try {
  const response = await fetch('/login-config', { cache: 'no-store', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(10000) })
  if (!response.ok) throw new Error('login_unavailable')
  const config = await response.json()
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
catch { node('status').textContent = 'Google 登入暫時未能載入，請稍後重整。' }
