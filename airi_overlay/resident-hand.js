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
    this.lastAt = undefined
    this.progress = 0
    this.locked = false
  }

  update(target, _pinch, now) {
    if (!target || !Number.isFinite(now)) {
      this.reset()
      return false
    }
    if (this.target !== target || (this.lastAt !== undefined && (now < this.lastAt || now - this.lastAt > 500))) {
      this.reset()
      this.target = target
      this.since = now
    }
    this.lastAt = now
    this.progress = clamp((now - this.since) / 2000)
    // One deliberate dwell per target. Leaving/lost tracking rearms it;
    // pinching is no longer necessary and cannot trigger an early click.
    if (this.locked || this.progress < 1)
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
    if (this.disposed)
      return
    const palm = residentPalm(points)
    if (!palm?.open) {
      this.clear()
      return
    }
    this.sample = { x: palm.x * innerWidth, y: palm.y * innerHeight, at: performance.now(), open: palm.open }
    if (!this.animation)
      this.animation = requestAnimationFrame(now => this.draw(now))
  }

  draw(now) {
    this.animation = undefined
    if (this.disposed || !this.sample || document.hidden || now - this.sample.at > 350) {
      this.clear()
      return
    }
    const dt = Math.min(100, Math.max(0, this.lastFrame === undefined ? 16 : now - this.lastFrame))
    this.lastFrame = now
    // Render independently of inference. Time-based smoothing avoids both
    // 5fps jumps and the extra latency of per-result fixed blending.
    const alpha = 1 - Math.exp(-dt / 35)
    this.position = this.position ? { x: this.position.x + (this.sample.x - this.position.x) * alpha, y: this.position.y + (this.sample.y - this.position.y) * alpha } : { x: this.sample.x, y: this.sample.y }
    const { x, y } = this.position
    this.cursor.hidden = false
    this.cursor.style.transform = `translate(${x}px,${y}px)`
    const modal = document.querySelector('.resident-photo-dialog[open]')
    const target = document.elementFromPoint(x, y)?.closest('.resident-assistant-panel [data-hand-action], .resident-photo-dialog [data-hand-action]')
    const available = item => item && item.isConnected && !item.disabled && item.getAttribute('aria-disabled') !== 'true'
      && !item.closest('[inert]') && item.getClientRects().length && (!modal || modal.contains(item))
    let eligible = available(target) ? target : undefined
    // A narrow edge tolerance absorbs hand jitter without jumping between
    // adjacent controls or selecting behind an open modal.
    if (!eligible && available(this.hovered)) {
      const rect = this.hovered.getBoundingClientRect()
      if (x >= rect.left - 8 && x <= rect.right + 8 && y >= rect.top - 8 && y <= rect.bottom + 8)
        eligible = this.hovered
    }
    if (this.hovered !== eligible) {
      this.hovered?.removeAttribute('data-hand-hover')
      this.hovered = eligible
      eligible?.setAttribute('data-hand-hover', 'true')
    }
    const selected = this.selection.update(eligible, false, now)
    this.cursor.style.setProperty('--hand-progress', String(this.selection.progress))
    this.cursor.dataset.state = this.selection.locked ? 'selected' : eligible ? 'dwelling' : 'moving'
    if (selected)
      eligible.click()
    if (this.disposed)
      return
    if (!eligible && this.sample.open) {
      const transcript = document.querySelector('.resident-transcript')
      if (transcript && (y < innerHeight * 0.15 || y > innerHeight * 0.85))
        transcript.scrollBy({ top: (y < innerHeight * 0.15 ? -1 : 1) * dt * 0.3, behavior: 'auto' })
    }
    this.animation = requestAnimationFrame(frame => this.draw(frame))
  }

  clear() {
    cancelAnimationFrame(this.animation)
    this.animation = undefined
    this.cursor.hidden = true
    this.hovered?.removeAttribute('data-hand-hover')
    this.hovered = undefined
    this.position = undefined
    this.sample = undefined
    this.lastFrame = undefined
    this.selection.reset()
  }

  dispose() {
    this.disposed = true
    this.clear()
    this.cursor.remove()
  }
}
