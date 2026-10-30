const status = document.getElementById('status')
async function signIn(response) {
  status.textContent = '正在核對登入…'
  try {
    const result = await fetch('/api/v1/resident/session', {
      headers: { Authorization: `Bearer ${response.credential}` },
      cache: 'no-store', credentials: 'omit', redirect: 'error', mode: 'same-origin',
    })
    const data = await result.json()
    if (!result.ok || data.authenticated !== true || !['staff', 'resident'].includes(data.role) || data.storage_acceptance !== true)
      throw new Error('identity_not_accepted')
    document.getElementById('googleButton').replaceChildren()
    status.textContent = 'Google 登入已核對成功。平台仍在準備，未開放居民對話或正式資料操作。'
  }
  catch {
    status.textContent = '暫時未能確認登入，請使用已核准嘅 Google 帳戶再試；沒有轉交其他服務。'
  }
}
try {
  const response = await fetch('/login-config', { cache: 'no-store', credentials: 'omit', redirect: 'error' })
  if (!response.ok)
    throw new Error('login_unavailable')
  const config = await response.json()
  await new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.onload = resolve
    script.onerror = reject
    document.head.append(script)
  })
  google.accounts.id.initialize({ client_id: config.client_id, callback: signIn, auto_select: false, ux_mode: 'popup' })
  google.accounts.id.renderButton(document.getElementById('googleButton'), { theme: 'outline', size: 'large', text: 'signin_with' })
  status.textContent = '請用已核准嘅 Google 帳戶登入。'
}
catch {
  status.textContent = 'Google 登入暫時未能載入，請稍後重整。'
}
