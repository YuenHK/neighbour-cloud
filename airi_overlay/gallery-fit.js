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

export function galleryFraming(model, viewport, fallback) {
  const internal = model?.internalModel
  if (internal?.settings?.json?.Neighbour?.fit !== 'visible-contain-v1')
    return fallback
  let bounds = cache.get(model)
  if (!bounds) {
    const core = internal.coreModel
    let left = Infinity
    let top = Infinity
    let right = -Infinity
    let bottom = -Infinity
    for (let index = 0; index < core.getDrawableCount(); index++) {
      if (core.getDrawableOpacity(index) <= 0.01)
        continue
      const vertices = internal.getDrawableVertices(index)
      for (let point = 0; point + 1 < vertices.length; point += 2) {
        const pixel = internal.localTransform.apply({ x: vertices[point], y: vertices[point + 1] })
        if (!Number.isFinite(pixel.x) || !Number.isFinite(pixel.y))
          continue
        left = Math.min(left, pixel.x)
        right = Math.max(right, pixel.x)
        top = Math.min(top, pixel.y)
        bottom = Math.max(bottom, pixel.y)
      }
    }
    if (right <= left || bottom <= top)
      return fallback
    bounds = { left, right, top, bottom }
    cache.set(model, bounds)
  }
  const scale = Math.min(viewport.width / (bounds.right - bounds.left), viewport.height / (bounds.bottom - bounds.top)) * 0.9
  if (!Number.isFinite(scale) || scale <= 0)
    return fallback
  return { scale, x: viewport.width / 2 - ((bounds.left + bounds.right - internal.width) / 2) * scale, y: viewport.height / 2 - ((bounds.top + bounds.bottom - internal.height) / 2) * scale }
}
