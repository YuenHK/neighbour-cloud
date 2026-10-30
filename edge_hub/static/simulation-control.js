/* Local simulation only. No hardware switching, persistent credentials or auto-resume. */
class SimulationControl {
  constructor({ request, key, now = Date.now, later = setTimeout, cancel = clearTimeout,
    notify = () => {} }) {
    Object.assign(this, { request, key, now, later, cancel, notify })
    this.armed = this.holding = this.acquiring = this.stopping = false
    this.epoch = 0
    this.lease = this.credential = this.timer = null
    this.seq = 0
    this.offset = 0
  }

  assertSimulation(state, latched = false) {
    if (state?.mode !== 'simulation' || state.connected !== false
      || state.hardware_acceptance !== false || state.software_stop_latched !== latched)
      throw new Error('simulation_not_ready')
    const lifecycleKnown = ['shutdown_requested', 'control_lifecycle_scope']
      .some(key => Object.hasOwn(state, key))
    if (lifecycleKnown && (state.shutdown_requested !== false
      || state.control_lifecycle_scope !== 'host shutdown intent only; not worker exit or hardware stop proof'))
      throw new Error('simulation_not_ready')
  }

  assertSoftwareStop(state) {
    this.assertSimulation(state, true)
    if (state.state !== 'safe_stop' || state.direction !== 'stop' || state.lease_active !== false)
      throw new Error('simulation_stop_unconfirmed')
  }

  assertSoftwareReset(state) {
    this.assertSimulation(state)
    if (state.state !== 'idle' || state.direction !== 'stop' || state.lease_active !== false)
      throw new Error('simulation_reset_unconfirmed')
  }

  async arm() {
    if (this.acquiring || this.holding || this.stopping || !this.key().trim())
      throw new Error('not_ready_to_arm')
    this.armed = false
    const epoch = ++this.epoch
    const state = await this.request('status')
    this.assertSimulation(state)
    if (!['idle', 'safe_stop'].includes(state.state) || state.direction !== 'stop' || state.lease_active !== false)
      throw new Error('simulation_not_ready')
    if (epoch !== this.epoch) return false
    this.armed = true
    this.notify('已準備模擬；按住方向才發送，放開停止。')
    return true
  }

  async press(direction) {
    if (!['forward', 'backward', 'left', 'right', 'turn_left', 'turn_right'].includes(direction)
      || !this.armed || this.holding || this.acquiring || this.stopping) return false
    const epoch = ++this.epoch
    const key = this.key().trim()
    this.holding = this.acquiring = true
    try {
      const lease = await this.request('lease', {}, key)
      if (typeof lease?.lease_token !== 'string' || lease.lease_token.length < 20
        || lease.lease_token.length > 128 || /[^A-Za-z0-9_-]/.test(lease.lease_token)
        || lease.mode !== 'simulation' || !Number.isSafeInteger(lease.server_time_ms) || lease.server_time_ms < 0)
        throw new Error('invalid_simulation_lease')
      if (epoch !== this.epoch || !this.holding) {
        await this.request('command', { lease_token: lease.lease_token, seq: 0,
          issued_at_ms: lease.server_time_ms, ttl_ms: 300, direction: 'stop' }, key, true)
        return false
      }
      this.lease = lease.lease_token
      this.credential = key
      this.offset = lease.server_time_ms - this.now()
      this.seq = 0
      await this.cycle(epoch, direction)
      return true
    }
    catch {
      await this.stop({ disarm: true })
      this.notify('模擬指令失敗：已停止續送；須重新準備，不會自動恢復。')
      return false
    }
    finally { this.acquiring = false }
  }

  command(direction) {
    return { lease_token: this.lease, seq: this.seq++,
      issued_at_ms: this.now() + this.offset, ttl_ms: 300, direction }
  }

  async cycle(epoch, direction) {
    if (!this.holding || epoch !== this.epoch || !this.lease) return
    try {
      const state = await this.request('command', this.command(direction), this.credential)
      if (epoch !== this.epoch || !this.holding) return
      this.assertSimulation(state)
      if (state.direction !== direction) throw new Error('simulation_stopped')
      this.notify(`模擬方向：${direction}；非實機動作。`)
      this.timer = this.later(() => { void this.cycle(epoch, direction) }, 75)
    }
    catch {
      if (epoch !== this.epoch) return
      await this.stop({ disarm: true })
      this.notify('逾時或指令失敗：停止續送，須重新準備。')
    }
  }

