export interface EdgeEvent {
  id: string
  type: 'litter_detected' | 'leak_detected' | 'temperature_drill' | 'robot_fault'
  zone: string
  at_ms: number
  severity: 'notice' | 'warning' | 'critical'
  details?: unknown
  evidence?: unknown
}

export class EdgeHubHttpError extends Error {
  constructor(readonly status: number) { super(`Edge Hub request failed: HTTP ${status}`) }
}
export class EdgeHubStreamError extends Error {}

export interface EdgeEventPage {
  items: EdgeEvent[]
  next_cursor: number
  has_more: boolean
  stream_id?: string
}

export async function fetchEdgeEventStreamState(baseUrl: string, fetcher: typeof fetch = fetch): Promise<{ stream_id: string, cursor: number }> {
  const data = await requestEdgeJson(`${baseUrl}/api/v1/events/stream`, fetcher) as { stream_id: string, cursor: number } | null
  if (!data || typeof data.stream_id !== 'string' || !/^[0-9a-f]{32}$/.test(data.stream_id)
    || !Number.isSafeInteger(data.cursor) || data.cursor < 0)
    throw new Error('Invalid Edge Hub stream identity')
  return data
}

export function isEdgeEvent(value: unknown): value is EdgeEvent {
  if (!value || typeof value !== 'object')
    return false
  const event = value as EdgeEvent
  return typeof event.id === 'string' && event.id.length > 0 && event.id.length <= 256
    && !/[\u0000-\u001F\u007F]/.test(event.id)
    && ['litter_detected', 'leak_detected', 'temperature_drill', 'robot_fault'].includes(event.type)
    && typeof event.zone === 'string' && event.zone.length > 0 && event.zone.length <= 2000
    && Number.isSafeInteger(event.at_ms) && event.at_ms >= 0
    && ['notice', 'warning', 'critical'].includes(event.severity)
}

export async function requestEdgeJson(url: string, fetcher: typeof fetch = fetch, timeoutMs = 3000): Promise<unknown> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 10_000)
    throw new Error('Invalid Edge Hub timeout')
  const controller = new AbortController()
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error('Edge Hub request timed out'))
      controller.abort()
    }, timeoutMs)
  })
  const operation = async () => {
    const response = await fetcher(url, { headers: { accept: 'application/json' },
      signal: controller.signal, redirect: 'error' })
    if (!response.ok)
      throw new EdgeHubHttpError(response.status)
    // Do not allocate an unbounded .text()/.json() body or trust Content-Length.
    if (!response.body)
      throw new Error('Invalid Edge Hub response body')
    reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let length = 0
    while (true) {
      const { done, value } = await reader.read()
      if (done)
        break
      length += value.byteLength
      if (length > 1024 * 1024)
        throw new Error('Edge Hub response too large')
      chunks.push(value)
    }
    const bytes = new Uint8Array(length)
    let offset = 0
    for (const chunk of chunks) {
      bytes.set(chunk, offset)
      offset += chunk.byteLength
    }
    try {
      return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as unknown
    }
    catch {
      throw new Error('Invalid Edge Hub JSON')
    }
  }
  try {
    return await Promise.race([operation(), timeout])
  }
  finally {
    clearTimeout(timer)
    controller.abort()
    // Never wait indefinitely for a misbehaving response body to acknowledge cancellation.
    void reader?.cancel().catch(() => {})
  }
}

export async function fetchEdgeEventCursor(baseUrl: string, fetcher: typeof fetch = fetch): Promise<number> {
  const data = await requestEdgeJson(`${baseUrl}/api/v1/events/cursor`, fetcher) as { cursor: number } | null
  if (!data || !Number.isSafeInteger(data.cursor) || data.cursor < 0)
    throw new Error('Invalid Edge Hub cursor')
  return data.cursor
}

export async function fetchEdgeEventPage(
  baseUrl: string, after: number, fetcher: typeof fetch = fetch, limit = 100, streamId?: string,
): Promise<EdgeEventPage> {
  if (!Number.isSafeInteger(after) || after < 0 || !Number.isInteger(limit) || limit < 1 || limit > 500)
    throw new Error('Invalid event page request')
  if (streamId !== undefined && !/^[0-9a-f]{32}$/.test(streamId))
    throw new Error('Invalid expected stream identity')
  const binding = streamId === undefined ? '' : `&stream_id=${streamId}`
  const page = await requestEdgeJson(`${baseUrl}/api/v1/events/page?after=${after}&limit=${limit}${binding}`, fetcher) as EdgeEventPage | null
  if (streamId !== undefined && (!page || page.stream_id !== streamId))
    throw new EdgeHubStreamError('Invalid bound event stream; explicit recovery required')
  if (!page || !Array.isArray(page.items) || page.items.length > limit || !page.items.every(isEdgeEvent)
    || typeof page.has_more !== 'boolean'
    || !Number.isSafeInteger(page.next_cursor) || page.next_cursor < after
    || ((page.has_more || page.items.length > 0) && page.next_cursor === after)
    || (page.has_more && page.items.length === 0)
    || (streamId !== undefined && page.stream_id !== streamId))
    throw new Error('Invalid or non-advancing event page')
  return page
}

export async function fetchEdgeEvents(
  baseUrl = 'http://127.0.0.1:8000',
  fetcher: typeof fetch = fetch,
  sinceMs?: number,
): Promise<EdgeEvent[]> {
  const suffix = sinceMs === undefined ? '' : `?since_ms=${encodeURIComponent(sinceMs)}`
  const events = await requestEdgeJson(`${baseUrl}/api/v1/events${suffix}`, fetcher)
  if (!Array.isArray(events) || events.length > 1000 || !events.every(isEdgeEvent))
    throw new Error('Invalid Edge Hub events')
  return events
}

export function findUnseenEvents(events: EdgeEvent[], seenIds: Set<string>): EdgeEvent[] {
  return events.filter(event => !seenIds.has(event.id))
}

export function edgeEventWebSocketUrl(baseUrl: string): string {
  return `${baseUrl.replace(/^http/, 'ws')}/ws/events`
}
