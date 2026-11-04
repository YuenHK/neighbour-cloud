// Native AIRI's manual playgrounds use the same authenticated resident engines.
// Constructing adapters/listing models never sends a synthesis or model request.
export function pcmWav(bytes, rate = 24000) {
  const result = new Uint8Array(44 + bytes.length)
  const view = new DataView(result.buffer)
  const text = (offset, value) => {
    for (let i = 0;
      i < value.length;
      i++) result[offset + i] = value.charCodeAt(i)
  }
  text(0, 'RIFF')
  view.setUint32(4, result.length - 8, true)
  text(8, 'WAVEfmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, rate, true)
  view.setUint32(28, rate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, bytes.length, true)
  result.set(bytes, 44)
  return result
}

export async function previewWav(response) {
  if (!response.ok || !response.body)
    throw new Error('語音暫時未能試聽。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const pieces = []
  let pending = ''
  let size = 0
  let done = false
  try {
    while (!done) {
      const item = await reader.read()
      if (item.done)
        break
      pending += decoder.decode(item.value, { stream: true })
      if (pending.length > 1000000)
        throw new Error('試聽回覆太長。')
      let at
      while ((at = pending.indexOf('\n\n')) >= 0) {
        const frame = pending.slice(0, at)
        pending = pending.slice(at + 2)
        if (!frame.startsWith('data: '))
          throw new Error('試聽格式未能核對。')
        const data = JSON.parse(frame.slice(6))
        if (data.error)
          throw new Error('語音暫時未能試聽；沒有自動重送。')
        if (data.done === true) {
          done = true
          break
        }
        if (typeof data.audio !== 'string' || data.audio.length > 12000)
          throw new Error('試聽格式未能核對。')
        const bytes = Uint8Array.from(atob(data.audio), c => c.charCodeAt(0))
        size += bytes.length
        if (size > 6000000 || bytes.length % 2)
          throw new Error('試聽回覆未能核對。')
        pieces.push(bytes)
      }
    }
  }
  finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
  if (!done || !size)
    throw new Error('試聽未完成，沒有播放不完整音訊。')
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const piece of pieces) {
    bytes.set(piece, offset)
    offset += piece.length
  }
  return pcmWav(bytes)
}

async function recordingWav(file) {
  if (!(file instanceof Blob) || file.size > 8000000)
    throw new Error('請使用最多 45 秒錄音。')
  const raw = new Uint8Array(await file.arrayBuffer())
  if (raw.length >= 44 && new TextDecoder().decode(raw.subarray(8, 16)) === 'WAVEfmt '
    && new DataView(raw.buffer).getUint32(24, true) === 16000
    && new DataView(raw.buffer).getUint16(22, true) === 1
    && new DataView(raw.buffer).getUint16(34, true) === 16) {
    return new Blob([raw], { type: 'audio/wav' })
  }
  const context = new (globalThis.AudioContext || globalThis.webkitAudioContext)({ sampleRate: 16000 })
  try {
    const audio = await context.decodeAudioData(raw.buffer.slice(0))
    if (audio.duration < 0.25 || audio.duration > 45 || audio.sampleRate !== 16000)
      throw new Error('請使用 0.25 至 45 秒錄音。')
    const pcm = new Uint8Array(audio.length * 2)
    const view = new DataView(pcm.buffer)
    for (let i = 0;
      i < audio.length;
      i++) {
      let sample = 0
      for (let channel = 0;
        channel < audio.numberOfChannels;
        channel++) sample += audio.getChannelData(channel)[i] / audio.numberOfChannels
      view.setInt16(i * 2, Math.round(Math.max(-1, Math.min(1, sample)) * 32767), true)
    }
    return new Blob([pcmWav(pcm, 16000)], { type: 'audio/wav' })
  }
  finally { await context.close() } // Decode only: never connects to an audio destination.
}

export function managedNativeFetch(kind, { transport, speech, transcribe }) {
  return async (_input, init = {}) => {
    if (kind === 'hearing') {
      if (!(init.body instanceof FormData))
        throw new Error('請先提供錄音。')
      const audio = await recordingWav(init.body.get('file'))
      const text = await transcribe(audio, init.signal)
      return new Response(JSON.stringify({ text }), { headers: { 'Content-Type': 'application/json' } })
    }
    const body = JSON.parse(String(init.body || '{}'))
    if (kind === 'chat') {
      if (body.model !== 'gemma-4-26b-a4b-it')
        throw new Error('目前已接入免費 Gemma，未啟用其他模型。')
      return transport.fetch('/api/v1/resident/model/v1/chat/completions', {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
        signal: init.signal,
      })
    }
    if (body.model !== 'azure-hiumaan-f0' || body.voice !== 'zh-HK-HiuMaanNeural' || typeof body.input !== 'string')
      throw new Error('請選擇 Microsoft 語音服務。')
    let input = body.input
    if (input.trimStart().startsWith('<')) {
      const xml = new DOMParser().parseFromString(input, 'application/xml')
      if (xml.querySelector('parsererror'))
        throw new Error('試聽文字格式不正確。')
      input = xml.documentElement.textContent || '' // No submitted SSML/voice is forwarded.
    }
    const response = await transport.fetch('/_audio/v1/audio/resident-stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: init.signal, body: JSON.stringify({ model: 'azure-hiumaan-f0', voice: 'zh-HK-HiuMaanNeural', speed: 1, input, preview: speech() }) })
    return new Response(await previewWav(response), { headers: { 'Content-Type': 'audio/wav' } })
  }
}
