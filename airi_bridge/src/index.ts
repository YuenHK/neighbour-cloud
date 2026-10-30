import { appendFileSync } from 'node:fs'
import { createAiriClient, publishAiriInput } from './client.js'
import { type EdgeEvent, edgeEventWebSocketUrl, fetchEdgeEventCursor, fetchEdgeEventPage, fetchEdgeEventStreamState, isEdgeEvent } from './edge-hub-client.js'
import { createEventDispatcher } from './event-dispatcher.js'
import { createEventSocket } from './event-socket.js'
import { runCursorPump } from './cursor-pump.js'
import { waitForAiriReady } from './airi-ready.js'
import { openCursorJournal } from './cursor-journal.js'
import { runJournalPump } from './journal-pump.js'
import { eventToAiriText } from './event-template.js'
import { createDeliveryReceipts } from './delivery-receipts.js'

const edgeHubUrl = process.env.EDGE_HUB_URL || 'http://127.0.0.1:8000'
const pollIntervalMs = Number(process.env.EDGE_HUB_POLL_MS || 500)
const eventLog = process.env.AIRI_BRIDGE_EVENT_LOG
if (eventLog)
  appendFileSync(eventLog, '')
const client = createAiriClient(process.env.AIRI_WS_URL)
const receipts = createDeliveryReceipts()
const deliveryLog = process.env.AIRI_BRIDGE_DELIVERY_LOG
const stopObserving = client.onEvent('output:gen-ai:chat:complete', (event) => {
  const id = receipts.observe(event)
  if (!id) return
  try {
    if (deliveryLog) appendFileSync(deliveryLog, `${id}\n`)
    console.info(`AIRI receiver-reported chat completion observed (not authenticated/durable ACK): ${id}`)
  }
  catch { console.error('AIRI receiver completion observed but receipt audit write failed') }
})
const cursorDirectory = process.env.AIRI_BRIDGE_CURSOR_DIR
let journal: ReturnType<typeof openCursorJournal> | undefined

const dispatcher = createEventDispatcher(event => {
  const text = eventToAiriText(event)
  const token = receipts.prepare(event.id, text)
  try { publishAiriInput(client, text, token) }
  catch (error) { receipts.cancel(token); throw error }
},
  eventLog ? id => appendFileSync(eventLog, `${id}\n`) : undefined)
const publishEvent = (event: EdgeEvent) => {
  if (dispatcher.dispatch(event) === 'dispatch-recorded')
    console.info(`Edge Hub transport dispatch recorded (not delivery ACK): ${event.id}`)
}
const edgeSocket = createEventSocket(edgeEventWebSocketUrl(edgeHubUrl), (text) => {
  try {
    if (text.length > 1024 * 1024)
      throw new Error('oversized notification')
    const event: unknown = JSON.parse(text)
    if (!isEdgeEvent(event))
      throw new Error('invalid notification')
    publishEvent(event)
  }
  catch {
    console.error('Edge Hub notification rejected or publish failed; cursor polling will retry')
  }
})
const shutdown = new AbortController()
const stop = () => { shutdown.abort(); edgeSocket.stop() }
process.on('SIGINT', stop)
process.on('SIGTERM', stop)

try {
  if (cursorDirectory)
    journal = openCursorJournal(cursorDirectory)
  const ready = await waitForAiriReady(client, shutdown.signal,
    () => console.info('AIRI transport reconnecting; waiting for SDK readiness, not dispatching events'))
  if (ready && journal) {
    await runJournalPump({
      signal: shutdown.signal, journal, pollMs: pollIntervalMs, publish: publishEvent,
      fetchState: () => fetchEdgeEventStreamState(edgeHubUrl),
      fetchPage: (cursor, streamId) => fetchEdgeEventPage(edgeHubUrl, cursor, fetch, 100, streamId),
      onReady: () => console.info('AIRI local cursor journal ready; page-only transport, not receiver ACK'),
      onError: () => console.error('Unable to read or dispatch bound event pages; cursor retained for retry'),
    })
  }
  else if (ready) await runCursorPump({
    signal: shutdown.signal, pollMs: pollIntervalMs,
    fetchCursor: () => fetchEdgeEventCursor(edgeHubUrl),
    fetchPage: cursor => fetchEdgeEventPage(edgeHubUrl, cursor),
    publish: publishEvent,
    onReady: () => {
      edgeSocket.start()
      console.info('AIRI bridge cursor polling ready; notifications are optional')
    },
    onError: phase => console.error(phase === 'initial-cursor'
      ? 'Unable to initialize Edge Hub cursor; waiting with bounded retry backoff'
      : 'Unable to poll or publish Edge Hub events; cursor retained for retry'),
  })
}
finally {
  process.off('SIGINT', stop)
  process.off('SIGTERM', stop)
  stopObserving()
  try { client.close() }
  finally {
    try { edgeSocket.stop() }
    finally { journal?.close() }
  }
}
