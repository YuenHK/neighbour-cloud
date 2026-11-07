import { isAdaptiveResident, residentDisplayMagnification, upperBodyFraming } from './resident-display.js'

// Opt-in framing for reviewed gallery archives. Native/user models keep AIRI's
// existing framing unless their runtime manifest explicitly asks for this fit.
const cache = new WeakMap()
const aliased = new WeakSet()

export function installGalleryMouthAlias(model) {
  const internal = model?.internalModel
  if (internal?.settings?.json?.Neighbour?.fit !== 'visible-contain-v1' || aliased.has(model))
    return
  const core = internal.coreModel
  const ids = Array.from(core.getModel().parameters.ids)
  if (!ids.includes('ParamMouthOpenY') && ids.includes('PARAM_MOUTH_OPEN_Y')) {
    const original = core.getParameterIndex
    core.getParameterIndex = function (identifier) {
      return original.call(this, identifier === 'ParamMouthOpenY' ? 'PARAM_MOUTH_OPEN_Y' : identifier)
    }
  }
  aliased.add(model)
}

export function galleryFraming(model, viewport, fallback, modelId) {
  const internal = model?.internalModel
  const adaptive = isAdaptiveResident()
  // Original MoFox archive cannot be altered under its terms. Fit its verified
  // immutable content ID at view time instead of changing the author's files.
  const originalMofox = typeof modelId === 'string' && /^(?:cloud-live2d-|display-model-sha256-live2d-zip-)8b93e71f792d13de4588c99b7c469e82f3f0e6cc9389257780812b5dafaa5c31$/.test(modelId)
  if (!internal || (!adaptive && internal.settings?.json?.Neighbour?.fit !== 'visible-contain-v1' && !originalMofox))
    return fallback
  let bounds = cache.get(model)
  if (!bounds) {
    const core = internal.coreModel
    let left = Infinity
    let top = Infinity
    let right = -Infinity
    let bottom = -Infinity
    const points = []
    for (let index = 0; index < core.getDrawableCount(); index++) {
      if (core.getDrawableOpacity(index) <= 0.01)
        continue
      const vertices = internal.getDrawableVertices(index)
      for (let point = 0; point + 1 < vertices.length; point += 2) {
        const pixel = internal.localTransform.apply({ x: vertices[point], y: vertices[point + 1] })
        if (!Number.isFinite(pixel.x) || !Number.isFinite(pixel.y))
          continue
        points.push([pixel.x, pixel.y])
        left = Math.min(left, pixel.x)
        right = Math.max(right, pixel.x)
        top = Math.min(top, pixel.y)
        bottom = Math.max(bottom, pixel.y)
      }
    }
    if (right <= left || bottom <= top)
      return fallback
    const upper = points.filter(point => point[1] <= top + (bottom - top) * 0.35).map(point => point[0]).sort((a, b) => a - b)
    const middle = Math.floor(upper.length / 2)
    const focusX = upper.length ? (upper[middle] + upper[Math.max(0, middle - (upper.length % 2 === 0 ? 1 : 0))]) / 2 : (left + right) / 2
    bounds = { left, right, top, bottom, focusX }
    cache.set(model, bounds)
  }
  if (adaptive) {
    const magnification = residentDisplayMagnification()
    const fit = upperBodyFraming(bounds, viewport, magnification, magnification > 1 ? bounds.focusX : undefined)
    return fit ? { scale: fit.scale, x: fit.x + internal.width / 2 * fit.scale, y: fit.y + internal.height / 2 * fit.scale } : fallback
  }
  const scale = Math.min(viewport.width / (bounds.right - bounds.left), viewport.height / (bounds.bottom - bounds.top)) * 0.9
  if (!Number.isFinite(scale) || scale <= 0)
    return fallback
  return { scale, x: viewport.width / 2 - ((bounds.left + bounds.right - internal.width) / 2) * scale, y: viewport.height / 2 - ((bounds.top + bounds.bottom - internal.height) / 2) * scale }
}
