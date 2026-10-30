// Geometry and gesture boundaries only; never infer or record a resident's intent.
export function inspectResidentView({ renderer, camera, origin, height, fov, scale = 1 }) {
  if (renderer === 'live2d' || renderer === 'spine')
    return Number.isFinite(scale) && scale > 0 && scale <= 1.8 ? 'safe' : 'close-up'
  if (renderer !== 'vrm' || height === 0)
    return 'pending'
  if (!Number.isFinite(height) || height < 0)
    return 'invalid-view'
  if (![camera?.x, camera?.y, camera?.z, origin?.x, origin?.y, origin?.z, fov].every(Number.isFinite))
    return 'invalid-view'
  if (camera.y < origin.y - height * 0.2)
    return 'low-angle'
  const distance = Math.hypot(camera.x - origin.x, camera.y - origin.y, camera.z - origin.z)
  const visibleHeight = 2 * distance * Math.tan(fov * Math.PI / 360)
  return fov > 0 && fov < 120 && visibleHeight >= height * 0.45 ? 'safe' : 'close-up'
}

export function isCameraGesture(start, point) {
  return !!start && Math.hypot(point.x - start.x, point.y - start.y) > 12
}
