// Common to every estate page. Only renew passive discovery/read-only connection.
(() => {
  if (globalThis.EpDiscoveryReady) return
  let pending = false
  async function renew() {
    if (pending) return
    pending = true
    try {
      const response = await fetch('/api/v1/robot/ep/discovery', {
        method: 'POST', credentials: 'omit', cache: 'no-store', redirect: 'error',
        signal: AbortSignal.timeout(5000),
      })
      return response.ok
    }
    catch { return false }
    finally { pending = false }
  }
  globalThis.EpDiscoveryReady = renew()
  // Also run in background tabs; no dependence on robot view or microphone.
  setInterval(() => { void renew() }, 10000)
})()
