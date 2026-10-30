import { afterEach, describe, expect, it, vi } from 'vitest'
import { VoiceTurn, voiceWav } from '../../airi_overlay/voice-turn.js'
import { orderedAudio } from '../../airi_overlay/ordered-audio.js'

afterEach(() => vi.useRealTimers())
describe('complete voice turns', () => {
  it('releases queued blobs on reset even if the older ASR request is still pending', async () => {
    let finish!: (text: string) => void
    const turn = new VoiceTurn(() => new Promise(resolve => { finish = resolve }), vi.fn(async () => {}))
    turn.ready(new Float32Array(1))
    await Promise.resolve()
    turn.ready(new Float32Array(16000))
    const buffers = Reflect.get(turn, 'buffers') as Set<{ audio?: Blob }>
    const queued = [...buffers]
    expect(queued).toHaveLength(1)
    expect(queued[0].audio).toBeInstanceOf(Blob)
    turn.reset()
    expect(buffers.size).toBe(0)
    expect(queued[0].audio).toBeUndefined()
    for (let i = 0; i < 20; i++) turn.ready(new Float32Array(1))
    expect(Reflect.get(turn, 'retainedWork')).toBe(2)
    expect(buffers.size).toBe(0)
    finish('過期')
    await Promise.resolve()
  })
  it('drops partial transcripts around a failed segment then accepts a fresh turn', async () => {
    vi.useFakeTimers()
    const transcribe = vi.fn().mockResolvedValueOnce('不要')
      .mockRejectedValueOnce(new Error('private failure'))
      .mockResolvedValueOnce('新一輪')
    const send = vi.fn(async () => {})
    const turn = new VoiceTurn(transcribe, send)
    turn.ready(new Float32Array(1)); turn.ready(new Float32Array(1))
    await vi.advanceTimersByTimeAsync(600)
    expect(send).not.toHaveBeenCalled()
    turn.start(); turn.end(); turn.ready(new Float32Array(1))
    await vi.advanceTimersByTimeAsync(600)
    expect(send).toHaveBeenCalledExactlyOnceWith('新一輪')
  })
  it('bounds queued audio and ignores the late result of a discarded turn', async () => {
    vi.useFakeTimers()
    let finish!: (text: string) => void
    const transcribe = vi.fn(() => new Promise<string>(resolve => { finish = resolve }))
    const send = vi.fn(async () => {})
    const turn = new VoiceTurn(transcribe, send)
    turn.ready(new Float32Array(1))
    await Promise.resolve()
    turn.ready(new Float32Array(1)); turn.ready(new Float32Array(1))
    finish('過期')
    await vi.advanceTimersByTimeAsync(600)
    expect(transcribe).toHaveBeenCalledTimes(1)
    expect(send).not.toHaveBeenCalled()
  })
  it.each([new Float32Array(), new Float32Array([NaN]), new Float32Array([Infinity]),
    new Float32Array(45 * 16000 + 1)])('rejects invalid or excessive samples before ASR', async (samples) => {
    const transcribe = vi.fn(async () => 'never')
    const turn = new VoiceTurn(transcribe, vi.fn(async () => {}))
    turn.ready(samples)
    await Promise.resolve()
    expect(transcribe).not.toHaveBeenCalled()
  })
  it('overlaps merge waiting with ASR instead of adding another 500ms', async () => {
    vi.useFakeTimers()
    let finish!: (text: string) => void
    const send = vi.fn(async () => {})
    const turn = new VoiceTurn(() => new Promise(resolve => { finish = resolve }), send)
    turn.start(); turn.end(); turn.ready(new Float32Array(100))
    await vi.advanceTimersByTimeAsync(1500)
    finish('辨識完成')
    await vi.advanceTimersByTimeAsync(1)
    expect(send).toHaveBeenCalledExactlyOnceWith('辨識完成')
  })
  it('serializes whole VAD operations and owns queued samples', async () => {
    const observed: number[] = []
    let finish!: () => void
    const queue = orderedAudio(async (samples) => {
      if (!observed.length) await new Promise<void>(resolve => { finish = resolve })
      observed.push(samples[0])
    }, error => { throw error })
    const samples = new Float32Array([1])
    queue.push(samples); await Promise.resolve()
    samples[0] = 2; queue.push(samples); samples[0] = 3
    expect(observed).toEqual([])
    finish()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(observed).toEqual([1, 2])
  })
  it('preserves first and last samples with a correct 16k mono WAV header', async () => {
    const blob = voiceWav(new Float32Array([0.5, -1, 1]))
    const data = new DataView(await blob.arrayBuffer())
    expect(data.getUint32(24, true)).toBe(16000)
    expect(data.getUint32(40, true)).toBe(6)
    expect(data.getInt16(44, true)).toBe(16384)
    expect(data.getInt16(48, true)).toBe(32767)
  })
  it('does not send an old ASR result while the speaker has resumed', async () => {
    vi.useFakeTimers()
    const send = vi.fn(async () => {})
    const turn = new VoiceTurn(vi.fn().mockResolvedValueOnce('你好').mockResolvedValueOnce('我係 Anson'), send)
    turn.start(); turn.end(); turn.ready(new Float32Array(100))
    await vi.advanceTimersByTimeAsync(100)
    turn.start()
    await vi.advanceTimersByTimeAsync(1000)
    expect(send).not.toHaveBeenCalled()
    turn.end(); turn.ready(new Float32Array(100))
    await vi.advanceTimersByTimeAsync(600)
    expect(send).toHaveBeenCalledExactlyOnceWith('你好 我係 Anson')
  })
  it('ignores late results after microphone shutdown', async () => {
    vi.useFakeTimers()
    let finish!: (text: string) => void
    const send = vi.fn(async () => {})
    const turn = new VoiceTurn(() => new Promise(resolve => { finish = resolve }), send)
    turn.start(); turn.end(); turn.ready(new Float32Array(10))
    await Promise.resolve()
    turn.reset(); finish('舊錄音')
    await vi.advanceTimersByTimeAsync(1000)
    expect(send).not.toHaveBeenCalled()
  })
  it('serializes ASR and preserves segment order', async () => {
    vi.useFakeTimers()
    const transcribe = vi.fn().mockResolvedValueOnce('第一').mockResolvedValueOnce('第二')
    const send = vi.fn(async () => {})
    const turn = new VoiceTurn(transcribe, send)
    turn.ready(new Float32Array(1)); turn.ready(new Float32Array(1))
    await vi.advanceTimersByTimeAsync(600)
    expect(send).toHaveBeenCalledExactlyOnceWith('第一 第二')
  })
})
