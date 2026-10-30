// QR remains in browser memory. Only an explicit click reads WLAN credentials.
(() => {
  const node = id => document.getElementById(id)
  let targetId = null
  let busy = false
  let polling = false
  let active = false
  let revision = ''
  let qrUrl = ''
  let epoch = 0
  let lastError = ''
  async function request(action, body, method = 'GET') {
    const response = await fetch(`/api/v1/robot/ep/manual-pairing/${action}`, {
      method,
      headers: { 'X-Operator-Key': node('epKey').value, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
      signal: AbortSignal.timeout(10000),
    })
    const data = await response.json()
    if (!response.ok)
      throw new Error(typeof data.detail === 'string' ? data.detail : '配網操作未完成，請重整頁面。')
    return data
  }
  function clearQr() {
    if (node('qrDialog').open)
      node('qrDialog').close()
    node('qrImage').removeAttribute('src')
    node('zoomImage').removeAttribute('src')
    node('zoom').hidden = true
    if (qrUrl)
      URL.revokeObjectURL(qrUrl)
    qrUrl = ''
    revision = ''
  }
  function showQr(data) {
    if (!data.svg_base64)
      return
    if (!/^[A-Z0-9+/=]+$/i.test(data.svg_base64) || data.svg_base64.length > 500000)
      throw new Error('配網碼格式不符，請重新產生。')
    clearQr()
    qrUrl = URL.createObjectURL(new Blob([Uint8Array.from(atob(data.svg_base64), c => c.charCodeAt(0))], { type: 'image/svg+xml' }))
    node('qrImage').src = node('zoomImage').src = qrUrl
    node('zoom').hidden = false
    node('network').textContent = `配網 Wi-Fi：${data.ssid || ''} · 點擊 QR Code 放大`
    revision = data.revision || ''
  }
  async function poll() {
    if (busy || polling)
      return
    polling = true
    try {
      const data = await request('status')
      targetId = data.target?.id || null
      active = data.active === true
      node('target').textContent = `配網機體 SN：${data.target?.sn || '0930'}`
      node('generate').disabled = !targetId || !data.safety_hold || data.acceptance_busy
      node('passwordGenerate').disabled = node('generate').disabled
      node('end').disabled = !active
      node('reply').textContent = (data.candidates || []).map(item => `收到配網回覆 IP：${item.ip}（SN 尚未核對）`).join('；')
      if (lastError)
        node('notice').textContent = lastError
      else if (data.acceptance_busy)
        node('notice').textContent = '請先返回驗收頁按「結束並斷線」，再產生配網碼。'
      else if (!targetId)
        node('notice').textContent = '找不到唯一的 0930 保存記錄，未開啟配網。'
      else if (data.pairing === 'joined_network')
        node('notice').textContent = '已收到配網回覆，沒有自動連線。請確認 EP 青綠長亮，記下 IP 後結束配網。'
      else if (data.pairing === 'receiver_failed')
        node('notice').textContent = '配網接收已中斷，請結束後重新手動產生。'
      else if (active)
        node('notice').textContent = '請用 0930 掃碼；QR 會保持顯示，不會自動連線。'
      if (!lastError && data.qr_revision && data.qr_revision !== revision) {
        const mine = epoch
        const qr = await request('qr')
        if (mine === epoch)
          showQr(qr)
      }
    }
    catch (error) { node('notice').textContent = error.message }
    finally { polling = false }
  }
  async function generate(password) {
    if (busy || !targetId || node('generate').disabled)
      return
    busy = true
    lastError = ''
    const mine = ++epoch
    clearQr()
    node('generate').disabled = node('passwordGenerate').disabled = true
    node('notice').textContent = '正在讀取目前 Wi-Fi 並產生配網碼…'
    const body = { device_id: targetId }
    if (password !== undefined)
      body.password = password
    node('wifiPassword').value = ''
    try {
      const data = await request('qr', body, 'POST')
      if (mine === epoch) {
        showQr(data)
        active = true
        node('notice').textContent = '請用 0930 掃碼；不會自動連線或移動。'
      }
    }
    catch (error) {
      lastError = error.message
      node('notice').textContent = error.message
      if (error.message.includes('Windows'))
        node('manualPassword').open = true
    }
    finally {
      if (body.password !== undefined)
        body.password = ''
      busy = false
      node('generate').disabled = node('passwordGenerate').disabled = false
      node('end').disabled = !active
    }
  }
  node('generate').addEventListener('click', () => void generate())
  node('passwordForm').addEventListener('submit', (event) => {
    event.preventDefault()
    void generate(node('wifiPassword').value)
  })
  node('end').addEventListener('click', async () => {
    if (busy)
      return
    busy = true
    ++epoch
    clearQr()
    try {
      await request('end', {}, 'POST')
      lastError = ''
      active = false
      node('notice').textContent = '已結束配網，沒有建立控制連線。'
      node('network').textContent = ''
      node('end').disabled = true
    }
    catch (error) { node('notice').textContent = error.message }
    finally { busy = false }
  })
  node('zoom').addEventListener('click', () => {
    if (qrUrl)
      node('qrDialog').showModal()
  })
  node('closeZoom').addEventListener('click', () => node('qrDialog').close())
  setInterval(poll, 1200)
  void poll()
})()
