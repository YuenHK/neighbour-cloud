// Cloud shell identity stays in memory; only the backend accepts Google claims.
// Importing this factory performs no login, recording, playback or API call.
/** @typedef {{token: string, expiresAtMs: number}} IdentityToken */
/** @param {{origin: string, fetcher?: typeof fetch, now?: () => number,
 * onState?: (state: {state: string, role?: string}) => void, onClear?: () => void,
 * onReady?: (provider: () => IdentityToken) => Promise<void> | void}} options */
export function createCloudSession({ origin, fetcher = (...args) => globalThis.fetch(...args),
  now = () => Date.now(), onState = () => {}, onClear = () => {}, onReady = async () => {} }) {
  const parsed = new URL(origin)
  if (parsed.protocol !== 'https:' || parsed.origin !== origin || parsed.port || parsed.username || parsed.password
    || parsed.pathname !== '/' || parsed.search || parsed.hash || typeof fetcher !== 'function') {
    throw new Error('cloud_session_configuration_required')
  }
  let generation = 0
  /** @type {AbortController | undefined} */
  let waiting
  /** @type {IdentityToken | undefined} */
  let current

  function clear() {
    generation++
    waiting?.abort()
    waiting = undefined
    current = undefined
    onClear()
    onState({ state: 'signed_out' })
  }

  function token() {
    if (!current || current.expiresAtMs - now() <= 60000)
      throw new Error('cloud_sign_in_required')
    return { token: current.token, expiresAtMs: current.expiresAtMs }
  }

  /** @param {string} value */
  async function accept(value) {
    clear()
    const identity = generation
    onState({ state: 'checking' })
    const controller = new AbortController()
    waiting = controller
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(10000)])
    const cancelled = () => new DOMException('cloud_sign_in_cancelled', 'AbortError')
    /** @template T @param {Promise<T>} promise */
    const bounded = async (promise) => {
      let reject = () => {}
      /** @type {Promise<never>} */
      const stop = new Promise((_, fail) => { reject = () => fail(cancelled()) })
      signal.addEventListener('abort', reject, { once: true })
      try {
        if (signal.aborted)
          throw cancelled()
        return await Promise.race([promise, stop])
      }
      finally {
        signal.removeEventListener('abort', reject)
      }
    }
    try {
      if (typeof value !== 'string' || value.length > 16384 || !/^[\w-]+\.[\w-]+\.[\w-]+$/.test(value))
        throw new Error('invalid_token')
      // Expiry is scheduling metadata only. Signature/audience/issuer/role
      // acceptance always comes from the authenticated backend response.
      const payload = JSON.parse(atob(value.split('.')[1].replaceAll('-', '+').replaceAll('_', '/')))
      if (typeof payload?.exp !== 'number')
        throw new Error('invalid_expiry')
      const expiresAtMs = payload.exp * 1000
      if (!Number.isSafeInteger(expiresAtMs) || expiresAtMs - now() <= 60000)
        throw new Error('expired_token')
      const response = await bounded(fetcher(`${origin}/api/v1/resident/session`, {
        method: 'GET', headers: { Authorization: `Bearer ${value}` }, signal,
        cache: 'no-store', credentials: 'omit', redirect: 'error', mode: 'same-origin', referrerPolicy: 'no-referrer',
      }))
      if (!response.ok)
        throw new Error('identity_unavailable')
      const data = await bounded(response.json())
      if (identity !== generation || signal.aborted || data?.authenticated !== true
        || !['staff', 'resident'].includes(data.role) || typeof data.storage_acceptance !== 'boolean') {
        throw new Error('identity_not_accepted')
      }
      if (data.storage_acceptance) {
        // Staging login cannot silently open a resident service or capture mic.
        onState({ state: 'storage_acceptance', role: data.role })
        return { state: 'storage_acceptance' }
      }
      current = { token: value, expiresAtMs }
      await onReady(() => {
        if (identity !== generation)
          throw new Error('cloud_sign_in_changed')
        return token()
      })
      if (identity !== generation)
        return { state: 'cancelled' }
      onState({ state: 'ready', role: data.role })
      return { state: 'ready', role: data.role }
    }
    catch {
      if (identity !== generation)
        return { state: 'cancelled' }
      clear()
      onState({ state: 'unavailable' })
      return { state: 'unavailable' }
    }
    finally {
      if (waiting === controller)
        waiting = undefined
    }
  }
  return { accept, clear, token }
}
