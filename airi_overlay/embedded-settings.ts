// Only layout dimensions cross the two local origins. Native form state stays in AIRI.
export function observeEmbeddedSettings() {
  const hubOrigin = Reflect.get(globalThis, '__NEIGHBOUR_REMOTE__') === true ? location.origin : 'http://127.0.0.1:8000'
  if (window.self === window.top)
    return () => {}
  const root = document.querySelector<HTMLElement>('.estate-inline-settings')
  if (!root)
    return () => {}
  let previous = 0
  const report = () => {
    if (!root.getClientRects().length || root.clientWidth === 0)
      return
    const height = Math.ceil(root.getBoundingClientRect().height) + 2
    if (height < 100 || height === previous)
      return
    previous = height
    window.parent.postMessage({ type: 'estate:settings-size', height }, hubOrigin)
  }
  const observer = new ResizeObserver(report)
  observer.observe(root)
  report()
  return () => observer.disconnect()
}
