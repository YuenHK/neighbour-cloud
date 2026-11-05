// Device preparation is passive. No getUserMedia, audio playback, network call,
// automatic full screen, saved browser policy, or permission prompt is created.
const permissionLabels = { granted: '已允許', prompt: '首次使用須本人允許', denied: '已拒絕，需由職員在瀏覽器處理' }
const boundedPermission = async (navigator, name) => {
  if (typeof navigator.permissions?.query !== 'function') return '未能讀取，請在居民頁確認'
  let timer
  try {
    const value = await Promise.race([
      navigator.permissions.query({ name }),
      new Promise(resolve => { timer = setTimeout(() => resolve(null), 1500) }),
    ])
    return permissionLabels[value?.state] || '未能讀取，請在居民頁確認'
  }
  catch { return '未能讀取，請在居民頁確認' }
  finally { clearTimeout(timer) }
}

function environment(win) {
  try {
    // The management iframe intentionally denies media. Query the same-origin
    // portal's existing permissions, never interpret that iframe policy as a
    // broken microphone/camera. No cross-origin window is touched.
    if (win.top && win.top.location.origin === win.location.origin) return win.top
  }
  catch { /* Standalone management previews use their own available context. */ }
  return win
}

export async function kioskReadiness(win) {
  const context = environment(win), navigator = context.navigator
  const media = context.isSecureContext === true && typeof navigator.mediaDevices?.getUserMedia === 'function'
  const [microphone, camera] = await Promise.all([
    media ? boundedPermission(navigator, 'microphone') : '此環境不支援',
    media ? boundedPermission(navigator, 'camera') : '此環境不支援',
  ])
  const standalone = context.matchMedia?.('(display-mode: standalone)').matches === true || navigator.standalone === true
  const rows = [
    { label: '安全連線', text: context.isSecureContext === true ? 'HTTPS／安全環境' : '需要 HTTPS 安全環境', ok: context.isSecureContext === true },
    { label: '語音及鏡頭介面', text: media ? '瀏覽器提供介面；仍需實測' : '未提供收音／鏡頭介面', ok: media },
    { label: '咪高峰權限', text: microphone, ok: microphone === permissionLabels.granted },
    { label: '鏡頭權限', text: camera, ok: camera === permissionLabels.granted },
    { label: '語音播放介面', text: context.AudioContext || context.webkitAudioContext ? '有播放介面；須在居民頁實聽' : '未找到音訊介面', ok: !!(context.AudioContext || context.webkitAudioContext) },
    { label: '手勢運算介面', text: media && context.WebAssembly ? '可準備裝置內手勢運算；仍需測光線及距離' : '缺少鏡頭或運算介面', ok: !!(media && context.WebAssembly) },
    { label: '顯示模式', text: standalone ? '已在主畫面／獨立視窗開啟' : '瀏覽器分頁；可由職員加入主畫面', ok: standalone },
  ]
  return { rows, readsOnly: true, hardwareTested: false, residentUrl: '/?workspace=resident' }
}

export function mountKiosk(document, win) {
  const check = document.getElementById('kioskCheck'), full = document.getElementById('kioskFullscreen')
  const list = document.getElementById('kioskChecks'), status = document.getElementById('kioskStatus')
  if (!check || !full || !list || !status) return
  let checking = false
  check.addEventListener('click', async () => {
    if (checking) return
    checking = true
    check.disabled = true
    status.textContent = '正在讀取瀏覽器支援及現有權限…'
    try {
      const value = await kioskReadiness(win)
      const nodes = []
      for (const row of value.rows) {
        const label = document.createElement('dt'), result = document.createElement('dd')
        label.textContent = row.label
        result.textContent = row.text
        result.dataset.state = row.ok ? 'good' : 'action'
        nodes.push(label, result)
      }
      list.replaceChildren(...nodes)
      list.hidden = false
      status.textContent = '裝置環境已檢查；沒有啟動收音、鏡頭或朗讀。請按下方步驟完成現場測試。'
    }
    catch { status.textContent = '瀏覽器未能提供檢查結果；可在居民頁逐項確認，沒有改動系統設定。' }
    finally { checking = false; check.disabled = false }
  })
  full.addEventListener('click', async () => {
    const target = environment(win).document.documentElement
    if (typeof target.requestFullscreen !== 'function') {
      status.textContent = '這個瀏覽器未提供全螢幕按鈕；可由職員使用「加入主畫面」或瀏覽器全螢幕。'
      return
    }
    try { await target.requestFullscreen(); status.textContent = '已進入全螢幕；按 Esc 或裝置的返回操作可離開。' }
    catch { status.textContent = '未能進入全螢幕；原有畫面保留，請由職員使用瀏覽器的顯示選項。' }
  })
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') mountKiosk(document, window)
