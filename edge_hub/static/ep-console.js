// No connection, Wi-Fi password read or motor command occurs on page load.
globalThis.EpManualControl = class {
  constructor(request, notify, now = Date.now) {
    this.request = request
    this.notify = notify
    this.now = now
    this.armed = this.holding = false
    this.epoch = 0
    this.timer = this.lease = null
  }

  async arm() {
    if (this.holding)
      throw new Error('請先放開方向並確認停止。')
    this.armed = false
    const epoch = ++this.epoch
    const status = await this.request('connection', undefined, 'GET')
    if (status.connection !== 'connected' || !status.control || status.control.lease_active
      || status.control.software_stop_latched !== false || status.control.direction !== 'stop'
      || !['idle', 'safe_stop'].includes(status.control.state)) {
      throw new Error('EP 尚未就緒；請先確認靜止及停止鎖定。')
    }
    if (epoch !== this.epoch)
      return false
    this.armed = true
    this.notify('已準備；按住方向才移動，放開停止。')
    return true
  }

  async press(direction) {
    if (this.holding
      || !['forward', 'backward', 'left', 'right', 'turn_left', 'turn_right'].includes(direction)) {
      return
    }
    this.holding = true
    this.notify('按住方向移動，放開停止。')
    const epoch = ++this.epoch
    try {
      if (!this.armed) {
        await this.request('prepare-control', {})
        if (epoch !== this.epoch || !this.holding)
          return
        const status = await this.request('connection', undefined, 'GET')
        if (status.connection !== 'connected' || !status.control || status.control.lease_active
          || status.control.software_stop_latched !== false || status.control.direction !== 'stop'
          || !['idle', 'safe_stop'].includes(status.control.state)) {
          throw new Error('EP 尚未就緒。')
        }
        if (epoch !== this.epoch || !this.holding)
          return
        this.armed = true
      }
      const lease = await this.request('lease', {})
      if (typeof lease.lease_token !== 'string' || !/^[\w-]{20,128}$/.test(lease.lease_token)
        || lease.mode !== 'dji-ep-sdk-live' || !Number.isSafeInteger(lease.server_time_ms)) {
        throw new Error('EP 控制授權資料不符。')
      }
      const offset = lease.server_time_ms - this.now()
      if (epoch !== this.epoch || !this.holding) {
        await this.request('command', { lease_token: lease.lease_token, seq: 0, issued_at_ms: this.now() + offset, ttl_ms: 300, direction: 'stop' })
        return
      }
      this.lease = lease.lease_token
      this.seq = 0
      this.offset = offset
      const cycle = async () => {
        if (epoch !== this.epoch || !this.holding)
          return
        try {
          const state = await this.request('command', this.command(direction))
          if (state.state !== 'manual' || state.direction !== direction || state.connected !== true)
            throw new Error('EP 動作未確認。')
          if (epoch === this.epoch && this.holding)
            this.timer = setTimeout(cycle, 100)
        }
        catch {
          await this.release(true)
          this.notify('EP 指令未確認；已停止續送，請現場核對後再按方向。')
        }
      }
      await cycle()
    }
    catch (error) {
      await this.release(true)
      const detail = typeof error?.message === 'string' ? error.message.slice(0, 180) : '請核對連線及停止鎖定。'
      this.notify(`未能準備遙控：${detail}`)
    }
  }

  command(direction) {
    return { lease_token: this.lease, seq: this.seq++, issued_at_ms: this.now() + this.offset, ttl_ms: 300, direction }
  }

  async release(disarm = false) {
    ++this.epoch
    clearTimeout(this.timer)
    this.timer = null
    this.holding = false
    if (disarm)
      this.armed = false
    if (!this.lease)
      return
    const command = this.command('stop')
    this.lease = null
    try {
      const result = await this.request('command', command, 'POST', true)
      if (result.direction !== 'stop' || result.lease_active !== false || result.state === 'fault')
        throw new Error('stop_unconfirmed')
    }
    catch {
      this.armed = false
      this.notify('停止送達未確認；請立即在現場核對及停機。')
    }
  }
}

