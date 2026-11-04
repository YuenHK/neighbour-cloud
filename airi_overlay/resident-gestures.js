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
/** Keep gentle conversational motion only while actual audio is scheduled. */
export function residentSpeechGesture(active, care = false) {
  if (active) {
    const kind = care ? 'care' : 'speaking'
    Reflect.set(globalThis, key, Object.freeze({ kind, start: performance.now(), duration: durations[kind], continuous: true }))
  }
  else if (Reflect.get(globalThis, key)?.continuous) {
    Reflect.deleteProperty(globalThis, key)
  }
}
/** @param {{kind:string,start:number,duration:number,continuous?:boolean}|undefined} gesture @param {number} now */
export function gestureOffsets(gesture, now) {
  if (!gesture || !durations[gesture.kind] || !Number.isFinite(now) || !Number.isFinite(gesture.start)
    || !Number.isFinite(gesture.duration) || gesture.duration <= 0) {
    return undefined
  }
  const elapsed = (now - gesture.start) / gesture.duration
  const p = gesture.continuous && elapsed >= 0 ? elapsed % 1 : elapsed
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

/**
 * Additive VRM bone rotations in degrees, relative to the native idle pose.
 * @param {{kind:string,start:number,duration:number,continuous?:boolean}|undefined} gesture
 * @param {number} now
 */
export function bodyGestureOffsets(gesture, now) {
  if (!gestureOffsets(gesture, now))
    return undefined
  const elapsed = (now - gesture.start) / gesture.duration
  const p = gesture.continuous ? elapsed % 1 : elapsed
  const envelope = Math.sin(Math.PI * p) ** 2
  const wave = Math.sin(6 * Math.PI * p)
  let left = (gesture.kind === 'greeting' ? 0.05 : 0.25) * envelope
  let right = envelope
  if (gesture.kind === 'speaking') {
    // Alternate the leading hand, then leave a quieter phrase. Greeting
    // waves never repeat throughout an ordinary spoken answer.
    const beat = Math.floor(elapsed) % 3
    left = envelope * (beat === 1 ? 1 : beat === 2 ? 0.12 : 0.25)
    right = envelope * (beat === 0 ? 1 : beat === 2 ? 0.12 : 0.25)
  }
  const greeting = gesture.kind === 'greeting'
  const care = gesture.kind === 'care'
  const listen = gesture.kind === 'listen'
  if (care || listen)
    left = right = envelope * (listen ? 0.35 : 0.65)
  const lift = greeting ? 48 : 8
  const bend = greeting ? 8 : care ? 110 : 75
  const fold = greeting ? 110 : 15
  return {
    spine: [(listen ? 2.2 : care ? 1.5 : 0.6) * envelope, 0.6 * (left - right), 0.5 * (right - left)],
    leftShoulder: [0, -1.3 * left, -1.4 * left],
    rightShoulder: [0, 1.3 * right, 1.4 * right],
    leftUpperArm: [-2 * left, -4 * left, -8 * left],
    rightUpperArm: [-2 * right, 4 * right, lift * right],
    leftLowerArm: [0, -bend * left, -fold * left],
    rightLowerArm: [0, bend * right, fold * right],
    leftHand: [-14 * left, -4 * left, 3 * left],
    rightHand: [(greeting ? -38 : -14) * right, 4 * right, (greeting ? 10 * wave : -3) * right],
  }
}
