import { createCloudTransport } from '/cloud/cloud-transport.js'
import { frameIdentity } from '/cloud/cloud-frame.js'
import { preloadModules } from '/cloud/module-warmup.js'
let transport
try {
  const scripts = ['console', 'fleet'].map(kind => {
    const value = document.querySelector(`link[data-robot-script="${kind}"]`)?.getAttribute('href')
    return { key: kind, path: value && new RegExp(`^/cloud/robot-assets/ep-${kind}-[a-f0-9]{12}\\.js$`).test(value) ? value : `/cloud/robot-assets/ep-${kind}.js` }
  })
  void preloadModules(document, scripts)
  const identity = await frameIdentity({ target: window, parent, origin: location.origin,
    onClose() { transport?.clearAuth(); location.replace('/cloud/signed-out') } })
  transport = createCloudTransport({ origin: location.origin, tokenProvider: () => identity })
  const response = await transport.fetch('/api/v1/resident/session', { signal: AbortSignal.timeout(10000) })
  const principal = await response.json()
  if (!response.ok || principal.role !== 'staff' || principal.authenticated !== true) throw new Error('staff_required')
  Object.defineProperties(globalThis, {
    __NEIGHBOUR_CLOUD__: { value: true },
    __NEIGHBOUR_CLOUD_TRANSPORT__: { value: transport },
  })
  parent.postMessage({ type: 'neighbour-robot-stage', state: 'interface' }, location.origin)
  for (const script of scripts) await import(script.path)
  parent.postMessage({ type: 'neighbour-robot-ready' }, location.origin)
  const body = document.querySelector('.fleet-console')
  if (body) new ResizeObserver(() => {
    parent.postMessage({ type: 'neighbour-robot-size', height: Math.ceil(body.getBoundingClientRect().height) }, location.origin)
  }).observe(body)
  window.addEventListener('message', event => {
    if (event.source === parent && event.origin === location.origin && event.data?.type === 'neighbour-robot-pause')
      window.dispatchEvent(new Event('blur'))
  })
  window.addEventListener('pagehide', () => transport.clearAuth(), { once: true })
}
catch {
  transport?.clearAuth()
  document.body.textContent = '控制台未能核對管理登入，請由管理工作台重新開啟。'
  parent.postMessage({ type: 'neighbour-robot-error' }, location.origin)
}
