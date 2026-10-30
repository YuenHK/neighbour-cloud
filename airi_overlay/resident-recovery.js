// Recover only local initialization or a server-proven pre-dispatch refusal.
// Unknown network/model/ASR/voice outcomes are never automatically replayed.
/** @param {number} ms @param {AbortSignal | null | undefined} signal @returns {Promise<void>} */
export function recoveryWait(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('cancelled', 'AbortError'))
      return
    }
    let timer
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException('cancelled', 'AbortError'))
    }
    timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

/** @param {{fetch: (path: string, init: RequestInit) => Promise<Response>}} base */
export function recoveringFetch(base, { renew = async () => false, wait = recoveryWait } = {}) {
  /** @param {string} path @param {RequestInit} init */
  return async (path, init = {}) => {
    const response = await base.fetch(path, init)
    if (init.signal?.aborted)
      return response
    // A boundary 401 precedes every application operation. Reuse the exact
    // request/intent IDs after replacing only an anonymous site's expired token.
    if (response.status === 401 && await renew())
      return base.fetch(path, init)
    if (response.status !== 503)
      return response
    const failure = await response.clone().json().catch(() => ({}))
    if (failure.code !== 'service_maintenance' || failure.operation_outcome !== 'not_attempted')
      return response
    for (let attempt = 0; attempt < 6; attempt++) {
      await wait(1500, init.signal)
      const signals = [AbortSignal.timeout(3000)]
      if (init.signal)
        signals.push(init.signal)
      const ready = await base.fetch('/api/v1/resident/session', { method: 'GET', signal: AbortSignal.any(signals) }).catch(() => null)
      if (ready?.ok)
        return base.fetch(path, init)
    }
    return response
  }
}

export class InputRecovery {
  constructor({ wait = recoveryWait, now = () => Date.now() } = {}) {
    this.wait = wait
    this.now = now
    this.entries = new Map()
    this.controller = new AbortController()
  }

  /** @param {string} key @param {() => Promise<void> | void} action */
  run(key, action) {
    if (this.controller.signal.aborted)
      return Promise.resolve(false)
    let item = this.entries.get(key)
    if (item?.pending)
      return item.pending
    if (!item || this.now() - item.started > 300000) {
      item = { started: this.now(), attempts: 0, pending: undefined }
      this.entries.set(key, item)
    }
    if (item.attempts >= 2)
      return Promise.resolve(false)
    const work = async () => {
      while (item.attempts < 2 && !this.controller.signal.aborted) {
        item.attempts++
        await this.wait(item.attempts * 1000, this.controller.signal)
        if (this.controller.signal.aborted)
          return false
        try {
          await action()
          return true
        }
        catch { /* Only retry initialization, never a provider request. */ }
      }
      return false
    }
    item.pending = work().catch(() => false).finally(() => {
      item.pending = undefined
    })
    return item.pending
  }

  close() {
    this.controller.abort()
    this.entries.clear()
  }
}
