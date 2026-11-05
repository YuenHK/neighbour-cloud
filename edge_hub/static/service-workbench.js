(() => {
  const node = id => document.getElementById(id)
  const labels = { general: '一般協助', human_support: '主動聯絡住戶', litter: '垃圾清理', water: '漏水／積水', hazard: '危險情況回報' }
  const states = { new: '待查看', acknowledged: '跟進中', resolved: '已完成' }
  let reading = null
  let updating = false
  let generation = 0
  let offset = 0
  let latestCreated
  let latestSignalType
  let audioContext
  let pendingSound = false
  const drafts = new Map()
  const corrections = new Map()
  let group = globalThis.ZhiweiWorkSection === 'care' ? 'care' : 'requests'
  const filters = globalThis.ZhiweiWorkFilters?.create(node('caseFilters'), { onChange() {
    offset = 0; generation++; void load()
  } })
  filters?.scope(group)
  async function enableSound() {
    try {
      const Context = globalThis.AudioContext || globalThis.webkitAudioContext
      if (!Context) return
      audioContext ??= new Context()
      if (audioContext.state !== 'running') await audioContext.resume()
      if (pendingSound) playSound()
    }
    catch { /* Visual notifications and automatic updates remain available. */ }
  }
  document.addEventListener('pointerdown', () => void enableSound(), { capture: true })
  document.addEventListener('keydown', () => void enableSound(), { capture: true })
  function playSound() {
    if (!audioContext || audioContext.state !== 'running') return
    try {
      const oscillator = audioContext.createOscillator()
      const gain = audioContext.createGain()
      gain.gain.value = 0.05
      oscillator.frequency.value = 660
      oscillator.connect(gain)
      gain.connect(audioContext.destination)
      oscillator.start()
      oscillator.stop(audioContext.currentTime + 0.22)
      pendingSound = false
    }
    catch { pendingSound = true } // Audio failure must not stop case refresh.
  }
  function notify() {
    node('caseAlert').textContent = '有新的求助或巡查待辦，請查看。'
    document.title = '有新求助 · 鄰伴'
    pendingSound = true
    playSound()
  }
  async function request(path, options = {}) {
    const response = await fetch(`/api/v1/service-desk/requests${path}`, { ...options, headers: { 'Content-Type': 'application/json', 'X-Operator-Key': node('operatorKey').value }, signal: AbortSignal.timeout(8000), cache: 'no-store', credentials: 'omit', redirect: 'error' })
    if (!response.ok)
      throw new Error('service_request_failed')
    return response.json()
  }
  function append(parent, tag, text, className) {
    const item = document.createElement(tag)
    item.textContent = text
    if (className)
      item.className = className
    parent.append(item)
    return item
  }
  function render(data) {
    if (!data || !Array.isArray(data.items) || data.items.length > 50
      || typeof data.has_more !== 'boolean' || !data.counts
      || !['new', 'acknowledged', 'resolved'].every(key => data.counts[key] === undefined
        || (Number.isSafeInteger(data.counts[key]) && data.counts[key] >= 0))
      || data.items.some(row => !/^[a-f0-9]{32}$/.test(row.id) || !labels[row.kind] || !states[row.status]
        || typeof row.message !== 'string' || typeof row.location !== 'string' || typeof row.contact !== 'string'
        || !Number.isSafeInteger(row.revision) || row.revision < 1 || !Number.isSafeInteger(row.created_at_ms))) {
      throw new Error('service_invalid')
    }
    node('caseNewCount').textContent = String(data.counts.new || 0)
    node('caseActiveCount').textContent = String(data.counts.acknowledged || 0)
    node('caseClosedCount').textContent = String(data.counts.resolved || 0)
    const signalType = Number.isSafeInteger(data.latest_case_number) ? 'case_number' : 'timestamp'
    const signal = signalType === 'case_number' ? data.latest_case_number : data.latest_created_at_ms
    if (latestSignalType === signalType && latestCreated !== undefined && signal > (latestCreated || 0))
      notify()
    latestCreated = signal
    latestSignalType = signalType
    const container = node('serviceCases')
    const existing = new Map([...container.children].filter(card => card.dataset?.caseId).map(card => [card.dataset.caseId, card]))
    const cards = []
    let deferredEdit = false
    for (const row of data.items) {
      const previous = existing.get(row.id)
      const editing = previous?.querySelector('dialog[open]') || (previous?.contains(document.activeElement) && document.activeElement.matches('textarea,input,select'))
      if (previous && (previous.caseSnapshot === JSON.stringify(row) || editing)) {
        const changed = previous.caseSnapshot !== JSON.stringify(row)
        previous.querySelectorAll('button:not([data-case-close])').forEach(button => { button.disabled = changed })
        deferredEdit ||= changed
        cards.push(previous)
        existing.delete(row.id)
        continue
      }
      previous?.remove()
      const card = document.createElement('article')
      card.className = 'service-case'
      if (!previous) card.className += ' service-case-arriving'
      card.dataset.state = row.status
      card.dataset.caseId = row.id
      card.dataset.revision = String(row.revision)
      card.caseSnapshot = JSON.stringify(row)
      const content = document.createElement('div')
      const urgentCare = row.kind === 'human_support' && row.message.startsWith('【需即時關懷】')
      append(content, 'span', `${urgentCare ? '需即時關懷 · ' : ''}${row.team || labels[row.kind]} · ${states[row.status]}`, `service-badge${row.kind === 'hazard' || urgentCare ? ' warning' : ''}`)
      append(content, 'p', row.message)
      append(content, 'small', `${row.location || '位置未填寫'} · ${new Date(row.created_at_ms).toLocaleString('zh-HK', { timeZone: 'Asia/Hong_Kong', hour12: false })}`)
      if (row.contact)
        append(content, 'small', `聯絡方法：${row.contact}`)
      if (row.assignee)
        append(content, 'small', `負責職員：${row.assignee}`)
      if (row.note)
        append(content, 'p', `最新跟進：${row.note}`)
      if (/^[a-f0-9]{32}$/.test(row.source_event_id || '')) {
        append(content, 'small', row.patrol_status === 'false_positive' ? '巡查回報 · 職員已核實為誤報' : row.status === 'new' ? '巡查候選 · 請先查看三張相片核實' : '巡查回報 · 職員跟進')
        const source = append(content, 'a', '查看現場回報及相片')
        source.href = '/admin#reports'
        source.addEventListener('click', () => {
          try { sessionStorage.setItem('neighbourPatrolEvent', row.source_event_id) } catch {}
          source.closest('dialog')?.close()
        })
        if (row.patrol_sync_pending)
          append(content, 'small', '進度已保存，現場回報同步中。')
      }
      if (row.intake_mode === 'automatic') {
        append(content, 'small', '數字人主動分流 · 待職員核實（不是診斷）')
        if (row.profile)
          append(content, 'small', `居民稱呼：${row.profile}`)
        if (row.contact_preference === 'declined')
          append(content, 'p', '居民暫不希望主動聯絡，請先核實及尊重其選擇。')
        else if (!row.contact_available)
          append(content, 'p', '尚未提供單位或電話，暫未能直接聯絡；可待居民補充。')
      }
      if (row.overdue)
        append(content, 'span', '已過跟進時限', 'service-badge warning')
      if (row.due_at_ms)
        append(content, 'small', `跟進期限：${new Date(row.due_at_ms).toLocaleString('zh-HK', { hour12: false })}`)
      append(content, 'small', `個案編號 ${row.case_number || row.id.slice(0, 8)}${row.unit ? ` · ${row.unit}` : ''} · ${row.source_event_id ? '機械人巡查' : '數字人接收'}`)
      card.append(content)
      if (row.status !== 'resolved') {
        const controls = append(card, 'div', '', 'service-case-controls')
        const note = append(controls, 'textarea', '')
        note.placeholder = '跟進內容／回覆居民'
        note.setAttribute('aria-label', '跟進內容／回覆居民')
        note.maxLength = 1000
        note.rows = 2
        note.value = drafts.get(row.id) || ''
        note.addEventListener('input', () => drafts.set(row.id, note.value))
        const action = append(controls, 'button', row.status === 'new' ? row.source_event_id ? '核實並接手' : '接手跟進' : '標記完成')
        action.type = 'button'
        action.addEventListener('click', () => void update(row, action, note.value))
        if (row.status === 'acknowledged') {
          const progress = append(controls, 'button', '只更新跟進')
          progress.type = 'button'
          progress.addEventListener('click', () => void update(row, progress, note.value, true))
        }
      }
      if (row.message !== '已按保存期限清除') {
        const details = append(card, 'details', '', 'service-case-correction')
        append(details, 'summary', '更正資料')
        append(details, 'small', '核實居民要求後更正；不改個案編號、處理進度或保存期限。')
        const draft = corrections.get(row.id) || { message: row.message, location: row.location, contact: row.contact, reason: '' }
        const inputs = {}
        for (const [field, label, limit] of [['message', '求助內容', 2000], ['location', '位置／單位', 120], ['contact', '聯絡方法', 200], ['reason', '更正原因', 300]]) {
          const wrapper = append(details, 'label', label)
          const input = append(wrapper, field === 'message' ? 'textarea' : 'input', '')
          input.setAttribute('aria-label', label)
          input.maxLength = limit
          input.value = draft[field]
          input.addEventListener('input', () => {
            draft[field] = input.value
            corrections.set(row.id, draft)
          })
          inputs[field] = input
        }
        const save = append(details, 'button', '儲存更正')
        save.type = 'button'
        save.addEventListener('click', () => {
          const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]))
          if (!values.message || values.reason.length < 2) {
            node('caseStatus').textContent = '請保留求助內容，並填寫更正原因。'
            return
          }
          void update(row, save, '', false, values)
        })
      }
      // Keep the live list short. Existing validated forms and draft handling
      // stay in a native modal rather than expanding underneath every case.
      const dialog = document.createElement('dialog')
      dialog.className = 'service-case-dialog'
      const heading = append(dialog, 'div', '', 'service-case-dialog-heading')
      const title = append(heading, 'h3', `個案 ${row.case_number || row.id.slice(0, 8)} · ${labels[row.kind]}`)
      title.id = `case-title-${row.id}`
      dialog.setAttribute('aria-labelledby', title.id)
      const close = append(heading, 'button', '關閉')
      close.type = 'button'
      close.dataset.caseClose = 'true'
      close.addEventListener('click', () => dialog.close())
      const body = append(dialog, 'div', '', 'service-case-dialog-body')
      while (card.firstChild) body.append(card.firstChild)
      if (globalThis.location?.pathname?.startsWith('/cloud/') && row.message !== '已按保存期限清除') {
        const photo = append(body, 'div', '', 'service-case-photo')
        const view = append(photo, 'button', '查看居民自願附相')
        view.type = 'button'
        let photoUrl
        view.addEventListener('click', async () => {
          view.disabled = true
          try {
            const reply = await fetch(`/api/v1/service-desk/requests/${row.id}/photo`, { cache: 'no-store', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(10000) })
            if (reply.status === 404 || reply.status === 410) { view.textContent = '沒有可查看的居民附相'; return }
            if (!reply.ok || !reply.headers.get('content-type')?.startsWith('image/jpeg')) throw new Error('case_photo_unavailable')
            const blob = await reply.blob()
            if (blob.size > 40000 || !dialog.open) throw new Error('case_photo_closed')
            if (photoUrl) URL.revokeObjectURL(photoUrl)
            photoUrl = URL.createObjectURL(blob)
            const image = append(photo, 'img', '')
            image.alt = '居民已確認供個案跟進的相片'
            image.src = photoUrl
            image.style.cssText = 'display:block;max-width:240px;max-height:240px;border-radius:12px;margin:10px 0'
            view.textContent = '居民已確認供職員跟進，非身份核證'
          }
          catch { view.disabled = false; view.textContent = '相片暫時未能載入，按此再試' }
        })
        dialog.addEventListener('close', () => {
          if (photoUrl) URL.revokeObjectURL(photoUrl)
          photoUrl = undefined
          photo.querySelectorAll('img').forEach(image => image.remove())
          view.disabled = false
          view.textContent = '查看居民自願附相'
        })
      }
      const summary = append(card, 'div', '', 'service-case-summary')
      const top = append(summary, 'div', '', 'service-case-summary-heading')
      append(top, 'strong', `#${row.case_number || row.id.slice(0, 8)} · ${labels[row.kind]}`, 'service-case-title')
      append(top, 'span', `${urgentCare ? '需即時關懷 · ' : ''}${states[row.status]}`,
        `service-badge${urgentCare ? ' warning' : ''}`)
      const quote = row.message.includes('居民原話：') ? row.message.split('居民原話：').slice(1).join('居民原話：').split('\n主動分流')[0]
        : row.message.replace(/^【[^】]*】/, '')
      append(summary, 'p', quote, 'service-case-preview')
      const metadata = append(summary, 'div', '', 'service-case-metadata')
      append(metadata, 'span', row.unit || row.location || '待補充位置', 'service-case-location')
      append(metadata, 'span', row.team || labels[row.kind])
      const changedAt = row.updated_at_ms && row.updated_at_ms !== row.created_at_ms ? row.updated_at_ms : row.created_at_ms
      append(summary, 'small', `${changedAt !== row.created_at_ms ? '最近更新' : '建立'}：${new Date(changedAt).toLocaleString('zh-HK', { timeZone: 'Asia/Hong_Kong', hour12: false })}`, 'service-case-time')
      if (row.due_at_ms) append(summary, 'small', `${row.overdue ? '已過跟進期限' : '跟進期限'}：${new Date(row.due_at_ms).toLocaleString('zh-HK', { hour12: false })}`, `service-case-due${row.overdue ? ' overdue' : ''}`)
      const open = append(card, 'button', '查看及跟進', 'service-case-open')
      open.type = 'button'
      open.addEventListener('click', () => dialog.showModal())
      dialog.addEventListener('close', () => { open.focus(); void load() })
      card.append(dialog)
      cards.push(card)
      existing.delete(row.id)
    }
    for (const card of existing.values()) {
      if (card.contains(document.activeElement) && document.activeElement.matches('textarea,input,select')) {
        card.querySelectorAll('button:not([data-case-close])').forEach(button => { button.disabled = true })
        cards.push(card)
        deferredEdit = true
      }
      else card.remove()
    }
    for (const child of [...container.children]) if (!child.dataset?.caseId) child.remove()
    cards.forEach((card, index) => {
      if (container.children[index] !== card) container.insertBefore(card, container.children[index] || null)
    })
    if (!cards.length)
      append(container, 'p', filters ? '沒有符合條件的個案；可以清除篩選再查看全部。' : group === 'care' ? '暫時沒有需要關懷跟進的個案。' : '暫時沒有居民求助；有新回報會自動出現。', 'service-empty')
    node('caseStatus').textContent = group === 'care' ? '關懷清單已更新。' : '求助單已更新；正在查看的職員請接手跟進。'
    if (deferredEdit) node('caseStatus').textContent += ' 正編輯的個案另有更新，離開輸入欄後會顯示；草稿保留。'
    node('casesPage').textContent = `第 ${offset / 50 + 1} 頁${Number.isSafeInteger(data.matched_total) ? ` · 共 ${data.matched_total} 項符合條件` : ''}`
    node('casesPrevious').disabled = offset === 0
    node('casesNext').disabled = !data.has_more
  }
  function load() {
    if (updating)
      return Promise.resolve()
    if (reading)
      return reading
    const version = generation
    reading = (async () => {
      try {
        const data = await request(`?offset=${offset}&limit=50&group=${group}${filters ? '&' + filters.query() : ''}`)
        if (version === generation && !data.items?.length && offset > 0 && Number.isSafeInteger(data.matched_total)) {
          offset = Math.max(0, Math.ceil(data.matched_total / 50) - 1) * 50
          generation++
          return
        }
        if (version === generation)
          render(data)
      }
      catch {
        if (version !== generation)
          return
        node('caseStatus').textContent = '求助單暫時未能更新，以下不是最新狀態；操作已暫停。'
        for (const id of ['caseNewCount', 'caseActiveCount', 'caseClosedCount'])
          node(id).textContent = '—'
        node('serviceCases').querySelectorAll('button:not([data-case-close])').forEach((button) => {
          button.disabled = true
        })
        node('casesNext').disabled = true
        node('casesPrevious').disabled = true
      }
      finally {
        reading = null
        if (version !== generation && !updating)
          void load()
      }
    })()
    return reading
  }
  async function update(row, button, note, progressOnly = false, correction = null) {
    if (updating || button.disabled)
      return
    updating = true
    generation++
    button.disabled = true
    let failed = false
    try {
      const body = correction ? { expected_revision: row.revision, ...correction } : { expected_revision: row.revision, status: progressOnly || row.status === 'new' ? 'acknowledged' : 'resolved', assignee: row.assignee || '管理團隊', note: note.trim() || row.note || '' }
      await request(`/${row.id}${correction ? '/details' : ''}`, { method: 'PATCH', body: JSON.stringify(body) })
      button.closest('dialog')?.close()
      if (correction) corrections.delete(row.id)
      else drafts.delete(row.id)
      node('caseAlert').textContent = ''
      document.title = '鄰伴 · 管理工作台'
      node('caseStatus').textContent = correction ? '已更正個案資料。' : '已更新跟進狀態。'
    }
    catch {
      failed = true
      node('caseStatus').textContent = '更新未確認，正在重新核對；不會重複提交。'
    }
    finally {
      updating = false
      if (reading)
        await reading
      await load()
      if (failed)
        node('caseStatus').textContent += ' 上次狀態更新未確認，請查看當前進度。'
    }
  }
  node('serviceCases').addEventListener('focusout', () => queueMicrotask(() => void load()))
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void load() })
  node('casesPrevious').addEventListener('click', () => {
    if (!reading && !updating && offset >= 50) {
      offset -= 50
      void load()
    }
  })
  node('casesNext').addEventListener('click', () => {
    if (!reading && !updating && !node('casesNext').disabled) {
      offset += 50
      void load()
    }
  })
  void load()
  document.addEventListener('worksectionchange', (event) => {
    if (!['requests', 'care'].includes(event.detail) || group === event.detail)
      return
    group = event.detail
    filters?.scope(group)
    offset = 0
    generation++
    void load()
  })
  setInterval(() => {
    void load()
  }, 2000)
})()
