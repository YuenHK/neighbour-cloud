// Only the latest selected view may replace an image; closed dialogs own no URLs.
globalThis.NeighbourLatestPhoto = class {
  constructor(initialUrl, request = (...args) => globalThis.fetch(...args), urls = URL) {
    this.activeUrl = initialUrl
    this.request = request
    this.urls = urls
    this.generation = 0
    this.closed = false
    this.controller = null
  }

  async load(path, options, apply) {
    if (this.closed) return false
    if (!path.startsWith('/api/v1/patrol/events/') || path.includes('\\')) throw new Error('invalid_photo_path')
    const generation = ++this.generation
    this.controller?.abort()
    const controller = new AbortController()
    this.controller = controller
    try {
      const response = await this.request(path, { ...options, cache: 'no-store', credentials: 'omit', redirect: 'error',
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]) })
      if (!response.ok) throw new Error('photo_unavailable')
      const blob = await response.blob()
      if (this.closed || generation !== this.generation) return false
      const url = this.urls.createObjectURL(blob)
      try { apply(url) }
      catch { this.urls.revokeObjectURL(url); throw new Error('photo_display_failed') }
      if (this.activeUrl) this.urls.revokeObjectURL(this.activeUrl)
      this.activeUrl = url
      return true
    }
    catch {
      if (this.closed || generation !== this.generation) return false
      throw new Error('photo_unavailable')
    }
  }

  close() {
    this.closed = true
    this.generation++
    this.controller?.abort()
    if (this.activeUrl) this.urls.revokeObjectURL(this.activeUrl)
    this.activeUrl = null
  }
}
