import { cloudFetch } from '/cloud/admin-request.js'
const link = document.getElementById('remoteRobotConsole')
const status = document.getElementById('robotConsoleStatus')
let busy = false
let loaded = false
async function read() {
  if (location.hash !== '#robots' || busy || loaded) return
  busy = true
  try {
    const response = await cloudFetch('/api/v1/service-desk/presentation', { signal: AbortSignal.timeout(12000) })
    if (!response.ok) throw new Error('unavailable')
    const data = await response.json()
    if (typeof data.robot_remote_url === 'string' && /^https:\/\/[a-z0-9-]+\.ngrok-free\.(app|dev)$/.test(data.robot_remote_url)) {
      link.href = data.robot_remote_url + '/robots'
      link.hidden = false
      status.textContent = '街外入口已設定；是否在線以控制台實際回應為準。首次開啟需用已核准的 Google 帳戶登入。'
    }
    else status.textContent = '街外入口尚未設定。現場控制台可獨立使用；居民服務與管理資料不受影響。'
    loaded = true
  }
  catch { status.textContent = '暫時未能核對入口。請稍後重新進入此分頁。' }
  finally { busy = false }
}
window.addEventListener('hashchange', read)
void read()
