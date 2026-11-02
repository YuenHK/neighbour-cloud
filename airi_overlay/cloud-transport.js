// Opt-in cloud transport candidate. Importing it starts no login or request.
// The server alone verifies Google signatures, subjects and permissions.
const photoPath = /^\/api\/v1\/patrol\/events\/[\w-]{1,120}\/photo$/
const staffEventPath = /^\/api\/v1\/events\/[\w-]{1,120}$/
const followupPath = /^\/api\/v1\/patrol\/events\/[a-f0-9]{32}\/followup$/
const modelUploadPath = /^\/api\/v1\/service-desk\/airi-models\/cloud-live2d-[a-f0-9]{64}$/
const robotPath = /^\/api\/v1\/robot\/ep\/(?:fleet|qr|connection|connect|disconnect|cancel-pairing|lease|stop|prepare-control|command|reset-stop|discovery|devices\/[A-Za-z0-9_-]{1,60}(?:\/(?:frame\.jpg|connection|video-frame|connect|disconnect|prepare-control|lease|stop|command|video-start|video-stop|gimbal-start|gimbal-follow|gimbal-target|gimbal-stop|speed|manual-warning|infrared-warning|check-stop|reset-stop|patrol))?)$/
const allowedHeaders = new Set(['content-type', 'accept', 'x-resident-session', 'x-resident-turn'])
const allowedOptions = new Set(['method', 'body', 'headers', 'signal', 'cache', 'credentials', 'redirect', 'mode', 'referrerPolicy', 'keepalive'])
const abortError = () => new DOMException('cloud_request_cancelled', 'AbortError')

/** @template T @param {Promise<T>} promise @param {AbortSignal | undefined} signal @param {number | undefined} timeoutMs */
function waitFor(promise, signal, timeoutMs = undefined) {
  if (signal?.aborted)
    return Promise.reject(abortError())
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let timer
  /** @type {(() => void) | undefined} */
  let onAbort
  const races = [promise]
  if (signal) {
    races.push(new Promise((_, reject) => {
      onAbort = () => reject(abortError())
      signal.addEventListener('abort', onAbort, { once: true })
    }))
  }
  if (timeoutMs !== undefined) {
    races.push(new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('cloud_sign_in_unavailable')), timeoutMs)
    }))
  }
  return Promise.race(races).finally(() => {
    clearTimeout(timer)
    if (onAbort)
      signal?.removeEventListener('abort', onAbort)
  })
}

/**
 * @param {{origin: string, tokenProvider: () => Promise<{token: string, expiresAtMs: number}> | {token: string, expiresAtMs: number}, fetcher?: typeof fetch, now?: () => number, authTimeoutMs?: number}} options
 */
