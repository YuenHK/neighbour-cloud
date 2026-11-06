import { cloudFetch } from '/cloud/admin-request.js'

// Loaded only after staff authentication. No extra card, test push or resident
// content. Browser permission is still native and needs a trusted interaction.
const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
let pending
let active = false
let attempts = 0
let lastAttempt = -Infinity
const state = value => { document.documentElement.dataset.staffNotifications = value }

function activate() {
  if (pending || active || !supported || Notification.permission !== 'granted')
    return pending
  if (attempts >= 2 || performance.now() - lastAttempt < 30000)
    return undefined
  attempts++
  lastAttempt = performance.now()
  state('connecting')
  pending = (async () => {
    const registration = await navigator.serviceWorker.register('/staff-sw.js', { scope: '/' })
    await navigator.serviceWorker.ready
    let subscription = await registration.pushManager.getSubscription()
    if (!subscription) {
      const response = await cloudFetch('/api/v1/service-desk/notifications', { signal: AbortSignal.timeout(10000) })
      if (!response.ok)
        throw new Error('push_configuration_unavailable')
      const config = await response.json()
      const bytes = Uint8Array.from(atob(config.public_key.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
      subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes })
    }
    const response = await cloudFetch('/api/v1/service-desk/notifications', {
      method: 'POST', body: JSON.stringify(subscription.toJSON()), headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(10000),
    })
    if (!response.ok)
      throw new Error('push_registration_unconfirmed')
    const value = await response.json()
    localStorage.setItem('neighbour-push-id', value.subscription_id)
    localStorage.setItem('neighbour-push-preference', 'on')
    active = true
    state('ready')
  })().catch(() => state('unavailable')).finally(() => { pending = undefined })
  return pending
}

function disarm() {
  document.removeEventListener('pointerup', permission, true)
  document.removeEventListener('keydown', permission, true)
}
function permission(event) {
  if (!event.isTrusted || document.hidden || (event.type === 'keydown' && !['Enter', ' '].includes(event.key)))
    return
  disarm()
  // Invoke directly within this event, before any worker or network await.
  if (Notification.permission === 'default') {
    void Notification.requestPermission().then(value => {
      if (value === 'granted')
        void activate()
      else state('permission-required')
    }).catch(() => state('permission-required'))
  }
  else if (Notification.permission === 'granted') {
    void activate()
  }
}

if (!supported) {
  state('unsupported')
}
else if (Notification.permission === 'granted') {
  void activate()
}
else if (Notification.permission === 'default') {
  state('permission-required')
  document.addEventListener('pointerup', permission, true)
  document.addEventListener('keydown', permission, true)
}
else {
  state('permission-required')
}
window.addEventListener('online', () => { if (!document.hidden) void activate() })
window.addEventListener('pagehide', disarm, { once: true })
