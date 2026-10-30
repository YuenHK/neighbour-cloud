(() => {
  async function open(eventId) {
    const dialog = document.createElement('dialog')
    dialog.className = 'event-photo-dialog'
    const title = document.createElement('h2')
    title.textContent = '相片私隱檢查'
    const notice = document.createElement('p')
    notice.setAttribute('role', 'status')
    const canvas = document.createElement('canvas')
    canvas.width = 640; canvas.height = 360
    canvas.style.cssText = 'width:100%;height:auto;touch-action:none;cursor:crosshair'
    canvas.setAttribute('aria-label', '拖曳框選要遮蓋的部分；也可使用遮蓋全張相片按鈕')
    const redraw = document.createElement('button')
    redraw.textContent = '更新遮蓋預覽'
    const coverAll = document.createElement('button')
    coverAll.textContent = '遮蓋全張相片'
    const label = document.createElement('label')
    const confirm = document.createElement('input')
    confirm.type = 'checkbox'
    label.append(confirm, ' 我已檢查整張預覽，人臉、車牌、門牌及其他私人資料已遮蓋；同意只傳這張預覽到免費 AI 複核。')
    const send = document.createElement('button')
    send.textContent = '傳送已檢查預覽'
    send.disabled = true
    const close = document.createElement('button')
    close.textContent = '取消／關閉'
    const boxes = []
    let prepared = null, start = null, busy = false, alive = true, picture = null
    const context = canvas.getContext('2d')
    function paint() {
      if (!picture) return
      context.drawImage(picture, 0, 0)
      context.fillStyle = '#000'
      for (const [x,y,w,h] of boxes) context.fillRect(x,y,w,h)
    }
    function invalidate() { prepared = null; confirm.checked = false; send.disabled = true }
    function point(event) {
      const r = canvas.getBoundingClientRect()
      return [Math.max(0, Math.min(639, Math.floor((event.clientX-r.left)*640/r.width))),
        Math.max(0, Math.min(359, Math.floor((event.clientY-r.top)*360/r.height)))]
    }
    canvas.addEventListener('pointerdown', event => {
      if (busy || !picture || boxes.length >= 64) return
      invalidate()
      start = point(event); canvas.setPointerCapture(event.pointerId)
    })
    canvas.addEventListener('pointerup', event => {
      if (!start) return
      const end = point(event), x = Math.min(start[0],end[0]), y = Math.min(start[1],end[1])
      const w = Math.abs(start[0]-end[0])+1, h = Math.abs(start[1]-end[1])+1
      start = null
      boxes.push([x,y,w,h]); invalidate(); paint()
      notice.textContent = '已補遮，請按「更新遮蓋預覽」，再檢查最終畫面。'
    })
    canvas.addEventListener('pointercancel', () => { start = null })
    coverAll.onclick = () => { if (!busy) { boxes.splice(0,boxes.length,[0,0,640,360]); invalidate(); paint() } }
    async function request(suffix, body) {
      const response = await fetch(`/api/v1/patrol/events/${encodeURIComponent(eventId)}/${suffix}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Operator-Key': document.querySelector('#operatorKey').value },
        body: JSON.stringify(body), cache: 'no-store', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(20000),
      })
      if (!response.ok) throw new Error('request_failed')
      return response.json()
    }
    async function preview() {
      if (busy) return
      busy = true; invalidate(); redraw.disabled = true
      notice.textContent = '正在本機準備遮蓋預覽，未上傳相片…'
      try {
        const result = await request('privacy-preview', { boxes })
        const img = new Image()
        img.src = 'data:image/jpeg;base64,' + result.jpeg
        await img.decode()
        if (!alive) return
        picture = img; paint(); prepared = result
        notice.textContent = result.notice
      }
      catch { if (alive) notice.textContent = '預覽未完成，沒有上傳。請關閉後在本機核實相片。' }
      finally { busy = false; redraw.disabled = false }
    }
    confirm.onchange = () => { send.disabled = busy || !prepared || !confirm.checked }
    redraw.onclick = preview
    send.onclick = async () => {
      if (busy || !prepared || !confirm.checked) return
      busy = true; send.disabled = true; redraw.disabled = true
      try {
        const result = await request('privacy-approve', { token: prepared.token, preview_sha256: prepared.preview_sha256, confirmed: true })
        if (!alive) return
        notice.textContent = result.status === 'reviewed'
          ? `免費 AI 已複核：${result.findings.length ? '仍見原先候選' : '未確認原先候選'}。最終請職員核實，未自動派工。`
          : '今次未完成雲端複核；可能額度不足或服務忙碌。沒有切換付費服務，請職員本機核實。'
      }
      catch { if (alive) notice.textContent = '未能確認複核結果，不會自動重送；請職員本機核實。' }
      finally { busy = false; invalidate(); redraw.disabled = false }
    }
    close.onclick = () => dialog.close()
    dialog.addEventListener('close', () => { alive = false; picture = null; dialog.remove() }, { once: true })
    dialog.append(title, notice, canvas, coverAll, redraw, label, send, close)
    document.body.append(dialog); dialog.showModal(); await preview()
  }
  globalThis.ZhiweiPhotoPrivacy = { open }
})()
