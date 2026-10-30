// Memory-only, same-origin identity handoff to one current service frame.
// Neither importing this module nor creating a broker starts media or a login.
/** @param {{origin: string, frameWindow: () => Window | null,
 * tokenProvider: () => {token: string, expiresAtMs: number}}} options */
export function createFrameBroker({ origin, frameWindow, tokenProvider }) {
  const url = new URL(origin)
  if (url.protocol !== 'https:' || url.origin !== origin || url.port)
    throw new Error('cloud_frame_configuration_required')
  let active = true
  /** @type {Set<MessagePort>} */
  const ports = new Set()
  /** @param {MessageEvent} event */
  function receive(event) {
    if (!active || event.origin !== origin || !event.source || event.source !== frameWindow()
      || event.data?.type !== 'neighbour-cloud-identity-v1'
      || !/^[a-f0-9]{32}$/.test(event.data.nonce) || event.ports?.length !== 1)
      return
    const port = event.ports[0]
    if (ports.size >= 2) {
      port.close()
      return
    }
    try {
      const identity = tokenProvider()
      port.postMessage({ type: 'neighbour-cloud-identity-v1', nonce: event.data.nonce, ...identity })
      ports.add(port)
    }
    catch {
      port.postMessage({ type: 'neighbour-cloud-signed-out' })
      port.close()
    }
  }
  function close() {
    active = false
    for (const port of ports) {
      try { port.postMessage({ type: 'neighbour-cloud-signed-out' }) }
      finally { port.close() }
    }
    ports.clear()
  }
  return { receive, close }
}

/** @param {{target: Window, parent: Window, origin: string,
 * channel?: MessageChannel, nonce?: string, timeoutMs?: number,
 * onClose?: () => void}} options */
export function frameIdentity({ target, parent, origin, channel = new MessageChannel(),
  nonce = crypto.randomUUID().replaceAll('-', ''), timeoutMs = 10000, onClose = () => {} }) {
  if (target === parent || new URL(origin).origin !== origin || !origin.startsWith('https://')
    || !/^[a-f0-9]{32}$/.test(nonce) || timeoutMs < 1 || timeoutMs > 10000)
    return Promise.reject(new Error('cloud_parent_required'))
  /** @type {Promise<{token: string, expiresAtMs: number}>} */
  const result = new Promise((resolve, reject) => {
    let accepted = false
    const port = channel.port1
    const timer = setTimeout(() => {
      port.close()
      reject(new Error('cloud_identity_unavailable'))
    }, timeoutMs)
    port.onmessage = (event) => {
      const data = event.data
      if (data?.type === 'neighbour-cloud-signed-out') {
        clearTimeout(timer)
        port.close()
        onClose()
        if (!accepted)
          reject(new Error('cloud_sign_in_required'))
        return
      }
      if (accepted || data?.type !== 'neighbour-cloud-identity-v1' || data.nonce !== nonce
        || typeof data.token !== 'string' || !/^[\w-]+\.[\w-]+\.[\w-]+$/.test(data.token)
        || !Number.isSafeInteger(data.expiresAtMs) || data.expiresAtMs - Date.now() <= 60000)
        return
      accepted = true
      clearTimeout(timer)
      resolve({ token: data.token, expiresAtMs: data.expiresAtMs })
    }
    port.start()
    parent.postMessage({ type: 'neighbour-cloud-identity-v1', nonce }, origin, [channel.port2])
  })
  return result
}
