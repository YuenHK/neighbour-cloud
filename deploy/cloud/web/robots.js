const frame = document.getElementById('robotConsoleFrame')
const status = document.getElementById('robotConsoleStatus')
const retry = document.getElementById('retryRobotConsole')
let ready = false, timer
function pause() {
  if (ready) frame.contentWindow?.postMessage({ type: 'neighbour-robot-pause' }, location.origin)
}
function connect() {
  clearTimeout(timer)
  ready = false
  status.textContent = '正在載入控制台，沿用管理工作台登入…'
  retry.hidden = true
  window.dispatchEvent(new Event('cloud-robot-reset'))
  frame.hidden = false
  frame.src = '/cloud/robots'
  timer = setTimeout(() => {
    if (!ready) { status.textContent = '控制台未完成載入，可以重新連接。'; retry.hidden = false }
  }, 20000)
}
function read() {
  if (location.hash !== '#robots') { pause(); return }
  if (!frame.getAttribute('src')) connect()
}
retry.addEventListener('click', connect)
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== frame.contentWindow) return
  if (event.data?.type === 'neighbour-robot-ready') {
    clearTimeout(timer)
    ready = true
    status.textContent = '控制台已載入，請選擇機體。'
    retry.hidden = false
    if (location.hash !== '#robots') pause()
  }
  if (event.data?.type === 'neighbour-robot-error') {
    clearTimeout(timer)
    status.textContent = '管理登入未能核對，請重新進入管理工作台。'
    retry.hidden = false
  }
  if (event.data?.type === 'neighbour-robot-size' && Number.isFinite(event.data.height))
    frame.style.height = Math.max(620, Math.min(1600, event.data.height + 12)) + 'px'
})
window.addEventListener('hashchange', read)
window.addEventListener('pagehide', pause)
document.addEventListener('visibilitychange', () => { if (document.hidden) pause() })
void read()
