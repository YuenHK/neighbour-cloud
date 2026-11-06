import type { MotionManagerPlugin } from './composables/live2d/motion-manager'

import { readResidentGaze, ResidentGazeFilter } from './resident-gaze-state.js'
import { gestureOffsets } from './resident-gestures.js'

export function residentGesturePlugin(): MotionManagerPlugin {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  let active = false
  let previousEyes: number[] | undefined
  const gazeFilter = new ResidentGazeFilter()
  return (ctx) => {
    const gesture = Reflect.get(globalThis, '__NEIGHBOUR_RESIDENT_GESTURE__')
    const offsets = !document.hidden && !reduced.matches ? gestureOffsets(gesture, performance.now()) : undefined
    if (document.hidden || reduced.matches)
      gazeFilter.reset()
    const gaze = !document.hidden && !reduced.matches ? gazeFilter.update(readResidentGaze(performance.now()), performance.now()) : undefined
    if (!offsets && !gaze && !active)
      return
    active = !!offsets || !!gaze
    // Absolute offsets from the user's saved pose avoid accumulating drift.
    // Do not write modelParameters, mouth/eye values or camera/view settings.
    const pose = ctx.modelParameters.value
    const clamp = (value: number) => Math.max(-30, Math.min(30, value))
    ctx.model.setParameterValueById('ParamAngleX', clamp((pose.angleX || 0) + (offsets?.x || 0) - (gaze?.x || 0) * 20))
    ctx.model.setParameterValueById('ParamAngleY', clamp((pose.angleY || 0) + (offsets?.y || 0) - (gaze?.y || 0) * 13))
    ctx.model.setParameterValueById('ParamAngleZ', clamp((pose.angleZ || 0) + (offsets?.z || 0)))
    ctx.model.setParameterValueById('ParamBodyAngleZ', clamp((pose.bodyAngleZ || 0) + (offsets?.body || 0)))
    if (gaze) {
      previousEyes ||= [ctx.model.getParameterValueById('ParamEyeBallX'), ctx.model.getParameterValueById('ParamEyeBallY')]
      ctx.model.setParameterValueById('ParamEyeBallX', -gaze.x * 0.85)
      ctx.model.setParameterValueById('ParamEyeBallY', -gaze.y * 0.6)
    }
    else if (previousEyes) {
      ctx.model.setParameterValueById('ParamEyeBallX', previousEyes[0])
      ctx.model.setParameterValueById('ParamEyeBallY', previousEyes[1])
      previousEyes = undefined
    }
  }
}
