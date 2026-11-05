import { mountCommunitySystems } from '/cloud/community-systems.js'
export function prepareCommunityIntroduction(document, { snapshot = () => ({}) } = {}) {
  const dialog = document.getElementById('communityIntroduction')
  const trigger = document.getElementById('platformIntro')
  if (!dialog || !trigger) return
  let view, timer
  const host = document.getElementById('introSystems')
  trigger.addEventListener('click', () => {
    if (dialog.open) return
    dialog.showModal()
    if (host) {
      view ||= mountCommunitySystems(host)
      view.update(snapshot()); view.resume(); view.overview('eleuthia')
    }
  })
  document.getElementById('replayCommunitySystems')?.addEventListener('click', () => {
    if (!dialog.open || !view) return
    clearTimeout(timer)
    view.orbit({ replay: true }); view.resume()
    host.scrollIntoView({ block: 'start', behavior: 'auto' })
    timer = setTimeout(() => { if (dialog.open) view.overview('eleuthia') },
      document.defaultView.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 2700)
  })
  dialog.addEventListener('close', () => { clearTimeout(timer); view?.pause() })
  document.defaultView.addEventListener('pagehide', () => { clearTimeout(timer); view?.destroy() }, { once: true })
  document.getElementById('closeCommunityIntroduction')?.addEventListener('click', () => dialog.close())
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return
    const r = dialog.getBoundingClientRect()
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close()
  })
}
