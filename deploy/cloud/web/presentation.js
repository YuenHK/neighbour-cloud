// Warm the real AIRI editor after staff authentication, before entry is revealed.
const frame = document.getElementById('cloudAiriSettings')
const status = document.getElementById('cloudSettingsStatus')
const retry = document.getElementById('cloudSettingsRetry')
const boot = document.getElementById('settingsBoot')
let timer
let pending, resolveReady, rejectReady
function load() {
  clearTimeout(timer)
  status.textContent = '正在載入 AIRI 設定，首次開啟可能需稍等…'
  status.hidden = false
  retry.hidden = true
  frame.inert = true
  frame.parentElement.classList.add('is-loading')
  boot.hidden = false
  window.dispatchEvent(new Event('cloud-settings-reset'))
  frame.src = '/cloud/resident?estate=1&settings=1'
  timer = setTimeout(() => {
    status.textContent = 'AIRI 設定仍未完成載入，可重新載入；平台原有設定不會被清除。'
    retry.hidden = false
    rejectReady?.(new Error('airi_settings_startup_timeout'))
  }, 45000)
}
export function prepareSettings() {
  if (!pending) {
    pending = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject })
    load()
  }
  return pending
}
retry.addEventListener('click', () => { pending = undefined; void prepareSettings().catch(() => {}) })
function read() {
  if (['#avatar', '#settings'].includes(location.hash) && !frame.getAttribute('src'))
    void prepareSettings().catch(() => {})
}
window.addEventListener('hashchange', read)
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== frame.contentWindow) return
  if (event.data?.type === 'estate:settings-ready') {
    clearTimeout(timer)
    status.hidden = true
    retry.hidden = true
    frame.inert = false
    frame.parentElement.classList.remove('is-loading')
    boot.hidden = true
    resolveReady?.()
  }
  if (event.data?.type === 'estate:settings-size' && Number.isFinite(event.data.height))
    frame.style.height = `${Math.max(600, Math.min(20000, event.data.height))}px`
  if (event.data?.type === 'estate:settings-wheel' && Number.isFinite(event.data.deltaY))
    window.scrollBy({ top: Math.max(-2000, Math.min(2000, event.data.deltaY)) })
})
void read()
