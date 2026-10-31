// Load the real AIRI editor only after staff authentication and tab selection.
const frame = document.getElementById('cloudAiriSettings')
function read() {
  if (location.hash === '#avatar' && !frame.getAttribute('src'))
    frame.src = '/cloud/resident?estate=1&settings=1'
}
window.addEventListener('hashchange', read)
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== frame.contentWindow) return
  if (event.data?.type === 'estate:settings-size' && Number.isFinite(event.data.height))
    frame.style.height = `${Math.max(600, Math.min(20000, event.data.height))}px`
  if (event.data?.type === 'estate:settings-wheel' && Number.isFinite(event.data.deltaY))
    window.scrollBy({ top: Math.max(-2000, Math.min(2000, event.data.deltaY)) })
})
void read()
