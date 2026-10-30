(() => {
  const tabs = [...document.querySelectorAll('.service-tabs [role="tab"]')]
  if (!tabs.length)
    return
  const groups = { work: ['caseHeading', 'requests'], care: [], reports: ['eventsPanel'], knowledge: ['knowledgeForm', 'residentMemoriesForm'], usage: ['quotaHeading'], avatar: [] }
  const frameOrigin = Reflect.get(globalThis, '__NEIGHBOUR_REMOTE__') === true ? location.origin : 'http://127.0.0.1:4173'
  window.addEventListener('message', (event) => {
    const frame = document.getElementById('airiSettingsFrame')
    if (!frame || event.origin !== frameOrigin || event.source !== frame.contentWindow)
      return
    const { type, height, deltaY } = event.data || {}
    if (type === 'estate:settings-size' && Number.isFinite(height) && height >= 100 && height <= 32000)
      frame.style.height = `${Math.ceil(height)}px`
    if (type === 'estate:settings-wheel' && !document.getElementById('panel-avatar').hidden
      && Number.isFinite(deltaY) && Math.abs(deltaY) <= 2000)
      window.scrollBy({ top: deltaY, behavior: 'instant' })
  })
  function select() {
    const previous = location.hash.slice(1)
    const hash = previous === 'settings' ? 'avatar' : ['voiceSettingsForm', 'health'].includes(previous) ? 'usage' : previous
    const active = Object.keys(groups).find(key => key === hash || groups[key].includes(hash)) || 'work'
    let activePanel
    for (const tab of tabs) {
      const selected = tab.getAttribute('href') === `#${active}`
      tab.setAttribute('aria-selected', String(selected))
      tab.tabIndex = selected ? 0 : -1
      if (selected) {
        activePanel = tab.getAttribute('aria-controls')
        document.getElementById(activePanel).setAttribute('aria-labelledby', tab.id)
      }
    }
    for (const panel of new Set(tabs.map(tab => tab.getAttribute('aria-controls'))))
      document.getElementById(panel).hidden = panel !== activePanel
    // Load the native editor only on first entry. Keep it mounted while switching
    // work tabs so unsaved native form fields and the current settings page survive.
    if (active === 'avatar') {
      const frame = document.getElementById('airiSettingsFrame')
      if (frame && !frame.getAttribute('src'))
        frame.setAttribute('src', frame.getAttribute('data-src'))
    }
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('keydown', (event) => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
      if (next < 0)
        return
      event.preventDefault()
      tabs[next].focus()
      location.hash = tabs[next].getAttribute('href')
    })
  })
  window.addEventListener('hashchange', select)
  select()
})()
