// Only short-lived face position, never an image, identifier or embedding.
const key = '__NEIGHBOUR_RESIDENT_GAZE__'
export function clearResidentGaze() {
  Reflect.deleteProperty(globalThis, key)
}
export function readResidentGaze(now) {
  const value = Reflect.get(globalThis, key)
  if (!value || ![value.x, value.y, value.at, now].every(Number.isFinite) || now < value.at || now - value.at > 1200)
    return undefined
  return { x: Math.max(-1, Math.min(1, value.x)), y: Math.max(-1, Math.min(1, value.y)) }
}
export function selectResidentFace(detections, width, height, previous) {
  if (!Array.isArray(detections) || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0)
    return undefined
  const candidates = detections.flatMap((face) => {
    const box = face?.boundingBox
    if (!box || ![box.originX, box.originY, box.width, box.height].every(Number.isFinite)
      || box.width <= 0 || box.height <= 0 || box.width > width || box.height > height
      || (face.categories?.[0]?.score ?? 0) < 0.65) {
      return []
    }
    const x = (box.originX + box.width / 2) / width
    const y = (box.originY + box.height / 2) / height
    return x >= 0 && x <= 1 && y >= 0 && y <= 1 ? [{ x, y, area: box.width * box.height }] : []
  })
  // Keep the nearest spatial target during a conversation; this is not identity matching.
  candidates.sort((a, b) => previous
    ? Math.hypot(a.x - previous.x, a.y - previous.y) - Math.hypot(b.x - previous.x, b.y - previous.y)
    : b.area - a.area)
  return candidates[0]
}
