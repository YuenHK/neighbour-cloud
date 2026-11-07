/** The available browser viewport, not a monitor ID or physical pixel claim. */
export function isLedViewport(width, height) {
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0 && width <= 256 && height <= 768
}
export function isLedResident() {
  return globalThis.document?.body?.dataset?.cloudView === 'resident' && isLedViewport(globalThis.innerWidth, globalThis.innerHeight)
}

/** Match the resident presentation, never the staff model editor or saved profile. */
export function residentViewportMode(width, height) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0)
    return 'desktop'
  if (height >= width)
    return 'portrait'
  return width <= 900 || height <= 360 ? 'compact-landscape' : 'desktop'
}
export function isAdaptiveResident() {
  return globalThis.document?.body?.dataset?.cloudView === 'resident'
    && residentViewportMode(globalThis.innerWidth, globalThis.innerHeight) !== 'desktop'
}
