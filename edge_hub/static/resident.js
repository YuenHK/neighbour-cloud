(() => {
  const privacy = document.querySelector?.('.resident-privacy-notice')
  const staff = document.querySelector?.('.resident-topbar .service-staff-link')
  if (privacy && staff && !staff.parentElement.classList.contains('resident-topbar-actions')) {
    const actions = document.createElement('div')
    actions.className = 'resident-topbar-actions'
    staff.parentElement.append(actions)
    actions.append(privacy, staff)
  }
  const frame = document.getElementById('residentAssistant')
  const frameOrigin = Reflect.get(globalThis, '__NEIGHBOUR_REMOTE__') === true ? location.origin : 'http://127.0.0.1:4173'
  const status = document.getElementById('assistantLoadStatus')
  const fallback = document.getElementById('assistantFallback')
  let ready = false
  window.addEventListener('message', (event) => {
    if (event.origin !== frameOrigin || event.source !== frame.contentWindow
      || event.data?.type !== 'estate-assistant-ready') {
      return
    }
    ready = true
    status.hidden = true
    fallback.hidden = true
  })
  // A fast iframe can mount before this deferred script. Request a fresh
  // acknowledgement without reloading a resident's active conversation.
  function checkReady() {
    frame.contentWindow?.postMessage({ type: 'estate-assistant-check' }, frameOrigin)
  }
  frame.addEventListener('load', checkReady)
  checkReady()
  setTimeout(() => {
    if (ready)
      return
    status.textContent = '數字人仍在載入，可以稍候或重新開啟。'
    fallback.hidden = false
  }, 20000)
})()
