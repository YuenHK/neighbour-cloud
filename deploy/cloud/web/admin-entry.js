import { createCloudTransport } from '/cloud/cloud-transport.js'
import { createFrameBroker, frameIdentity } from '/cloud/cloud-frame.js'

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
  const settings = document.getElementById('cloudAiriSettings')
  const makeBroker = () => createFrameBroker({ origin: location.origin, frameWindow: () => settings?.contentWindow,
    tokenProvider: () => identity })
  let broker = makeBroker()
  const robotFrame = document.getElementById('robotConsoleFrame')
  const makeRobotBroker = () => createFrameBroker({ origin: location.origin,
    frameWindow: () => robotFrame?.contentWindow, tokenProvider: () => identity })
  let robotBroker = makeRobotBroker()
  window.addEventListener('message', event => broker.receive(event))
  window.addEventListener('message', event => robotBroker.receive(event))
  window.addEventListener('cloud-settings-reset', () => { broker.close(); broker = makeBroker() })
  window.addEventListener('cloud-robot-reset', () => { robotBroker.close(); robotBroker = makeRobotBroker() })
  window.addEventListener('pagehide', () => broker.close(), { once: true })
  window.addEventListener('pagehide', () => robotBroker.close(), { once: true })
  window.addEventListener('pagehide', () => transport.clearAuth(), { once: true })
  for (const name of ['photo-privacy', 'latest-photo', 'api-quota', 'work-sections', 'workspace-navigation',
    'runtime', 'service-workbench', 'estate-management', 'presentation', 'robots']) await import(`/cloud/admin/${name}.js`)
  if (data.governance_supported === true) await import('/cloud/admin/governance.js')
  const { prepareSettings } = await import('/cloud/admin/presentation.js')
  parent.postMessage({ type: 'neighbour-service-stage', area: 'staff', state: 'settings' }, location.origin)
  await prepareSettings()
  parent.postMessage({ type: 'neighbour-service-ready', area: 'staff' }, location.origin)
}
catch {
  parent.postMessage({ type: 'neighbour-service-error', area: 'staff' }, location.origin)
  transport?.clearAuth()
  document.body.replaceChildren(Object.assign(document.createElement('p'), { textContent: '請由鄰伴登入頁，以已核准的職員帳戶進入管理工作台。' }))
}
