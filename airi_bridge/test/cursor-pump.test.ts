import { afterEach, describe, expect, it, vi } from 'vitest'
import { runCursorPump } from '../src/cursor-pump.js'
import { createEventDispatcher } from '../src/event-dispatcher.js'
import type { EdgeEventPage } from '../src/edge-hub-client.js'

const event = { id: 'one', type: 'temperature_drill' as const, zone: 'test', at_ms: 1, severity: 'notice' as const }
const empty = (cursor: number) => ({ items: [], next_cursor: cursor, has_more: false })
afterEach(() => vi.useRealTimers())

describe('cursor pump isolated recovery', () => {
  it('retries initial cursor failures with capped backoff and no history fallback', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const fetchCursor = vi.fn().mockRejectedValueOnce(Error()).mockRejectedValueOnce(Error())
      .mockRejectedValueOnce(Error()).mockResolvedValue(42)
    const fetchPage = vi.fn(async (cursor) => { controller.abort(); return empty(cursor) })
    const onReady = vi.fn(), onError = vi.fn()
    const task = runCursorPump({ signal: controller.signal, fetchCursor, fetchPage,
      publish: vi.fn(), onReady, onError, retryMs: 100, maxRetryMs: 200 })
    await vi.advanceTimersByTimeAsync(99)
    expect(fetchCursor).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchCursor).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(200)
    expect(fetchCursor).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(200)
    await task
    expect(fetchCursor).toHaveBeenCalledTimes(4)
    expect(fetchPage).toHaveBeenCalledWith(42)
    expect(onReady).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledExactlyOnceWith('initial-cursor')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('retains a cursor on HTTP failure and never samples a new tail', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const fetchCursor = vi.fn().mockResolvedValue(10)
    const fetchPage = vi.fn().mockRejectedValueOnce(Error()).mockResolvedValueOnce({ items: [event], next_cursor: 11, has_more: false })
      .mockImplementation(async (cursor) => { controller.abort(); return empty(cursor) })
    const publish = vi.fn()
    const task = runCursorPump({ signal: controller.signal, fetchCursor, fetchPage, publish, retryMs: 50, pollMs: 50 })
    await vi.advanceTimersByTimeAsync(100)
    await task
    expect(fetchCursor).toHaveBeenCalledTimes(1)
    expect(fetchPage.mock.calls.map(call => call[0])).toEqual([10, 10, 11])
    expect(publish).toHaveBeenCalledExactlyOnceWith(event)
  })

  it('does not advance a failed page and relies on dispatcher dedup for a partial send', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const next = { ...event, id: 'two' }
    const send = vi.fn().mockImplementationOnce(() => {}).mockImplementationOnce(() => { throw Error() })
    const dispatcher = createEventDispatcher(send)
    const fetchPage = vi.fn().mockResolvedValueOnce({ items: [event, next], next_cursor: 2, has_more: false })
      .mockResolvedValueOnce({ items: [event, next], next_cursor: 2, has_more: false })
      .mockImplementation(async (cursor) => { controller.abort(); return empty(cursor) })
    const task = runCursorPump({ signal: controller.signal, fetchCursor: async () => 0, fetchPage,
      publish: e => { dispatcher.dispatch(e) }, retryMs: 50, pollMs: 50 })
    await vi.advanceTimersByTimeAsync(100)
    await task
    expect(fetchPage.mock.calls.map(call => call[0])).toEqual([0, 0, 2])
    expect(send.mock.calls.map(call => call[0].id)).toEqual(['one', 'two', 'two'])
    expect(dispatcher.status().transport_dispatches).toBe(2)
  })

  it('aborts retry sleep immediately and does not publish a late in-flight result', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    let resolvePage!: (value: EdgeEventPage) => void
    const publish = vi.fn()
    const fetchPage = vi.fn(() => new Promise<EdgeEventPage>(resolve => { resolvePage = resolve }))
    const task = runCursorPump({ signal: controller.signal, fetchCursor: async () => 1,
      fetchPage, publish })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchPage).toHaveBeenCalledTimes(1)
    controller.abort()
    resolvePage({ ...empty(2), items: [event] })
    await task
    expect(publish).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    const other = new AbortController()
    const retry = runCursorPump({ signal: other.signal, fetchCursor: async () => { throw Error() },
      fetchPage: vi.fn(), publish })
    await vi.advanceTimersByTimeAsync(0)
    expect(vi.getTimerCount()).toBe(1)
    other.abort()
    await retry
    expect(vi.getTimerCount()).toBe(0)
  })

  it('bounds each page burst and rejects backwards cursors without overlapping requests', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const fetchPage = vi.fn(async (cursor: number) => ({ items: [event], next_cursor: cursor + 1, has_more: true }))
    const task = runCursorPump({ signal: controller.signal, fetchCursor: async () => 0, fetchPage, publish: vi.fn() })
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchPage).toHaveBeenCalledTimes(10)
    controller.abort()
    await task
    const other = new AbortController()
    const bad = vi.fn().mockResolvedValue(empty(0))
    const onError = vi.fn()
    const stopped = runCursorPump({ signal: other.signal, fetchCursor: async () => 10,
      fetchPage: bad, publish: vi.fn(), onError })
    await vi.advanceTimersByTimeAsync(0)
    expect(onError).toHaveBeenCalledExactlyOnceWith('poll')
    other.abort()
    await stopped
  })

  it('rejects invalid polling settings before I/O and respects an already-aborted signal', async () => {
    const controller = new AbortController()
    const fetchCursor = vi.fn()
    for (const pollMs of [NaN, 0, -1, 1, Infinity, 60_001])
      await expect(runCursorPump({ signal: controller.signal, fetchCursor, fetchPage: vi.fn(), publish: vi.fn(), pollMs })).rejects.toThrow('timing')
    expect(fetchCursor).not.toHaveBeenCalled()
    controller.abort()
    await runCursorPump({ signal: controller.signal, fetchCursor, fetchPage: vi.fn(), publish: vi.fn() })
    expect(fetchCursor).not.toHaveBeenCalled()
  })
})
