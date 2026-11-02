// Short, per-frame gestures. No API calls, timers, storage or conversation data.
const key = '__NEIGHBOUR_RESIDENT_GESTURE__'
const durations = { greeting: 2300, listen: 1700, speaking: 2600, care: 2300 }
/** @param {'greeting'|'listen'|'speaking'|'care'|'clear'} kind */
export function residentGesture(kind) {
  if (kind === 'clear') {
    Reflect.deleteProperty(globalThis, key)
    return
  }
  const duration = durations[kind]
  if (!duration)
    return
  const now = performance.now()
  const old = Reflect.get(globalThis, key)
  if (old?.kind === kind && now - old.start < 900)
    return
  Reflect.set(globalThis, key, Object.freeze({ kind, start: now, duration }))
}
/** @param {{kind:string,start:number,duration:number}|undefined} gesture @param {number} now */
export function gestureOffsets(gesture, now) {
  if (!gesture || !durations[gesture.kind] || !Number.isFinite(now) || !Number.isFinite(gesture.start)
    || !Number.isFinite(gesture.duration) || gesture.duration <= 0) {
    return undefined
  }
  const p = (now - gesture.start) / gesture.duration
  if (p < 0 || p > 1)
    return undefined
  const envelope = Math.sin(Math.PI * p) ** 2
  const wave = Math.sin(4 * Math.PI * p)
  if (gesture.kind === 'greeting')
    return { x: 1.4 * envelope, y: 4 * wave * envelope, z: 2 * envelope, body: 0.7 * envelope }
  if (gesture.kind === 'listen')
    return { x: 0, y: 4 * Math.sin(2 * Math.PI * p) * envelope, z: 0.5 * envelope, body: 0 }
  if (gesture.kind === 'care')
    return { x: -0.7 * envelope, y: 1.4 * wave * envelope, z: 1.3 * envelope, body: 0.2 * envelope }
  return { x: Math.sin(2 * Math.PI * p) * envelope, y: 1.5 * wave * envelope, z: 0.6 * envelope, body: 0.25 * envelope }
}
