// Explicit resident-only API selection. Importing this module starts no login.
// The cloud host must inject its authenticated transport before a request;
// a missing transport never sends resident content to Notebook loopback.
/** @typedef {{fetch: typeof fetch}} CloudTransport */
/**
 * Select the existing native endpoints or an explicitly injected cloud transport.
 * The transport owns login and cancellation; this boundary never retries or
 * selects an alternate model/voice. Host boot must set cloud mode deliberately.
 * @param {{cloud?: boolean, transport?: () => CloudTransport | undefined, fetcher?: typeof fetch}} options
 */
export function createResidentApi({ cloud = false, transport, fetcher = (...args) => globalThis.fetch(...args) } = {}) {
  if (typeof cloud !== 'boolean' || typeof fetcher !== 'function')
    throw new Error('resident_api_configuration_required')

  /** @type {typeof fetch} */
  const request = async (input, init) => {
    if (!cloud)
      return fetcher(input, init)
    let selected
    try {
      selected = transport?.()
    }
    catch {
      throw new Error('cloud_transport_not_ready')
    }
    if (typeof input !== 'string' || !selected || typeof selected.fetch !== 'function')
      throw new Error('cloud_transport_not_ready')
    return selected.fetch(input, init)
  }

  /** @param {string} endpoint @param {object} body @param {AbortSignal | undefined} signal @param {Record<string, string>} extra */
  const post = (endpoint, body, signal, extra = {}) => request(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...extra },
    body: JSON.stringify(body),
    signal,
    cache: 'no-store',
    credentials: 'omit',
    redirect: 'error',
  })

  return {
    cloud,
    /** @param {object} body @param {AbortSignal} [signal] */
    chat(body, signal) {
      return post(cloud ? '/api/v1/resident/chat' : 'http://127.0.0.1:8000/api/v1/resident/chat', { ...body, native_settings: true }, signal)
    },
    /** @param {unknown} value @param {{sessionId: string, turnId: string}} ids @param {AbortSignal} [signal] */
    async completePlan(value, ids, signal) {
      if (!cloud || !value || typeof value !== 'object')
        throw new Error('invalid_cloud_plan')
      const plan = /** @type {{object?: unknown, system_prompt?: unknown, messages?: unknown}} */ (value)
      const outputPolicy = '\n居民畫面只輸出自然、可直接朗讀的對話文字，不輸出 ACT、DELAY 或其他角色控制標記。'
      if (plan.object !== 'resident.plan' || typeof plan.system_prompt !== 'string'
        || !plan.system_prompt.trim() || plan.system_prompt.length + outputPolicy.length > 14000
        || !Array.isArray(plan.messages) || !plan.messages.length || plan.messages.length > 60
        || plan.messages.some(item => !item || !['user', 'assistant'].includes(item.role)
          || typeof item.content !== 'string' || item.content.length > 16000)
        || !ids || !/^[a-f0-9]{32}$/.test(ids.sessionId) || !/^[a-f0-9]{32}$/.test(ids.turnId)) {
        throw new Error('invalid_cloud_plan')
      }
      return post('/api/v1/resident/model/v1/chat/completions', {
        model: 'gemma-4-26b-a4b-it',
        stream: true,
        messages: [{ role: 'system', content: plan.system_prompt + outputPolicy }, ...plan.messages.map(item => ({ role: item.role, content: item.content }))],
      }, signal, { 'X-Resident-Session': ids.sessionId, 'X-Resident-Turn': ids.turnId })
    },
    pcm: { fetcher: request, endpoint: cloud ? '/_audio/v1/audio/resident-stream' : 'http://127.0.0.1:8765/v1/audio/resident-stream' },
    timing: { fetcher: request, endpoint: cloud ? '/api/v1/resident/timing' : 'http://127.0.0.1:8000/api/v1/resident/timing' },
  }
}
