import type { EdgeEvent, EdgeEventPage } from './edge-hub-client.js'

interface Options {
  signal: AbortSignal
  fetchCursor: () => Promise<number>
  fetchPage: (cursor: number) => Promise<EdgeEventPage>
  publish: (event: EdgeEvent) => void
  commitCursor?: (cursor: number) => void
  onReady?: () => void
  onError?: (phase: 'initial-cursor' | 'poll') => void
  pollMs?: number
  retryMs?: number
  maxRetryMs?: number
}

export class CursorPumpRecoveryError extends Error {}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve(); return }
    const finish = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = setTimeout(finish, ms)
    signal.addEventListener('abort', finish, { once: true })
  })
}

// One awaited loop: no overlapping fetches or automatic rewind to a fresh tail.
// Cursor bookkeeping is process-local unless a commit hook is provided;
// even a persisted local transport cursor is not a durable outbox/delivery ACK.
export async function runCursorPump(options: Options): Promise<void> {
  const { signal } = options
  const pollMs = options.pollMs ?? 500
  const retryMs = options.retryMs ?? 1000
  const maxRetryMs = options.maxRetryMs ?? 30_000
  if (![pollMs, retryMs, maxRetryMs].every(value => Number.isSafeInteger(value) && value >= 50 && value <= 60_000)
    || retryMs > maxRetryMs)
    throw new Error('Invalid cursor pump timing settings')
  let cursor: number | undefined
  let delay = retryMs
  let failedPhase: 'initial-cursor' | 'poll' | undefined
  while (!signal.aborted) {
    let wait = pollMs
    try {
      if (cursor === undefined) {
        const tail = await options.fetchCursor()
        if (signal.aborted)
          return
        if (!Number.isSafeInteger(tail) || tail < 0)
          throw new Error('Invalid initial cursor')
        options.commitCursor?.(tail)
        options.onReady?.()
        cursor = tail
      }
      for (let pages = 0; pages < 10 && !signal.aborted; pages++) {
        const page = await options.fetchPage(cursor)
        if (signal.aborted)
          return
        // Defense against a faulty provider: retain the last cursor on failure.
        if (!Number.isSafeInteger(page.next_cursor) || page.next_cursor < cursor
          || ((page.items.length > 0 || page.has_more) && page.next_cursor <= cursor))
          throw new Error('Invalid page cursor')
        for (const event of page.items) {
          if (signal.aborted)
            return
          options.publish(event)
        }
        if (signal.aborted)
          return
        options.commitCursor?.(page.next_cursor)
        cursor = page.next_cursor
        if (!page.has_more)
          break
      }
      delay = retryMs
      failedPhase = undefined
    }
    catch (error) {
      if (signal.aborted)
        return
      if (error instanceof CursorPumpRecoveryError)
        throw error
      const phase = cursor === undefined ? 'initial-cursor' : 'poll'
      if (phase !== failedPhase) {
        options.onError?.(phase)
        failedPhase = phase
      }
      wait = delay
      delay = Math.min(delay * 2, maxRetryMs)
    }
    await pause(wait, signal)
  }
}
