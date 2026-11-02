// Resident conversations live in this instance only. Reset fences late replies.
export class ResidentSession {
  history = []
  busy = false
  generation = 0
  controller = null
  intent = null
  profile = ''
  sessionId = crypto.randomUUID().replaceAll('-', '')

  constructor(request, { maxMessages = 60, maxCharacters = 16000 } = {}) {
    if (!Number.isSafeInteger(maxMessages) || maxMessages < 4 || maxMessages > 60
      || !Number.isSafeInteger(maxCharacters) || maxCharacters < 2000 || maxCharacters > 16000) {
      throw new Error('invalid_resident_context_limit')
    }
    this.request = request
    this.maxMessages = maxMessages
    this.maxCharacters = maxCharacters
  }

  bounded(messages) {
    let remaining = this.maxCharacters
    const kept = []
    for (const item of [...messages].reverse()) {
      if (kept.length >= this.maxMessages || item.content.length > remaining)
        break
      kept.push({ role: item.role, content: item.content })
      remaining -= item.content.length
    }
    kept.reverse()
    while (kept.length && kept[0].role !== 'user')
      kept.shift()
    return kept
  }

  /** @param {string} text @param {string} style @param {(delta: string) => void} onDelta */
  async send(text, style = 'voice', onDelta = () => {}) {
    text = text.trim()
    if (!text || text.length > 2000 || this.busy)
      throw new Error('resident_busy_or_invalid')
    const epoch = this.generation
    this.busy = true
    const controller = new AbortController()
    this.controller = controller
    const user = { role: 'user', content: text }
    const name = text.match(/^(?:我叫|我係|我是|叫我)([^，。！？,!?\n]{1,20})[。！!]?$/)
    if (name)
      this.profile = name[1].normalize('NFKC').trim()
    const messages = this.bounded([...this.history, user])
    const fingerprint = JSON.stringify({ messages, style, profile: this.profile })
    if (this.intent?.fingerprint !== fingerprint)
      this.intent = { fingerprint, id: crypto.randomUUID().replaceAll('-', '') }
    try {
      const answer = await this.request({ messages, style, profile: this.profile, stream: true, submission_id: this.intent.id, session_id: this.sessionId }, controller.signal, (delta) => {
        if (epoch === this.generation && !controller.signal.aborted)
          onDelta(delta)
      })
      if (epoch !== this.generation)
        return null
      if (typeof answer !== 'string' || !answer.trim() || answer.length > 4000)
        throw new Error('resident_reply_invalid')
      this.history = this.bounded([...this.history, user, { role: 'assistant', content: answer.trim() }])
      this.intent = null
      return answer.trim()
    }
    finally {
      if (epoch === this.generation) {
        this.busy = false
        this.controller = null
      }
    }
  }

  cancelPending() {
    this.generation++
    this.controller?.abort()
    this.controller = null
    this.busy = false
    // Keep history, identity and intent ID: retry must not create a second case.
  }

  reset() {
    this.generation++
    this.controller?.abort()
    this.controller = null
    this.history = []
    this.intent = null
    this.profile = ''
    this.sessionId = crypto.randomUUID().replaceAll('-', '')
    this.busy = false
  }
}
