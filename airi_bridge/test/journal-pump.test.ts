import { afterEach, describe, expect, it, vi } from 'vitest'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { openCursorJournal } from '../src/cursor-journal.js'
import { runJournalPump } from '../src/journal-pump.js'
import { createEventDispatcher } from '../src/event-dispatcher.js'
import { EdgeHubHttpError } from '../src/edge-hub-client.js'

const id = 'a'.repeat(32)
const event = { id: 'one', type: 'temperature_drill' as const, zone: 'test', at_ms: 1, severity: 'notice' as const }
const roots: string[] = []
const directory = () => { const root = mkdtempSync(join(tmpdir(), 'zhiwei-journal-pump-')); roots.push(root); return root }
afterEach(() => {
  vi.useRealTimers()
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
})
const empty = (cursor: number) => ({ stream_id: id, items: [], next_cursor: cursor, has_more: false })

describe('opt-in journal-backed local transport pump', () => {
  it('saves first tail, commits a sent page, and resumes saved progress rather than a new tail', async () => {
    vi.useFakeTimers()
    const root = directory()
    let journal = openCursorJournal(root)
    try {
      for (const [remote, initial] of [[1, 1], [3, 2]]) {
        const stop = new AbortController(), publish = vi.fn()
        const page = vi.fn().mockResolvedValueOnce({ stream_id: id, items: [event], next_cursor: initial + 1, has_more: false })
          .mockImplementation(async (cursor) => { stop.abort(); return empty(cursor) })
        const task = runJournalPump({ signal: stop.signal, journal, fetchState: async () => ({ stream_id: id, cursor: remote }),
          fetchPage: page, publish, pollMs: 50 })
        await vi.advanceTimersByTimeAsync(50)
        await task
        expect(page.mock.calls[0]).toEqual([initial, id])
        expect(publish).toHaveBeenCalledExactlyOnceWith(event)
        expect(journal.state()!.cursor).toBe(initial + 1)
        journal.close()
        journal = openCursorJournal(root)
      }
    }
    finally { journal.close() }
  })

  it('does not commit an audit-failed page and uses same-process dispatcher retry without resending transport', async () => {
    vi.useFakeTimers()
    const journal = openCursorJournal(directory()), stop = new AbortController()
    journal.append({ stream_id: id, cursor: 1 })
    const next = { ...event, id: 'two' }, send = vi.fn()
    let failed = false
    const dispatcher = createEventDispatcher(send, (identity) => {
      if (identity === 'two' && !failed) { failed = true; throw Error('synthetic audit failure') }
    })
    const page = vi.fn().mockResolvedValueOnce({ stream_id: id, items: [event, next], next_cursor: 3, has_more: false })
      .mockResolvedValueOnce({ stream_id: id, items: [event, next], next_cursor: 3, has_more: false })
      .mockImplementation(async (cursor) => { stop.abort(); return empty(cursor) })
    try {
      const task = runJournalPump({ signal: stop.signal, journal, fetchState: async () => ({ stream_id: id, cursor: 3 }),
        fetchPage: page, publish: e => { dispatcher.dispatch(e) }, pollMs: 50, retryMs: 50 })
      await vi.advanceTimersByTimeAsync(0)
      expect(journal.state()!.cursor).toBe(1)
      await vi.advanceTimersByTimeAsync(100)
      await task
      expect(page.mock.calls.map(call => call[0])).toEqual([1, 1, 3])
      expect(send).toHaveBeenCalledTimes(2)
      expect(journal.state()!.cursor).toBe(3)
    }
    finally { stop.abort(); journal.close() }
  })

  it.each(['identity', 'ahead'])('halts on saved %s conflict before reading any page', async (failure) => {
    const journal = openCursorJournal(directory())
    journal.append({ stream_id: id, cursor: 10 })
    const page = vi.fn(), publish = vi.fn()
    try {
      await expect(runJournalPump({ signal: new AbortController().signal, journal,
        fetchState: async () => ({ stream_id: failure === 'identity' ? 'b'.repeat(32) : id, cursor: 9 }),
        fetchPage: page, publish })).rejects.toThrow('explicit recovery')
      expect(page).not.toHaveBeenCalled()
      expect(publish).not.toHaveBeenCalled()
      expect(journal.state()!.cursor).toBe(10)
    }
    finally { journal.close() }
  })

  it.each(['409', 'wrong-response-id'])('halts on bound page %s without resampling tail or dispatch', async (failure) => {
    const journal = openCursorJournal(directory())
    journal.append({ stream_id: id, cursor: 1 })
    const fetchState = vi.fn().mockResolvedValue({ stream_id: id, cursor: 1 }), publish = vi.fn()
    const page = failure === '409' ? vi.fn().mockRejectedValue(new EdgeHubHttpError(409))
      : vi.fn().mockResolvedValue({ ...empty(2), stream_id: 'b'.repeat(32), items: [event] })
    try {
      await expect(runJournalPump({ signal: new AbortController().signal, journal, fetchState,
        fetchPage: page, publish })).rejects.toThrow('explicit recovery')
      expect(fetchState).toHaveBeenCalledTimes(1)
      expect(page).toHaveBeenCalledTimes(1)
      expect(publish).not.toHaveBeenCalled()
      expect(journal.state()!.cursor).toBe(1)
    }
    finally { journal.close() }
  })

  it('halts after a failed commit; a transport return is not proof of remote delivery', async () => {
    const journal = openCursorJournal(directory())
    journal.append({ stream_id: id, cursor: 1 })
    const append = journal.append
    journal.append = next => { if (next.cursor === 2) throw Error('synthetic disk failure'); return append(next) }
    const page = vi.fn().mockResolvedValue({ stream_id: id, items: [event], next_cursor: 2, has_more: false })
    const publish = vi.fn()
    try {
      await expect(runJournalPump({ signal: new AbortController().signal, journal,
        fetchState: async () => ({ stream_id: id, cursor: 1 }), fetchPage: page, publish }))
        .rejects.toThrow('commit failed')
      expect(publish).toHaveBeenCalledTimes(1)
      expect(page).toHaveBeenCalledTimes(1)
      expect(journal.state()!.cursor).toBe(1)
    }
    finally { journal.close() }
  })

  it('does not initialize a journal from a late result after stop', async () => {
    const journal = openCursorJournal(directory()), stop = new AbortController(), page = vi.fn()
    try {
      await runJournalPump({ signal: stop.signal, journal,
        fetchState: async () => { stop.abort(); return { stream_id: id, cursor: 50 } },
        fetchPage: page, publish: vi.fn() })
      expect(journal.state()).toBeUndefined()
      expect(page).not.toHaveBeenCalled()
    }
    finally { journal.close() }
  })

  it('keeps journal mode opt-in and page-only in the actual entrypoint without starting it', () => {
    const source = readFileSync(new URL('../src/index.ts', import.meta.url), 'utf8')
    expect(source).toContain('process.env.AIRI_BRIDGE_CURSOR_DIR')
    const branch = source.split('if (ready && journal)')[1].split('else if (ready)')[0]
    expect(branch).toContain('runJournalPump')
    expect(branch).toContain('fetchEdgeEventStreamState')
    expect(branch).not.toContain('edgeSocket.start')
    expect(readFileSync(new URL('../../scripts/run_airi_bridge.ps1', import.meta.url), 'utf8'))
      .not.toContain('AIRI_BRIDGE_CURSOR_DIR')
  })
})
