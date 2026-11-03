import { cloudFetch } from '/cloud/admin-request.js'
const area = document.createElement('section')
area.className = 'service-card'
area.innerHTML = '<h2>手機工作提示</h2><p>有新個案時通知你登入查看，通知不會顯示居民資料。手機須允許通知；iPhone／iPad 請先加入主畫面。</p><div class="service-actions"><button type="button" data-push-toggle>開啟工作提示</button><button type="button" class="service-button-secondary" data-push-test hidden>測試工作提示</button></div><p role="status"></p>'
document.querySelector('#panel-usage')?.append(area)
const button = area.querySelector('[data-push-toggle]'), test = area.querySelector('[data-push-test]'), status = area.querySelector('[role=status]')
const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
let testTimer
function enabled(value) {
  button.dataset.enabled = String(value)
  button.textContent = value ? '關閉工作提示' : '開啟工作提示'
  test.hidden = !value
  if (!value) { clearTimeout(testTimer); test.disabled = false }
}
function cooldown(seconds) {
  clearTimeout(testTimer)
  test.disabled = seconds > 0
  if (seconds > 0) testTimer = setTimeout(() => { test.disabled = false }, seconds * 1000)
}
if (!supported) {
  button.disabled = true; status.textContent = '此瀏覽器未提供推送通知，工作台仍會自動更新。'
}
button.onclick = async () => {
  button.disabled = true
  try {
    // Request inside the click's activation, before service-worker/network waits.
    const disabling = button.dataset.enabled === 'true'
    if (!disabling && await Notification.requestPermission() !== 'granted') throw new Error('permission')
    const registration = await navigator.serviceWorker.register('/staff-sw.js', { scope: '/' })
    await navigator.serviceWorker.ready
    const existing = await registration.pushManager.getSubscription()
    if (disabling) {
      const identity = localStorage.getItem('neighbour-push-id')
      if (identity) {
        const response = await cloudFetch('/api/v1/service-desk/notifications/' + identity, { method: 'DELETE' })
        if (!response.ok) throw new Error('remove_failed')
      }
      await existing?.unsubscribe(); localStorage.removeItem('neighbour-push-id')
      enabled(false); status.textContent = '工作提示已關閉。'; return
    }
    const config = await cloudFetch('/api/v1/service-desk/notifications').then(r => { if (!r.ok) throw new Error(); return r.json() })
    const bytes = Uint8Array.from(atob(config.public_key.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
    const subscription = existing || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes })
    const response = await cloudFetch('/api/v1/service-desk/notifications', { method: 'POST', body: JSON.stringify(subscription.toJSON()), headers: { 'Content-Type': 'application/json' } })
    if (!response.ok) throw new Error('subscribe_failed')
    const value = await response.json(); localStorage.setItem('neighbour-push-id', value.subscription_id)
    enabled(true); status.textContent = '已開啟。可按「測試工作提示」，毋須建立個案；請在手機核對是否收到通知。'
  } catch { status.textContent = '未能開啟；請確認已允許通知或已加入主畫面。工作台仍會自動更新。' }
  finally { button.disabled = false }
}
test.onclick = async () => {
  const identity = localStorage.getItem('neighbour-push-id')
  if (!identity || test.disabled) return
  test.disabled = true
  try {
    const response = await cloudFetch(`/api/v1/service-desk/notifications/${identity}/test`, { method: 'POST', signal: AbortSignal.timeout(15000) })
    if (!response.ok) throw new Error('test_failed')
    const result = await response.json()
    if (['expired', 'not_registered'].includes(result.state)) {
      localStorage.removeItem('neighbour-push-id'); enabled(false)
      status.textContent = '訂閱已到期，請重新開啟工作提示。'; return
    }
    cooldown(result.retry_after_seconds || 60)
    status.textContent = result.accepted
      ? '測試已交予手機推送服務，請查看手機通知；未代表手機已收到。每分鐘可測試一次，不會建立個案。'
      : result.state === 'cooldown' ? '請稍等一分鐘再測試，沒有重複發送。' : '推送服務暫未接受，請稍後再試；沒有建立個案。'
  } catch { cooldown(60); status.textContent = '測試結果未能確認，請先查看手機；一分鐘後才可再試，避免重複通知。' }
}
if (supported && localStorage.getItem('neighbour-push-id')) {
  enabled(true)
  const identity = localStorage.getItem('neighbour-push-id')
  cloudFetch(`/api/v1/service-desk/notifications/${identity}/status`, { signal: AbortSignal.timeout(10000) })
    .then(r => { if (!r.ok) throw new Error(); return r.json() })
    .then(value => {
      if (!value.registered) { localStorage.removeItem('neighbour-push-id'); enabled(false); status.textContent = '訂閱已到期，請重新開啟工作提示。' }
      else cooldown(value.test_retry_after_seconds || 0)
    }).catch(() => { status.textContent = '暫未核對到訂閱狀態；可稍後再試，工作台仍會自動更新。' })
}
