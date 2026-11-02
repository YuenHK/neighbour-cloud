import type { MotionManagerPlugin } from './composables/live2d/motion-manager'
import { gestureOffsets } from './resident-gestures.js'

export function residentGesturePlugin(): MotionManagerPlugin {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  let active = false
  return (ctx) => {
    const gesture = Reflect.get(globalThis, '__NEIGHBOUR_RESIDENT_GESTURE__')
    const offsets = !document.hidden && !reduced.matches ? gestureOffsets(gesture, performance.now()) : undefined
    if (!offsets && !active) return
    active = !!offsets
    // Absolute offsets from the user's saved pose avoid accumulating drift.
    // Do not write modelParameters, mouth/eye values or camera/view settings.
    const pose = ctx.modelParameters.value
    const clamp = (value: number) => Math.max(-30, Math.min(30, value))
    ctx.model.setParameterValueById('ParamAngleX', clamp((pose.angleX || 0) + (offsets?.x || 0)))
    ctx.model.setParameterValueById('ParamAngleY', clamp((pose.angleY || 0) + (offsets?.y || 0)))
    ctx.model.setParameterValueById('ParamAngleZ', clamp((pose.angleZ || 0) + (offsets?.z || 0)))
    ctx.model.setParameterValueById('ParamBodyAngleZ', clamp((pose.bodyAngleZ || 0) + (offsets?.body || 0)))
  }
}
