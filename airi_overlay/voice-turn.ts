// Keep the VAD's complete, pre-padded 16 kHz audio; never start a second recorder late.
export function voiceWav(samples: Float32Array): Blob {
  const bytes = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(bytes)
  const label = (offset: number, text: string) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)))
  label(0, 'RIFF')
  view.setUint32(4, bytes.byteLength - 8, true)
  label(8, 'WAVE')
  label(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, 16000, true)
  view.setUint32(28, 32000, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  label(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  samples.forEach((v, i) => view.setInt16(44 + i * 2, Math.round(Math.max(-1, Math.min(1, v)) * 32767), true))
  return new Blob([bytes], { type: 'audio/wav' })
}

export class VoiceTurn {
  private epoch = 0
  private active = false
  private pending = 0
  private retainedWork = 0 // Includes cancelled jobs until their chain callbacks drain.
  private queuedSamples = 0
  private buffers = new Set<{ audio?: Blob }>()
  private endedAt = 0
  private parts: string[] = []
  private timer?: ReturnType<typeof setTimeout>
  private chain: Promise<void> = Promise.resolve()
  constructor(private transcribe: (audio: Blob) => Promise<string | undefined>, private send: (text: string) => Promise<void>, private delay = 500, private minimum = 1) {}
  start() {
    this.active = true
    this.clearTimer()
  }

  end() {
    this.active = false
    this.endedAt = Date.now() // merge delay overlaps ASR, not added afterwards.
  }

  reset() {
    for (const item of this.buffers) item.audio = undefined
    this.buffers.clear()
    this.epoch++
    this.active = false
    this.pending = 0
    this.queuedSamples = 0
    this.endedAt = 0
    this.parts = []
    this.clearTimer()
  }

  private clearTimer() {
    if (this.timer)
      clearTimeout(this.timer)
    this.timer = undefined
  }

  ready(samples: Float32Array) {
    // Bound retained audio while a slow provider is busy. Drop the whole turn,
    // not just a word/segment that could change the user's intended meaning.
    if (!samples.length || samples.length > 45 * 16000 || this.retainedWork >= 2
      || this.queuedSamples + samples.length > 45 * 16000
      || !samples.every(Number.isFinite)) {
      this.reset()
      console.warn('[voice-turn] Invalid or excessive queued audio; turn discarded without retry')
      return
    }
    if (!this.endedAt)
      this.endedAt = Date.now()
    const epoch = this.epoch
    const sampleCount = samples.length
    const item: { audio?: Blob } = { audio: voiceWav(samples) }
    this.buffers.add(item)
    this.pending++
    this.retainedWork++
    this.queuedSamples += sampleCount
    this.clearTimer()
    this.chain = this.chain.then(async () => {
      if (epoch !== this.epoch) {
        this.retainedWork--
        return
      }
      const audio = item.audio
      item.audio = undefined
      this.buffers.delete(item)
      if (!audio) {
        this.retainedWork--
        return
      }
      try {
        const text = await this.transcribe(audio)
        if (epoch === this.epoch && text?.trim())
          this.parts.push(text.trim())
      }
      catch {
        if (epoch === this.epoch)
          this.reset()
        console.error('[voice-turn] Transcription failed; whole turn discarded without retry')
      }
      finally {
        this.retainedWork--
        if (epoch === this.epoch) {
          this.pending--
          this.queuedSamples -= sampleCount
          this.schedule()
        }
      }
    })
  }

  private schedule() {
    if (this.active || this.pending || !this.parts.length)
      return
    this.clearTimer()
    const epoch = this.epoch
    this.timer = setTimeout(() => {
      if (epoch !== this.epoch || this.active || this.pending)
        return
      const text = this.parts.join(' ').replace(/\s+/g, ' ').trim()
      this.parts = []
      if ([...text.replace(/[\s\p{P}\p{S}]/gu, '')].length >= this.minimum)
        void this.send(text).catch(error => console.error('[voice-turn] Send failed', error))
    }, Math.max(0, this.delay - (Date.now() - this.endedAt)))
  }
}
