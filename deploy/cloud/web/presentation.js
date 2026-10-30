let revision = 0
let loaded = false
const field = id => document.getElementById(id)
async function read() {
  if (loaded || location.hash !== '#avatar') return
  try {
    const response = await globalThis.__NEIGHBOUR_CLOUD_TRANSPORT__.fetch('/api/v1/service-desk/presentation', {})
    if (!response.ok) throw new Error('unavailable')
    const data = await response.json()
    revision = data.revision
    for (const [id, key] of [['presentationName', 'name'], ['presentationGreeting', 'greeting'],
      ['presentationPersona', 'persona'], ['presentationBackground', 'background']]) field(id).value = data[key]
    loaded = true
    field('presentationStatus').textContent = '儲存後，下次開啟居民服務台就會套用畫面設定。'
  }
  catch { field('presentationStatus').textContent = '暫時未能載入設定，請稍後再開啟此分頁。' }
}
field('cloudPresentationForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  if (!revision) return
  const button = event.currentTarget.querySelector('button')
  button.disabled = true
  field('presentationStatus').textContent = '正在儲存…'
  try {
    const response = await globalThis.__NEIGHBOUR_CLOUD_TRANSPORT__.fetch('/api/v1/service-desk/presentation', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: revision,
        name: field('presentationName').value, greeting: field('presentationGreeting').value,
        persona: field('presentationPersona').value, background: field('presentationBackground').value }) })
    if (!response.ok) throw new Error('unknown')
    const data = await response.json()
    revision = data.revision
    field('presentationStatus').textContent = '已儲存；下次開啟居民服務台會套用畫面設定。'
  }
  catch {
    loaded = false
    field('presentationStatus').textContent = '未能確認儲存結果；內容保留，請重新查看設定後再試。'
  }
  finally { button.disabled = false }
})
window.addEventListener('hashchange', read)
void read()
