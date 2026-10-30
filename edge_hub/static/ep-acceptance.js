// Loading or polling this page never connects a robot. POST actions are never retried.
(() => {
  const node = id => document.getElementById(id)
  const stage = Number(document.body?.dataset.acceptanceStage || 2)
  let busy = false
  let polling = false
  let actionError = ''
  let selected = null
  let signature = ''
  let pairingActive = false
  let shortState = null
  let shortPress = null
  let shortUsedLocal = false
  let motorStopId = null
  let latestState = null
  let autoAttempts = 0
  let autoNextAt = 0
  async function request(action, body, keepalive = false, scope = 'acceptance') {
    const response = await fetch(`/api/v1/robot/ep/${scope}/${action}`, {
      method: action === 'status' ? 'GET' : 'POST',
      headers: { 'X-Operator-Key': node('epKey').value, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
      keepalive,
      signal: keepalive ? undefined : AbortSignal.timeout(['connect', 'prepare'].includes(action) ? 24000 : 6000),
    })
    const data = await response.json()
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : '操作未確認，請重新整理。')
      error.status = response.status
      throw error
    }
    return data
  }
  function render(data) {
    latestState = data
    selected = data.selected_id || null
    pairingActive = data.manual_pairing_active === true
    node('pairingGate').hidden = !pairingActive
    node('endPairing').disabled = busy || !pairingActive
    const next = JSON.stringify(data.devices)
    if (next !== signature) {
      signature = next
      const previousChoice = node('device').value
      node('device').replaceChildren()
      const placeholder = document.createElement('option')
      placeholder.value = ''
      placeholder.textContent = '請選擇已通過上一階段的機體 SN'
      node('device').append(placeholder)
      for (const item of data.devices || []) {
        const option = document.createElement('option')
        option.value = item.id
        option.textContent = item.sn
        node('device').append(option)
      }
      node('device').value = (data.devices || []).some(item => item.id === previousChoice) ? previousChoice : ''
    }
    if (selected)
      node('device').value = selected
    node('device').disabled = busy || !!selected
    node('connect').disabled = busy || pairingActive || !!selected || !node('device').value || data.safety_hold !== true
    node('disconnect').disabled = busy || !selected
    if (stage >= 3) {
      node('prepare').disabled = busy || pairingActive || !selected || data.connection !== 'connected'
        || data.acceptance_stage !== stage || data.prepare_attempted === true || data.safety_hold !== true
        || data.chassis_motion_allowed !== true
        || data.control?.software_stop_latched === true || data.control?.state === 'fault'
      node('prepareConfirm').disabled = busy || data.prepare_attempted === true
      const latched = data.control?.software_stop_latched === true
      const fault = data.control?.state === 'fault'
      node('resetPanel').hidden = !selected || (!latched && !fault)
      node('resetNotice').textContent = fault
        ? '這台有故障鎖定，本頁不能解除；請結束並回報。'
        : '這台保留舊停止鎖定；確認靜止後可手動解除，不會自動準備或移動。'
      node('resetStop').disabled = busy || pairingActive || !selected || data.connection !== 'connected'
        || data.acceptance_stage !== stage || data.safety_hold !== true || data.prepared_idle
        || data.chassis_motion_allowed !== true || !latched || fault || data.control?.lease_active === true
    }
    node('elapsed').textContent = `觀察時間：${data.elapsed_seconds || 0} / 120 秒`
    const age = data.chassis_status_age_ms
    const fresh = Number.isFinite(age) && age < 1500
    node('telemetry').textContent = data.connection === 'connected'
      ? fresh ? '已收到底盤狀態；請以現場觀察為準。' : '底盤狀態尚未收到或已過期，請結束驗收並在現場關機。'
      : ''
    node('status').textContent = actionError || data.error || (data.connection === 'connected'
      ? data.elapsed_seconds >= 120 ? '已到 2 分鐘，請記錄有沒有飄移，再按「結束並斷線」。' : '已連線：請勿操作，觀察車輪及機身。'
      : data.connection === 'connecting' ? '正在連線，沒有開啟移動功能…' : selected ? '連線未完成，請先結束本次驗收。' : '尚未連線：選好機體後，才按手動連線。')
    if (stage >= 3 && data.connection === 'connected' && !data.prepared_idle && !actionError) {
      node('status').textContent = data.acceptance_stage !== stage
        ? '目前是另一驗收階段，請先斷線再於本頁連線。'
        : data.prepare_attempted
          ? '準備未完成，請結束驗收；不會自動重試。'
          : data.chassis_motion_allowed !== true
            ? '已連線，底盤狀態尚未確認；請保持平放，持續未確認就結束驗收。'
            : '已連線，尚未準備。確認雲台周圍空曠，再按「準備控制模式」。'
      if (data.control?.software_stop_latched || data.control?.state === 'fault')
        node('status').textContent = node('resetNotice').textContent
    }
    if (pairingActive)
      node('status').textContent = '請先按上方「結束配網」，然後再按「手動連線」。不會自動連線。'
    if (stage >= 4) {
      if (data.short_press_session && shortState?.short_press_session !== data.short_press_session)
        shortUsedLocal = false
      shortState = data
      node('elapsed').textContent = `最低速度 0.15 m/s · 主機最長 ${shortMaxMs() / 1000} 秒 · 本次只測一次`
      updateShortButton()
      if (data.prepared_idle && !actionError && !pairingActive)
        node('status').textContent = '準備完成；本頁只容許一次最低速短按，請以現場是否停穩驗收。'
      if (stage >= 5 && !shortPress && data.last_short_receipt?.stage === stage)
        node('shortResult').textContent = shortStopMessage(data.last_short_receipt.stop_origin)
      if (stage === 6) {
        node('autoConnect').disabled = busy || data.prepared_idle === true || data.connection === 'connected'
        if (data.connection === 'connected' || data.prepared_idle) {
          node('autoConnect').checked = false
          node('autoConnectStatus').textContent = '已連線，自動嘗試已停止；準備及電機操作仍由你決定。'
        }
        const esc = data.esc_diagnostics
        const reasons = {
          waiting_body_telemetry: '等待新鮮的底盤位置、姿態、速度及四輪資料。',
          body_wheel_time_mismatch: '底盤與四輪資料時間未對齊，暫不可釋放。',
          collecting_body_window: '正核對至少 2 秒的底盤與四輪共同窗口。',
          rebuilding_mode_epoch: '電機模式已切換，正收集切換後的新資料。',
          body_motion_in_window: '底盤位置或姿態仍有變化，暫不可釋放。',
          body_motion_current: '最新底盤位置或姿態偏離停穩參考，暫不可釋放。',
          body_reference_mismatch: '底盤偏離本次固定停穩參考，暫不可釋放。',
          confirmed_body_departure: '底盤持續偏離停穩參考，本次阻擋保留；請結束並回報。',
          body_velocity_nonzero: '底盤速度回報未停穩，暫不可釋放。',
          wheel_rotation_in_window: '四輪角度路徑仍顯示轉動，暫不可釋放。',
          wheel_spike_unresolved: '最新輪速或角度尖峰未獲佐證，暫不可釋放。',
          wheel_rpm_quality: '四輪轉速窗口品質不符，暫不可釋放。',
          waiting_for_samples: '未收到四輪轉速回報。',
          waiting_after_stop: '等待停止後的新轉速回報。',
          invalid_sample: '轉速回報格式不符，未能確認停穩。',
          sequence_not_advancing: '轉速回報的序號未持續更新，未能確認資料新鮮。',
          nonzero_speed: '回報仍有車輪轉速，未能釋放。',
          sample_gap: '轉速回報有中斷，正重新確認。',
          stale_sample: '轉速回報已過期，未能釋放。',
          speed_above_rest_limit: '回報轉速超出實驗停穩範圍，未能釋放。',
          encoder_changed: '車輪編碼器角度仍有變化，未能確認停穩。',
          unverified_snapshot: '轉速資料快照未通過驗證，請結束並回報。',
          delayed_callback: '轉速回報處理延遲，未能確認停穩。',
          encoder_excursion: '車輪角度出現實際位移範圍，未能確認停穩。',
          encoder_directional_drift: '車輪角度有持續方向趨勢，未能確認停穩。',
          encoder_drift_since_rest: '確認後又出現角度累積變化，請結束並回報。',
          rpm_inconsistent: '轉速窗口未通過一致性檢查，暫不可釋放。',
          rpm_inconsistent_since_rest: '確認後轉速出現異常，請結束並回報。',
          rebuilding_after_signal_anomaly: '先前訊號異常已記錄，正重建完整的新停穩窗口；暫不可釋放。',
          rpm_unresolved_spike: '轉速尖峰尚未由相鄰角度回報確認，請等候。',
          collecting_rest_samples: '正核對至少 2 秒的轉速與角度一致性。',
        }
        node('wheelStatus').textContent = !data.prepared_idle
          ? ''
          : data.wheel_rest_confirmed === true
            ? '已取得至少 2 秒的停穩回報證據；仍須你現場確認機體與四輪停穩。'
            : !esc
                ? '目前程序未提供轉速診斷；請結束驗收並回報，勿重試準備。'
                : `${reasons[esc.reason] || '未能確認四輪停穩。'}${Array.isArray(esc.speeds_rpm) ? ` 四輪回報：${esc.speeds_rpm.join('／')} rpm。` : ''}`
        if (data.prepared_idle && data.rest_evidence_version === 'body-window-v5'
          && data.wheel_rest_confirmed !== true && esc?.reason === 'wheel_spike_unresolved'
          && esc.rpm_blocker?.at_latest_sample === true) {
          node('wheelStatus').textContent = '正在等下一筆輪速資料核對尖峰；未完成前不會釋放。'
        }
        if (data.prepared_idle && ['snapshot-window-v2', 'snapshot-window-v3'].includes(data.rest_evidence_version)
          && data.wheel_rest_confirmed !== true && esc?.first_block_evidence) {
          const first = esc.first_block_evidence
          node('wheelStatus').textContent = ['sustained_reference_excursion', 'reference_center_shift'].includes(first.kind)
            ? esc.encoder_center_within_reference
              ? '先前曾確認持續偏離停止參考；目前中心已回到附近，但本次阻擋保留，請結束並回報。'
              : '已確認持續偏離停止參考，本次驗收已阻擋；請結束並回報。'
            : '本次停穩證據曾中斷或出現異常，阻擋仍保留；請結束並回報。'
        }
        if (data.prepared_idle && data.rest_evidence_version === 'snapshot-window-v3'
          && data.wheel_rest_confirmed === true && esc?.first_signal_anomaly && esc.signal_recoveries > 0) {
          node('wheelStatus').textContent = '先前訊號異常已保留記錄；目前完整新窗口合格，仍須你親眼確認機體與四輪停穩。'
        }
        if (motorStopId !== data.motor_stop_id) {
          motorStopId = data.motor_stop_id
          node('motorStationary').checked = false
        }
        node('releaseMotor').disabled = busy || pairingActive || !selected || !data.prepared_idle
          || data.connection !== 'connected'
          || data.rest_evidence_version !== 'body-window-v5'
          || data.acceptance_stage !== 6 || data.safety_hold !== true || data.wheel_rest_confirmed !== true
          || data.chassis_motion_allowed !== true || data.control?.lease_active !== false
          || data.control?.software_stop_latched === true || data.control?.state === 'fault'
          || !data.motor_stop_id || !['holding_zero', 'engaged_reply'].includes(data.motor_state)
        node('motorStatus').textContent = data.connection !== 'connected'
          ? '尚未連線，未確認電機狀態。'
          : data.motor_state === 'released_reply'
            ? '已收到釋放回覆；請觀察有沒有滑行或飄移。按住前進才會重新啟用電機。'
            : data.motor_state === 'engaged_reply'
              ? '已重新啟用；放開停止後，請重新確認停穩，再按釋放。'
              : data.motor_state === 'holding_zero'
                ? '零速保持，尚未釋放。底盤與四輪證據合格後，由你確認並按第 3 步。'
                : data.prepared_idle ? '電機模式未確認，已停用操作；請保持平放並在本機關機。' : '手動連線及準備後，才可驗收釋放。'
        node('releaseObservation').textContent = data.motor_state === 'released_reply' && data.motor_release_receipt
          ? `釋放回覆後：${data.released_observation_seconds || 0} / 120 秒。計時不代表實體驗收通過；請勿觸碰機體或車輪。`
          : '尚未收到本輪釋放成功回覆，釋放觀察尚未開始。'
        if (data.connection === 'connected' && data.rest_evidence_version !== 'body-window-v5')
          node('motorStatus').textContent = '目前仍用舊判定。請結束並斷線，再重新連線載入新版；不用關機或重掃碼。'
      }
    }
  }
  async function poll() {
    if (busy || polling)
      return
    polling = true
    try {
      const [data, pairing] = await Promise.all([
        request('status'),
        request('status', undefined, false, 'manual-pairing'),
      ])
      render({ ...data, manual_pairing_active: pairing.active === true })
    }
    catch {
      latestState = null
      shortState = null
      if (stage === 6)
        node('autoConnect').checked = false
      node('connect').disabled = true
      if (stage >= 3) {
        node('prepare').disabled = true
        node('resetStop').disabled = true
      }
      if (stage === 6) {
        node('releaseMotor').disabled = true
        node('motorStationary').checked = false
        node('motorStatus').textContent = '目前電機狀態未確認，操作已停用；不沿用之前的保持或釋放狀態。'
        node('wheelStatus').textContent = '未取得最新停穩判定。'
        node('releaseObservation').textContent = '無法核對當前釋放觀察狀態。'
      }
      if (stage >= 4) {
        node('shortPress').disabled = true
        void releaseShortPress(undefined, 'cancel')
      }
      node('status').textContent = '控制台狀態未確認，不會自動重連 EP。請保持機體靜止，重新整理頁面。'
    }
    finally { polling = false }
    if (stage === 6)
      void maybeAutoConnect()
  }
  async function maybeAutoConnect() {
    if (stage !== 6 || !node('autoConnect').checked || busy || polling || !latestState
      || pairingActive || !node('stationary').checked || !node('device').value
      || latestState.safety_hold !== true || latestState.prepared_idle
      || latestState.connection !== 'not_connected' || Date.now() < autoNextAt) {
      return
    }
    if (latestState.selected_id && (latestState.prepare_attempted
      || latestState.control?.lease_active || latestState.control?.software_stop_latched
      || latestState.control?.state === 'fault'
      || latestState.last_connection_error?.code !== 'handshake_timeout')) {
      node('autoConnect').checked = false
      node('autoConnectStatus').textContent = '目前狀態不可自動重試；保留現有連線及鎖定。'
      return
    }
    if (autoAttempts >= 3) {
      node('autoConnect').checked = false
      node('autoConnectStatus').textContent = '已試 3 次仍未連線；請核對 EP 是否已入網，需要時重新掃碼。'
      return
    }
    busy = true
    autoAttempts += 1
    actionError = ''
    node('autoConnectStatus').textContent = `正在自動連線（${autoAttempts} / 3），不會準備或移動…`
    try {
      await request('connect-auto', { device_id: node('device').value, stage: 6, confirmed_stationary: true, confirmed_auto_connect: true })
    }
    catch (error) {
      actionError = error.message
      if (error.status !== 503)
        node('autoConnect').checked = false
    }
    finally {
      autoNextAt = Date.now() + 5000
      busy = false
    }
    await poll()
    if (node('autoConnect').checked && latestState?.last_connection_error?.code !== 'handshake_timeout')
      node('autoConnect').checked = false
  }
  node('acceptanceForm').addEventListener('submit', async (event) => {
    event.preventDefault()
    if (busy || pairingActive || selected || !node('stationary').checked || !node('device').value)
      return
    busy = true
    actionError = ''
    node('connect').disabled = true
    node('status').textContent = '正在手動連線…'
    try {
      const body = { device_id: node('device').value, confirmed_stationary: true }
      if (stage >= 3)
        body.stage = stage
      await request('connect', body)
    }
    catch (error) { actionError = error.message }
    finally { busy = false }
    await poll()
  })
  node('device').addEventListener('change', () => void poll())
  node('endPairing').addEventListener('click', async () => {
    if (busy || !pairingActive)
      return
    busy = true
    actionError = ''
    node('endPairing').disabled = true
    try {
      await request('end', {}, false, 'manual-pairing')
    }
    catch (error) { actionError = error.message }
    finally { busy = false }
    // Refresh readiness only. Never chain an acceptance connection after end.
    await poll()
  })
  if (stage >= 3) {
    node('resetStop').addEventListener('click', async () => {
      if (busy || !selected || node('resetStop').disabled || !node('resetStationary').checked)
        return
      busy = true
      actionError = ''
      node('resetStop').disabled = true
      try {
        await request('reset-stop', { confirmed_stationary: true })
        node('resetStationary').checked = false
      }
      catch (error) { actionError = error.message }
      finally { busy = false }
      await poll()
    })
    node('prepare').addEventListener('click', async () => {
      if (busy || !selected || node('prepare').disabled || !node('prepareConfirm').checked)
        return
      busy = true
      actionError = ''
      node('prepare').disabled = true
      node('status').textContent = '正在準備：雲台會回正，底盤移動仍禁止。'
      try {
        await request('prepare', { confirmed_gimbal_recenter: true })
      }
      catch (error) { actionError = error.message }
      finally { busy = false }
      await poll()
    })
  }
  if (stage === 6) {
    node('autoConnect').addEventListener('change', () => {
      if (node('autoConnect').checked) {
        autoAttempts = 0
        autoNextAt = 0
        node('autoConnectStatus').textContent = '已開啟；選好機體並確認現場靜止後，本頁會自動嘗試連線。'
        void maybeAutoConnect()
      }
      else {
        node('autoConnectStatus').textContent = '不再開始新的自動連線嘗試。'
      }
    })
    node('stationary').addEventListener('change', () => void maybeAutoConnect())
    node('releaseMotor').addEventListener('click', async () => {
      if (busy || node('releaseMotor').disabled || !node('motorStationary').checked)
        return
      busy = true
      actionError = ''
      node('releaseMotor').disabled = true
      node('motorStationary').checked = false
      try {
        await request('motor-release', {
          session_id: shortState.short_press_session,
          stop_id: shortState.motor_stop_id,
          confirmed_stationary: true,
        })
      }
      catch (error) { actionError = error.message }
      finally { busy = false }
      await poll()
    })
  }
  node('disconnect').addEventListener('click', async () => {
    if (busy)
      return
    if (stage === 6)
      node('autoConnect').checked = false
    if (stage >= 4)
      void releaseShortPress(undefined, 'disconnect')
    busy = true
    actionError = ''
    try {
      await request('disconnect', {})
    }
    catch { actionError = '斷線未確認，請在現場關機。' }
    finally { busy = false }
    await poll()
  })
  window.addEventListener('pagehide', () => {
    if (stage === 6)
      node('autoConnect').checked = false
    if (stage >= 4)
      void releaseShortPress(undefined, 'pagehide')
    if (busy || selected)
      void request('disconnect', {}, true).catch(() => {})
  })
  function updateShortButton() {
    const data = shortState || {}
    node('shortPress').disabled = busy || pairingActive || !selected || data.acceptance_stage !== stage
      || data.safety_hold !== true
      || (stage === 6 && data.rest_evidence_version !== 'body-window-v5')
      || data.connection !== 'connected' || data.prepared_idle !== true || data.movement_enabled !== true
      || data.chassis_motion_allowed !== true || data.control?.software_stop_latched === true
      || data.control?.state === 'fault' || data.short_press_used === true || shortUsedLocal
      || !data.short_press_session || !node('clearPath').checked
  }
  function shortMaxMs() {
    return stage >= 5 ? 500 : 200
  }
  function shortStopMessage(origin) {
    if (stage >= 5) {
      if (origin === 'release')
        return '已記錄由按鍵放開觸發停止；請現場確認是否立即停穩、沒有飄移，再結束並回報。'
      if (origin === 'cancelled_before_start')
        return '放開先到，沒有發出前進；本次未驗到移動後停止，請結束並回報。'
      if (['limit', 'host_limit'].includes(origin))
        return '今次仍由 0.5 秒上限停止，尚未驗到提前放開；請結束並回報，不重按。'
      return '由保護事件停止，尚未確認按鍵提前放開；請結束並回報。'
    }
    return '軟件停止回覆已確認；請現場確認車輪真正停穩及沒有飄移，再結束驗收。'
  }
  async function releaseShortPress(press = shortPress, source = 'release') {
    if (!press || press.released)
      return
    press.released = true
    clearTimeout(press.timer)
    node('shortPress').disabled = true
    node('shortPress').setAttribute('aria-pressed', 'false')
    try {
      const data = await request('short-press-release', { session_id: press.session, press_id: press.id, source }, true)
      const control = data.control || {}
      if (control.direction !== 'stop' || control.lease_active !== false || control.state === 'fault')
        throw new Error('stop_unconfirmed')
      if (shortPress === press && shortState?.short_press_session === press.session)
        node('shortResult').textContent = shortStopMessage(data.short_press_stop_origin)
    }
    catch {
      if (shortPress === press && shortState?.short_press_session === press.session)
        node('shortResult').textContent = '停止未確認，請在現場關機；不會重試或恢復移動。'
    }
  }
  async function startShortPress(event) {
    if (event.isTrusted === false || (event.button !== undefined && event.button !== 0)
      || node('shortPress').disabled || busy || shortUsedLocal || !node('clearPath').checked) {
      return
    }
    const eventAge = typeof event.timeStamp === 'number' && globalThis.performance?.now
      ? Math.max(0, performance.now() - event.timeStamp)
      : 0
    const issuedAt = Math.floor(Date.now() - eventAge)
    const maxMs = shortMaxMs()
    if (eventAge >= maxMs) {
      node('shortResult').textContent = '按鍵已過期，沒有要求移動。請先確認現場狀態。'
      return
    }
    event.preventDefault()
    const press = { id: crypto.randomUUID().replaceAll('-', ''), session: shortState.short_press_session, released: false }
    shortPress = press
    shortUsedLocal = true
    if (stage === 6)
      node('motorStationary').checked = false
    node('shortPress').setAttribute('aria-pressed', 'true')
    node('shortResult').textContent = `正在短按；請立即放開。本次主機最多 ${maxMs / 1000} 秒，不會續送方向。`
    press.timer = setTimeout(() => void releaseShortPress(press, 'limit'), Math.max(1, maxMs - Math.ceil(eventAge)))
    try {
      if (stage === 6) {
        await request('motor-activate', { session_id: press.session, press_id: press.id, issued_at_ms: issuedAt, confirmed_clear_path: true })
        if (press.released || shortPress !== press || shortState?.short_press_session !== press.session)
          return
        if (Date.now() - issuedAt >= maxMs) {
          await releaseShortPress(press, 'limit')
          return
        }
      }
      await request('short-press-start', { session_id: press.session, press_id: press.id, issued_at_ms: issuedAt, confirmed_clear_path: true })
    }
    catch {
      await releaseShortPress(press, 'cancel')
    }
  }
  if (stage >= 4) {
    node('clearPath').addEventListener('change', () => {
      updateShortButton()
      if (!node('clearPath').checked)
        void releaseShortPress(undefined, 'cancel')
    })
    node('shortPress').addEventListener('pointerdown', (event) => {
      if (event.pointerId !== undefined)
        node('shortPress').setPointerCapture?.(event.pointerId)
      void startShortPress(event)
    })
    for (const event of ['pointerup', 'pointercancel', 'lostpointercapture'])
      node('shortPress').addEventListener(event, () => void releaseShortPress(undefined, event === 'pointerup' ? 'release' : 'cancel'))
    node('shortPress').addEventListener('blur', () => void releaseShortPress(undefined, 'blur'))
    for (const event of ['pointerup', 'pointercancel', 'blur'])
      window.addEventListener(event, () => void releaseShortPress(undefined, event === 'pointerup' ? 'release' : event === 'blur' ? 'blur' : 'cancel'))
    node('shortPress').addEventListener('keydown', (event) => {
      if ([' ', 'Enter'].includes(event.key) && !event.repeat)
        void startShortPress(event)
    })
    node('shortPress').addEventListener('keyup', (event) => {
      if ([' ', 'Enter'].includes(event.key))
        void releaseShortPress()
    })
    document.addEventListener('visibilitychange', () => {
      if (document.hidden)
        void releaseShortPress(undefined, 'blur')
    })
  }
  setInterval(poll, 1000)
  void poll()
})()
