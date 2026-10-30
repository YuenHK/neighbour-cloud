import { describe, expect, it } from 'vitest'
import { createDeliveryReceipts } from '../src/delivery-receipts.js'

function completion(token: string, text = '固定測試事件') {
  return { type: 'output:gen-ai:chat:complete', data: {
    text, textRaw: token, 'stage-web': true,
    message: { role: 'assistant', content: '已收到模擬事件。' },
  } }
}

describe('receiver-reported event completion', () => {
  it('correlates exact completion once without treating it as durable ACK', () => {
    const receipts = createDeliveryReceipts()
    const token = receipts.prepare('event-1', '固定測試事件')
    expect(receipts.observe(completion(token))).toBe('event-1')
    expect(receipts.observe(completion(token))).toBeUndefined()
    expect(receipts.status()).toEqual({ pending: 0, receiver_completions_observed: 1,
      authenticated_delivery: false, durable_delivery: false, speech_playback_verified: false })
  })
  it.each(['input:text', 'output:gen-ai:chat:message', 'error'])('rejects %s and transport echoes', (type) => {
    const receipts = createDeliveryReceipts()
    const token = receipts.prepare('event-1', '固定測試事件')
    const event = completion(token)
    event.type = type
    expect(receipts.observe(event)).toBeUndefined()
    expect(receipts.status().pending).toBe(1)
  })
  it('rejects mismatched token/text, empty output and non-receiver flags', () => {
    const receipts = createDeliveryReceipts()
    const token = receipts.prepare('event-1', '固定測試事件')
    expect(receipts.observe(completion('unrelated'))).toBeUndefined()
    expect(receipts.observe(completion(token, '其他事件'))).toBeUndefined()
    const empty = completion(token)
    empty.data.message.content = ''
    expect(receipts.observe(empty)).toBeUndefined()
    const noReceiver = completion(token)
    noReceiver.data['stage-web'] = false
    expect(receipts.observe(noReceiver)).toBeUndefined()
    expect(receipts.status().pending).toBe(1)
  })
  it('bounds pending attempts without silently dropping unconfirmed events', () => {
    const receipts = createDeliveryReceipts(1)
    const token = receipts.prepare('event-1', '固定測試事件')
    expect(() => receipts.prepare('event-2', 'text')).toThrow(/capacity/)
    receipts.cancel(token)
    expect(receipts.observe(completion(token))).toBeUndefined()
    expect(() => receipts.prepare('event-2', 'text')).not.toThrow()
  })
  it.each([null, {}, { type: 'output:gen-ai:chat:complete', data: null }])('ignores malformed inputs', (event) => {
    expect(createDeliveryReceipts().observe(event)).toBeUndefined()
  })
})
