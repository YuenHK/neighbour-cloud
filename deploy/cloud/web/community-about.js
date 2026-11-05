import { mountCommunitySystems } from '/cloud/community-systems.js'
export function prepareCommunityIntroduction(document, { snapshot = () => ({}) } = {}) {
  const dialog = document.getElementById('communityIntroduction')
  const trigger = document.getElementById('platformIntro')
  if (!dialog || !trigger) return
  let view
  const host = document.getElementById('introSystems')
  trigger.addEventListener('click', () => {
    if (dialog.open) return
    dialog.showModal()
    trigger.setAttribute('aria-expanded', 'true')
    if (host) {
      view ||= mountCommunitySystems(host)
      view.update(snapshot()); view.resume(); view.orbit()
    }
  })
  dialog.addEventListener('close', () => {
    trigger.setAttribute('aria-expanded', 'false')
    view?.pause()
  })
  document.defaultView.addEventListener('pagehide', () => { view?.destroy() }, { once: true })
  document.getElementById('closeCommunityIntroduction')?.addEventListener('click', () => dialog.close())
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return
    const r = dialog.getBoundingClientRect()
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close()
  })
}