export function createCloudTransport({ origin, tokenProvider, fetcher = (...args) => globalThis.fetch(...args), now = () => Date.now(), authTimeoutMs = 10000 }) {
  try {
    const base = new URL(origin)
    if (base.protocol !== 'https:' || base.origin !== origin || base.port || base.username || base.password
      || base.pathname !== '/' || base.search || base.hash || typeof tokenProvider !== 'function'
      || typeof fetcher !== 'function' || typeof now !== 'function'
      || !Number.isFinite(authTimeoutMs) || authTimeoutMs < 1 || authTimeoutMs > 30000) {
      throw new Error('cloud_transport_configuration_required')
    }
  }
  catch {
    throw new Error('cloud_transport_configuration_required')
  }
  let generation = 0
  let lifecycle = new AbortController()
  /** @type {{token: string, expiresAtMs: number} | undefined} */
  let cached
  /** @type {{promise: Promise<string>, cancel: AbortController} | undefined} */
  let pending

  function obtain() {
    if (cached && cached.expiresAtMs - now() > 60000)
      return Promise.resolve(cached.token)
    if (pending)
      return pending.promise
    const identity = generation
    const cancel = new AbortController()
    const provider = Promise.resolve().then(() => {
      if (identity !== generation)
        throw new Error('cloud_sign_in_changed')
      return tokenProvider()
    })
    /** @type {Promise<string>} */
    const task = waitFor(provider, cancel.signal, authTimeoutMs).then((answer) => {
      if (identity !== generation)
        throw new Error('cloud_sign_in_changed')
      if (!answer || typeof answer.token !== 'string' || answer.token.length > 16384
        || !/^[\w-]+\.[\w-]+\.[\w-]+$/.test(answer.token)
        || !Number.isSafeInteger(answer.expiresAtMs) || !Number.isFinite(now())
        || answer.expiresAtMs - now() <= 60000) {
        throw new Error('cloud_sign_in_unavailable')
      }
      cached = { token: answer.token, expiresAtMs: answer.expiresAtMs }
      return answer.token
    }).catch(() => {
      throw new Error(identity === generation ? 'cloud_sign_in_unavailable' : 'cloud_sign_in_changed')
    }).finally(() => {
      if (pending?.promise === task)
        pending = undefined
    })
    pending = { promise: task, cancel }
    return task
  }

  /** @param {string} path @param {RequestInit} init */
  function request(path, init) {
    try {
      if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')
        || !init || typeof init !== 'object' || Object.keys(init).some(key => !allowedOptions.has(key))) {
        throw new Error('cloud_request_invalid')
      }
      const url = new URL(path, origin)
      const supported = url.pathname.startsWith('/api/v1/resident/') || url.pathname.startsWith('/api/v1/service-desk/')
        || url.pathname === '/api/v1/events.csv' || photoPath.test(url.pathname)
        || ['/api/v1/events', '/api/v1/event-stats', '/api/v1/patrol/followups', '/api/v1/patrol/workbench'].includes(url.pathname)
        || staffEventPath.test(url.pathname) || followupPath.test(url.pathname) || robotPath.test(url.pathname)
        || ['/api/v1/governance/audit', '/api/v1/governance/retention'].includes(url.pathname)
        || ['/v1/audio/resident-stream', '/_audio/v1/audio/resident-stream'].includes(url.pathname)
      if (url.origin !== origin || url.username || url.password || url.hash || !supported) {
        throw new Error('cloud_request_invalid')
      }
      const method = (init.method || 'GET').toUpperCase()
      const modelUpload = ((method === 'PUT' && modelUploadPath.test(url.pathname))
        || (method === 'POST' && url.pathname === '/api/v1/service-desk/airi-models/prepare'))
        && init.body instanceof Blob && init.body.size > 0 && init.body.size <= 32 * 1024 * 1024
      if (init.keepalive !== undefined && (typeof init.keepalive !== 'boolean' || !robotPath.test(url.pathname)))
        throw new Error('cloud_request_invalid')
      if (!['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)
        || (init.body != null && ((!modelUpload && typeof init.body !== 'string') || ['GET', 'HEAD'].includes(method)))) {
        throw new Error('cloud_request_invalid')
      }
      for (const [key, expected] of Object.entries({ cache: 'no-store', credentials: 'omit', redirect: 'error', mode: 'same-origin', referrerPolicy: 'no-referrer' })) {
        if (Reflect.get(init, key) !== undefined && Reflect.get(init, key) !== expected)
          throw new Error('cloud_request_invalid')
      }
      const headers = new Headers(init.headers)
      for (const key of headers.keys()) {
        if (!allowedHeaders.has(key))
          throw new Error('cloud_request_invalid')
      }
      if (init.body != null && !headers.has('content-type'))
        headers.set('Content-Type', 'application/json')
      return { url, method, headers, body: init.body, signal: init.signal || undefined, keepalive: init.keepalive }
    }
    catch {
      throw new Error('cloud_request_invalid')
    }
  }

  return {
    /** @param {string} path @param {RequestInit} init */
    async fetch(path, init = {}) {
      const options = request(path, init)
      if (options.signal?.aborted)
        throw abortError()
      const identity = generation
      const scopeSignal = lifecycle.signal
      const token = await waitFor(obtain(), options.signal)
      if (options.signal?.aborted)
        throw abortError()
      if (identity !== generation)
        throw new Error('cloud_sign_in_changed')
      const signal = options.signal ? AbortSignal.any([options.signal, scopeSignal]) : scopeSignal
      options.headers.set('Authorization', `Bearer ${token}`)
      try {
        const response = await fetcher(options.url.href, { method: options.method, headers: options.headers, body: options.body, signal, credentials: 'omit', redirect: 'error', cache: 'no-store', mode: 'same-origin', referrerPolicy: 'no-referrer', ...(options.keepalive === undefined ? {} : { keepalive: options.keepalive }) })
        if (identity !== generation) {
          try {
            void response.body?.cancel().catch(() => undefined)
          }
          catch {
            // A locked/uncooperative late body must not delay rejecting it.
          }
          throw abortError()
        }
        if (response.status === 401 && cached?.token === token)
          cached = undefined // A future explicit request may sign in again; never replay this request.
        return response
      }
      catch (error) {
        if (signal.aborted || (error instanceof DOMException && error.name === 'AbortError'))
          throw abortError()
        throw new Error('cloud_request_failed')
      }
    },
    clearAuth() {
      generation++
      const previousLifecycle = lifecycle
      lifecycle = new AbortController()
      cached = undefined
      const old = pending
      pending = undefined
      old?.cancel.abort()
      previousLifecycle.abort()
      // Native fetch aborts active bodies as well as header waits. The UI
      // still owns already decoded audio, resident history and draft state.
    },
  }
}
