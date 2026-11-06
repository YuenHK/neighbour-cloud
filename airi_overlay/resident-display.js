/** The available browser viewport, not a monitor ID or physical pixel claim. */
export function isLedViewport(width, height) {
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0 && width <= 256 && height <= 768
}
export function isLedResident() {
  return globalThis.document?.body?.dataset?.cloudView === 'resident' && isLedViewport(globalThis.innerWidth, globalThis.innerHeight)
}
