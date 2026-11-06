import type { MotionManagerPlugin } from './composables/live2d/motion-manager'

import { readResidentGaze, ResidentGazeFilter } from './resident-gaze-state.js'
import { gestureOffsets, live2dGestureOffsets } from './resident-gestures.js'

export function residentGesturePlugin(): MotionManagerPlugin {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  let active = false
  let previousEyes: number[] | undefined
  let currentModel: unknown
  let parameters: { ids: string[], minimumValues: ArrayLike<number>, maximumValues: ArrayLike<number> } | undefined
  const poses = new Map<string, { before: number, after: number }>()
  const gazeFilter = new ResidentGazeFilter()
  return (ctx) => {
    if (currentModel !== ctx.model) {
      currentModel = ctx.model
      poses.clear()
      previousEyes = undefined
      parameters = ctx.model.getModel?.()?.parameters
    }
    const gesture = Reflect.get(globalThis, '__NEIGHBOUR_RESIDENT_GESTURE__')
    const offsets = !document.hidden && !reduced.matches ? gestureOffsets(gesture, performance.now()) : undefined
    if (document.hidden || reduced.matches)
      gazeFilter.reset()
    const gaze = !document.hidden && !reduced.matches ? gazeFilter.update(readResidentGaze(performance.now()), performance.now()) : undefined
    const limbs = offsets ? live2dGestureOffsets(gesture, performance.now()) : undefined
    for (const [name, previous] of poses) {
      if (Math.abs(ctx.model.getParameterValueById(name) - previous.after) < 1e-6)
        ctx.model.setParameterValueById(name, previous.before)
    }
    poses.clear()
    if (parameters && limbs) {
      for (const [name, amount] of Object.entries(limbs)) {
        // Never create Cubism virtual parameters for unsupported limbs.
        const legacy = name.replace(/^Param/, 'PARAM_').replace(/([a-z])([A-Z])/g, '$1_$2').toUpperCase()
        const id = parameters.ids.includes(name) ? name : legacy
        const index = parameters.ids.indexOf(id)
        if (index < 0)
          continue
        const min = parameters.minimumValues[index]
        const max = parameters.maximumValues[index]
        const before = ctx.model.getParameterValueById(id)
        if (![min, max, before, amount].every(Number.isFinite) || max <= min)
          continue
        const after = Math.max(min, Math.min(max, before + (max - min) * 0.45 * amount))
        ctx.model.setParameterValueById(id, after)
        poses.set(id, { before, after })
      }
    }
    if (!offsets && !gaze && !active)
      return
    active = !!offsets || !!gaze
    // Absolute offsets from the user's saved pose avoid accumulating drift.
    // Do not write modelParameters, mouth/eye values or camera/view settings.
    const pose = ctx.modelParameters.value
    const clamp = (value: number) => Math.max(-30, Math.min(30, value))
    const scan = gesture?.kind === 'idle' && gaze ? 0 : 1
    ctx.model.setParameterValueById('ParamAngleX', clamp((pose.angleX || 0) + (offsets?.x || 0) * scan - (gaze?.x || 0) * 20))
    ctx.model.setParameterValueById('ParamAngleY', clamp((pose.angleY || 0) + (offsets?.y || 0) * scan - (gaze?.y || 0) * 13))
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
