// Kept separate from the native fetch functions and their loopback defaults.
/** @param {string} path @param {RequestInit} init */
export async function cloudFetch(path, init = {}) {
  const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
  if (Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') !== true || typeof transport?.fetch !== 'function')
    throw new Error('verified_cloud_transport_required')
  const headers = new Headers(init.headers)
  // Native presentation modules include an empty compatibility field. Google
  // is the sole cloud identity; no operator credential or claimed role is used.
  headers.delete('X-Operator-Key')
  if (headers.has('Authorization')) throw new Error('client_identity_override_forbidden')
  return transport.fetch(path, { ...init, headers })
}
