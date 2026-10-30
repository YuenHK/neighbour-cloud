import { afterEach, describe, expect, it, vi } from 'vitest'
import { Client } from '@proj-airi/server-sdk'
import type { ClientConnector, WebSocketEvent } from '@proj-airi/server-sdk'
import { waitForAiriReady } from '../src/airi-ready.js'

afterEach(() => vi.useRealTimers())

class FakeClient {
  connectionStatus = 'idle'
  listeners = new Set<(context: { status: string }) => void>()
  connect = vi.fn(async (_options: unknown) => {
    this.change('reconnecting')
    throw new Error('raw failure with private details must not escape')
  })
  onConnectionStateChange(listener: (context: { status: string }) => void) {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  change(status: string) {
    this.connectionStatus = status
    for (const listener of this.listeners) listener({ status })
  }
}

describe('SDK-owned AIRI readiness', () => {
  it('keeps one subscription and one connect through initial rejection until ready', async () => {
    const client = new FakeClient(), controller = new AbortController(), waiting = vi.fn()
    const task = waitForAiriReady(client, controller.signal, waiting)
    await Promise.resolve()
    expect(client.listeners.size).toBe(1)
    client.change('reconnecting')
    expect(waiting).toHaveBeenCalledTimes(1)
    client.change('ready')
    expect(await task).toBe(true)
    expect(client.connect).toHaveBeenCalledTimes(1)
    expect(client.listeners.size).toBe(0)
  })

  it('stops on SDK terminal failure without reconnecting or leaking the rejection', async () => {
    const client = new FakeClient()
    const task = waitForAiriReady(client, new AbortController().signal)
    const rejected = expect(task).rejects.toThrow('AIRI connection stopped; check service, configuration or credentials')
    await Promise.resolve()
    client.change('failed')
    await rejected
    expect(client.connect).toHaveBeenCalledTimes(1)
    expect(client.listeners.size).toBe(0)
    client.change('ready')
  })

  it('aborts waiting and ignores a late SDK ready', async () => {
    const client = new FakeClient(), controller = new AbortController()
    const task = waitForAiriReady(client, controller.signal)
    controller.abort()
    expect(await task).toBe(false)
    client.change('ready')
    expect(client.listeners.size).toBe(0)
    expect(client.connect).toHaveBeenCalledTimes(1)
    const stopped = new AbortController()
    stopped.abort()
    const untouched = new FakeClient()
    expect(await waitForAiriReady(untouched, stopped.signal)).toBe(false)
    expect(untouched.connect).not.toHaveBeenCalled()
  })

  it('handles already-ready and already-terminal clients without new transport calls', async () => {
    const client = new FakeClient(), signal = new AbortController().signal
    client.change('ready')
    expect(await waitForAiriReady(client, signal)).toBe(true)
    client.change('closed')
    await expect(waitForAiriReady(client, signal)).rejects.toThrow('connection stopped')
    expect(client.connect).not.toHaveBeenCalled()
  })

  it('uses actual SDK reconnect after a synthetic connector refusal, with no sockets', async () => {
    vi.useFakeTimers()
    const connect = vi.fn(() => { throw new Error('synthetic service unavailable') })
    const client = new Client({ name: 'isolated-ready-test', autoConnect: false,
      autoReconnect: true, connector: { connect } })
    const controller = new AbortController(), waiting = vi.fn()
    const task = waitForAiriReady(client, controller.signal, waiting)
    await vi.advanceTimersByTimeAsync(0)
    expect(client.connectionStatus).toBe('reconnecting')
    expect(waiting).toHaveBeenCalledTimes(1)
    expect(connect).toHaveBeenCalledTimes(1)
    controller.abort()
    expect(await task).toBe(false)
    client.close()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(connect).toHaveBeenCalledTimes(1)
  })

  it('uses actual SDK terminal-auth classification; invalid token is never reattempted', async () => {
    vi.useFakeTimers()
    const connect = vi.fn(() => { throw new Error('invalid token') })
    const client = new Client({ name: 'isolated-auth-test', autoConnect: false,
      autoReconnect: true, connector: { connect } })
    const task = waitForAiriReady(client, new AbortController().signal)
    const rejection = expect(task).rejects.toThrow('connection stopped')
    await vi.advanceTimersByTimeAsync(0)
    await rejection
    client.close()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(connect).toHaveBeenCalledTimes(1)
  })

  it('reaches actual SDK ready after initial refusal and a synthetic announce handshake', async () => {
    vi.useFakeTimers()
    let attempts = 0
    const connector: ClientConnector<WebSocketEvent> = {
      connect(events) {
        attempts++
        if (attempts === 1) throw new Error('synthetic unavailable')
        return {
          send(message) {
            if (message.type === 'extension:module:announce') {
              const reply: WebSocketEvent = {
                type: 'extension:module:announced',
                data: { ...message.data },
                metadata: { source: { kind: 'plugin', plugin: { id: 'server' }, id: 'fixture' },
                  event: { id: 'fixture-announce' } },
              }
              queueMicrotask(() => events.message(reply))
            }
            return true
          },
          close() { events.close({ code: 1000, reason: 'fixture-close', wasClean: true }) },
        }
      },
    }
    const client = new Client({ name: 'isolated-recovered', autoConnect: false, autoReconnect: true,
      heartbeat: false, connector })
    const controller = new AbortController()
    try {
      const task = waitForAiriReady(client, controller.signal)
      await vi.advanceTimersByTimeAsync(60_000)
      expect(await task).toBe(true)
      expect(client.connectionStatus).toBe('ready')
      expect(attempts).toBe(2)
    }
    finally { controller.abort(); client.close() }
  })
})
