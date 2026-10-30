(() => {
  const panel = document.getElementById('panel-knowledge')
  if (!panel) return
  const details = document.createElement('details')
  details.className = 'service-card'
  const summary = document.createElement('summary')
  summary.textContent = '資料保存及查閱紀錄'
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  const list = document.createElement('ul')
  const backupStatus = document.createElement('p')
  backupStatus.setAttribute('role', 'status')
  const refresh = document.createElement('button')
  refresh.textContent = '更新紀錄'
  let busy = false
  async function load() {
    if (busy) return
    busy = true; refresh.disabled = true
    try {
      const request = async suffix => {
        const response = await fetch('/api/v1/governance/' + suffix, {
          headers: { 'X-Operator-Key': document.querySelector('#operatorKey').value },
          cache: 'no-store', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(5000),
        })
        if (!response.ok) throw new Error('unavailable')
        return response.json()
      }
      const [policy, audit] = await Promise.all([request('retention'),request('audit?limit=20')])
      status.textContent = `${policy.notice} ${policy.automatic_deletion_enabled ? '自動檢查已啟用。' : '自動清理尚未啟用。'}${policy.maintenance?.last_success === false ? '上次清理未完成，請管理人員核對；未當成成功。' : ''}`
      const backups = policy.backups
      backupStatus.textContent = backups?.last_success
        ? `服務資料每日自動備份，保留最近 ${backups.retained_sets} 份（最多七份）。最近備份：${new Date(backups.last_backup_ms).toLocaleString('zh-HK', { timeZone: 'Asia/Hong_Kong' })}。已檢查資料庫及隔離復原；不包含相片原檔、金鑰、模型或機體控制設定，亦未取代正式資料。`
        : backups?.last_success === false ? '備份檢查未完成，請聯絡系統維護人員；不能當成可復原。' : '首次服務資料備份尚未完成。'
      list.replaceChildren()
      for (const row of audit.items) {
        const item = document.createElement('li')
        const action = row.method === 'GET' ? '查看' : row.method === 'RETENTION' ? '保存期限檢查' : '更新／處理'
        const area = row.route.includes('patrol') ? '巡查相片' : row.route.includes('memories') ? '保存記憶' : row.route.includes('knowledge') ? '屋苑資料' : row.route.includes('service-desk') ? '居民個案' : '現場回報'
        const result = row.status === null ? '結果未確認' : row.status < 400 ? '已完成' : '未完成／被拒絕'
        item.textContent = `${new Date(row.at_ms).toLocaleString('zh-HK')} · ${row.actor === 'automatic_policy' ? '系統' : '職員入口'} · ${action} ${row.method === 'RETENTION' ? '' : area} · ${result}`
        list.append(item)
      }
    }
    catch { status.textContent = '暫時未能讀取保存安排或查閱紀錄，沒有當成已更新。'; backupStatus.textContent = '備份狀態暫時無法核對。' }
    finally { busy = false; refresh.disabled = false }
  }
  details.append(summary,status,backupStatus,refresh,list)
  panel.append(details)
  details.addEventListener('toggle', () => { if (details.open) void load() })
  refresh.onclick = load
})()
