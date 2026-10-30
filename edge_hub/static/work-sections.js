(() => {
  const tabs = [...document.querySelectorAll('[data-work-section]')]
  if (!tabs.length)
    return
  let current
  function select() {
    const hash = location.hash.slice(1)
    const group = hash === 'care' ? 'care' : ['reports', 'eventsPanel'].includes(hash) ? 'reports' : 'requests'
    document.getElementById('caseWorkspace').hidden = group === 'reports'
    document.getElementById('eventsPanel').hidden = group !== 'reports'
    document.getElementById('caseHeading').textContent = group === 'care' ? '關懷跟進' : '求助查詢'
    globalThis.ZhiweiWorkSection = group
    if (group !== current) {
      current = group
      document.dispatchEvent(new CustomEvent('worksectionchange', { detail: group }))
    }
  }
  window.addEventListener('hashchange', select)
  select()
})()
