// Resident-only PCM playback. Every reset aborts network and stops scheduled nodes.
export class ResidentPcm {
  constructor({ fetcher = (...args) => globalThis.fetch(...args), endpoint = 'http://127.0.0.1:8765/v1/audio/resident-stream', context = /** @type {AudioContext | undefined} */ (undefined), started = () => {}, failed = () => {}, ended = () => {}, wait = /** @type {(ms: number) => Promise<void>} */ (ms => new Promise(resolve => setTimeout(resolve, ms))) } = {}) {
    this.fetcher = fetcher
    this.endpoint = endpoint
    this.context = context
    this.ownsContext = !context
    this.started = started
    this.failed = failed
    this.ended = ended
    this.wait = wait
    this.sealed = false
    this.sources = new Set()
    this.controller = new AbortController()
    this.chain = Promise.resolve()
    this.queued = 0
    this.finished = false
    this.next = 0
  }

  write(text) {
    // Model sentence streams also carry paragraph breaks and stripped markup.
    // They remain in the transcript, but are not synthesis requests.
    if (this.controller.signal.aborted || !text.trim())
      return
    if (++this.queued > 12) {
      this.cancel()
      this.failed()
      return
    }
    this.chain = this.chain.then(() => this.sentence(text)).catch(() => {
      if (!this.controller.signal.aborted) {
        this.cancel()
        this.failed()
      }
    }).finally(() => {
      this.queued--
      this.checkEnd()
    })
  }

  /** @param {string} text @param {number} attempt @returns {Promise<void>} */
  async sentence(text, attempt = 0) {
    if (this.controller.signal.aborted)
      return
    this.context ??= new (globalThis.AudioContext || globalThis.webkitAudioContext)({ sampleRate: 24000 })
    await this.context.resume()
    if (this.context.state !== 'running')
      throw new Error('audio_locked')
    const signal = AbortSignal.any([this.controller.signal, AbortSignal.timeout(35000)])
    const response = await this.fetcher(this.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      body: JSON.stringify({ model: 'azure-hiumaan-f0', voice: 'zh-HK-HiuMaanNeural', input: text, speed: 1 }),
    })
    if (!response.ok || !response.body)
      throw new Error('voice_unavailable')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let pending = ''
    let done = false
    let bytes = 0
    try {
      while (!done) {
        const result = await reader.read()
        if (result.done)
          break
        pending += decoder.decode(result.value, { stream: true })
        if (pending.length > 1000000)
          throw new Error('oversized_frame')
        let boundary
        while ((boundary = pending.indexOf('\n\n')) >= 0) {
          const frame = pending.slice(0, boundary)
          pending = pending.slice(boundary + 2)
          if (!frame.startsWith('data: '))
            throw new Error('invalid_frame')
          const data = JSON.parse(frame.slice(6))
          // The router emits busy only before acquiring a synthesis slot.
          // No provider was called and no audio was emitted: a bounded retry is safe.
          if (data.error === 'busy' && bytes === 0 && attempt < 2) {
            await reader.cancel().catch(() => {})
            await this.wait(500 * (attempt + 1))
            if (this.controller.signal.aborted)
              return
            return this.sentence(text, attempt + 1)
          }
          if (data.error)
            throw new Error('voice_unavailable')
          if (data.done === true) {
            done = true
            break
          }
          if (typeof data.audio !== 'string' || data.audio.length > 12000)
            throw new Error('invalid_pcm')
          const raw = atob(data.audio)
          bytes += raw.length
          if (!raw.length || raw.length % 2 || bytes > 5760000)
            throw new Error('invalid_pcm')
          while (this.next - this.context.currentTime > 3) {
            if (signal.aborted)
              throw new Error('cancelled')
            await new Promise(resolve => setTimeout(resolve, 25))
          }
          if (signal.aborted)
            throw new Error('cancelled')
          const buffer = this.context.createBuffer(1, raw.length / 2, 24000)
          const samples = buffer.getChannelData(0)
          for (let i = 0; i < samples.length; i++) {
            let value = raw.charCodeAt(i * 2) | raw.charCodeAt(i * 2 + 1) << 8
            if (value >= 32768)
              value -= 65536
            samples[i] = value / 32768
          }
          const node = this.context.createBufferSource()
          node.buffer = buffer
          node.connect(this.context.destination)
          globalThis.dispatchEvent?.(new CustomEvent('resident-pcm-node', { detail: { source: node, context: this.context } }))
          this.sources.add(node)
          node.onended = () => {
            this.sources.delete(node)
            node.disconnect()
            this.checkEnd()
          }
          const at = Math.max(this.context.currentTime + 0.06, this.next)
          this.next = at + buffer.duration
          node.start(at)
          if (!this.finished) {
            this.finished = true
            this.started()
          }
        }
      }
      if (!done || !bytes)
        throw new Error('incomplete_voice')
    }
    finally {
      await reader.cancel().catch(() => {})
      reader.releaseLock()
    }
  }

  cancel() {
    this.controller.abort()
    for (const node of this.sources) {
      try {
        node.stop()
      }
      catch {}
    }
    this.sources.clear()
    if (this.ownsContext)
      void this.context?.close().catch(() => {})
  }

  end() {
    this.sealed = true
    this.checkEnd()
  }

  checkEnd() {
    if (this.sealed && !this.queued && !this.sources.size && !this.controller.signal.aborted) {
      this.ended()
      this.cancel()
    }
  }
}

export class ResidentTiming {
  constructor(now = () => performance.now(), inputEndedAt = /** @type {number | undefined} */ (undefined), { fetcher = (...args) => globalThis.fetch(...args), endpoint = 'http://127.0.0.1:8000/api/v1/resident/timing' } = {}) {
    this.now = now
    this.start = typeof inputEndedAt === 'number' && Number.isFinite(inputEndedAt) && inputEndedAt <= now() && now() - inputEndedAt <= 180000 ? inputEndedAt : now()
    this.marks = {}
    this.seen = new Set()
    this.fetcher = fetcher
    this.endpoint = endpoint
  }

  mark(name) {
    if (!this.seen.has(name)) {
      this.seen.add(name)
      this.marks[name] = Math.round(this.now() - this.start)
    }
  }

  report() {
    if (!Object.keys(this.marks).length)
      return Promise.resolve()
    const marks = this.marks
    this.marks = {}
    return Promise.resolve().then(() => this.fetcher(this.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ marks }),
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(2500),
    })).catch(() => {})
  }
}
