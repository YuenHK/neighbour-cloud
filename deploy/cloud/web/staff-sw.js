// No fetch handler or cache: no conversation, password, photo or API is stored.
self.addEventListener('push', (event) => {
  let value
  try { value = event.data?.json() } catch { return }
  if (value?.type !== 'staff-update') return
  event.waitUntil(self.registration.showNotification('鄰伴・有新事項', {
    body: '請登入管理工作台查看及跟進。', tag: 'neighbour-workbench',
    icon: '/assets/service/service-mark.svg', badge: '/assets/service/service-mark.svg',
    data: { url: '/?workspace=staff' },
  }))
})
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(self.clients.openWindow('/?workspace=staff'))
})
