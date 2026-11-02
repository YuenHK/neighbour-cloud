// Local fleet UI. Page load reads only; cameras start after the user's view action.
globalThis.EpFleetKeys = Object.freeze({ w: 'forward', arrowup: 'forward', s: 'backward', arrowdown: 'backward', a: 'left', arrowleft: 'left', d: 'right', arrowright: 'right', q: 'turn_left', e: 'turn_right' })

if (typeof document !== 'undefined' && document.body?.dataset.epUi === 'fleet') {
  const hardwareOnly = document.body.dataset.hardwareOnly === 'true'
  const node = id => document.getElementById(id)
  const models = new Map()
  const controls = new Map()
  const views = new Map()
  const attempted = new Map()
  const connecting = new Set()
  let irHold = null
  let selected = null
  let switching = false
  let qrUrl = ''
  let polling = false
  let controlFault = false
  let manualOperation = true
  let viewEpoch = 0
  let pressedKey = ''
  let listSignature = ''
  let qrBusy = false
  let qrRevision = ''
  let qrSyncBusy = false
  let authRefresh = null
  let configBusy = false
  let patrolBusy = false
  let patrolSelected = null
  let patrolReady = !hardwareOnly
  let deliveryState = null
  const patrolDrafts = new Map()
  let cursor = null
  const directionButtons = [...document.querySelectorAll('[data-ep-direction]')]

  async function renewOperator() {
    if (!authRefresh) {
      authRefresh = (async () => {
        const response = await fetch('/robots', { cache: 'no-store', credentials: 'omit', redirect: 'error' })
        if (!response.ok)
          throw new Error('控制台恢復中，會自動重新連線。')
        const page = new DOMParser().parseFromString(await response.text(), 'text/html')
        const token = page.querySelector('#epKey')?.value
        if (typeof token !== 'string' || token.length < 20)
          throw new Error('控制台恢復中，會自動重新連線。')
        node('epKey').value = token
      })().finally(() => { authRefresh = null })
    }
    return authRefresh
  }
  async function api(action, body, method = 'POST', keepalive = false, deviceId = null, allowRefresh = true) {
    if (deviceId !== null && !/^ep-[1-8]$/.test(deviceId))
      throw new Error('機體識別不符。')
    const prefix = deviceId ? `devices/${deviceId}${action ? '/' : ''}` : ''
    const abort = new AbortController()
    const timeout = setTimeout(() => abort.abort(), ['connect', 'video-start', 'prepare-control', 'gimbal-follow'].includes(action) ? 22000 : 6000)
    try {
      const response = await fetch(`/api/v1/robot/ep/${prefix}${action}`, { method, headers: { 'X-Operator-Key': node('epKey').value, 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: abort.signal, keepalive, cache: 'no-store', credentials: 'omit', redirect: 'error' })
      const result = await response.json()
      if (response.status === 403 && allowRefresh) {
        await renewOperator()
        if (method === 'GET')
          return api(action, undefined, method, keepalive, deviceId, false)
        throw new Error('連線已恢復，請放開方向後重新操作。')
      }
      if (!response.ok)
        throw new Error(typeof result.detail === 'string' ? result.detail : '操作未完成，請重試。')
      return result
    }
    finally { clearTimeout(timeout) }
  }
  const notice = (message) => {
    node('driveNotice').textContent = message
  }
  // Explicit arguments keep the device ID in the fifth position even for short calls.
  function requestFor(id) {
    return (action, body, method = 'POST', keepalive = false) => api(action, body, method, keepalive, id)
  }
  function getControl(id) {
    if (!controls.has(id))
      controls.set(id, new globalThis.EpManualControl(requestFor(id), notice))
    return controls.get(id)
  }
  function battery(model) {
    return Number.isInteger(model.battery_percent) && model.battery_percent >= 0 && model.battery_percent <= 100
      ? `電量 ${model.battery_percent}%`
      : '電量未回報'
  }
  function deviceLabel(model) {
    return model?.sn || '待確認機體'
  }
  function blocked(model) {
    return model?.context_capture_busy === true || model?.connection !== 'connected' || model.control?.software_stop_latched === true || model.control?.state === 'fault'
  }
  function updateControls() {
    const model = models.get(selected)
    const patrol = model?.patrol || {}
    if (irHold && (irHold.id !== selected || model?.connection !== 'connected')) stopInfrared()
    node('infraredWarning').disabled = !model || model.connection !== 'connected'
    node('patrolToggle').disabled = !patrolReady || patrolBusy || !model || (!patrol.enabled && (model.connection !== 'connected' || !model.video_enabled))
    node('patrolToggle').textContent = patrol.enabled ? '巡邏回報：開' : '巡邏回報：關'
    node('patrolToggle').setAttribute('aria-pressed', String(!!patrol.enabled))
    node('patrolStatus').textContent = patrol.last_error || ({ off: '開啟鏡頭後可啟用，回報附相片供職員核實。', waiting: '等待本機辨識…', queued: '多機輪流辨識 · 等候處理最新畫面…', analysing: '正在辨識最新畫面…', collecting_photos: '發現候選 · 正在收集現場相片…', waiting_stationary: '等候機體停穩，再拍攝環境相片。', waiting_camera: '鏡頭已停止或未有新影像，暫停辨識。', observing: '巡邏觀察中 · 候選附相片，等候職員核實。', unavailable: '本機辨識暫未完成，請人工查看鏡頭。' }[patrol.state || 'off'])
    if (hardwareOnly && !patrolReady) {
      node('patrolStatus').textContent = '自動巡查回報尚未接通雲端；目前可人手遙控及查看鏡頭。'
      for (const id of ['patrolZone', 'patrolRestricted', 'patrolCloud']) node(id).disabled = true
    }
    else if (hardwareOnly) {
      node('patrolZone').disabled = patrolBusy
      node('patrolRestricted').disabled = patrolBusy
      node('patrolCloud').disabled = true
      node('patrolCloud').checked = false
      if (deliveryState?.pending > 0) node('patrolStatus').textContent += ` 雲端待送達 ${deliveryState.pending} 份；現場相片已保留。`
      else if (deliveryState?.case_number) node('patrolStatus').textContent += ` 最近回報已送達，個案 ${deliveryState.case_number}。`
    }
    node('warningStatus').textContent = ({ starting: '已要求綠色彈道燈及提示音，請現場核實。', completed: '機體已回覆完成，實際效果請現場核實。', unconfirmed: '彈道燈、提示音或關燈未完全確認，請現場查看，沒有自動重試。' }[model?.warning?.state] || '')
    if (patrolSelected !== selected) {
      patrolSelected = selected
      const draft = patrolDrafts.get(selected) || patrol
      node('patrolZone').value = draft.zone || ''
      node('patrolRestricted').checked = draft.restricted_area === true
      node('patrolCloud').checked = draft.cloud_review === true
    }
    node('driveControls').hidden = !selected
    node('dockEmpty').hidden = !!selected
    directionButtons.forEach((button) => {
      button.disabled = switching || configBusy || !model || blocked(model)
    })
    node('stopSelected').disabled = !model || model.connection !== 'connected'
    node('resetArea').hidden = !model || !model.control?.software_stop_latched
    const controlFaulted = model?.control?.state === 'fault'
    node('resetSelected').disabled = model?.connection !== 'connected'
    node('resetSelected').textContent = controlFaulted ? '檢查停止回覆（不移動）' : '解除停止鎖定'
    if (controlFaulted) notice(model.stop_confirmation?.code === 'confirmed' ? '停止回覆已確認；原故障仍保留，等待核對，未解鎖或移動。' : '機體已連線，但之前停止回覆未確認，移動仍被故障鎖定；可在現場確認停穩後檢查停止回覆。')
    const follow = model?.follow_enabled !== false
    node('followSelected').disabled = !model || model.connection !== 'connected' || configBusy
    node('followSelected').textContent = follow ? '跟隨：開' : '跟隨：關'
    node('followSelected').setAttribute('aria-pressed', String(follow))
    node('speedLevel').disabled = !model || model.connection !== 'connected' || configBusy
    if (!configBusy && document.activeElement !== node('speedLevel')) {
      node('speedLevel').value = String(model?.speed_level || 1)
      node('speedValue').textContent = `${(0.15 * (model?.speed_level || 1)).toFixed(2)} m/s`
    }
    node('gimbalHint').textContent = follow ? '鏡頭跟隨底盤正前方' : '將游標放在選定畫面，控制雲台角度'
    for (const [id, view] of views) {
      const item = models.get(id)
      view.telemetry.textContent = item?.connection === 'connected' ? battery(item) : '已斷線'
      view.panel.classList.toggle('selected', id === selected)
      view.select.textContent = id === selected ? `操作中 · ${deviceLabel(item)}` : `操作 ${deviceLabel(item)}`
    }
  }
  async function releaseAll() {
    pressedKey = ''
    const stopping = [...controls.values()].map(control => control.release(true))
    stopping.push(stopCursor())
    await Promise.allSettled(stopping)
  }
  async function selectDevice(id) {
    if (switching || configBusy || !views.has(id) || selected === id)
      return
    switching = true
    updateControls()
    await releaseAll()
    selected = models.get(id)?.connection === 'connected' ? id : null
    if (selected) {
      node('driveControlLabel').textContent = `操作 ${deviceLabel(models.get(selected))}`
    }
    node('stationary').checked = false
    notice(selected ? '' : '這台 EP 未連線。')
    switching = false
    updateControls()
  }
  async function connectDevice(id) {
    if (connecting.has(id))
      return
    connecting.add(id)
    renderList()
    try {
      const status = await api('connect', {}, 'POST', false, id)
      const canonical = status.canonical_device_id || id
      if (canonical !== id) {
        models.delete(id)
        models.set(canonical, { ...models.get(canonical), ...status, id: canonical, error: '' })
      }
      else {
        Object.assign(models.get(id), status, { error: '' })
      }
    }
    catch (error) { models.get(id).error = `${error.message} 請確認 EP 已開機並使用同一 Wi-Fi；換網後可重新掃碼。` }
    finally {
      connecting.delete(id)
      renderList()
    }
  }
  function showList() {
    node('pairingView').hidden = false
    node('devicesView').hidden = false
    node('fleetLayout').classList.toggle('has-known', true)
  }
  function renderList() {
    const signature = JSON.stringify([controlFault, manualOperation, [...models.values()].map(item => [item.id, item.sn, item.connection, item.battery_percent, item.remembered, item.error, item.status_cached, item.status_stale, connecting.has(item.id)])])
    const count = [...models.values()].filter(item => item.connection === 'connected').length
    node('fleetCount').textContent = `${models.size} 台已加入 · ${count} 台已連線`
    node('deviceList').dataset.count = String(models.size)
    node('deviceList').dataset.density = models.size >= 5 ? 'compact' : 'normal'
    node('monitorEp').disabled = controlFault || count === 0
    node('backToDevices').hidden = true
    if (signature === listSignature)
      return
    listSignature = signature
    node('deviceList').replaceChildren()
    for (const item of [...models.values()].sort((a, b) => Number(b.connection === 'connected') - Number(a.connection === 'connected') || deviceLabel(a).localeCompare(deviceLabel(b)))) {
      const card = document.createElement('article')
      const online = item.connection === 'connected'
      card.className = `device-card ${online ? 'is-online' : 'is-offline'}`
      const heading = document.createElement('h3')
      heading.textContent = deviceLabel(item)
      heading.title = deviceLabel(item)
      const label = document.createElement('p')
      label.className = 'device-sn-label'
      label.textContent = item.sn ? '機體 SN' : '機體'
      const status = document.createElement('p')
      status.className = 'device-status'
      status.textContent = connecting.has(item.id)
        ? '正在連線…'
        : item.status_stale ? '狀態未更新 · 正在核對' : controlFault ? '控制故障 · 尚未連線' : online ? `在線 · ${item.status_cached ? '正在核對狀態' : battery(item)}` : item.auto_reconnect === false ? '離線 · 未啟用自動連線' : '離線 · 自動檢查中'
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'primary'
      button.disabled = controlFault || (!online && !manualOperation) || connecting.has(item.id)
      button.textContent = connecting.has(item.id) ? '連線中…' : online ? '開啟遙控' : manualOperation && !controlFault ? '連線' : '離線'
      button.addEventListener('click', () => {
        if (models.get(item.id).connection === 'connected')
          void openViews([item.id], item.id)
        else if (manualOperation && !controlFault)
          void connectDevice(item.id)
      })
      const remove = document.createElement('button')
      remove.type = 'button'
      remove.className = 'forget-ep'
      remove.textContent = '刪除記錄'
      remove.disabled = online || connecting.has(item.id) || item.status_stale === true
      remove.title = item.status_stale ? '狀態正在核對，稍後再試' : online ? '先斷開機體再刪除記錄' : '只移除清單記錄'
      let confirmed = false
      remove.addEventListener('click', async () => {
        if (!confirmed) { confirmed = true; remove.textContent = '再按一次確認刪除'; return }
        remove.disabled = true
        try {
          await api('', undefined, 'DELETE', false, item.id)
          models.delete(item.id)
          controls.delete(item.id)
          attempted.delete(item.id)
          if (selected === item.id) selected = null
          updateControls()
          listSignature = ''
          renderList()
        }
        catch (error) { notice(error.message); remove.disabled = false }
      })
      const identity = document.createElement('div')
      identity.className = 'device-identity'
      identity.append(label, heading)
      card.append(identity, status, button, remove)
      if (item.error && !online) {
        const error = document.createElement('p')
        error.className = 'device-error'
        error.textContent = item.error
        card.append(error)
      }
      node('deviceList').append(card)
    }
  }
  async function poll() {
    if (polling || document.hidden)
      return
    polling = true
    try {
      const result = await api('fleet', undefined, 'GET')
      deliveryState = result.delivery || null
      patrolReady = !hardwareOnly || deliveryState?.paired === true
      controlFault = result.safety_hold === true
      manualOperation = hardwareOnly || result.manual_only === true
      node('fleetLayout').classList.toggle('has-control-fault', controlFault)
      node('makeQr').disabled = result.safety_hold === true || qrBusy
      node('manualWifiQr').disabled = result.safety_hold === true
      node('addEp').disabled = result.safety_hold === true
      node('monitorEp').disabled = result.safety_hold === true
      node('addEp').hidden = controlFault
      node('monitorEp').hidden = controlFault
      if (result.safety_hold)
        node('pairStatus').textContent = '控制故障尚未排除，暫不能新增或遙控機體。'
      if (result.qr_revision && qrRevision && result.qr_revision !== qrRevision && !qrSyncBusy) {
        qrSyncBusy = true
        void api('qr', undefined, 'GET').then(showQr).catch(() => {
          node('pairStatus').textContent = '請重新整理取得目前的 QR Code。'
        }).finally(() => { qrSyncBusy = false })
      }
      if (Date.now() - (result.pairing_diagnostics?.last_wrong_code_at_ms || 0) < 15000)
        node('pairStatus').textContent = '收到舊組網碼的回覆，請用這台 EP 重新掃描目前的 QR Code。'
      const currentIds = new Set(result.devices.map(item => item.id))
      for (const id of models.keys()) {
        if (!currentIds.has(id)) {
          void controls.get(id)?.release(true)
          models.delete(id)
        }
      }
      node('fleetNotice').textContent = result.notice || result.discovery_error || ''
      for (const item of result.devices) {
        const previous = models.get(item.id)
        models.set(item.id, { ...previous, ...item, error: item.connection === 'connected' ? '' : item.error || previous?.error || '' })
        if (!previous)
          showList()
        if (blocked(item))
          void controls.get(item.id)?.release(true)
        const scan = item.scan_id
        if (!manualOperation && !result.safety_hold && !result.auto_monitoring && item.connection !== 'connected' && Number.isSafeInteger(scan) && scan > (attempted.get(item.id) || 0)
          && scan > (item.auto_connect_suppressed_scan || 0) && Number.isSafeInteger(item.scan_received_at_ms)
          && Date.now() - item.scan_received_at_ms < 15000) {
          attempted.set(item.id, scan)
          showList()
          void connectDevice(item.id)
        }
      }
      renderList()
      if (controlFault) {
        node('pairingView').hidden = true
        node('devicesView').hidden = false
      }
      updateControls()
    }
    catch {
      for (const model of models.values()) model.connection = 'not_connected'
      await releaseAll()
      updateControls()
      renderList()
      node('fleetNotice').textContent = '控制台連線中斷，正在自動重連；如機體仍移動，請現場停機。'
    }
    finally { polling = false }
  }
  async function configureSelected(action, body) {
    const id = selected
    if (!id || configBusy)
      return
    configBusy = true
    updateControls()
    await releaseAll()
    try {
      Object.assign(models.get(id), await api(action, body, 'POST', false, id))
      notice('')
    }
    catch (error) { notice(error.message) }
    finally {
      configBusy = false
      updateControls()
    }
  }
  async function stopCursor() {
    const old = cursor
    cursor = null
    if (!old)
      return
    clearTimeout(old.timer)
    if (old.session) {
      try {
        await api('gimbal-stop', { generation: old.session.generation }, 'POST', true, old.id)
      }
      catch { notice('雲台停止送達未確認，請現場核對。') }
    }
  }
  function pointGimbal(id, event) {
    if (id !== selected || configBusy || models.get(id)?.follow_enabled !== false || event.pointerType === 'touch')
      return
    if (event.target.closest('button, input, details, summary')) {
      void stopCursor()
      return
    }
    const rect = views.get(id).panel.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
    const target = { yaw: (x - 0.5) * 120, pitch: Math.max(-20, Math.min(25, (0.5 - y) * 50)) }
    if (cursor?.id === id) {
      cursor.target = target
      return
    }
    const current = { id, target, session: null, seq: 0, timer: null }
    cursor = current
    const run = async () => {
      if (cursor !== current || selected !== id || !node('driveDialog').open)
        return
      try {
        if (!current.session) {
          current.session = await api('gimbal-start', {}, 'POST', false, id)
          current.offset = current.session.server_time_ms - Date.now()
          if (cursor !== current || selected !== id) {
            await api('gimbal-stop', { generation: current.session.generation }, 'POST', true, id)
            return
          }
        }
        await api('gimbal-target', { generation: current.session.generation, seq: current.seq++, issued_at_ms: Date.now() + current.offset, ...current.target }, 'POST', false, id)
        if (cursor === current)
          current.timer = setTimeout(run, 100)
      }
      catch (error) {
        if (cursor === current) {
          await stopCursor()
          notice(error.message)
        }
      }
    }
    void run()
  }
  async function frameLoop(id, epoch) {
    const view = views.get(id)
    if (!view || epoch !== viewEpoch)
      return
    try {
      // One bounded viewer heartbeat, not a worker JSON/base64 roundtrip per frame.
      if (!view.heartbeatAt || Date.now() - view.heartbeatAt >= 1000) {
        view.heartbeatAt = Date.now()
        await api('video-frame', undefined, 'GET', false, id)
      }
      const response = await fetch(`/api/v1/robot/ep/devices/${id}/frame.jpg?after=${encodeURIComponent(view.frameKey || '')}`, {
        headers: { 'X-Operator-Key': node('epKey').value }, cache: 'no-store', credentials: 'omit',
        redirect: 'error', signal: AbortSignal.timeout(2000),
      })
      if (response.status === 403) { await renewOperator(); throw new Error('refresh') }
      if (response.status === 204 && response.headers.get('X-Frame-State') === 'unchanged') {
        view.timer = setTimeout(() => { void frameLoop(id, epoch) }, views.size === 1 ? 80 : 200)
        return
      }
      const frame = { jpeg: response.status === 200 && response.ok ? await response.blob() : null,
        age_ms: Number(response.headers.get('X-Frame-Age-Ms') || 0), video_enabled: true }
      view.frameKey = response.headers.get('X-Frame-Key') || ''
      if (epoch !== viewEpoch)
        return
      if (!frame.jpeg) {
        view.image.hidden = true
        view.message.textContent = frame.video_enabled ? '等待即時影像…' : '影像未開啟'
      }
      else {
        const next = URL.createObjectURL(frame.jpeg)
        view.image.src = next
        view.image.hidden = false
        view.message.textContent = ''
        if (view.url)
          URL.revokeObjectURL(view.url)
        view.url = next
        clearTimeout(view.staleTimer)
        view.staleTimer = setTimeout(() => {
          view.image.hidden = true
          view.message.textContent = '影像中斷'
        }, Math.max(50, 1200 - (frame.age_ms || 0)))
      }
    }
    catch {
      view.image.hidden = true
      view.message.textContent = '影像中斷'
    }
    if (epoch === viewEpoch)
      view.timer = setTimeout(() => { void frameLoop(id, epoch) }, views.size === 1 ? 80 : 200)
  }
  async function openViews(ids, initialId = null) {
    if (node('driveDialog').open)
      return
    const epoch = ++viewEpoch
    selected = null
    notice('')
    node('viewGrid').replaceChildren()
    node('viewGrid').className = `view-grid ${ids.length === 1 ? 'single' : 'split'}`
    node('driveTitle').textContent = ids.length === 1 ? deviceLabel(models.get(ids[0])) : '分割監看 · 點畫面切換 EP'
    for (const id of ids) {
      const panel = document.createElement('section')
      panel.className = 'view-tile'
      panel.setAttribute('aria-label', `${deviceLabel(models.get(id))}，點擊畫面切換控制`)
      panel.addEventListener('click', (event) => {
        if (event.target.closest('button, input, summary, details, .floating-controls'))
          return
        void selectDevice(id).then(() => pointGimbal(id, event))
      })
      panel.addEventListener('pointermove', event => pointGimbal(id, event))
      panel.addEventListener('pointerenter', event => pointGimbal(id, event))
      panel.addEventListener('pointerleave', () => {
        if (cursor?.id === id)
          void stopCursor()
      })
      const image = document.createElement('img')
      image.alt = `${deviceLabel(models.get(id))} 即時影像`
      image.hidden = true
      const message = document.createElement('p')
      message.className = 'video-message'
      message.textContent = '正在開啟影像…'
      const hud = document.createElement('div')
      hud.className = 'hud'
      const select = document.createElement('button')
      select.type = 'button'
      select.className = 'select-ep'
      select.addEventListener('click', () => void selectDevice(id))
      const telemetry = document.createElement('span')
      telemetry.className = 'telemetry'
      hud.append(select, telemetry)
      const crosshair = document.createElement('span')
      crosshair.className = 'crosshair'
      crosshair.textContent = '+'
      crosshair.setAttribute('aria-hidden', 'true')
      panel.append(image, message, hud, crosshair)
      node('viewGrid').append(panel)
      views.set(id, { panel, image, message, select, telemetry, url: null, timer: null })
    }
    node('driveDialog').showModal()
    if (initialId)
      await selectDevice(initialId)
    updateControls()
    await Promise.allSettled(ids.map(async (id) => {
      try {
        await api('video-start', {}, 'POST', false, id)
        if (epoch !== viewEpoch) {
          await api('video-stop', {}, 'POST', true, id)
          return
        }
        void frameLoop(id, epoch)
      }
      catch (error) {
        if (epoch === viewEpoch)
          views.get(id).message.textContent = error.message
      }
    }))
  }
  async function closeViews() {
    stopInfrared()
    ++viewEpoch
    const ids = [...views.keys()]
    await releaseAll()
    selected = null
    for (const view of views.values()) {
      clearTimeout(view.timer)
      clearTimeout(view.staleTimer)
      if (view.url)
        URL.revokeObjectURL(view.url)
    }
    views.clear()
    node('driveDialog').close()
    if (document.fullscreenElement)
      void document.exitFullscreen().catch(() => {})
    updateControls()
    await Promise.allSettled(ids.map(async (id) => {
      await api('patrol', { enabled: false }, 'POST', true, id).catch(() => {})
      await api('video-stop', {}, 'POST', true, id)
    }))
  }
  async function stopSelected() {
    const id = selected
    if (!id)
      return
    await Promise.allSettled([getControl(id).release(true), stopCursor()])
    try {
      const state = await api('stop', {}, 'POST', true, id)
      if (state.direction !== 'stop' || state.lease_active !== false || state.state === 'fault')
        throw new Error('停止未確認，請現場停機。')
      models.get(id).control = state
      notice('已鎖定停止。')
      updateControls()
    }
    catch (error) { notice(error.message) }
  }
  directionButtons.forEach((button) => {
    button.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || !selected || switching || blocked(models.get(selected)))
        return
      event.preventDefault()
      button.setPointerCapture(event.pointerId)
      void getControl(selected).press(button.dataset.epDirection)
    })
    for (const name of ['pointerup', 'pointercancel', 'pointerleave', 'lostpointercapture']) {
      button.addEventListener(name, () => {
        if (selected)
          void getControl(selected).release()
      })
    }
  })
  document.addEventListener('keydown', (event) => {
    if (!node('driveDialog').open || !selected || switching || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName))
      return
    const key = event.key.toLowerCase()
    if (key === ' ') {
      event.preventDefault()
      if (!event.repeat)
        void stopSelected()
    }
    else if (globalThis.EpFleetKeys[key]) {
      event.preventDefault()
      if (event.repeat || pressedKey || blocked(models.get(selected)))
        return
      pressedKey = key
      void getControl(selected).press(globalThis.EpFleetKeys[key])
    }
  })
  document.addEventListener('keyup', (event) => {
    if (event.key.toLowerCase() === pressedKey) {
      pressedKey = ''
      if (selected)
        void getControl(selected).release()
    }
  })
  node('stopSelected').addEventListener('click', () => void stopSelected())
  node('resetSelected').addEventListener('click', async () => {
    const id = selected
    if (!id || !node('stationary').checked)
      return notice('請先確認這台 EP 已靜止。')
    try {
      const result = await api('reset-stop', { confirmed_stationary: true }, 'POST', false, id)
      models.get(id).control = result
      node('stationary').checked = false
      notice('')
      updateControls()
    }
    catch (error) { notice(error.message) }
  })
  node('disconnectSelected').addEventListener('click', async () => {
    const id = selected
    if (!id)
      return
    await closeViews()
    try {
      await api('disconnect', {}, 'POST', false, id)
      await poll()
    }
    catch (error) { node('fleetNotice').textContent = error.message }
  })
  node('closeDrive').addEventListener('click', () => void closeViews())
  node('driveDialog').addEventListener('cancel', (event) => {
    event.preventDefault()
    void closeViews()
  })
  node('followSelected').addEventListener('click', () => {
    void configureSelected('gimbal-follow', { enabled: models.get(selected)?.follow_enabled === false })
  })
  node('speedLevel').addEventListener('input', () => {
    node('speedValue').textContent = `${(0.15 * Number(node('speedLevel').value)).toFixed(2)} m/s`
  })
  node('speedLevel').addEventListener('change', () => {
    void configureSelected('speed', { level: Number(node('speedLevel').value) })
  })
  node('fullScreenViews').addEventListener('click', () => {
    void releaseAll()
    const change = document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()
    void change.catch(() => notice('未能切換全螢幕，請重試。'))
  })
  document.addEventListener('fullscreenchange', () => {
    node('fullScreenViews').textContent = document.fullscreenElement ? '退出全螢幕' : '全螢幕'
  })
  node('monitorEp').addEventListener('click', () => {
    const ids = [...models.values()].filter(item => item.connection === 'connected').map(item => item.id)
    if (ids.length)
      void openViews(ids)
  })
  node('addEp').addEventListener('click', () => {
    node('pairingView').hidden = false
    node('pairingView').scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  })
  node('backToDevices').addEventListener('click', showList)
  function showQr(data) {
    if (!data.svg_base64)
      return
    if (typeof data.svg_base64 !== 'string' || !/^[A-Z0-9+/=]+$/i.test(data.svg_base64) || data.svg_base64.length > 500000)
      throw new Error('QR Code 格式不符。')
    if (qrUrl)
      URL.revokeObjectURL(qrUrl)
    qrRevision = typeof data.revision === 'string' ? data.revision : ''
    qrUrl = URL.createObjectURL(new Blob([Uint8Array.from(atob(data.svg_base64), char => char.charCodeAt(0))], { type: 'image/svg+xml' }))
    node('epQr').src = node('qrZoomImage').src = qrUrl
    node('zoomQr').hidden = false
    node('qrEmpty').hidden = true
    node('networkName').textContent = data.ssid
    node('makeQr').textContent = '更新 Wi-Fi QR Code'
    node('pairStatus').textContent = ''
  }
  async function makeQr(body) {
    if (qrBusy)
      return
    qrBusy = true
    node('makeQr').disabled = true
    node('pairStatus').textContent = '正在產生…'
    try {
      showQr(await api('qr', body))
    }
    catch (error) { node('pairStatus').textContent = error.message }
    finally {
      qrBusy = false
      node('makeQr').disabled = false
      node('wifiPassword').value = ''
    }
  }
  node('makeQr').addEventListener('click', () => void makeQr({ use_current_wifi: true }))
  node('manualWifiForm').addEventListener('submit', (event) => {
    event.preventDefault()
    void makeQr({ ssid: node('wifiSsid').value, password: node('wifiPassword').value })
  })
  node('zoomQr').addEventListener('click', () => node('qrDialog').showModal())
  node('closeQr').addEventListener('click', () => node('qrDialog').close())
  function stopInfrared() {
    const hold = irHold
    if (!hold) return
    irHold = null
    clearTimeout(hold.timer)
    void api('infrared-warning', { press_id: hold.press, active: false }, 'POST', true, hold.id).catch(() => {
      notice('停止回覆未確認；已停止續送，請現場核實。')
    })
  }
  async function startInfrared(event) {
    if (event.type === 'pointerdown' && event.button !== 0) return
    if (irHold || !selected || node('infraredWarning').disabled) return
    event.preventDefault()
    if (event.type === 'pointerdown') node('infraredWarning').setPointerCapture?.(event.pointerId)
    const hold = { id: selected, press: `${Date.now()}-${Math.random().toString(36).slice(2)}` }
    irHold = hold
    async function renew() {
      if (irHold !== hold) return
      try {
        await api('infrared-warning', { press_id: hold.press, active: true }, 'POST', false, hold.id)
        if (irHold === hold) hold.timer = setTimeout(renew, 400)
      }
      catch { stopInfrared(); notice('紅外線警示未確認，已停止續送。') }
    }
    await renew()
  }
  node('infraredWarning').addEventListener('pointerdown', startInfrared)
  for (const name of ['pointerup', 'pointercancel', 'lostpointercapture'])
    node('infraredWarning').addEventListener(name, stopInfrared)
  node('infraredWarning').addEventListener('keydown', event => {
    if ([' ', 'Enter'].includes(event.key) && !event.repeat) void startInfrared(event)
  })
  node('infraredWarning').addEventListener('keyup', stopInfrared)
  const abandon = () => { stopInfrared(); void releaseAll() }
  for (const name of ['blur', 'offline']) window.addEventListener(name, abandon)
  window.addEventListener('pagehide', () => { stopInfrared(); void closeViews() })
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { stopInfrared(); void closeViews() }
  })
  setInterval(poll, 800)
  async function configurePatrol(toggle = false) {
    const id = selected
    if (!id || patrolBusy)
      return
    const enabled = toggle ? !models.get(id)?.patrol?.enabled : !!models.get(id)?.patrol?.enabled
    const settings = { enabled, zone: node('patrolZone').value.trim(), restricted_area: node('patrolRestricted').checked, cloud_review: node('patrolCloud').checked }
    patrolDrafts.set(id, settings)
    if (!toggle && !enabled)
      return
    patrolBusy = true
    updateControls()
    try { models.get(id).patrol = await api('patrol', settings, 'POST', false, id) }
    catch (error) { notice(error.message) }
    finally { patrolBusy = false; updateControls() }
  }
  node('patrolToggle').addEventListener('click', () => void configurePatrol(true))
  for (const id of ['patrolZone', 'patrolRestricted', 'patrolCloud']) node(id).addEventListener('change', () => void configurePatrol())
  void Promise.resolve(globalThis.EpDiscoveryReady).then(poll).then(() => api('qr', undefined, 'GET')).then((data) => {
    if (data.safety_hold) {
      node('pairStatus').textContent = '控制故障尚未排除，暫不能新增或遙控機體。'
      return
    }
    if (data.svg_base64)
      showQr(data)
    else if (!manualOperation)
      void makeQr({ use_current_wifi: true })
  }).catch(() => { node('pairStatus').textContent = '請產生 QR Code。' })
}
