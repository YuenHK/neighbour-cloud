import { type EdgeEvent, isEdgeEvent } from './edge-hub-client.js'

// Same-process, bounded transport/audit bookkeeping. No receiver ACK or crash durability.
export function createEventDispatcher(send: (event: EdgeEvent) => void,
  audit?: (id: string) => void, capacity = 10_000) {
  if (!Number.isSafeInteger(capacity) || capacity < 1 || capacity > 10_000)
    throw new Error('Invalid dispatch capacity')
  const recorded = new Map<string, boolean>()
  let transportDispatches = 0
  return {
    dispatch(event: EdgeEvent): 'already-recorded' | 'dispatch-recorded' {
      if (!isEdgeEvent(event))
        throw new Error('Invalid dispatch event')
      if (recorded.get(event.id) === true)
        return 'already-recorded'
      if (!recorded.has(event.id)) {
        if (recorded.size >= capacity) {
          const completed = [...recorded].find(([, logged]) => logged)
          if (!completed)
            throw new Error('Dispatch audit capacity exhausted')
          recorded.delete(completed[0])
        }
        try { send(event) }
        catch { throw new Error('AIRI transport unavailable; dispatch not recorded') }
        // The send call returned, not a remote ACK. Remember it BEFORE a fallible log write.
        recorded.set(event.id, false)
        transportDispatches++
      }
      try { audit?.(event.id) }
      catch { throw new Error('Bridge audit pending; transport dispatch not repeated') }
      recorded.set(event.id, true)
      return 'dispatch-recorded'
    },
    status() {
      return { tracked_ids: recorded.size, pending_audit: [...recorded.values()].filter(value => !value).length,
        transport_dispatches: transportDispatches, delivery_acknowledged: false }
    },
  }
}
