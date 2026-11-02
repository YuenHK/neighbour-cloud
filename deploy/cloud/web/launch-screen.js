// Progress follows real service milestones. Animation never invents a percentage.
export function createLaunchScreen(document, { onRetry, onContinue }) {
  const node = id => document.getElementById(id)
  const root = node('launchScreen')
  const text = node('launchStatus')
  const retry = node('launchRetry')
  const skip = node('launchContinue')
  const steps = [...document.querySelectorAll('[data-launch-step]')]
  const phases = ['connect', 'interface', 'avatar']
  const titles = ['連接服務', '載入畫面', '準備角色']
  const descriptions = ['同鄰伴服務台接通，準備開始。', '正在載入對話介面同必要資料。', '準備數字人、表情同對話畫面。']
  let timer, ticker, active = false, area = 'resident', textAvailable = false, index = 0, startedAt = 0
  function stopTimers() { clearTimeout(timer); clearInterval(ticker) }
  function elapsed() {
    const seconds = Math.max(0, Math.floor((performance.now() - startedAt) / 1000))
    node('launchElapsed').textContent = seconds < 60 ? `已等候 ${seconds} 秒` : `已等候 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
  }
  function phase(value) {
    if (!active) return
    const next = phases.indexOf(value)
    if (next < 0 || (area === 'staff' && next === 2)) return
    index = Math.max(index, next)
    const total = area === 'staff' ? 2 : 3
    root.dataset.phase = phases[index]
    node('launchStep').textContent = `第 ${index + 1} / ${total} 步`
    node('launchComplete').textContent = `已完成 ${index} / ${total} 個階段`
    const progress = node('launchProgress')
    progress.setAttribute('aria-valuemax', String(total))
    progress.setAttribute('aria-valuenow', String(index))
    progress.setAttribute('aria-valuetext', `第 ${index + 1} 步，共 ${total} 步：${titles[index]}`)
    for (const [position, step] of steps.entries()) {
      const state = position < index ? 'done' : position === index ? 'current' : 'waiting'
      step.dataset.state = state
      step.hidden = position >= total
      step.querySelector('.launch-step-number').textContent = state === 'done' ? '✓' : String(position + 1).padStart(2, '0')
      step.querySelector('.launch-step-state').textContent = state === 'done' ? '已完成' : state === 'current' ? '進行中' : '稍後開始'
      if (state === 'current') step.setAttribute('aria-current', 'step')
      else step.removeAttribute('aria-current')
    }
    text.textContent = titles[index]
    node('launchDetail').textContent = area === 'staff' && index === 1 ? '正在為你準備管理工作台。' : descriptions[index]
  }
  function start(nextArea, value = 'connect') {
    const continuing = active && area === nextArea && value !== 'connect'
    stopTimers()
    area = nextArea
    active = true
    if (!continuing) { index = 0; startedAt = performance.now() }
    textAvailable = false
    root.hidden = false
    root.dataset.state = 'loading'
    root.dataset.area = area
    root.setAttribute('aria-busy', 'true')
    node('launchTitle').textContent = area === 'staff' ? '一齊照顧我哋嘅社區' : '今日，一齊開心傾吓！'
    node('launchNote').textContent = '畫面準備好，就會自動帶你入去。'
    retry.hidden = true
    skip.hidden = true
    phase(value)
    elapsed()
    ticker = setInterval(elapsed, 1000)
    timer = setTimeout(() => {
      if (!active) return
      root.dataset.state = 'slow'
      node('launchNote').textContent = '首次載入可能耐少少；你可以繼續等候，或重新連接。'
      retry.hidden = false
      skip.hidden = !textAvailable
    }, Math.max(0, 30000 - (performance.now() - startedAt)))
  }
  function hide() { stopTimers(); active = false; root.hidden = true; root.setAttribute('aria-busy', 'false') }
  function fail(message) {
    stopTimers()
    active = true
    root.hidden = false
    root.dataset.state = 'failed'
    root.setAttribute('aria-busy', 'false')
    text.textContent = '連接遇到阻礙'
    node('launchDetail').textContent = message
    node('launchNote').textContent = '原有資料會保留，可以重新連接。'
    node('launchProgress').setAttribute('aria-valuetext', `停留在${titles[index]}；連接未完成`)
    steps[index].querySelector('.launch-step-state').textContent = '未能完成'
    retry.hidden = false
    skip.hidden = !textAvailable
  }
  retry.addEventListener('click', onRetry)
  skip.addEventListener('click', () => { if (active && textAvailable) onContinue() })
  function checks(value) {
    if (!active || area !== 'resident') return
    textAvailable = value.textReady === true
    const labels = { interface: '對話介面', runtime: '對話及曉曼設定', avatar: '角色及背景', input: '語音收音' }
    const pending = Object.entries(labels).filter(([key]) => value.checks?.[key] !== 'ready')
    phase('avatar')
    node('launchDetail').textContent = pending.length ? `仍在核對：${pending.map(([key, label]) => `${label}${['action', 'failed'].includes(value.checks?.[key]) ? '（需要處理）' : ''}`).join('、')}。` : '必要畫面及輸入已準備好。'
    if (pending.some(([key]) => ['action', 'failed'].includes(value.checks?.[key]))) {
      retry.hidden = false
      skip.hidden = !textAvailable
      node('launchNote').textContent = '若瀏覽器未允許收音，可先用文字進入，再按咪高峰啟用。此檢查不會試用 API 或扣除 AI 額度。'
    }
  }
  return { start, phase, hide, fail, checks, staffSettings() {
    if (!active || area !== 'staff') return
    phase('interface')
    node('launchDetail').textContent = '正在預備 AIRI 原版設定、模型匯入器及各設定入口；完成後才進入管理工作台。'
  }, textReady() { textAvailable = true; if (!retry.hidden) skip.hidden = false } }
}
