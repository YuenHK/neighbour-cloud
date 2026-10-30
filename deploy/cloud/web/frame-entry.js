import { createCloudTransport } from '/cloud/cloud-transport.js'
import { frameIdentity } from '/cloud/cloud-frame.js'

let transport
try {
  const identity = await frameIdentity({ target: window, parent, origin: location.origin,
    onClose() { transport?.clearAuth(); location.replace('/cloud/signed-out') } })
  transport = createCloudTransport({ origin: location.origin, tokenProvider: () => identity })
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
