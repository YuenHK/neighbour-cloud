// Hold protocol prefixes until complete, so split control tags never reach UI/TTS.
export function createResidentTextFilter() {
  let pending = ''
  return {
    push(text) {
      pending += text
      let clean = ''
      while (pending) {
        const start = pending.indexOf('<')
        if (start < 0) {
          clean += pending
          pending = ''
          break
        }
        clean += pending.slice(0, start)
        pending = pending.slice(start)
        if (pending.length === 1)
          break
        if (!pending.startsWith('<|')) {
          clean += '<'
          pending = pending.slice(1)
          continue
        }
        const end = pending.indexOf('|>', 2)
        if (end < 0)
          break
        pending = pending.slice(end + 2)
      }
      return clean
    },
    finish() {
      const tail = pending === '<' ? '<' : ''
      pending = ''
      return tail
    },
  }
}

export function residentPlainText(text) {
  const filter = createResidentTextFilter()
  return filter.push(text) + filter.finish()
}

// Read actual network deltas; never fake streaming by animating a full answer.
export async function readResidentReply(response, onDelta, signal) {
  if (!response.ok)
    throw new Error('resident_chat_unavailable')
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    const data = await response.json()
    const raw = data.choices?.[0]?.message?.content
    if (typeof raw !== 'string' || raw.length > 4000 || signal.aborted)
      throw new Error('resident_reply_invalid')
    const answer = residentPlainText(raw)
    if (!answer.trim())
      throw new Error('resident_reply_invalid')
    onDelta(answer)
    return answer
  }
  const reader = response.body?.getReader()
  if (!reader)
    throw new Error('resident_stream_missing')
  const decoder = new TextDecoder()
  let pending = ''
  let answer = ''
  let done = false
  let received = 0
  const filter = createResidentTextFilter()
  function consume(line) {
    if (!line.startsWith('data:'))
      return
    const content = line.slice(5).trim()
    if (!content)
      return
    if (content === '[DONE]') {
      done = true
      return
    }
    const event = JSON.parse(content)
    if (event.error)
      throw new Error('resident_stream_error')
    const text = event.choices?.[0]?.delta?.content
    if (text === undefined || text === null)
      return
    if (typeof text !== 'string' || received + text.length > 4000)
      throw new Error('resident_reply_invalid')
    received += text.length
    const clean = filter.push(text)
    answer += clean
    if (clean)
      onDelta(clean)
  }
  try {
    while (!done) {
      if (signal.aborted)
        throw new Error('resident_cancelled')
      const item = await reader.read()
      if (signal.aborted)
        throw new Error('resident_cancelled')
      pending += decoder.decode(item.value, { stream: !item.done })
      if (pending.length > 64000)
        throw new Error('resident_stream_invalid')
      const lines = pending.split('\n')
      pending = lines.pop() || ''
      for (const line of lines) {
        consume(line.trimEnd())
        if (done)
          break
      }
      if (item.done) {
        if (pending)
          consume(pending.trimEnd())
        break
      }
    }
    const tail = filter.finish()
    answer += tail
    if (tail)
      onDelta(tail)
    if (!done || !answer.trim())
      throw new Error('resident_stream_incomplete')
    return answer.trim()
  }
  finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

// Keep spoken punctuation intact for the resident sentence segmenter;
// omit formatting marks which the voice should not pronounce.
export function residentSpeechText(text) {
  return residentPlainText(text)
    .replace(/\[([^\]\n]+)\]\(https:\/\/[^\s)]+\)/g, '$1')
    .replace(/https:\/\/[^\s<>，。！？、]+/g, '')
    .replace(/[*#`]/g, '')
}

export function residentMessageParts(text) {
  text = residentPlainText(text)
  const parts = []
  const pattern = /\[([^\]\n]{1,160})\]\((https:\/\/[^\s)]+)\)|(https:\/\/[^\s<>，。！？、]+)/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > last)
      parts.push({ text: text.slice(last, match.index), url: '' })
    parts.push({ text: match[1] || match[3], url: match[2] || match[3] })
    last = match.index + match[0].length
  }
  if (last < text.length)
    parts.push({ text: text.slice(last), url: '' })
  return parts
}
