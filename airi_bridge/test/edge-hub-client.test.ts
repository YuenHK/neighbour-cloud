import { describe, expect, it, vi } from 'vitest'
import { edgeEventWebSocketUrl, fetchEdgeEventCursor, fetchEdgeEventPage, fetchEdgeEvents, findUnseenEvents, isEdgeEvent, requestEdgeJson } from '../src/edge-hub-client.js'

const jsonResponse = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })

const event = {
  id: 'evt-1',
  type: 'litter_detected' as const,
  zone: 'A1',
  at_ms: 10,
  severity: 'notice' as const,
}

describe('Edge Hub event client', () => {
  it('boots from the ingestion tail rather than loading historical events', async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ cursor: 123 }))
    expect(await fetchEdgeEventCursor('http://127.0.0.1:8000', fetcher)).toBe(123)
    expect(fetcher.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/v1/events/cursor')
  })

  it('fetches a bounded ingestion-cursor page independently of event timestamps', async () => {
    const page = { items: [{ ...event, at_ms: 1 }], next_cursor: 124, has_more: false }
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(page))
    expect(await fetchEdgeEventPage('http://127.0.0.1:8000', 123, fetcher)).toEqual(page)
    expect(fetcher.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/v1/events/page?after=123&limit=100')
  })

  it('rejects a non-advancing cursor so a bad server cannot spin the bridge', async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [event], next_cursor: 123, has_more: true }))
    await expect(fetchEdgeEventPage('http://127.0.0.1:8000', 123, fetcher)).rejects.toThrow('non-advancing')
  })

  it('does not silently fall back to loading all events on a page error', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 503 })
    await expect(fetchEdgeEventPage('http://127.0.0.1:8000', 0, fetcher)).rejects.toThrow('HTTP 503')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('fetches only from the configured local API', async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse([event]))

    await expect(fetchEdgeEvents('http://127.0.0.1:8000', fetcher)).resolves.toEqual([event])
    expect(fetcher).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/v1/events',
      expect.objectContaining({ headers: { accept: 'application/json' }, redirect: 'error', signal: expect.any(AbortSignal) }),
    )
  })

  it('requests only events at or after the bridge cursor', async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse([]))

    await fetchEdgeEvents('http://127.0.0.1:8000', fetcher, 123)

    expect(fetcher).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/v1/events?since_ms=123',
      expect.objectContaining({ headers: { accept: 'application/json' }, redirect: 'error', signal: expect.any(AbortSignal) }),
    )
  })

  it('returns only event ids not previously published', () => {
    expect(findUnseenEvents([event, { ...event, id: 'evt-2' }], new Set(['evt-1'])))
      .toEqual([{ ...event, id: 'evt-2' }])
  })

  it('derives the local event WebSocket URL', () => {
    expect(edgeEventWebSocketUrl('http://127.0.0.1:8000'))
      .toBe('ws://127.0.0.1:8000/ws/events')
  })

  it('bounds a stalled fetch and aborts its request', async () => {
    const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>(() => {}))
    await expect(requestEdgeJson('http://127.0.0.1:8000/health', fetcher, 20)).rejects.toThrow('timed out')
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true)
  })

  it('includes a stalled response body in the same timeout budget', async () => {
    const response = new Response(new ReadableStream({ start() {} }))
    await expect(requestEdgeJson('http://127.0.0.1:8000/health', vi.fn().mockResolvedValue(response), 20))
      .rejects.toThrow('timed out')
  })

  it('rejects an oversized body without trusting content-length', async () => {
    const response = new Response('x'.repeat(1024 * 1024 + 1))
    await expect(requestEdgeJson('http://127.0.0.1:8000/health', vi.fn().mockResolvedValue(response)))
      .rejects.toThrow('too large')
  })

  it('rejects malformed page events before any cursor advancement', async () => {
    for (const item of [{ ...event, type: 'set_pwm' }, { ...event, id: 'bad\nlog' }, { ...event, at_ms: -1 }, null]) {
      const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [item], next_cursor: 124, has_more: false }))
      await expect(fetchEdgeEventPage('http://127.0.0.1:8000', 123, fetcher)).rejects.toThrow('Invalid')
    }
  })

  it('rejects nonempty final pages that do not advance', async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [event], next_cursor: 123, has_more: false }))
    await expect(fetchEdgeEventPage('http://127.0.0.1:8000', 123, fetcher)).rejects.toThrow('non-advancing')
  })

  it('uses the same whitelist for standalone WebSocket notifications', () => {
    expect(isEdgeEvent(event)).toBe(true)
    for (const item of [null, [], { ...event, severity: 'unlock' }, { ...event, zone: '' },
      { ...event, id: 'x'.repeat(257) }, { ...event, at_ms: Number.MAX_SAFE_INTEGER + 1 }])
      expect(isEdgeEvent(item)).toBe(false)
  })

  it('does not echo invalid JSON content into errors', async () => {
    const response = new Response('secret-do-not-log')
    await expect(requestEdgeJson('http://127.0.0.1:8000/health', vi.fn().mockResolvedValue(response)))
      .rejects.toThrow(/^Invalid Edge Hub JSON$/)
  })
})
