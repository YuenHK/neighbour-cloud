(() => {
  const element = (tag, text) => {
    const node = document.createElement(tag)
    if (text !== undefined) node.textContent = text
    return node
  }
  function render(root, rows) {
    root.replaceChildren()
    for (const row of rows) {
      const tr = element('tr')
      const name = element('th')
      name.scope = 'row'
      name.append(element('strong', row.service), element('small', row.platform))
      const official = row.provider || {}
      const local = row.guard?.counters?.[0]
      const known = ['ok', 'stale', 'snapshot'].includes(official.status) && Number.isFinite(official.remaining)
      const cap = row.id === 'cloudflare-gemma' ? 10000 : row.id === 'azure-voice' ? 500000 : official.limit
      const unit = row.id === 'cloudflare-gemma' ? 'Neurons／日' : row.id === 'azure-voice' ? '字元／月' : 'credits／月'
      const remaining = known ? official.remaining : local?.remaining
      const cell = element('td')
      if (Number.isFinite(cap)) cell.append(element('span', `免費配額 ${cap.toLocaleString('zh-HK')} ${unit}`))
      if (Number.isFinite(remaining) && Number.isFinite(cap) && cap > 0) {
        cell.append(element('strong', `${known ? official.status === 'stale' ? '上次記錄可用 ' : '可用 ' : '估計可用 '}${remaining.toLocaleString('zh-HK')}`))
        const bar = element('progress')
        bar.max = cap
        bar.value = Math.max(0, Math.min(cap, remaining))
        bar.setAttribute('aria-label', `${row.service}${known ? '' : '估計'}剩餘比例`)
        cell.append(bar)
      }
      else cell.append(element('span', '目前可用量未能取得'))
      const reset = element('td')
      const stamp = official.reset_at || (row.id === 'cloudflare-gemma' ? row.guard?.reset_at : null)
      reset.append(element('span', stamp ? new Date(stamp).toLocaleString('zh-HK', { hour12: false }) : '每月重設；確切日期未取得'))
      const state = row.operation?.state
      if (state && state !== 'ready') reset.append(element('small', { paused: '已暫停', blocked: '已到上限，等待重設', cooling: '暫時冷卻中', unknown: '狀態待確認', not_configured: '尚未設定' }[state] || '暫未就緒'))
      if (!known) reset.append(element('small', '未有官方即時餘額；可用量為預留緩衝後的估計'))
      if (official.status === 'stale') reset.append(element('small', '更新未成功，保留上次記錄'))
      tr.append(name, cell, reset)
      root.append(tr)
    }
  }
  globalThis.ZhiweiQuota = { render }
})()
