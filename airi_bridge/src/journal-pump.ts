import type { openCursorJournal, StreamPosition } from './cursor-journal.js'
import type { EdgeEvent, EdgeEventPage } from './edge-hub-client.js'
import { EdgeHubHttpError, EdgeHubStreamError } from './edge-hub-client.js'
import { CursorPumpRecoveryError, runCursorPump } from './cursor-pump.js'

interface Options {
  signal: AbortSignal
  journal: ReturnType<typeof openCursorJournal>
  fetchState: () => Promise<StreamPosition>
  fetchPage: (cursor: number, streamId: string) => Promise<EdgeEventPage>
  publish: (event: EdgeEvent) => void
  onReady?: () => void
  onError?: (phase: 'initial-cursor' | 'poll') => void
  pollMs?: number
  retryMs?: number
}

// Page-only path. Notifications must never dispatch around this binding/commit.
export async function runJournalPump(options: Options): Promise<void> {
  let streamId: string | undefined
  await runCursorPump({
    signal: options.signal, pollMs: options.pollMs, retryMs: options.retryMs,
    publish: options.publish, onReady: options.onReady, onError: options.onError,
    fetchCursor: async () => {
      const remote = await options.fetchState()
      if (options.signal.aborted) return remote.cursor
      try {
        const resumed = options.journal.resume(remote)
        streamId = remote.stream_id
        return resumed.cursor
      }
      catch { throw new CursorPumpRecoveryError('Cursor journal binding failed; explicit recovery required') }
    },
    fetchPage: async (cursor) => {
      try {
        const page = await options.fetchPage(cursor, streamId!)
        if (page.stream_id !== streamId)
          throw new EdgeHubStreamError('Bound event stream changed')
        return page
      }
      catch (error) {
        if (error instanceof EdgeHubStreamError || (error instanceof EdgeHubHttpError && error.status === 409))
          throw new CursorPumpRecoveryError('Bound event stream requires explicit recovery')
        throw error
      }
    },
    commitCursor: cursor => {
      try { options.journal.append({ stream_id: streamId!, cursor }) }
      catch { throw new CursorPumpRecoveryError('Cursor journal commit failed; stop and recover explicitly') }
    },
  })
}
