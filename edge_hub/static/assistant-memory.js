// Explicit local actions only. No credential persistence, automatic saves or retries.
const memoryStatus = document.querySelector('#memoryStatus')
const memoryItems = document.querySelector('#memoryItems')
let busy = false
let pairing = false
async function memoryRequest(path, method = 'GET', body) {
  const key = document.querySelector('#memoryKey').value
  if (!key) throw Error('請從本機控制台開啟此頁，或重新整理取得本機操作員授權')
  const controller = new AbortController()
  let timer
  try {
    const deadline = new Promise((_resolve, reject) => {
      timer = setTimeout(() => { controller.abort(); reject(Error('請求逾時；寫入結果可能未知，請先重新整理，不要重複提交')) }, 4000)
    })
    return await Promise.race([deadline, (async () => {
      const response = await fetch(path, { method, body: body === undefined ? undefined : JSON.stringify(body),
        headers: { 'X-Operator-Key': key, 'Content-Type': 'application/json' },
        credentials: 'omit', cache: 'no-store', redirect: 'error', signal: controller.signal })
      if (!response.ok) throw Error(`接口拒絕（${response.status}）；請核對權限或重新整理`)
      return response.json()
    })()])
  }
  finally { clearTimeout(timer); controller.abort() }
}
async function reloadMemory() {
  const data = await memoryRequest('/api/v1/assistant/memories')
  if (!Array.isArray(data.items) || data.items.length > 100) throw Error('記憶資料格式不符')
  memoryItems.replaceChildren()
  for (const item of data.items) {
    if (!/^[a-f0-9]{32}$/.test(item.id) || typeof item.text !== 'string' || !Number.isSafeInteger(item.revision)) throw Error('記憶資料格式不符')
    const li = document.createElement('li')
    const text = document.createElement('span'); text.textContent = item.text
    const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = '修改'
    edit.addEventListener('click', () => memoryAction(async () => {
      const value = window.prompt('修改這項本機記憶（最多 1000 字）', item.text)
      if (value === null) return
      if (!value.trim() || value.trim().length > 1000) throw Error('內容長度不符')
      await memoryRequest(`/api/v1/assistant/memories/${item.id}`, 'PUT', { text: value.trim(), revision: item.revision })
      await reloadMemory()
    }))
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '刪除'
    remove.addEventListener('click', () => memoryAction(async () => {
      if (!window.confirm('刪除這項本機記憶？既有聊天及備份不會一併刪除。')) return
      await memoryRequest(`/api/v1/assistant/memories/${item.id}?revision=${item.revision}`, 'DELETE')
      await reloadMemory()
    }))
    li.append(text, edit, remove); memoryItems.append(li)
  }
  memoryStatus.textContent = `已載入 ${data.items.length} 項本機記憶；不自動儲存聊天。`
}
async function memoryAction(action) {
  if (busy) return
  busy = true
  try { await action() }
  catch (error) { memoryStatus.textContent = error.message }
  finally { busy = false }
}
document.querySelector('#refreshMemory').addEventListener('click', () => memoryAction(reloadMemory))
document.querySelector('#saveMemory').addEventListener('click', () => memoryAction(async () => {
  const command = document.querySelector('#rememberCommand').value.trim()
  if (!command.startsWith('記住') || command.length <= 2) throw Error('請明確輸入「記住：內容」')
  await memoryRequest('/api/v1/assistant/remember', 'POST', { command })
  document.querySelector('#rememberCommand').value = ''
  await reloadMemory()
}))
document.querySelector('#revokeMemory').addEventListener('click', () => memoryAction(async () => {
  await memoryRequest('/api/v1/assistant/memory-capabilities/revoke', 'POST')
  memoryStatus.textContent = '全部記憶授權已撤銷；已儲存記憶未刪除。'
}))
document.querySelector('#pairMemory').addEventListener('click', () => {
  if (pairing || !document.querySelector('#memoryKey').value) {
    memoryStatus.textContent = '請先填入操作員密碼，或等待配對完成。'; return
  }
  const origin = Reflect.get(globalThis, '__NEIGHBOUR_REMOTE__') === true ? location.origin : 'http://127.0.0.1:4173'
  const popup = window.open(origin, '_blank')
  if (!popup) { memoryStatus.textContent = '彈出視窗被封鎖，尚未授權。'; return }
  pairing = true
  let issued = false
  const cleanup = () => { window.removeEventListener('message', ready); clearTimeout(timer); pairing = false }
  const ready = async event => {
    if (event.origin !== origin || event.source !== popup) return
    if (event.data?.type === 'zhiwei-memory-accepted' && issued) {
      cleanup()
      memoryStatus.textContent = 'AIRI 已確認記憶配對；請在新 AIRI 頁面以「記住：內容」測試。'
      return
    }
    if (event.data?.type !== 'zhiwei-memory-ready' || issued) return
    issued = true
    try {
      const data = await memoryRequest('/api/v1/assistant/memory-capabilities', 'POST')
      popup.postMessage({ type: 'zhiwei-memory-capability', token: data.token, expiresIn: data.expires_in_seconds }, origin)
      memoryStatus.textContent = '已發出只可用記憶的授權，正在等待 AIRI 確認；未確認前不當作配對成功。'
    }
    catch (error) { cleanup(); memoryStatus.textContent = error.message }
  }
  window.addEventListener('message', ready)
  const timer = setTimeout(() => { cleanup(); memoryStatus.textContent = issued
    ? 'AIRI 未確認配對；授權可能已發出，請核對新版畫面，勿當作成功。'
    : 'AIRI 配對逾時，未發出授權。可能仍載入舊離線快取；請正常重新整理 AIRI，按頁面更新提示後再試。' }, 60000)
})
