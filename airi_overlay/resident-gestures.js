// Short, per-frame gestures. No API calls, timers, storage or conversation data.
const key = '__NEIGHBOUR_RESIDENT_GESTURE__'
const durations = { greeting: 3200, listen: 1700, speaking: 2600, care: 3300, explain: 3600, agree: 2200, thanks: 2700, celebrate: 3000, idle: 5800 }

/** Continuous normalized arm pose; conversational head motion stays independent. */
export function continuousWelcomeBody(now, gentle = false) {
  if (!Number.isFinite(now) || now < 0)
    return undefined
  const phase = (now % 11000) / 11000
  const strength = gentle ? 0.58 : 1
  const lead = Math.cos(2 * Math.PI * phase)
  const invite = (value) => {
    const p = Math.max(0, Math.min(1, (value + 0.6) / 0.6))
    return p * p * (3 - 2 * p)
  }
  // A short overlap hands over the wave, then the other arm really rests.
  const left = invite(-lead)
  const right = invite(lead)
  const wave = Math.sin(2 * Math.PI * now / 1500) * strength
  return {
    leftShoulder: [0, -0.7 * left * strength, -0.8 * left * strength],
    rightShoulder: [0, 0.7 * right * strength, 0.8 * right * strength],
    // Raised palm stays beside the cheek, not above the crown. The other arm
    // returns to an arms-down pose; do not keep both hands on the head.
    leftUpperArm: [-2 * left, -3 * left, 72 * (1 - left)],
    rightUpperArm: [-2 * right, 3 * right, -72 * (1 - right)],
    leftLowerArm: [0, -4 * left, -5 - 135 * left],
    rightLowerArm: [0, 4 * right, 5 + 135 * right],
    leftHand: [-20 * left * strength, -4 * left, -18 * wave * left],
    rightHand: [-20 * right * strength, 4 * right, 18 * wave * right],
  }
}
export function continuousWelcomeLive2d(now, gentle = false) {
  const pose = continuousWelcomeBody(now, gentle)
  if (!pose)
    return undefined
  const left = Math.abs(pose.leftLowerArm[2]) / 140
  const right = Math.abs(pose.rightLowerArm[2]) / 140
  return {
    ParamArmLA: left * 0.85,
    ParamArmRA: right * 0.85,
    ParamHandL: pose.leftHand[2] / 18 * 0.45,
    ParamHandR: pose.rightHand[2] / 18 * 0.45,
    ParamShoulderL: left * 0.14,
    ParamShoulderR: right * 0.14,
  }
}
/** Small varied head/body motions, independent of waves, lips and saved pose. */
export function residentAmbientOffsets(now, kind = 'idle', hasGaze = false) {
  if (!Number.isFinite(now) || now < 0)
    return undefined
  const phase = now / 24000 * 2 * Math.PI
  const strength = kind === 'care' ? 0.38 : kind === 'idle' ? 1 : 0.55
  return {
    x: hasGaze ? 0 : Math.sin(phase) * 2.8 * strength,
    y: Math.sin(phase * 2 + 0.4) * 1.2 * strength,
    z: Math.sin(phase + 1.2) * 1.0 * strength,
    body: Math.sin(phase * 0.75) * 1.1 * strength,
  }
}
function settledGesture(gesture, now) {
  if (gesture?.continuous && ['greeting', 'agree', 'thanks', 'celebrate'].includes(gesture.kind) && now - gesture.start > gesture.duration)
    return { ...gesture, kind: 'speaking', start: gesture.start + gesture.duration, duration: durations.speaking }
  return gesture
}
/** Classify existing text locally; never send another model request or retain text. */
export function residentConversationGesture(user = '', reply = '') {
  const text = `${String(user).slice(-1200)} ${String(reply).slice(0, 900)}`
  if (/壓力|唔開心|難受|擔心|跳樓|自殺|想死|生活困難|好攰|害怕|驚|孤單|傷心|焦慮|漏水|火警|受傷/.test(text))
    return 'care'
  if (/多謝|謝謝|感謝|唔該晒/.test(user))
    return 'thanks'
  if (/揮手|你好|早晨|午安|晚安|hello|hi\b/i.test(user) && String(user).length < 65)
    return 'greeting'
  if (!/[唔不冇無]|失敗/.test(user) && /成功|好開心|好高興|考到|畢業|得獎|生日/.test(user))
    return 'celebrate'
  if (/^(?:好呀|好啊|好嘅|明白|知道|可以|係呀|係啊|對呀|冇錯)[！!。，\s]*$/.test(String(user).trim()))
    return 'agree'
  if (/點樣|如何|點解|甚麼|咩|分類|步驟|方法|首先|例如|可以分/.test(text))
    return 'explain'
  return 'speaking'
}
export function shouldResidentWelcome(state, now) {
  return !!state?.visible && !!state.mounted && !state.hidden && !state.busy && !state.speaking
    && !state.care && !state.draft && Number.isFinite(now) && Number.isFinite(state.lastAt)
    && now - state.lastAt >= 45000
    && (state.messages === 0 || (Number.isFinite(state.lastActivity) && now - state.lastActivity >= 75000))
}
/** @param {'greeting'|'listen'|'speaking'|'care'|'explain'|'agree'|'thanks'|'celebrate'|'idle'|'clear'} kind */
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
export function residentSpeechGesture(active, care = false, selected = 'speaking') {
  if (active) {
    const kind = care ? 'care' : durations[selected] && !['idle', 'listen'].includes(selected) ? selected : 'speaking'
    const old = Reflect.get(globalThis, key)
    if (old?.continuous && old.kind === kind)
      return
    Reflect.set(globalThis, key, Object.freeze({ kind, start: performance.now(), duration: durations[kind], continuous: true }))
  }
  else if (Reflect.get(globalThis, key)?.continuous) {
    Reflect.deleteProperty(globalThis, key)
  }
}
/** @param {{kind:string,start:number,duration:number,continuous?:boolean}|undefined} gesture @param {number} now */
export function gestureOffsets(gesture, now) {
  gesture = settledGesture(gesture, now)
  if (!gesture || !durations[gesture.kind] || !Number.isFinite(now) || !Number.isFinite(gesture.start)
    || !Number.isFinite(gesture.duration) || gesture.duration <= 0) {
    return undefined
  }
  const elapsed = (now - gesture.start) / gesture.duration
  const p = gesture.continuous && elapsed >= 0 ? elapsed % 1 : elapsed
  if (p < 0 || p > 1)
    return undefined
  const edge = Math.max(0, Math.min(1, p / 0.18, (1 - p) / 0.22))
  const envelope = gesture.kind === 'greeting' ? edge * edge * (3 - 2 * edge) : Math.sin(Math.PI * p) ** 2
  const wave = Math.sin(4 * Math.PI * p)
  if (gesture.kind === 'idle')
    return { x: 4.8 * Math.sin(2 * Math.PI * p) * envelope, y: 0.8 * wave * envelope, z: 1.1 * envelope, body: 0.8 * Math.sin(2 * Math.PI * p) * envelope }
  if (gesture.kind === 'thanks')
    return { x: 0, y: -4.5 * envelope, z: 0.4 * envelope, body: 0 }
  if (gesture.kind === 'agree')
    return { x: 0, y: 3.8 * wave * envelope, z: 0, body: 0 }
  if (gesture.kind === 'celebrate')
    return { x: 0.6 * wave * envelope, y: 2.5 * envelope, z: 1.2 * wave * envelope, body: 0.8 * wave * envelope }
  if (gesture.kind === 'explain')
    return { x: 2 * Math.sin(2 * Math.PI * p) * envelope, y: 1.2 * wave * envelope, z: 0.6 * envelope, body: 0.6 * wave * envelope }
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
  gesture = settledGesture(gesture, now)
  if (!gestureOffsets(gesture, now))
    return undefined
  const elapsed = (now - gesture.start) / gesture.duration
  const p = gesture.continuous ? elapsed % 1 : elapsed
  const edge = Math.max(0, Math.min(1, p / 0.18, (1 - p) / 0.22))
  const envelope = gesture.kind === 'greeting' ? edge * edge * (3 - 2 * edge) : Math.sin(Math.PI * p) ** 2
  const wave = Math.sin(6 * Math.PI * p)
  let left = (gesture.kind === 'greeting' ? 0.05 : 0.25) * envelope
  let right = envelope
  if (['speaking', 'explain'].includes(gesture.kind)) {
    // Alternate the leading hand, then leave a quieter phrase. Greeting
    // waves never repeat throughout an ordinary spoken answer.
    const beat = Math.floor(elapsed) % 3
    left = envelope * (beat === 1 ? 1 : beat === 2 ? 0.12 : 0.25)
    right = envelope * (beat === 0 ? 1 : beat === 2 ? 0.12 : 0.25)
  }
  const greeting = ['greeting', 'idle'].includes(gesture.kind)
  const care = gesture.kind === 'care'
  const listen = gesture.kind === 'listen'
  if (care || listen)
    left = right = envelope * (listen ? 0.35 : 0.65)
  if (gesture.kind === 'thanks' || gesture.kind === 'agree')
    left = right = envelope * 0.35
  if (gesture.kind === 'celebrate')
    left = right = envelope * 0.85
  const lift = greeting ? 48 : 8
  const bend = greeting ? 8 : care ? 110 : 75
  const fold = greeting ? 110 : 15
  return {
    spine: [(gesture.kind === 'thanks' ? 4 : listen ? 2.2 : care ? 1.5 : 0.6) * envelope, 0.6 * (left - right), 0.5 * (right - left)],
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

/** Normalised additive targets; renderer only writes parameters present in the rig. */
export function live2dGestureOffsets(gesture, now) {
  gesture = settledGesture(gesture, now)
  const body = bodyGestureOffsets(gesture, now)
  if (!body)
    return undefined
  const p = ((now - gesture.start) / gesture.duration) % 1
  const welcome = ['greeting', 'idle'].includes(gesture.kind)
  const right = body.rightUpperArm[2] / (welcome ? 48 : 8)
  const left = -body.leftUpperArm[2] / 8
  return {
    ParamBodyAngleX: body.spine[1] / 8,
    ParamBodyAngleY: body.spine[0] / 12,
    ParamArmLA: left * 0.28,
    ParamArmRA: right * (welcome ? 0.72 : 0.30),
    ParamHandL: left * 0.18,
    ParamHandR: right * (welcome ? 0.35 * Math.sin(6 * Math.PI * p) : 0.18),
    ParamShoulderL: left * 0.12,
    ParamShoulderR: right * 0.15,
  }
}