  async stop({ disarm = false, keepalive = false } = {}) {
    ++this.epoch
    this.holding = false
    if (disarm) this.armed = false
    this.cancel(this.timer)
    this.timer = null
    if (!this.lease) return
    const payload = this.command('stop')
    const key = this.credential
    this.lease = this.credential = null
    this.stopping = true
    try {
      const state = await this.request('command', payload, key, keepalive)
      this.assertSimulation(state)
      if (state.direction !== 'stop' || state.lease_active !== false || state.state !== 'safe_stop')
        throw new Error('simulation_stop_unconfirmed')
      this.notify('已確認模擬停止；不是實體急停驗收。')
    }
    catch {
      this.armed = false
      this.notify('未收到停止確認；已停止續送，依賴後端 TTL/watchdog，不可視作實機安全。')
    }
    finally { this.stopping = false }
  }
}

if (typeof module !== 'undefined') module.exports = { SimulationControl }

if (typeof document !== 'undefined') {
  const output = document.querySelector('#controlStatus')
  const keyInput = document.querySelector('#controlKey')
  async function request(action, body, key, keepalive = false) {
    const abort = new AbortController()
    let timer
    try {
      const timeout = new Promise((_resolve, reject) => {
        timer = setTimeout(() => { abort.abort(); reject(new Error('timeout')) }, 150)
      })
      const response = await Promise.race([fetch(`/api/v1/robot/simulation/${action}`, {
        method: body === undefined ? 'GET' : 'POST',
        headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-Operator-Key': key },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store', credentials: 'omit', redirect: 'error', keepalive, signal: abort.signal,
      }).then(async response => {
        if (!response.ok) throw new Error('request_rejected')
        return response.json()
      }), timeout])
      return response
    }
    finally { clearTimeout(timer); abort.abort() }
  }
  const control = new SimulationControl({ request, key: () => keyInput.value,
    notify: text => { output.textContent = text } })
  document.querySelector('#armSimulation').addEventListener('click', async () => {
    try { await control.arm() }
    catch { output.textContent = '未能準備模擬：請重新整理，並檢查模式、停止鎖定及服務版本。' }
  })
  for (const button of document.querySelectorAll('[data-direction]')) {
    button.addEventListener('pointerdown', event => {
      if (event.button !== 0) return
      event.preventDefault()
      button.setPointerCapture(event.pointerId)
      void control.press(button.dataset.direction)
    })
    for (const name of ['pointerup', 'pointercancel', 'pointerleave', 'lostpointercapture'])
      button.addEventListener(name, () => { void control.stop() })
  }
  const abandon = () => { void control.stop({ disarm: true, keepalive: true }) }
  for (const name of ['blur', 'pagehide', 'beforeunload', 'offline']) window.addEventListener(name, abandon)
  document.addEventListener('visibilitychange', () => { if (document.hidden) abandon() })
  keyInput.addEventListener('input', abandon)
  document.querySelector('#softwareStop').addEventListener('click', async () => {
    await control.stop({ disarm: true })
    try {
      const state = await request('software-stop', {}, keyInput.value.trim(), true)
      control.assertSoftwareStop(state)
      output.textContent = '模擬軟件停止已鎖定；不是硬件急停。'
    }
    catch { output.textContent = '停止鎖定未確認；停止續送，請檢查本機後端。' }
  })
  document.querySelector('#resetSimulationStop').addEventListener('click', async () => {
    if (!document.querySelector('#confirmStationary').checked || control.holding || control.acquiring) return
    await control.stop({ disarm: true })
    try {
      const state = await request('reset-software-stop', { confirmed_stationary: true }, keyInput.value.trim())
      control.assertSoftwareReset(state)
      document.querySelector('#confirmStationary').checked = false
      output.textContent = '僅模擬停止鎖定已重設；仍須重新按準備，沒有恢復移動。'
    }
    catch { output.textContent = '未能重設；不會自動解除或恢復。' }
  })
}
