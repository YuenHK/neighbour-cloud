// Load the real AIRI editor only after staff authentication and tab selection.
const frame = document.getElementById('cloudAiriSettings')
const status = document.getElementById('cloudSettingsStatus')
const retry = document.getElementById('cloudSettingsRetry')
let timer
function load() {
  clearTimeout(timer)
  status.textContent = '正在載入 AIRI 設定，首次開啟可能需稍等…'
  status.hidden = false
  retry.hidden = true
  window.dispatchEvent(new Event('cloud-settings-reset'))
  frame.src = '/cloud/resident?estate=1&settings=1'
  timer = setTimeout(() => {
    status.textContent = 'AIRI 設定仍未完成載入，可重新載入；平台原有設定不會被清除。'
    retry.hidden = false
  }, 45000)
}
retry.addEventListener('click', load)
function read() {
  if (['#avatar', '#settings'].includes(location.hash) && !frame.getAttribute('src'))
    load()
}
window.addEventListener('hashchange', read)
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== frame.contentWindow) return
  if (event.data?.type === 'estate:settings-ready') {
    clearTimeout(timer)
    status.hidden = true
    retry.hidden = true
  }
  if (event.data?.type === 'estate:settings-size' && Number.isFinite(event.data.height))
    frame.style.height = `${Math.max(600, Math.min(20000, event.data.height))}px`
  if (event.data?.type === 'estate:settings-wheel' && Number.isFinite(event.data.deltaY))
    window.scrollBy({ top: Math.max(-2000, Math.min(2000, event.data.deltaY)) })
})
void read()
