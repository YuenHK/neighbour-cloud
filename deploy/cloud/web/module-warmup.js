// Fetch code without executing it, mounting a console or contacting hardware.
export async function preloadModules(document, modules, options = {}) {
  const first = await preloadOnce(document, modules, options)
  return Promise.all(first.map(async result => {
    if (result.state !== 'failed') return result
    const module = modules.find(item => item.key === result.key)
    // One retry of same-origin program assets; never runs application modules.
    return (await preloadOnce(document, [module], { ...options, fresh: true }))[0]
  }))
}
function preloadOnce(document, modules, { onState = () => {}, timeoutMs = 10000, fresh = false } = {}) {
  return Promise.all(modules.map(({ key, path }) => new Promise(resolve => {
    if (!/^\/(?:assets\/[\w-]+\.js|cloud\/(?:admin\/[\w-]+\.js|robot-entry\.js|robot-assets\/ep-(?:fleet|console)(?:-[a-f0-9]{12})?\.js))$/.test(path)) {
      resolve({ key, state: 'failed' }); return
    }
    const absolute = new URL(path, document.location.origin).href
    const existing = !fresh && [...document.querySelectorAll('link[rel=modulepreload]')].find(link => link.href === absolute)
    const link = existing || document.createElement('link')
    let done = false, timer
    const finish = state => {
      if (done) return
      done = true
      clearTimeout(timer)
      link.removeEventListener('load', loaded)
      link.removeEventListener('error', failed)
      onState(key, state)
      resolve({ key, state })
    }
    const loaded = () => finish('loaded'), failed = () => finish('failed')
    onState(key, 'loading')
    link.addEventListener('load', loaded, { once: true })
    link.addEventListener('error', failed, { once: true })
    timer = setTimeout(failed, timeoutMs)
    const timing = document.defaultView.performance.getEntriesByName(absolute).at(-1)
    if (existing && timing?.responseEnd > 0 && (!timing.responseStatus || timing.responseStatus < 400)) {
      loaded(); return
    }
    if (!existing) {
      link.rel = 'modulepreload'; link.href = path
      document.head.append(link)
    }
  })))
}
