interface Connection {
  readonly connectionStatus: string
  connect: (options: { timeout: number, abortSignal: AbortSignal }) => Promise<void>
  onConnectionStateChange: (listener: (context: { status: string }) => void) => () => void
}

const live = new Set(['connecting', 'authenticating', 'announcing', 'reconnecting'])

// Observe the SDK's own reconnect policy; never call connect again to override
// terminal authentication failure or spawn a second transport/retry timer.
export function waitForAiriReady(client: Connection, signal: AbortSignal,
  onWaiting: () => void = () => {}): Promise<boolean> {
  if (signal.aborted)
    return Promise.resolve(false)
  if (client.connectionStatus === 'ready')
    return Promise.resolve(true)
  if (['failed', 'closed', 'closing'].includes(client.connectionStatus))
    return Promise.reject(new Error('AIRI connection stopped; check service, configuration or credentials'))
  return new Promise((resolve, reject) => {
    let settled = false
    let waitingReported = false
    let unsubscribe = () => {}
    const finish = (ready: boolean, failed = false) => {
      if (settled)
        return
      settled = true
      unsubscribe()
      signal.removeEventListener('abort', aborted)
      if (failed)
        reject(new Error('AIRI connection stopped; check service, configuration or credentials'))
      else
        resolve(ready)
    }
    const aborted = () => finish(false)
    const observe = () => {
      if (settled)
        return
      if (signal.aborted) { finish(false); return }
      const status = client.connectionStatus
      if (status === 'ready') { finish(true); return }
      if (['failed', 'closed', 'closing'].includes(status)) { finish(false, true); return }
      if (status === 'reconnecting' && !waitingReported) {
        waitingReported = true
        onWaiting()
      }
    }
    unsubscribe = client.onConnectionStateChange(observe)
    signal.addEventListener('abort', aborted, { once: true })
    try {
      void client.connect({ timeout: 15_000, abortSignal: signal }).then(() => {
        observe()
        if (!settled)
          finish(false, true) // A successful connect must correspond to ready.
      }, () => {
        observe()
        // SDK initial failures/timeouts may reject while its sole transport is
        // still connecting/reconnecting. Wait for state changes, not another connect.
        if (!settled && !live.has(client.connectionStatus))
          finish(false, true)
      })
    }
    catch { finish(false, true) }
  })
}