if (typeof document !== 'undefined' && document.body?.dataset.epUi !== 'fleet') {
  const node = id => document.querySelector(`#${id}`)
  let qrUrl = ''
  let actionBusy = false
  let polling = false
  let connected = false
  let motionBlocked = false
  let lastAutoScan = 0
  const directions = [...document.querySelectorAll('[data-ep-direction]')]
  const control = new globalThis.EpManualControl(request, (message) => {
    node('motionStatus').textContent = message
    updateButtons()
  })
  function updateButtons() {
    node('connectEp').disabled = actionBusy || connected
    node('disconnectEp').disabled = actionBusy || !connected
    node('stopEp').disabled = !connected
    node('resetEpStop').disabled = actionBusy || !connected
    directions.forEach((button) => {
      button.disabled = !connected || motionBlocked || actionBusy
    })
  }
  async function request(action, body, method = 'POST', keepalive = false) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), action === 'connect' ? 22000 : 7000)
    try {
      const response = await fetch(`/api/v1/robot/ep/${action}`, { method, headers: { 'Content-Type': 'application/json', 'X-Operator-Key': node('epKey').value }, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, cache: 'no-store', credentials: 'omit', redirect: 'error', keepalive })
      const data = await response.json()
      if (!response.ok)
        throw new Error(typeof data.detail === 'string' ? data.detail : 'EP 請求被拒絕。')
      return data
    }
    finally { clearTimeout(timer) }
  }
  function clearQr() {
    if (node('qrDialog').open)
      node('qrDialog').close()
    node('qrZoomImage').removeAttribute('src')
    node('zoomQr').hidden = true
    node('epQr').hidden = true
    node('epQr').removeAttribute('src')
    if (qrUrl)
      URL.revokeObjectURL(qrUrl)
    qrUrl = ''
    node('qrPlaceholder').hidden = false
    node('cancelPairing').hidden = true
    node('networkName').textContent = ''
    node('qrCountdown').textContent = ''
    node('wifiPassword').value = ''
  }
  async function action(task, output = 'epActionStatus') {
    if (actionBusy)
      return
    actionBusy = true
    node(output).textContent = ''
    for (const id of ['currentWifiQr', 'manualWifiQr', 'connectEp', 'disconnectEp', 'resetEpStop'])
      node(id).disabled = true
    updateButtons()
    try {
      await task()
    }
    catch (error) {
      node(output).textContent = error.message || 'EP 操作未確認，請重新整理核對。'
      if (output === 'pairStatus' && error.message?.includes('Windows'))
        node('manualWifiDetails').open = true
    }
    finally {
      actionBusy = false
      for (const id of ['currentWifiQr', 'manualWifiQr', 'connectEp', 'disconnectEp', 'resetEpStop'])
        node(id).disabled = false
      updateButtons()
    }
  }
  function showQr(data) {
    if (typeof data.svg_base64 !== 'string' || !/^[A-Z0-9+/=]+$/i.test(data.svg_base64)
      || data.svg_base64.length > 500000 || data.expires_in_seconds !== null) {
      throw new Error('組網碼格式不符。')
    }
    qrUrl = URL.createObjectURL(new Blob([Uint8Array.from(atob(data.svg_base64), char => char.charCodeAt(0))], { type: 'image/svg+xml' }))
    node('epQr').src = qrUrl
    node('epQr').hidden = false
    node('zoomQr').hidden = false
    node('qrZoomImage').src = qrUrl
    node('qrPlaceholder').hidden = true
    node('cancelPairing').hidden = false
    node('currentWifiQr').textContent = '更新 Wi-Fi QR Code'
    node('networkName').textContent = data.ssid
    node('qrCountdown').textContent = '持續顯示'
    node('wifiSsid').value = data.ssid
    node('pairStatus').textContent = connected ? '' : '請用 EP 掃描，自動連線。'
  }
  async function generateQr(body) {
    node('pairStatus').textContent = '正在讀取目前 Wi-Fi…'
    const data = await request('qr', body)
    clearQr()
    showQr(data)
  }
  node('currentWifiQr').addEventListener('click', () => action(() => generateQr({ use_current_wifi: true }), 'pairStatus'))
  node('zoomQr').addEventListener('click', () => {
    if (qrUrl)
      node('qrDialog').showModal()
  })
  node('closeQrDialog').addEventListener('click', () => node('qrDialog').close())
  node('qrDialog').addEventListener('click', (event) => {
    if (event.target === node('qrDialog'))
      node('qrDialog').close()
  })
  node('manualWifiForm').addEventListener('submit', (event) => {
    event.preventDefault()
    const body = { ssid: node('wifiSsid').value, password: node('wifiPassword').value }
    void action(() => generateQr(body), 'pairStatus')
  })
  node('cancelPairing').addEventListener('click', () => {
    clearQr()
    void action(async () => {
      await request('cancel-pairing', {})
      node('pairStatus').textContent = '已清除組網碼並停止等待。'
    }, 'pairStatus')
  })
  async function connectEp() {
    node('connectionStatus').textContent = '正在連線指定 EP…'
    await control.release(true)
    showStatus(await request('connect', { ip: node('epIp').value.trim(), confirmed: true }))
    node('motionStatus').textContent = '已連線，按住方向移動，放開停止。'
  }
  node('connectEp').addEventListener('click', () => action(connectEp))
  node('disconnectEp').addEventListener('click', () => action(async () => {
    await control.release(true)
    showStatus(await request('disconnect', {}))
    node('motionStatus').textContent = '已要求停止並斷開；請在現場核對機體。'
  }))
  directions.forEach((button) => {
    button.addEventListener('pointerdown', (event) => {
      if (event.button !== 0)
        return
      event.preventDefault()
      button.setPointerCapture(event.pointerId)
      void control.press(button.dataset.epDirection)
    })
    for (const name of ['pointerup', 'pointercancel', 'pointerleave', 'lostpointercapture'])
      button.addEventListener(name, () => { void control.release() })
  })
  node('stopEp').addEventListener('click', async () => {
    await control.release(true)
    try {
      const state = await request('stop', {}, 'POST', true)
      if (state.direction !== 'stop' || state.lease_active !== false || state.state === 'fault')
        throw new Error('停止未確認，請現場停機。')
      node('motionStatus').textContent = 'EP 軟件停止已鎖定；不是硬件急停。'
    }
    catch (error) { node('motionStatus').textContent = error.message }
    updateButtons()
  })
  node('resetEpStop').addEventListener('click', () => action(async () => {
    if (!node('confirmEpStationary').checked)
      throw new Error('請先在現場確認 EP 靜止。')
    await control.release(true)
    await request('reset-stop', { confirmed_stationary: true })
    node('confirmEpStationary').checked = false
    node('motionStatus').textContent = '已重設停止鎖定，可直接按住方向。'
  }, 'motionStatus'))
  function showStatus(data) {
    const justConnected = !connected && data.connection === 'connected'
    connected = data.connection === 'connected'
    motionBlocked = data.control?.state === 'fault' || data.control?.software_stop_latched === true
    node('resetPanel').hidden = !motionBlocked
    if (motionBlocked) {
      node('resetPanel').open = true
      node('motionStatus').textContent = data.control?.state === 'fault'
        ? '遙控異常，請在現場核對 EP。'
        : '已鎖定停止，確認 EP 靜止後可解除。'
    }
    if (justConnected && !control.holding && !motionBlocked)
      node('motionStatus').textContent = '按住方向移動，放開停止。'
    node('connectEp').textContent = '重試連線'
    node('connectionStatus').dataset.connected = String(connected)
    node('connectionStatus').textContent = connected
      ? '已連線'
      : '等待連線'
    if (!connected || data.control?.state === 'fault' || data.control?.software_stop_latched === true) {
      void control.release(true)
      updateButtons()
    }
    if (connected && data.ip)
      node('epIp').value = data.ip
    else if (data.detected_ip)
      node('epIp').value = data.detected_ip
    if (connected) {
      node('pairStatus').textContent = ''
    }
    else if (data.pairing === 'joined_network') {
      node('pairStatus').textContent = 'EP 已回應，正在準備連線。'
    }
    if (!connected && !actionBusy && Number.isSafeInteger(data.scan_id) && data.scan_id > lastAutoScan
      && data.scan_id > (data.auto_connect_suppressed_scan || 0) && data.detected_ip
      && Number.isSafeInteger(data.scan_received_at_ms) && Date.now() - data.scan_received_at_ms < 15000) {
      lastAutoScan = data.scan_id
      void action(connectEp)
    }
    else if (['expired', 'receiver_failed'].includes(data.pairing)) {
      node('pairStatus').textContent = '組網等待已結束；請核對 EP 組網模式、路由器及防火牆後重新產生。'
    }
    updateButtons()
  }
  async function poll() {
    if (polling || actionBusy || document.hidden)
      return
    polling = true
    try {
      showStatus(await request('connection', undefined, 'GET'))
    }
    catch {
      connected = false
      await control.release(true)
      node('connectionStatus').textContent = 'EP 狀態未能核對；已停用遙控，停止送達未確認，請現場核對。'
      updateButtons()
    }
    finally { polling = false }
  }
  const abandon = () => {
    void control.release(true)
    updateButtons()
  }
  for (const name of ['blur', 'pagehide', 'beforeunload', 'offline']) window.addEventListener(name, abandon)
  document.addEventListener('visibilitychange', () => {
    if (document.hidden)
      abandon()
  })
  setInterval(poll, 1000)
  void poll()
  void request('qr', undefined, 'GET').then((data) => {
    if (data.svg_base64)
      showQr(data)
  }).catch(() => { node('pairStatus').textContent = '請按上方按鈕產生組網碼。' })
}
