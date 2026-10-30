// RAM-only scoped capability, never operator credentials or browser storage.
export function installAssistantMemory() {
  if (typeof window === 'undefined')
    return
  let token = ''
  let expiresAt = 0
  const hubOrigin = Reflect.get(globalThis, '__NEIGHBOUR_REMOTE__') === true ? location.origin : 'http://127.0.0.1:8000'
  const originalFetch = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href)
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
    if (token && method === 'POST' && url.origin === hubOrigin && url.pathname === '/v1/chat/completions') {
      if (Date.now() >= expiresAt)
        throw new Error('記憶授權已到期，請在本機記憶後台重新授權')
      const request = new Request(input, init)
      const headers = new Headers(request.headers)
      headers.set('X-Assistant-Memory-Token', token)
      return originalFetch(new Request(request, { headers, redirect: 'error', credentials: 'omit', cache: 'no-store' }))
    }
    return originalFetch(input, init)
  }
  window.addEventListener('message', (event) => {
    if (![hubOrigin, 'http://localhost:8000'].includes(event.origin) || !window.opener || event.source !== window.opener
      || event.data?.type !== 'zhiwei-memory-capability') {
      return
    }
    if (typeof event.data.token !== 'string' || !/^[\w-]{43}$/.test(event.data.token)
      || event.data.expiresIn !== 28800) {
      return
    }
    token = event.data.token
    expiresAt = Date.now() + event.data.expiresIn * 1000
    window.opener.postMessage({ type: 'zhiwei-memory-accepted' }, event.origin)
    console.info('[local-memory] 本機記憶模式已授權；對話只用本機 Ollama，未啟用硬件。')
  })
  if (window.opener) {
    let parentOrigin = hubOrigin
    try {
      const referrerOrigin = new URL(document.referrer).origin
      if ([hubOrigin, 'http://localhost:8000'].includes(referrerOrigin))
        parentOrigin = referrerOrigin
    }
    catch { /* Missing referrer: use the canonical loopback origin. */ }
    window.opener.postMessage({ type: 'zhiwei-memory-ready' }, parentOrigin)
  }
}
