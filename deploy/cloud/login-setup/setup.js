const node = id => document.getElementById(id)
let setup
const sdk = new Promise((resolve, reject) => {
  const script = document.createElement('script')
  script.src = 'https://accounts.google.com/gsi/client'
  script.async = true
  script.onload = resolve
  script.onerror = reject
  document.head.append(script)
})
// A rejected SDK load is shown without logging credentials or an unhandled rejection.
void sdk.catch(() => undefined)
async function post(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Setup-Nonce': setup.csrf },
    body: JSON.stringify(body), credentials: 'omit', redirect: 'error', cache: 'no-store',
  })
  const data = await response.json()
  if (!response.ok)
    throw new Error(data.detail || '設定未確認。')
  return data
}
async function credential(response) {
  node('status').textContent = '正在核對 Google 身份同加密保存…'
  try {
    await post('/enrol', { credential: response.credential })
    node('googleButton').replaceChildren()
    node('status').textContent = '已核對身份並加密保存。可以返聊天回覆「登入設定已保存」。'
  }
  catch (error) {
    node('status').textContent = error.message
  }
}
node('configure').addEventListener('submit', async (event) => {
  event.preventDefault()
  node('continue').disabled = true
  try {
    await sdk
    const config = await post('/configure', { client_id: node('clientId').value.trim(), email: node('email').value.trim() })
    google.accounts.id.initialize({ client_id: config.client_id, nonce: config.nonce, callback: credential, auto_select: false, ux_mode: 'popup' })
    google.accounts.id.renderButton(node('googleButton'), { theme: 'outline', size: 'large', text: 'signin_with' })
    node('configure').hidden = true
    node('status').textContent = '請按 Google 登入，選剛才指定嘅帳戶。'
  }
  catch (error) {
    node('continue').disabled = false
    node('status').textContent = error.message || 'Google 登入元件未能載入，請稍後重整。'
  }
})
try {
  const response = await fetch('/setup', { cache: 'no-store', credentials: 'omit', redirect: 'error' })
  if (!response.ok)
    throw new Error('本機設定未能載入。')
  setup = await response.json()
  node('cloudOrigin').textContent = setup.origin
  node('localOrigin').textContent = setup.local_origin
  node('continue').disabled = setup.saved
  node('status').textContent = setup.saved ? '登入設定已保存，沒有覆寫。' : '填好 Client ID 同指定電郵，再繼續。'
}
catch {
  node('status').textContent = '本機設定未能載入，請保留此頁並回報。'
}
