(() => {
  const node = id => document.getElementById(id)
  let items = []
  let selected = null
  let creating = crypto.randomUUID().replaceAll('-', '')
  let saving = false
  let memoryGeneration = 0
  async function request(path, body, method = 'GET') {
    const response = await fetch(`/api/v1/service-desk/${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Operator-Key': node('operatorKey').value },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
    })
    if (!response.ok)
      throw new Error('estate_update_unconfirmed')
    return response.json()
  }
  async function loadKnowledge(identity = '') {
    const data = await request('knowledge')
    items = data.items
    const list = node('knowledgeList')
    list.replaceChildren(new Option('新增資料', ''))
    for (const item of items)
      list.add(new Option(`${item.enabled ? '' : '已停用 · '}${item.title}`, item.id))
    list.value = identity
    select()
  }
  function select() {
    selected = items.find(item => item.id === node('knowledgeList').value) || null
    creating = crypto.randomUUID().replaceAll('-', '')
    node('knowledgeTitle').value = selected?.title || ''
    node('knowledgeKeywords').value = selected?.keywords.join('、') || ''
    node('knowledgeAnswer').value = selected?.answer || ''
    node('knowledgeEnabled').checked = selected?.enabled ?? true
  }
  node('knowledgeList').addEventListener('change', select)
  node('knowledgeForm').addEventListener('submit', async (event) => {
    event.preventDefault()
    if (saving)
      return
    saving = true
    node('saveKnowledge').disabled = true
    const identity = selected?.id || creating
    try {
      await request(`knowledge/${identity}`, { title: node('knowledgeTitle').value.trim(), keywords: node('knowledgeKeywords').value.split(/[、，,\n]/).map(value => value.trim()).filter(Boolean), answer: node('knowledgeAnswer').value.trim(), enabled: node('knowledgeEnabled').checked, expected_revision: selected?.revision || 0 }, 'PUT')
      await loadKnowledge(identity)
      node('knowledgeStatus').textContent = '已儲存。啟用的資料即時供居民查詢。'
    }
    catch {
      node('knowledgeStatus').textContent = '儲存未確認，輸入仍保留；資料可能已更新，請重新核對後再處理。'
    }
    finally {
      saving = false
      node('saveKnowledge').disabled = false
    }
  })
  void loadKnowledge().catch(() => {
    node('knowledgeStatus').textContent = '資料暫時未能載入，請稍後重整。'
  })
  async function loadMemories() {
    const version = ++memoryGeneration
    const profile = node('residentMemoryProfile').value.trim()
    const data = await request(`resident-memories?profile=${encodeURIComponent(profile)}`)
    if (version !== memoryGeneration || profile !== node('residentMemoryProfile').value.trim())
      return
    node('residentMemoryItems').replaceChildren()
    for (const item of data.items) {
      const row = document.createElement('div')
      row.className = 'service-actions'
      const text = document.createElement('span')
      text.textContent = item.text
      const remove = document.createElement('button')
      remove.type = 'button'
      remove.textContent = '停止使用這項記憶'
      remove.addEventListener('click', async () => {
        remove.disabled = true
        try {
          await request(`resident-memories/${item.id}?profile=${encodeURIComponent(profile)}`, undefined, 'DELETE')
          await loadMemories()
        }
        catch { node('residentMemoryStatus').textContent = '更新未確認，請重新查看核對。' }
      })
      row.append(text, remove)
      node('residentMemoryItems').append(row)
    }
    node('residentMemoryStatus').textContent = data.items.length ? `共 ${data.items.length} 項。` : '這個稱呼暫時沒有已儲存記憶。'
  }
  node('residentMemoriesForm').addEventListener('submit', (event) => {
    event.preventDefault()
    void loadMemories().catch(() => {
      node('residentMemoryStatus').textContent = '暫時未能查看，請稍後再試。'
    })
  })
  node('residentMemoryProfile').addEventListener('input', () => {
    memoryGeneration++
    node('residentMemoryItems').replaceChildren()
    node('residentMemoryStatus').textContent = ''
  })
  let quotaReading = false
  async function loadQuota(refresh = false) {
    if (quotaReading)
      return
    quotaReading = true
    node('refreshQuota').disabled = true
    try {
      const result = await request(`quota${refresh ? '?refresh=true' : ''}`)
      const rows = result.overview?.active_rows || result.overview?.rows
      if (!Array.isArray(rows))
        throw new Error('quota_overview_missing')
      globalThis.ZhiweiQuota.render(node('apiQuotaRows'), rows)
      node('quotaFunctions').textContent = result.overview?.local_functions || ''
      node('quotaStatus').textContent = rows.some(row => ['stale', 'unavailable'].includes(row.provider?.status) || row.guard?.status === 'unavailable')
        ? '部分平台暫時未能更新；請留意「未取得」或「上次記錄」標示。'
        : `已核對 · ${new Date(result.overview.updated_at_ms).toLocaleString('zh-HK', { hour12: false })}`
      node('quotaLocalStatus').textContent = result.chat?.last_model
        ? `最近對話已完成${result.chat.last_route?.includes('fallback') ? '，已自動使用備援' : ''}。`
        : ''
    }
    catch {
      node('apiQuotaRows').replaceChildren()
      node('quotaLocalStatus').textContent = ''
      node('quotaStatus').textContent = '未能更新額度；目前數字未知，請稍後再核對。'
    }
    finally {
      quotaReading = false
      node('refreshQuota').disabled = false
    }
  }
  node('refreshQuota').addEventListener('click', () => void loadQuota(true))
  void loadQuota()
  setInterval(() => {
    if (!document.hidden)
      void loadQuota()
  }, 60000)
  let resourcesReading = false
  async function loadResources() {
    if (resourcesReading || document.hidden || node('panel-usage').hidden)
      return
    resourcesReading = true
    try {
      globalThis.ZhiweiQuota.resources(node('localResourceItems'), await request('resources'))
      node('localResourceStatus').textContent = '整台 Notebook 的即時使用率；磁碟為 AIRI 所在磁碟。'
    }
    catch {
      globalThis.ZhiweiQuota.resources(node('localResourceItems'), { metrics: {} })
      node('localResourceStatus').textContent = '目前未能讀取本機用量，不能當作 0%。'
    }
    finally { resourcesReading = false }
  }
  document.addEventListener('visibilitychange', () => void loadResources())
  window.addEventListener('hashchange', () => queueMicrotask(() => void loadResources()))
  setInterval(() => void loadResources(), 5000)
  void loadResources()
  let readinessReading = false
  async function loadReadiness() {
    const status = node('serviceReadiness')
    if (!status || readinessReading || document.hidden || node('panel-usage').hidden)
      return
    readinessReading = true
    try { globalThis.ZhiweiQuota.readiness(status, await request('readiness')) }
    catch { status.textContent = '目前未能確認服務狀態，請稍後再查看。' }
    finally { readinessReading = false }
  }
  document.addEventListener('visibilitychange', () => void loadReadiness())
  window.addEventListener('hashchange', () => queueMicrotask(() => void loadReadiness()))
  setInterval(() => void loadReadiness(), 10000)
  void loadReadiness()
})()
