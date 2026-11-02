import { cloudFetch } from '/cloud/admin-request.js'
const area = document.createElement('section')
area.className = 'service-card'
area.innerHTML = '<h2>手機工作提示</h2><p>有新個案時通知你登入查看，通知不會顯示居民資料。手機須允許通知；iPhone／iPad 請先加入主畫面。</p><button type="button">開啟工作提示</button><p role="status"></p>'
document.querySelector('#panel-usage')?.append(area)
const button = area.querySelector('button'), status = area.querySelector('[role=status]')
if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
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
      delete button.dataset.enabled; button.textContent = '開啟工作提示'; status.textContent = '工作提示已關閉。'; return
    }
    const config = await cloudFetch('/api/v1/service-desk/notifications').then(r => { if (!r.ok) throw new Error(); return r.json() })
    const bytes = Uint8Array.from(atob(config.public_key.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
    const subscription = existing || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes })
    const response = await cloudFetch('/api/v1/service-desk/notifications', { method: 'POST', body: JSON.stringify(subscription.toJSON()), headers: { 'Content-Type': 'application/json' } })
    if (!response.ok) throw new Error('subscribe_failed')
    const value = await response.json(); localStorage.setItem('neighbour-push-id', value.subscription_id)
    button.dataset.enabled = 'true'; button.textContent = '關閉工作提示'; status.textContent = '已開啟。通知到達時間受手機、瀏覽器及免費主機休眠影響，重要事項仍須當值職員留意。'
  } catch { status.textContent = '未能開啟；請確認已允許通知或已加入主畫面。工作台仍會自動更新。' }
  finally { button.disabled = false }
}
if (localStorage.getItem('neighbour-push-id')) { button.dataset.enabled = 'true'; button.textContent = '關閉工作提示' }
