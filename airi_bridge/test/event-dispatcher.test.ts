import { describe, expect, it, vi } from 'vitest'
import { createEventDispatcher } from '../src/event-dispatcher.js'

const event = { id: 'evt-1', type: 'robot_fault' as const, zone: 'simulation', at_ms: 1, severity: 'notice' as const }

describe('local transport dispatch, not remote acknowledgement', () => {
  it('deduplicates successful local dispatch without claiming delivery', () => {
    const send = vi.fn()
    const audit = vi.fn()
    const dispatcher = createEventDispatcher(send, audit)
    expect(dispatcher.dispatch(event)).toBe('dispatch-recorded')
    expect(dispatcher.dispatch(event)).toBe('already-recorded')
    expect(send).toHaveBeenCalledTimes(1)
    expect(audit).toHaveBeenCalledWith('evt-1')
    expect(dispatcher.status().delivery_acknowledged).toBe(false)
  })

  it('retries only the audit after a post-send log failure', () => {
    const send = vi.fn()
    const audit = vi.fn().mockImplementationOnce(() => { throw new Error('disk-full-secret') })
    const dispatcher = createEventDispatcher(send, audit)
    expect(() => dispatcher.dispatch(event)).toThrow('audit pending')
    expect(dispatcher.status().pending_audit).toBe(1)
    expect(dispatcher.dispatch(event)).toBe('dispatch-recorded')
    expect(send).toHaveBeenCalledTimes(1)
    expect(audit).toHaveBeenCalledTimes(2)
    expect(dispatcher.status().pending_audit).toBe(0)
  })

  it('does not mark a thrown transport send as completed', () => {
    const send = vi.fn().mockImplementationOnce(() => { throw new Error('not-connected-secret') })
    const audit = vi.fn()
    const dispatcher = createEventDispatcher(send, audit)
    expect(() => dispatcher.dispatch(event)).toThrow('transport unavailable')
    expect(audit).not.toHaveBeenCalled()
    expect(dispatcher.dispatch(event)).toBe('dispatch-recorded')
    expect(send).toHaveBeenCalledTimes(2)
  })

  it('never evicts pending audit entries to accept another send', () => {
    const send = vi.fn()
    const audit = vi.fn(() => { throw new Error('unavailable') })
    const dispatcher = createEventDispatcher(send, audit, 1)
    expect(() => dispatcher.dispatch(event)).toThrow('audit pending')
    expect(() => dispatcher.dispatch({ ...event, id: 'evt-2' })).toThrow('capacity')
    expect(send).toHaveBeenCalledTimes(1)
  })

  it('evicts only completed entries within its bounded same-process window', () => {
    const send = vi.fn()
    const dispatcher = createEventDispatcher(send, undefined, 1)
    dispatcher.dispatch(event)
    dispatcher.dispatch({ ...event, id: 'evt-2' })
    expect(dispatcher.status().tracked_ids).toBe(1)
    expect(dispatcher.status().transport_dispatches).toBe(2)
  })
})
