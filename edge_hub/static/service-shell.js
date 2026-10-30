(() => {
  const key = ['operatorKey', 'epKey', 'memoryKey', 'controlKey']
    .map(id => document.getElementById(id)?.value)
    .find(Boolean)
  const badges = () => document.querySelectorAll('[data-service-pending]')
  if (!key)
    return
  let busy = false
  async function refresh() {
    if (busy || document.hidden)
      return
    busy = true
    try {
      const response = await fetch('/api/v1/service-desk/summary', {
        headers: { 'X-Operator-Key': key },
        signal: AbortSignal.timeout(5000),
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
      })
      if (!response.ok)
        throw new Error('summary_unavailable')
      const data = await response.json()
      const count = data.counts?.new ?? 0
      if (!data.counts || !Number.isSafeInteger(count) || count < 0
        || data.delivery_scope !== 'local_staff_workbench_only') {
        throw new Error('summary_invalid')
      }
      badges().forEach((badge) => {
        badge.textContent = String(count)
        badge.classList.toggle('warning', count > 0)
        badge.classList.toggle('neutral', count === 0)
      })
      for (const [group, tabId] of [['care', 'tab-care'], ['requests', 'tab-work']]) {
        const tab = document.getElementById(tabId)
        const pending = data.pending_by_group?.[group] ?? 0
        if (!tab || !Number.isSafeInteger(pending) || pending < 0)
          continue
        let badge = tab.querySelector('[data-intake-pending]')
        if (!badge) {
          badge = document.createElement('span')
          badge.dataset.intakePending = group
          badge.className = 'service-badge warning'
          tab.append(badge)
        }
        badge.textContent = String(pending)
        badge.hidden = pending === 0
        badge.setAttribute('aria-label', `${pending} 項等待職員接手`)
      }
    }
    catch {
      badges().forEach((badge) => {
        badge.textContent = '未更新'
      })
    }
    finally { busy = false }
  }
  void refresh()
  setInterval(() => void refresh(), 5000)
})()
