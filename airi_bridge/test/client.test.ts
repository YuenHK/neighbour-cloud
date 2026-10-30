import { describe, expect, it, vi } from 'vitest'
import { publishAiriInput } from '../src/client.js'

describe('publishAiriInput', () => {
  it('sends only input:text with the approved template', () => {
    const sendOrThrow = vi.fn()
    publishAiriInput({ sendOrThrow }, '測試訊息')
    expect(sendOrThrow).toHaveBeenCalledWith({
      type: 'input:text',
      data: { text: '測試訊息', textRaw: '測試訊息' },
    })
  })
})
