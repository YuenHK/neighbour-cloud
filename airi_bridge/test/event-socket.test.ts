import { afterEach, describe, expect, it, vi } from 'vitest'
import { createEventSocket } from '../src/event-socket.js'

class Socket extends EventTarget {
  closed = 0
  close() { this.closed++ }
}

afterEach(() => vi.useRealTimers())

describe('optional Edge Hub notification socket', () => {
  it('starts without awaiting an open handshake and retries after timeout', () => {
    vi.useFakeTimers()
    const sockets: Socket[] = []
    const factory = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket })
    const manager = createEventSocket('ws://unused', vi.fn(), { factory, handshakeMs: 50, retryMs: 10 })
    manager.start()
    expect(factory).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(50)
    expect(sockets[0].closed).toBe(1)
    vi.advanceTimersByTime(10)
    expect(factory).toHaveBeenCalledTimes(2)
    manager.stop()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('backs off connection failures and never reconnects after explicit stop', () => {
    vi.useFakeTimers()
    const sockets: Socket[] = []
    const factory = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket })
    const manager = createEventSocket('ws://unused', vi.fn(), { factory, retryMs: 10, maxRetryMs: 20 })
    manager.start()
    sockets[0].dispatchEvent(new Event('error'))
    vi.advanceTimersByTime(10)
    sockets[1].dispatchEvent(new Event('close'))
    vi.advanceTimersByTime(19)
    expect(factory).toHaveBeenCalledTimes(2)
    vi.advanceTimersByTime(1)
    expect(factory).toHaveBeenCalledTimes(3)
    manager.stop()
    sockets[2].dispatchEvent(new Event('close'))
    vi.advanceTimersByTime(60_000)
    expect(factory).toHaveBeenCalledTimes(3)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('ignores stale socket messages and prevents duplicate starts', () => {
    vi.useFakeTimers()
    const sockets: Socket[] = []
    const publish = vi.fn()
    const factory = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket })
    const manager = createEventSocket('ws://unused', publish, { factory, retryMs: 10 })
    manager.start()
    manager.start()
    sockets[0].dispatchEvent(new Event('open'))
    sockets[0].dispatchEvent(new MessageEvent('message', { data: 'valid' }))
    expect(publish).toHaveBeenCalledWith('valid')
    sockets[0].dispatchEvent(new Event('close'))
    vi.advanceTimersByTime(10)
    sockets[0].dispatchEvent(new MessageEvent('message', { data: 'stale' }))
    expect(publish).toHaveBeenCalledTimes(1)
    expect(factory).toHaveBeenCalledTimes(2)
    manager.stop()
  })

  it('retries constructor failures without throwing into the polling loop', () => {
    vi.useFakeTimers()
    const factory = vi.fn(() => { throw new Error('private-error') })
    const manager = createEventSocket('ws://unused', vi.fn(), { factory, retryMs: 10 })
    expect(() => manager.start()).not.toThrow()
    vi.advanceTimersByTime(10)
    expect(factory).toHaveBeenCalledTimes(2)
    manager.stop()
  })

  it('resets retry delay after opening and isolates message callback errors', () => {
    vi.useFakeTimers()
    const sockets: Socket[] = []
    const factory = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket })
    const manager = createEventSocket('ws://unused', () => { throw new Error('publish-failed') },
      { factory, retryMs: 10, maxRetryMs: 40 })
    manager.start()
    sockets[0].dispatchEvent(new Event('error'))
    vi.advanceTimersByTime(10)
    sockets[1].dispatchEvent(new Event('error'))
    vi.advanceTimersByTime(20)
    sockets[2].dispatchEvent(new Event('open'))
    expect(() => sockets[2].dispatchEvent(new MessageEvent('message', { data: 'event' }))).not.toThrow()
    sockets[2].dispatchEvent(new Event('close'))
    vi.advanceTimersByTime(10)
    expect(factory).toHaveBeenCalledTimes(4)
    manager.stop()
    expect(vi.getTimerCount()).toBe(0)
  })
})
