// Only retries initialization. Never retries chat, uploads, case writes or AI calls.
export class StartupRepair {
  constructor({ onState = () => {}, wait = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
    this.onState = onState
    this.wait = wait
    this.reset()
  }
  reset() { this.epoch = (this.epoch || 0) + 1; this.used = new Set(); this.pending = new Map() }
  run(key, action, eligible = () => true) {
    if (this.pending.has(key)) return this.pending.get(key)
    if (this.used.has(key) || !eligible()) return Promise.resolve(false)
    this.used.add(key)
    const epoch = this.epoch
    const task = (async () => {
      this.onState(key, 'retrying')
      await this.wait(1000)
      if (epoch !== this.epoch || !eligible()) return false
      try {
        const result = await action()
        if (epoch !== this.epoch) return false
        this.onState(key, result ? 'retried' : 'unavailable')
        return !!result
      }
      catch { if (epoch === this.epoch) this.onState(key, 'unavailable'); return false }
    })()
    this.pending.set(key, task)
    void task.finally(() => { if (epoch === this.epoch) this.pending.delete(key) })
    return task
  }
}
