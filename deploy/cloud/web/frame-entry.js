import { createCloudTransport } from '/cloud/cloud-transport.js'
import { frameIdentity } from '/cloud/cloud-frame.js'
import { recoveringFetch } from '/cloud/resident-recovery.js'

let transport
try {
  let identity = await frameIdentity({ target: window, parent, origin: location.origin,
    onClose() { transport?.clearAuth(); location.replace('/cloud/signed-out') } })
  const claims = JSON.parse(atob(identity.token.split('.')[1].replaceAll('-', '+').replaceAll('_', '/')))
  const canRenew = claims.role === 'resident'
  let renewing
  const base = createCloudTransport({ origin: location.origin, tokenProvider: () => identity })
  async function renew() {
    if (!canRenew) return false
    if (renewing) return renewing
    renewing = (async () => {
      const response = await fetch('/api/v1/resident/access', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: '{}', credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(10000) })
      if (!response.ok) return false
      const value = await response.json()
      if (value.role !== 'resident' || typeof value.token !== 'string') return false
      base.clearAuth()
      identity = { token: value.token, expiresAtMs: value.expires_at_ms }
      return true
    })().catch(() => false).finally(() => { renewing = undefined })
    return renewing
  }
  transport = { fetch: recoveringFetch(base, { renew }), clearAuth: () => base.clearAuth() }
  Object.defineProperties(globalThis, {
    __NEIGHBOUR_CLOUD__: { value: true }, __NEIGHBOUR_REMOTE__: { value: true },
    __NEIGHBOUR_CLOUD_TRANSPORT__: { value: transport },
  })
  window.addEventListener('pagehide', () => transport.clearAuth(), { once: true })
  const entry = document.querySelector('meta[name="neighbour-cloud-entry"]')?.content
  if (!entry || !/^\/assets\/[\w-]+\.js$/.test(entry)) throw new Error('cloud_entry_unavailable')
  await import(entry)
}
catch {
  transport?.clearAuth()
  document.body.replaceChildren(Object.assign(document.createElement('p'), { textContent: '請由鄰伴登入頁進入服務台。' }))
}
