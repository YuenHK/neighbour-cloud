import type { VRM } from '@pixiv/three-vrm'
import type { Object3D } from 'three'

import { Euler, Quaternion, Vector3 } from 'three'

import { bodyGestureOffsets, gestureOffsets } from './resident-gestures.js'

const bones = ['head', 'chest', 'spine', 'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand'] as const
type GestureBone = typeof bones[number]
const zero = [0, 0, 0]

export function residentVrmGesture() {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  const poses = new Map<Object3D, { before: Quaternion, after: Quaternion, offset: Vector3 }>()
  const delta = new Quaternion()
  const euler = new Euler()
  let currentVrm: VRM | undefined
  function restore() {
    for (const [bone, pose] of poses) {
      if (bone.quaternion.equals(pose.after))
        bone.quaternion.copy(pose.before)
    }
    poses.clear()
  }
  function update(vrm: VRM, deltaSeconds = 1 / 60) {
    if (currentVrm !== vrm) {
      restore()
      currentVrm = vrm
    }
    if (document.hidden || reduced.matches) {
      restore()
      return
    }
    const gesture = Reflect.get(globalThis, '__NEIGHBOUR_RESIDENT_GESTURE__')
    const now = performance.now()
    const offsets = gestureOffsets(gesture, now)
    if (!offsets && !poses.size)
      return
    const targets: Partial<Record<GestureBone, number[]>> = {
      ...bodyGestureOffsets(gesture, now),
      ...(offsets
        ? {
            head: [offsets.y, offsets.x, offsets.z],
            chest: [offsets.y * 0.18, offsets.x * 0.18, offsets.body * 0.18],
          }
        : {}),
    }
    const dt = Number.isFinite(deltaSeconds) ? Math.max(0, Math.min(1 / 15, deltaSeconds)) : 1 / 60
    const blend = 1 - Math.exp(-9 * dt)
    // The native idle mixer runs first. Add small rotations to its current
    // pose, undoing our prior offset only when no animation replaced it.
    for (const name of bones) {
      const bone = vrm.humanoid.getNormalizedBoneNode(name)
      if (!bone)
        continue
      const old = poses.get(bone)
      if (old && bone.quaternion.equals(old.after))
        bone.quaternion.copy(old.before)
      const pose = old || { before: bone.quaternion.clone(), after: bone.quaternion.clone(), offset: new Vector3() }
      pose.before.copy(bone.quaternion)
      const target = targets[name] || zero
      const limit = name.endsWith('LowerArm') ? 120 : 75
      const clamp = (value: number) => Number.isFinite(value) ? Math.max(-limit, Math.min(limit, value)) : 0
      pose.offset.x += (clamp(target[0]) - pose.offset.x) * blend
      pose.offset.y += (clamp(target[1]) - pose.offset.y) * blend
      pose.offset.z += (clamp(target[2]) - pose.offset.z) * blend
      if (!targets[name] && pose.offset.lengthSq() < 1e-8) {
        poses.delete(bone)
        continue
      }
      const rad = Math.PI / 180
      delta.setFromEuler(euler.set(pose.offset.x * rad, pose.offset.y * rad, pose.offset.z * rad))
      bone.quaternion.multiply(delta)
      pose.after.copy(bone.quaternion)
      poses.set(bone, pose)
    }
  }
  return { update, restore }
}
