import { createCloudTransport } from '/cloud/cloud-transport.js'
import { frameIdentity } from '/cloud/cloud-frame.js'

let transport
try {
  const identity = await frameIdentity({ target: window, parent, origin: location.origin,
    onClose() { transport?.clearAuth(); location.replace('/cloud/signed-out') } })
  transport = createCloudTransport({ origin: location.origin, tokenProvider: () => identity })
  const proof = await transport.fetch('/api/v1/resident/session', { signal: AbortSignal.timeout(10000) })
  const data = await proof.json()
  if (!proof.ok || data.role !== 'staff' || data.authenticated !== true || data.storage_acceptance !== false)
    throw new Error('staff_identity_required')
  Object.defineProperties(globalThis, {
    __NEIGHBOUR_CLOUD__: { value: true }, __NEIGHBOUR_REMOTE__: { value: true },
    __NEIGHBOUR_CLOUD_TRANSPORT__: { value: transport },
  })
  window.addEventListener('pagehide', () => transport.clearAuth(), { once: true })
  for (const name of ['photo-privacy', 'latest-photo', 'api-quota', 'work-sections', 'workspace-navigation',
    'runtime', 'service-workbench', 'estate-management']) await import(`/cloud/admin/${name}.js`)
  if (data.governance_supported === true) await import('/cloud/admin/governance.js')
}
catch {
  transport?.clearAuth()
  document.body.replaceChildren(Object.assign(document.createElement('p'), { textContent: '請由鄰伴登入頁，以已核准的職員帳戶進入管理工作台。' }))
}
