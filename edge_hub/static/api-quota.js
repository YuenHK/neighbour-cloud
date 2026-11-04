(() => {
  const units = { azure_tts_characters: '計費字元', cloudflare_gemma_neuron_reservations: 'Neurons（本機預留）', gemini_chat_requests: '次請求', gemini_chat_characters: '輸入字', gemini_tts_requests: '次合成', gemini_tts_characters: '朗讀字', siliconflow_chat_requests: '次請求', siliconflow_input_characters: '輸入字', siliconflow_stt_seconds: '秒辨識' }
  function element(tag, text) {
    const item = document.createElement(tag)
    if (text !== undefined)
      item.textContent = text
    return item
  }
  function percentage(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null
  }
  function metric(cell, value, label, stale = false) {
    const percent = percentage(value)
    if (percent === null) {
      cell.append(element('span', '— 未取得'))
      return
    }
    cell.append(element('strong', `${stale ? '上次記錄 ' : ''}${percent.toLocaleString('zh-HK')}% 剩餘`))
    const bar = element('progress')
    bar.max = 100
    bar.value = percent
    bar.setAttribute('aria-label', `${label}${stale ? '上次記錄' : ''}剩餘比例`)
    if (stale)
      bar.className = 'service-quota-stale'
    cell.append(bar)
  }
  function render(root, rows) {
    root.replaceChildren()
    for (const row of rows) {
      const tr = element('tr')
      const name = element('th')
      name.scope = 'row'
      name.append(element('strong', row.service), element('small', row.platform))
      if (row.purpose)
        name.append(element('small', row.purpose))
      const provider = element('td')
      const official = row.provider || {}
      if (official.status === 'local') {
        provider.append(element('span', '不適用 · 本機運算'))
      }
      else if (official.status === 'not_configured') {
        provider.append(element('span', '尚未設定'))
      }
      else if (typeof official.balance === 'string') {
        provider.append(element('strong', `${official.status === 'stale' ? '上次記錄 ' : ''}帳戶餘額 ${official.balance}`))
        provider.append(element('small', '沒有總配額，不估算百分比'))
      }
      else {
        if (official.status === 'snapshot')
          provider.append(element('small', '官方頁面核對時的記錄'))
        metric(provider, official.percent, `${row.platform} 官方`, official.status === 'stale')
        if (percentage(official.percent) !== null)
          provider.append(element('small', `餘 ${official.remaining.toLocaleString('zh-HK')}／${official.limit.toLocaleString('zh-HK')} ${official.unit || 'credits'}`))
      }
      if (official.allocation)
        provider.append(element('small', official.allocation))
      const local = element('td')
      if (row.guard) {
        metric(local, row.guard.percent, `${row.service} 本機${row.guard.interval === 'month' ? '每月' : '每日'}可用量`)
        for (const item of row.guard.counters) {
          const valid = typeof item.remaining === 'number' && typeof item.limit === 'number'
          local.append(element('small', valid ? `餘 ${item.remaining.toLocaleString('zh-HK')}／${item.limit.toLocaleString('zh-HK')} ${units[item.meter] || ''}` : '本機用量未能讀取'))
        }
        local.append(element('small', '不是平台官方餘額'))
      }
      else { local.append(element('span', '—')) }
      const status = element('td')
      status.append(element('span', row.note))
      if (row.reset_label)
        status.append(element('strong', row.reset_label))
      if (official.status === 'unavailable')
        status.append(element('strong', '官方查詢暫未成功'))
      if (official.status === 'stale')
        status.append(element('strong', '更新失敗 · 只顯示上次記錄'))
      if (official.updated_at_ms)
        status.append(element('small', new Date(official.updated_at_ms).toLocaleString('zh-HK', { hour12: false })))
      if (official.period && !row.reset_label)
        status.append(element('small', official.period))
      if (row.guard?.period)
        status.append(element('small', row.guard.period))
      tr.append(name, provider, local, status)
      root.append(tr)
    }
  }
  function resources(root, data) {
    root.replaceChildren()
    for (const [key, label] of [['cpu', '處理器 CPU'], ['ram', '記憶體 RAM'], ['storage', '磁碟儲存']]) {
      const card = element('div')
      const value = data.metrics?.[key] || {}
      const percent = percentage(value.percent)
      card.append(element('span', label))
      card.append(element('strong', percent === null ? '— 未取得' : `${percent.toFixed(1)}% 已使用`))
      if (percent !== null) {
        const bar = element('progress')
        bar.max = 100
        bar.value = percent
        bar.setAttribute('aria-label', `${label}已使用比例`)
        card.append(bar)
      }
      if (Number.isFinite(value.total_bytes) && value.total_bytes > 0 && Number.isFinite(value.used_bytes))
        card.append(element('small', `${(value.used_bytes / 1073741824).toFixed(1)}／${(value.total_bytes / 1073741824).toFixed(1)} GB`))
      root.append(card)
    }
  }
  function readiness(root, data, now = Date.now()) {
    const expected = ['chat', 'speech', 'recognition', 'page']
    const labels = {chat:'對話設定',speech:'Microsoft 語音服務',recognition:'本機辨識',page:'數字人頁面'}
    if (!Array.isArray(data?.checks) || data.checks.length !== 4
      || !Number.isFinite(data.checked_at_ms) || Math.abs(now-data.checked_at_ms) > 30000
      || expected.some(id => data.checks.filter(row => row?.id === id && typeof row.ready === 'boolean').length !== 1)) {
      root.textContent = '目前未能確認服務狀態，請稍後再查看。'
      return
    }
    root.textContent = expected.map(id => `${labels[id]}：${data.checks.find(row => row.id === id).ready ? '就緒' : '需檢查'}`).join('　·　')
  }
  globalThis.ZhiweiQuota = { render, percentage, resources, readiness }
})()
