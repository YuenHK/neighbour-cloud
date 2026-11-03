// No fetch handler or private cache. This bounded store contains only opaque
// notification identifiers/timestamps, never cases, subscriptions or residents.
const recent = new Set()
async function claimNotification(id, remove = false) {
  if (!('indexedDB' in self)) return true
  const db = await new Promise(resolve => {
    const request = indexedDB.open('neighbour-notification-dedup', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('seen', { keyPath: 'id' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = request.onblocked = () => resolve(null)
  })
  if (!db) return true // OS tag + in-memory guard remain if storage is unavailable.
  return new Promise(resolve => {
    let claimed = true
    const transaction = db.transaction('seen', 'readwrite'), store = transaction.objectStore('seen')
    if (remove) store.delete(id)
    else {
      const request = store.getAll()
      request.onsuccess = () => {
        const cutoff = Date.now() - 7 * 86400000
        const rows = request.result.filter(row => row.at > cutoff).sort((a, b) => a.at - b.at)
        claimed = !rows.some(row => row.id === id)
        if (!claimed) return
        const retained = new Set(rows.slice(-127).map(row => row.id))
        for (const row of request.result) if (!retained.has(row.id)) store.delete(row.id)
        store.put({ id, at: Date.now() })
      }
    }
    transaction.oncomplete = () => { db.close(); resolve(claimed) }
    transaction.onerror = transaction.onabort = () => { db.close(); resolve(true) }
  })
}
self.addEventListener('push', (event) => {
  let value
  try { value = event.data?.json() } catch { return }
  if (!['staff-update', 'staff-test'].includes(value?.type)) return
  const id = value.notification_id
  if (id !== undefined && (typeof id !== 'string' || !/^[a-f0-9]{64}$/.test(id))) return
  event.waitUntil((async () => {
    if (id) {
      if (recent.has(id)) return
      recent.add(id)
      if (recent.size > 128) recent.delete(recent.values().next().value)
      if (!await claimNotification(id)) return
    }
    const testing = value.type === 'staff-test'
    try {
      await self.registration.showNotification(testing ? '鄰伴・測試工作提示' : '鄰伴・有新事項', {
        body: testing ? '已收到測試提示。毋須建立或處理個案。' : '請登入管理工作台查看及跟進。',
        tag: testing ? 'neighbour-workbench-test' : 'neighbour-workbench', renotify: false,
        icon: '/assets/brand/icon-192.png', badge: '/assets/brand/favicon-32.png',
        data: { url: '/?workspace=staff' },
      })
    } catch (error) {
      if (id) { recent.delete(id); await claimNotification(id, true) }
      throw error
    }
  })())
})
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(self.clients.openWindow('/?workspace=staff'))
})
