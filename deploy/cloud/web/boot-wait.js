import { mountCommunitySystems } from '/cloud/community-systems.js'
import { createCommunityState } from '/cloud/community-state.js'
const diagram = mountCommunitySystems(document.getElementById('bootSystems'), { compact: true })
const systems = createCommunityState(value => diagram.update(value))
systems.boot()
const status = document.getElementById('bootStatus')
const retry = document.getElementById('bootRetry')
let generation = 0, timer, controller, started = 0, closed = false
async function check(current) {
  controller = new AbortController()
  const timeout = setTimeout(() => controller?.abort(), 5000)
  let terminal = false
  try {
    const response = await fetch('/health', { cache: 'no-store', credentials: 'omit', signal: controller.signal })
    const value = await response.json()
    if (closed || current !== generation) return
    systems.boot(value)
    if (response.ok && value.public_ready === true) { location.replace('/'); return }
    terminal = value.rollout_failed === true
    status.textContent = terminal ? '服務暫時未能完成啟動，請稍後重新連接。'
      : value.rollout_waiting === true ? '平台正在安全更新，完成後會自動進入。'
        : '正在啟動服務及讀取已保存的設定，準備好會自動進入。'
  }
  catch { if (!closed && current === generation) {
    systems.repair('minerva', 'retrying')
    status.textContent = '連接需時較長，正在有限期內重新連接…'
  } }
  finally { clearTimeout(timeout) }
  if (closed || current !== generation) return
  if (terminal || Date.now() - started >= 120000) {
    if (!terminal) status.textContent = '啟動需時較長，可以稍後重新連接。'
    retry.hidden = false
    if (!terminal) systems.fail('minerva')
    return
  }
  timer = setTimeout(() => check(current), Math.min(5000, 1000 + (Date.now() - started) / 10))
}
function start() {
  clearTimeout(timer); controller?.abort(); retry.hidden = true; started = Date.now()
  void check(++generation)
}
retry.addEventListener('click', start)
window.addEventListener('pagehide', () => { closed = true; generation++; clearTimeout(timer); controller?.abort(); diagram.destroy() }, { once: true })
start()
