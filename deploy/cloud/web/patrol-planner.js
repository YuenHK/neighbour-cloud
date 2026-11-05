import { cloudFetch } from '/cloud/admin-request.js'

const panel = document.getElementById('patrolPlanning')
const canvas = document.getElementById('patrolMapCanvas')
const status = document.getElementById('patrolPlanStatus')
const name = document.getElementById('patrolMapName')
const cell = document.getElementById('patrolCellSize')
const paint = document.getElementById('patrolPaint')
const profile = document.getElementById('patrolProfile')
const notice = document.getElementById('patrolProfileNotice')
const api = '/api/v1/service-desk/patrol-planning'
let revision = 0, map = { name: '巡查區域', width: 20, height: 16, cell_cm: 50, clearance_cm: 35, floor: [], blocked: [] }
let start, goal, route = [], pending = false, loaded = false, generation = 0
const key = value => `${value.x},${value.y}`

function draw() {
  const ctx = canvas.getContext('2d')
  const width = canvas.width / map.width, height = canvas.height / map.height
  const floor = new Set(map.floor.map(key)), walls = new Set(map.blocked.map(key))
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  for (let y = 0; y < map.height; y++) for (let x = 0; x < map.width; x++) {
    const point = { x, y }
    ctx.fillStyle = walls.has(key(point)) ? '#43534f' : floor.has(key(point)) ? '#d8ece2' : '#e8e9ec'
    if (start && key(start) === key(point)) ctx.fillStyle = '#4c88bd'
    if (goal && key(goal) === key(point)) ctx.fillStyle = '#d68c4e'
    ctx.fillRect(x * width + 1, y * height + 1, width - 2, height - 2)
  }
  if (route.length) {
    ctx.beginPath(); ctx.strokeStyle = '#c29915'; ctx.lineWidth = 5
    for (const [index, point] of route.entries()) {
      const x = (point.x + .5) * width, y = (point.y + .5) * height
      if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y)
    }
    ctx.stroke()
  }
}
function draft() { return { ...map, name: name.value.trim(), cell_cm: Number(cell.value) } }
function changed() { generation++; route = []; draw(); status.textContent = '地圖草稿已修改；路線需要重新模擬。' }
async function request(path, options) {
  const reply = await cloudFetch(path, { ...options, signal: AbortSignal.timeout(15000) })
  const value = await reply.json()
  if (!reply.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '地圖資料未能核對；草稿保留。')
  return value
}
async function run(action) {
  if (pending) return
  pending = true
  try { await action() }
  catch (error) { status.textContent = error.message || '暫未完成；地圖草稿保留，沒有發出硬件指令。' }
  finally { pending = false }
}
async function load() {
  const before = generation
  const value = await request(api)
  if (generation !== before) { status.textContent = '載入期間草稿已修改，沒有覆蓋；請再次按讀取。'; return }
  revision = value.revision
  if (value.map) {
    map = value.map; name.value = map.name; cell.value = String(map.cell_cm)
    start = goal = undefined; route = []; generation++; draw()
  }
  loaded = true
  status.textContent = value.map ? `已讀取第 ${revision} 版地圖。` : '尚未儲存地圖；先畫已勘察地面。'
}
panel?.addEventListener('toggle', () => { if (panel.open && !loaded) void run(load) })
canvas?.addEventListener('click', event => {
  const rect = canvas.getBoundingClientRect()
  const point = { x: Math.floor((event.clientX-rect.left) / rect.width * map.width), y: Math.floor((event.clientY-rect.top) / rect.height * map.height) }
  if (point.x < 0 || point.y < 0 || point.x >= map.width || point.y >= map.height) return
  if (paint.value === 'start') start = point
  else if (paint.value === 'goal') goal = point
  else {
    map.floor = map.floor.filter(item => key(item) !== key(point))
    map.blocked = map.blocked.filter(item => key(item) !== key(point))
    if (paint.value === 'floor') map.floor.push(point)
    if (paint.value === 'blocked') map.blocked.push(point)
  }
  changed()
})
name?.addEventListener('input', changed)
cell?.addEventListener('change', changed)
profile?.addEventListener('change', () => {
  notice.textContent = profile.value === 's1' ? 'S1 官方只支援 RoboMaster Lab；此處只模擬，未提供 SDK 遙控。' : profile.value === 'ep' ? 'EP 地圖不代表即時定位；完成現場驗收前不會執行路線。' : '只模擬路線，沒有硬件指令。'
  changed()
})
document.getElementById('patrolPlan')?.addEventListener('click', () => void run(async () => {
  if (!start || !goal) throw new Error('先用畫筆設定起點同終點。')
  const before = generation
  const value = await request(api + '/simulate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ map: draft(), start, goal, profile: profile.value }) })
  if (before !== generation) { status.textContent = '草稿已改，舊模擬結果未套用。'; return }
  route = value.path; draw(); status.textContent = `模擬路線 ${value.distance_m} 米；沒有連線或移動機械人。`
}))
document.getElementById('patrolMapSave')?.addEventListener('click', () => void run(async () => {
  if (!loaded) throw new Error('請先讀取平台地圖版本，草稿會保留。')
  const before = generation
  const value = await request(api, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, map: draft() }) })
  revision = value.revision
  status.textContent = before === generation ? `地圖已儲存為第 ${revision} 版；沒有啟用自主行車。` : `較早地圖已儲存為第 ${revision} 版；等待期間的新修改仍是未儲存草稿。`
}))
document.getElementById('patrolMapLoad')?.addEventListener('click', () => {
  if (generation && !globalThis.confirm('讀取會取代此頁地圖草稿，是否繼續？')) return
  void run(load)
})
document.getElementById('patrolMapExport')?.addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({ format: 'neighbour-survey-map-v1', map: draft() }, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = 'neighbour-survey-map.json'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
})
document.getElementById('patrolMapImport')?.addEventListener('change', event => void run(async () => {
  const file = event.target.files?.[0]
  if (!file || file.size > 200000) throw new Error('請選擇 200 KB 以內的地圖 JSON。')
  const before = generation
  const value = JSON.parse(await file.text())
  if (generation !== before) throw new Error('讀檔期間草稿已修改，沒有覆蓋；請核對後重新匯入。')
  if (value.format !== 'neighbour-survey-map-v1' || !value.map) throw new Error('這不是鄰伴地圖。')
  const candidate = value.map
  if (!Number.isInteger(candidate.width) || !Number.isInteger(candidate.height) || candidate.width < 4 || candidate.width > 64 || candidate.height < 4 || candidate.height > 64 || ![50, 100].includes(candidate.cell_cm) || ![candidate.floor, candidate.blocked].every(items => Array.isArray(items) && items.length <= 4096 && items.every(point => Number.isInteger(point.x) && Number.isInteger(point.y) && point.x >= 0 && point.y >= 0 && point.x < candidate.width && point.y < candidate.height)) || typeof candidate.name !== 'string' || candidate.name.length > 60 || !Number.isInteger(candidate.clearance_cm) || candidate.clearance_cm < 20 || candidate.clearance_cm > 100) throw new Error('地圖格式或範圍不正確；原草稿保留。')
  map = candidate; name.value = map.name; cell.value = String(map.cell_cm); start = goal = undefined; changed()
  status.textContent = '地圖已匯入此頁草稿；按儲存後才同步平台。'
}))
if (canvas) draw()
