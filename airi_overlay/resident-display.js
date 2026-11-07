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

/** Temporary resident close-up: keep the head and torso, allow lower-body cropping. */
export function upperBodyFraming(bounds, viewport) {
  const width = bounds.right - bounds.left
  const height = bounds.bottom - bounds.top
  if (![width, height, viewport.width, viewport.height].every(value => Number.isFinite(value) && value > 0))
    return undefined
  // Hands, wide sleeves and hair can extend far beyond the central torso.
  const scale = Math.min(viewport.width / (width * 0.64), viewport.height * 0.88 / (height * 0.60)) * 0.94
  return {
    scale,
    x: viewport.width / 2 - (bounds.left + bounds.right) / 2 * scale,
    y: viewport.height * 0.04 - bounds.top * scale,
  }
}
