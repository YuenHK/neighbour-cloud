// Palm mapping adapted from the user's 揮手鑑古/QingmingPortal/hand-math.mjs.
// Resident-only navigation; never controls the robot, staff pages or browser permissions.
const clamp = value => Math.max(0, Math.min(1, value))
export function residentPalm(points) {
  if (!Array.isArray(points) || points.length !== 21 || points.some(p => !Number.isFinite(p?.x) || !Number.isFinite(p?.y)))
    return undefined
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y)
  const palm = [0, 5, 9, 13, 17].reduce((p, i) => ({ x: p.x + points[i].x / 5, y: p.y + points[i].y / 5 }), { x: 0, y: 0 })
  const fingers = [[8, 6], [12, 10], [16, 14], [20, 18]].filter(([tip, pip]) => distance(points[tip], points[0]) > distance(points[pip], points[0]) * 1.12).length
  const span = distance(points[5], points[17])
  if (span < 0.025)
    return undefined
  return { x: clamp((1 - palm.x - 0.12) / 0.76), y: clamp((palm.y - 0.12) / 0.76), open: fingers >= 2, pinch: distance(points[4], points[8]) / span < 0.35 }
}

export class HandSelection {
  constructor() { this.reset() }
  reset() {
    this.target = undefined
    this.since = 0
    this.pinched = 0
    this.locked = false
  }

  update(target, pinch, now) {
    if (!target || !Number.isFinite(now)) {
      this.reset()
      return false
    }
    if (this.target !== target) {
      this.reset()
      this.target = target
      this.since = now
    }
    if (!pinch) {
      this.pinched = 0
      this.locked = false
      return false
    }
    if (this.locked || now - this.since < 900)
      return false
    if (!this.pinched) {
      this.pinched = now
      return false
    }
    if (now - this.pinched < 400)
      return false
    this.locked = true
    return true
  }
}

export class ResidentHandPointer {
  constructor() {
    this.selection = new HandSelection()
    this.cursor = document.createElement('div')
    this.cursor.className = 'resident-hand-cursor'
    this.cursor.setAttribute('aria-hidden', 'true')
    this.cursor.hidden = true
    document.body.append(this.cursor)
  }

  update(points) {
    const palm = residentPalm(points)
    if (!palm || (!palm.open && !palm.pinch)) {
      this.clear()
      return
    }
    const next = { x: palm.x * innerWidth, y: palm.y * innerHeight }
    this.position = this.position ? { x: this.position.x + (next.x - this.position.x) * 0.5, y: this.position.y + (next.y - this.position.y) * 0.5 } : next
    const { x, y } = this.position
    this.cursor.hidden = false
    this.cursor.style.transform = `translate(${x}px,${y}px)`
    const target = document.elementFromPoint(x, y)?.closest('.resident-assistant-panel [data-hand-action]')
    const eligible = target && !target.disabled && target.getClientRects().length ? target : undefined
    if (this.hovered !== eligible) {
      this.hovered?.removeAttribute('data-hand-hover')
      this.hovered = eligible
      eligible?.setAttribute('data-hand-hover', 'true')
    }
    if (this.selection.update(eligible, palm.pinch, performance.now()))
      eligible.click()
    if (!eligible && palm.open && !palm.pinch) {
      const transcript = document.querySelector('.resident-transcript')
      if (transcript && (palm.y < 0.15 || palm.y > 0.85))
        transcript.scrollBy({ top: palm.y < 0.15 ? -55 : 55, behavior: 'auto' })
    }
    clearTimeout(this.expiry)
    this.expiry = setTimeout(() => this.clear(), 900)
  }

  clear() {
    clearTimeout(this.expiry)
    this.cursor.hidden = true
    this.hovered?.removeAttribute('data-hand-hover')
    this.hovered = undefined
    this.position = undefined
    this.selection.reset()
  }

  dispose() {
    this.clear()
    this.cursor.remove()
  }
}
