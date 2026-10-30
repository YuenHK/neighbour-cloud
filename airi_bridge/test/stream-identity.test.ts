import { describe, expect, it, vi } from 'vitest'
import { fetchEdgeEventPage, fetchEdgeEventStreamState } from '../src/edge-hub-client.js'

const id = 'a'.repeat(32)
const reply = (data: unknown) => new Response(JSON.stringify(data))
describe('stream-bound cursor primitives, not automatic durable replay', () => {
  it('fetches the persistent stream identity and rejects legacy or malformed states', async () => {
    expect(await fetchEdgeEventStreamState('http://127.0.0.1:8000', vi.fn().mockResolvedValue(reply({ stream_id: id, cursor: 5 }))))
      .toEqual({ stream_id: id, cursor: 5 })
    for (const data of [{ cursor: 5 }, { stream_id: 'bad', cursor: 5 }, { stream_id: id, cursor: -1 }])
      await expect(fetchEdgeEventStreamState('http://127.0.0.1:8000', vi.fn().mockResolvedValue(reply(data)))).rejects.toThrow('identity')
  })
  it('binds pages to the expected stream and never retries an unbound page on conflict', async () => {
    const fetcher = vi.fn().mockResolvedValue(reply({ stream_id: id, items: [], next_cursor: 5, has_more: false }))
    await fetchEdgeEventPage('http://127.0.0.1:8000', 5, fetcher, 100, id)
    expect(fetcher.mock.calls[0][0]).toContain(`stream_id=${id}`)
    const conflict = vi.fn().mockResolvedValue(new Response('', { status: 409 }))
    await expect(fetchEdgeEventPage('http://127.0.0.1:8000', 5, conflict, 100, id)).rejects.toThrow('409')
    expect(conflict).toHaveBeenCalledTimes(1)
    const wrong = vi.fn().mockResolvedValue(reply({ stream_id: 'b'.repeat(32), items: [], next_cursor: 5, has_more: false }))
    await expect(fetchEdgeEventPage('http://127.0.0.1:8000', 5, wrong, 100, id)).rejects.toThrow('Invalid')
  })
})
