import { randomUUID } from 'node:crypto'

// Receiver-reported chat completion, not authenticated/durable delivery or
// proof of speech playback. Never accept a transport echo as a completion.
export function createDeliveryReceipts(capacity = 1000) {
  if (!Number.isSafeInteger(capacity) || capacity < 1 || capacity > 1000)
    throw new Error('Invalid receipt capacity')
  const pending = new Map<string, { id: string, text: string }>()
  let observed = 0
  return {
    prepare(id: string, text: string) {
      if (pending.size >= capacity) throw new Error('Receiver receipt capacity exhausted')
      const token = `zhiwei-receipt:${randomUUID()}`
      pending.set(token, { id, text })
      return token
    },
    cancel(token: string) { pending.delete(token) },
    observe(event: unknown): string | undefined {
      if (!event || typeof event !== 'object') return
      const envelope = event as { type?: unknown, data?: unknown }
      if (envelope.type !== 'output:gen-ai:chat:complete'
        || !envelope.data || typeof envelope.data !== 'object') return
      const data = envelope.data as Record<string, unknown>
      if (typeof data.textRaw !== 'string') return
      const receipt = pending.get(data.textRaw)
      if (!receipt || data.text !== receipt.text
        || (data['stage-web'] !== true && data['stage-tamagotchi'] !== true)) return
      const message = data.message as { role?: unknown, content?: unknown } | undefined
      if (!message || message.role !== 'assistant' || typeof message.content !== 'string'
        || !message.content.trim() || message.content.length > 65536) return
      pending.delete(data.textRaw)
      observed++
      return receipt.id
    },
    status() {
      return { pending: pending.size, receiver_completions_observed: observed,
        authenticated_delivery: false, durable_delivery: false, speech_playback_verified: false }
    },
  }
}
