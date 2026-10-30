(() => {
  const panel = document.querySelector('#panel-usage')
  const card = document.createElement('section')
  card.className = 'service-card'
  card.hidden = true
  const title = document.createElement('h2')
  title.textContent = '曉曼語音開關'
  const summary = document.createElement('p')
  summary.setAttribute('role', 'status')
  const action = document.createElement('button')
  action.type = 'button'
  const note = document.createElement('p')
  note.className = 'service-muted'
  note.textContent = '到額停止，不自動收費。開關只控制新語音合成，不重設用量或批准付款；文字對話仍可使用。中文每字計 2 個字元，本機可用量不是官方剩餘額度。'
  card.append(title, summary, action, note)
  panel?.prepend(card)
  let current
  let loading = false
  async function load(paused) {
    if (loading) return
    loading = true
    action.disabled = true
    try {
      const response = await fetch('/api/v1/service-desk/voice-control', {
        method: typeof paused === 'boolean' ? 'PUT' : 'GET',
        headers: { 'Content-Type': 'application/json', 'X-Operator-Key': document.querySelector('#operatorKey').value },
        body: typeof paused === 'boolean' ? JSON.stringify({ paused }) : undefined,
        cache: 'no-store', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(5000),
      })
      if (!response.ok) throw new Error('unavailable')
      current = await response.json()
      card.hidden = !current.configured
      const state = current.paused ? '已暫停新語音合成' : current.blocked ? '可用量不足，已停止新合成' : '可使用'
      summary.textContent = state
      action.textContent = current.paused ? '恢復免費語音' : '暫停語音'
      action.disabled = current.used === null || (!current.paused && current.blocked)
    }
    catch {
      if (!card.hidden) summary.textContent = '暫時未能核對語音狀態；未更改開關，請稍後再試。'
    }
    finally { loading = false }
  }
  action.addEventListener('click', () => { if (current) void load(!current.paused) })
  window.addEventListener('hashchange', () => { if (location.hash === '#usage') void load() })
  document.querySelector('#refreshQuota')?.addEventListener('click', () => { void load() })
  void load()
})()
