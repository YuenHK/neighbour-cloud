// Optional best-effort notifications. Cursor polling must not await this connection.
type Socket = Pick<WebSocket, 'addEventListener' | 'removeEventListener' | 'close'>

interface Options {
  factory?: (url: string) => Socket
  handshakeMs?: number
  retryMs?: number
  maxRetryMs?: number
}

export function createEventSocket(url: string, onText: (text: string) => void, options: Options = {}) {
  const factory = options.factory ?? (url => new WebSocket(url))
  const handshakeMs = options.handshakeMs ?? 5000
  const retryMs = options.retryMs ?? 1000
  const maxRetryMs = options.maxRetryMs ?? 30_000
  if (![handshakeMs, retryMs, maxRetryMs].every(value => Number.isFinite(value) && value > 0)
    || maxRetryMs < retryMs)
    throw new Error('Invalid notification retry settings')
  let stopped = true
  let current: Socket | undefined
  let cleanup: (() => void) | undefined
  let handshake: ReturnType<typeof setTimeout> | undefined
  let retry: ReturnType<typeof setTimeout> | undefined
  let delay = retryMs

  function dispose() {
    clearTimeout(handshake)
    handshake = undefined
    cleanup?.()
    cleanup = undefined
    const socket = current
    current = undefined
    try { socket?.close() }
    catch { /* Broken sockets must not stop cursor polling. */ }
  }

  function schedule() {
    if (stopped || retry !== undefined)
      return
    retry = setTimeout(() => {
      retry = undefined
      connect()
    }, delay)
    delay = Math.min(delay * 2, maxRetryMs)
  }

  function connect() {
    if (stopped)
      return
    let socket: Socket
    try { socket = factory(url) }
    catch { schedule(); return }
    current = socket
    let opened = false
    const failed = () => {
      if (current !== socket || stopped)
        return
      dispose()
      schedule()
    }
    const open = () => {
      if (current !== socket || stopped)
        return
      opened = true
      delay = retryMs
      clearTimeout(handshake)
      handshake = undefined
    }
    const message: EventListener = (event) => {
      if (current !== socket || stopped || !opened)
        return
      try { onText(String((event as MessageEvent).data)) }
      catch { /* Polling retains responsibility for recovering unpublished events. */ }
    }
    socket.addEventListener('open', open)
    socket.addEventListener('error', failed)
    socket.addEventListener('close', failed)
    socket.addEventListener('message', message)
    cleanup = () => {
      socket.removeEventListener('open', open)
      socket.removeEventListener('error', failed)
      socket.removeEventListener('close', failed)
      socket.removeEventListener('message', message)
    }
    handshake = setTimeout(failed, handshakeMs)
  }

  return {
    start() {
      if (!stopped)
        return
      stopped = false
      delay = retryMs
      connect()
    },
    stop() {
      stopped = true
      clearTimeout(retry)
      retry = undefined
      dispose()
    },
  }
}
