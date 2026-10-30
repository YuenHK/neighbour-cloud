// Offline preparation UI: deliberately no movement, connection or media endpoints.
globalThis.ZhiweiEpPreparation = {
  format(data) {
    if (data?.schema !== 'ep-offline-preparation-v1' || data.target_model !== 'EP'
      || data.scope !== 'offline_preparation_not_hardware_acceptance'
      || data.connection !== 'not_connected'
      || ['motion_enabled', 'video_enabled', 'audio_enabled', 'hardware_acceptance', 'autonomous_navigation']
        .some(key => data[key] !== false)
      || data.sdk_timeout_scope !== 'host_timer_not_hardware_watchdog')
      throw new Error('inconsistent_ep_preparation')
    const sdk = data.adapted_runtime_report_state === 'reported_offline_pass'
      ? '專案適配版離機匯入／合成解碼報告已核對（非原版 wheel，非實機驗收）'
      : data.sdk_report_state === 'blocked_native_wheel_abi'
      ? '現成 SDK wheel 與本機 Python 不符' : 'SDK 執行環境尚未驗證'
    return `EP 實機未接通；${sdk}。人手控制／聲畫全部停用；尚待現場停止、斷網及 PC 中斷、人工接管、畫面私隱與聲音驗收。`
  },
  async read(key, request = fetch, timeoutMs = 2000) {
    if (typeof key !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(key))
      throw new Error('operator_key_required')
    const controller = new AbortController()
    let timer
    try {
      const deadline = new Promise((_resolve, reject) => {
        timer = setTimeout(() => {
          controller.abort()
          reject(new Error('ep_preparation_timeout'))
        }, timeoutMs)
      })
      const operation = (async () => {
        const response = await request('/api/v1/robot/ep/preparation', {
          method: 'GET', headers: { 'X-Operator-Key': key }, signal: controller.signal,
          credentials: 'omit', redirect: 'error', cache: 'no-store',
        })
        if (!response.ok) throw new Error('ep_preparation_unavailable')
        return response.json()
      })()
      return await Promise.race([operation, deadline])
    }
    finally {
      clearTimeout(timer)
      controller.abort()
    }
  },
}

if (typeof document !== 'undefined') {
  const button = document.querySelector('#refreshEp')
  const status = document.querySelector('#epStatus')
  button.addEventListener('click', async () => {
    if (button.disabled) return
    button.disabled = true
    try {
      const data = await ZhiweiEpPreparation.read(document.querySelector('#epKey').value)
      status.textContent = ZhiweiEpPreparation.format(data)
    }
    catch {
      status.textContent = '未能核對（權限／接口未載入／逾時／資料不一致）；所有實機功能仍停用。'
    }
    finally { button.disabled = false }
  })
}
