// UI phases are driven by the actual service frame, never by a fake percent.
export function createLaunchScreen(document, { onRetry, onContinue }) {
  const root = document.getElementById('launchScreen')
  const text = document.getElementById('launchStatus')
  const retry = document.getElementById('launchRetry')
  const skip = document.getElementById('launchContinue')
  const steps = [...document.querySelectorAll('[data-launch-step]')]
  let timer, active = false, area = 'resident', textAvailable = false
  function phase(value) {
    if (!active) return
    const index = ['connect', 'interface', 'avatar'].indexOf(value)
    if (index < 0) return
    for (const [position, step] of steps.entries()) {
      step.dataset.state = position < index ? 'done' : position === index ? 'current' : 'waiting'
      step.hidden = area === 'staff' && position === 2
    }
    text.textContent = value === 'connect' ? '正在連接鄰伴…' : value === 'interface' ? '正在載入服務畫面…' : '正在準備數字人，等我一陣呀。'
  }
  function start(nextArea, value = 'connect') {
    clearTimeout(timer)
    area = nextArea
    active = true
    textAvailable = false
    root.hidden = false
    root.dataset.state = 'loading'
    root.setAttribute('aria-busy', 'true')
    document.getElementById('launchTitle').textContent = area === 'staff' ? '為你準備管理工作台' : '鄰伴，就喺你身邊'
    retry.hidden = true
    skip.hidden = true
    phase(value)
    timer = setTimeout(() => {
      if (!active) return
      text.textContent = '首次載入可能需要耐少少，資源仍在準備中。'
      retry.hidden = false
      skip.hidden = !textAvailable
    }, 30000)
  }
  function hide() { clearTimeout(timer); active = false; root.hidden = true; root.setAttribute('aria-busy', 'false') }
  function fail(message) {
    clearTimeout(timer)
    active = true
    root.hidden = false
    root.dataset.state = 'failed'
    root.setAttribute('aria-busy', 'false')
    text.textContent = message
    retry.hidden = false
    skip.hidden = !textAvailable
  }
  retry.addEventListener('click', onRetry)
  skip.addEventListener('click', () => { if (active && textAvailable) onContinue() })
  return { start, phase, hide, fail, textReady() { textAvailable = true; if (!retry.hidden) skip.hidden = false } }
}
