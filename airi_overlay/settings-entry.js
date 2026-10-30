// Always load the published settings shell, while keeping native Router URLs.
(() => {
  const hubOrigin = Reflect.get(globalThis, '__NEIGHBOUR_REMOTE__') === true ? location.origin : 'http://127.0.0.1:8000'
  const theme = document.createElement('link')
  theme.rel = 'stylesheet'
  theme.href = '/estate-theme.css?embedded-layout=20261027-preview-scroll-v2'
  theme.dataset.estateTheme = 'true'
  document.head.append(theme)
  if (location.pathname === '/ui/estate-settings-entry.html')
    history.replaceState(history.state, '', `/settings${location.search}${location.hash}`)
  // Wheel events do not reliably chain across the two local origins. Keep
  // scrollable editors native; forward only the remainder to the outer page.
  if (window.self !== window.top) {
    window.addEventListener('wheel', (event) => {
      if (event.ctrlKey || event.defaultPrevented || !event.deltaY)
        return
      const direction = Math.sign(event.deltaY)
      for (const node of event.composedPath()) {
        if (!(node instanceof HTMLElement) || node === document.body || node === document.documentElement)
          continue
        const style = getComputedStyle(node)
        if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1
          && (direction < 0 ? node.scrollTop > 0 : node.scrollTop + node.clientHeight < node.scrollHeight - 1))
          return
      }
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1
      const deltaY = Math.max(-2000, Math.min(2000, event.deltaY * unit))
      if (!Number.isFinite(deltaY))
        return
      event.preventDefault()
      window.parent.postMessage({ type: 'estate:settings-wheel', deltaY }, hubOrigin)
    }, { passive: false })
  }
})()
