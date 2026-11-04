import type { VRM } from '@pixiv/three-vrm'
import type { Object3D } from 'three'

import { Euler, Quaternion } from 'three'

import { gestureOffsets } from './resident-gestures.js'

export function residentVrmGesture() {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  const poses = new Map<Object3D, { before: Quaternion, after: Quaternion }>()
  const delta = new Quaternion()
  const euler = new Euler()
  function restore() {
    for (const [bone, pose] of poses) {
      if (bone.quaternion.equals(pose.after))
        bone.quaternion.copy(pose.before)
    }
    poses.clear()
  }
  function update(vrm: VRM) {
    const gesture = Reflect.get(globalThis, '__NEIGHBOUR_RESIDENT_GESTURE__')
    const offsets = !document.hidden && !reduced.matches ? gestureOffsets(gesture, performance.now()) : undefined
    if (!offsets) {
      restore()
      return
    }
    // The native idle mixer runs first. Add small rotations to its current
    // pose, undoing our prior offset only when no animation replaced it.
    for (const [name, weight] of [['head', 1], ['chest', 0.18]] as const) {
      const bone = vrm.humanoid.getNormalizedBoneNode(name)
      if (!bone)
        continue
      const old = poses.get(bone)
      if (old && bone.quaternion.equals(old.after))
        bone.quaternion.copy(old.before)
      const before = bone.quaternion.clone()
      const rad = Math.PI / 180 * weight
      delta.setFromEuler(euler.set(offsets.y * rad, offsets.x * rad, (name === 'head' ? offsets.z : offsets.body) * rad))
      bone.quaternion.multiply(delta)
      poses.set(bone, { before, after: bone.quaternion.clone() })
    }
  }
  return { update, restore }
}
