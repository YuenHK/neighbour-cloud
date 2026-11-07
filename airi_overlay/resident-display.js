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

/** Aspect ratio also catches the same LED panel at a scaled CSS resolution. */
export function isNarrowLedViewport(width, height) {
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0 && width / height <= 0.4
}
export function residentDisplayMagnification() {
  return globalThis.document?.body?.dataset?.cloudView === 'resident'
    && isNarrowLedViewport(globalThis.innerWidth, globalThis.innerHeight)
    ? 2
    : 1
}

/**
 * Temporary resident close-up: keep the head and torso, allow lower-body cropping.
 * @param {{left:number,right:number,top:number,bottom:number}} bounds
 * @param {{width:number,height:number}} viewport
 * @param {number} magnification
 * @param {number|undefined} focusX
 */
export function upperBodyFraming(bounds, viewport, magnification = 1, focusX = undefined) {
  const width = bounds.right - bounds.left
  const height = bounds.bottom - bounds.top
  if (![width, height, viewport.width, viewport.height, magnification].every(value => Number.isFinite(value) && value > 0))
    return undefined
  // Hands, wide sleeves and hair can extend far beyond the central torso.
  const scale = Math.min(viewport.width / (width * 0.64), viewport.height * 0.88 / (height * 0.60)) * 0.94 * magnification
  return {
    scale,
    x: viewport.width / 2 - (Number.isFinite(focusX) ? focusX : (bounds.left + bounds.right) / 2) * scale,
    y: viewport.height * 0.04 - bounds.top * scale,
  }
}
