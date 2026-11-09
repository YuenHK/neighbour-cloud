import type { VRM } from '@pixiv/three-vrm'
import type { Object3D, PerspectiveCamera } from 'three'

import { Box3, Euler, Quaternion, Vector3 } from 'three'

import { isAdaptiveResident, residentDisplayMagnification, upperBodyFraming } from './resident-display.js'
import { readResidentGaze } from './resident-gaze-state.js'
import { bodyGestureOffsets, continuousWelcomeBody, gestureOffsets, residentAmbientOffsets } from './resident-gestures.js'

const bones = ['head', 'chest', 'spine', 'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand'] as const
type GestureBone = typeof bones[number]
const zero = [0, 0, 0]

/** Fit the projection only: changing model scale disturbs VRM spring physics. */
export function residentVrmDisplay() {
  let fitted: { vrm: VRM, camera: PerspectiveCamera, beforeView: PerspectiveCamera['view'], afterView: string, cameraPosition: Vector3, cameraRotation: Quaternion, aspect: number, zoom: number, fov: number, width: number, height: number } | undefined
  function restore() {
    if (fitted && JSON.stringify(fitted.camera.view) === fitted.afterView) {
      fitted.camera.view = fitted.beforeView ? { ...fitted.beforeView } : null
      fitted.camera.updateProjectionMatrix()
    }
    fitted = undefined
  }
  function update(vrm: VRM, camera?: PerspectiveCamera) {
    if (!camera)
      return
    if (!isAdaptiveResident()) {
      restore()
      return
    }
    if (fitted?.vrm === vrm && fitted.camera === camera && JSON.stringify(camera.view) === fitted.afterView
      && camera.position.equals(fitted.cameraPosition) && camera.quaternion.equals(fitted.cameraRotation)
      && camera.aspect === fitted.aspect && camera.zoom === fitted.zoom && camera.fov === fitted.fov
      && globalThis.innerWidth === fitted.width && globalThis.innerHeight === fitted.height) {
      return
    }
    restore()
    vrm.scene.updateMatrixWorld(true)
    camera.updateMatrixWorld(true)
    camera.updateProjectionMatrix()
    const box = new Box3().setFromObject(vrm.scene)
    if (box.isEmpty())
      return
    const projected = new Box3()
    for (const x of [box.min.x, box.max.x]) {
      for (const y of [box.min.y, box.max.y]) {
        for (const z of [box.min.z, box.max.z])
          projected.expandByPoint(new Vector3(x, y, z).project(camera))
      }
    }
    const magnification = residentDisplayMagnification()
    const head = magnification > 1 ? vrm.humanoid?.getNormalizedBoneNode?.('head') : undefined
    const focusX = head?.getWorldPosition(new Vector3()).project(camera).x
    const fit = upperBodyFraming({ left: projected.min.x, right: projected.max.x, top: -projected.max.y, bottom: -projected.min.y }, { width: 2, height: 2 }, magnification, focusX)
    if (!fit)
      return
    const ratio = fit.scale
    const center = new Vector3((1 - fit.x) / ratio, (fit.y - 1) / ratio, 0)
    if (!Number.isFinite(ratio) || ratio <= 0 || ratio > 100)
      return
    const beforeView = camera.view ? { ...camera.view } : null
    const base = beforeView?.enabled ? beforeView : { fullWidth: globalThis.innerWidth, fullHeight: globalThis.innerWidth / camera.aspect, offsetX: 0, offsetY: 0, width: globalThis.innerWidth, height: globalThis.innerWidth / camera.aspect }
    const width = base.width / ratio
    const height = base.height / ratio
    const aspect = camera.aspect
    camera.setViewOffset(base.fullWidth, base.fullHeight, base.offsetX + (center.x + 1) * base.width / 2 - width / 2, base.offsetY + (1 - center.y) * base.height / 2 - height / 2, width, height)
    camera.aspect = aspect
    camera.updateProjectionMatrix()
    fitted = { vrm, camera, beforeView, afterView: JSON.stringify(camera.view), cameraPosition: camera.position.clone(), cameraRotation: camera.quaternion.clone(), aspect, zoom: camera.zoom, fov: camera.fov, width: globalThis.innerWidth, height: globalThis.innerHeight }
  }
  return { update, restore }
}

export function residentVrmGesture() {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  const poses = new Map<Object3D, { before: Quaternion, after: Quaternion, offset: Vector3 }>()
  const delta = new Quaternion()
  const forearmTwist = new Quaternion()
  const forearmAxis = new Vector3(1, 0, 0)
  const euler = new Euler()
  let currentVrm: VRM | undefined
  let eyePose: { vrm: VRM, auto: boolean, yaw: number, pitch: number } | undefined
  const gazeOffset = new Vector3()
  function restore() {
    for (const [bone, pose] of poses) {
      if (bone.quaternion.equals(pose.after))
        bone.quaternion.copy(pose.before)
    }
    poses.clear()
    gazeOffset.set(0, 0, 0)
    if (eyePose?.vrm.lookAt) {
      eyePose.vrm.lookAt.autoUpdate = eyePose.auto
      eyePose.vrm.lookAt.yaw = eyePose.yaw
      eyePose.vrm.lookAt.pitch = eyePose.pitch
    }
    eyePose = undefined
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
    const welcome = document.body?.dataset?.cloudView === 'resident' ? continuousWelcomeBody(now, gesture?.kind === 'care', vrm.meta?.metaVersion) : undefined
    const gaze = readResidentGaze(now)
    const ambient = welcome ? residentAmbientOffsets(now, gesture?.kind || 'idle', !!gaze) : undefined
    const scan = gesture?.kind === 'idle' && gaze ? 0 : 1
    const dt = Number.isFinite(deltaSeconds) ? Math.max(0, Math.min(1 / 15, deltaSeconds)) : 1 / 60
    const blend = 1 - Math.exp(-9 * dt)
    gazeOffset.lerp(new Vector3(gaze ? -gaze.x * 20 : 0, gaze ? gaze.y * 12 : 0, 0), 1 - Math.exp(-(gaze ? 16 : 9) * dt))
    if (gaze && vrm.lookAt) {
      eyePose ||= { vrm, auto: vrm.lookAt.autoUpdate, yaw: vrm.lookAt.yaw, pitch: vrm.lookAt.pitch }
      vrm.lookAt.autoUpdate = false
      // Head may turn further; eyes stay inside the native gentle range.
      vrm.lookAt.yaw = Math.max(-12, Math.min(12, gazeOffset.x * 0.85))
      vrm.lookAt.pitch = Math.max(-8, Math.min(8, gazeOffset.y * 0.85))
    }
    else if (eyePose?.vrm.lookAt) {
      eyePose.vrm.lookAt.autoUpdate = eyePose.auto
      eyePose.vrm.lookAt.yaw = eyePose.yaw
      eyePose.vrm.lookAt.pitch = eyePose.pitch
      eyePose = undefined
    }
    if (!offsets && !poses.size && !gaze && !welcome)
      return
    const targets: Partial<Record<GestureBone, number[]>> = {
      ...bodyGestureOffsets(gesture, now),
      ...welcome,
      ...(offsets
        ? {
            head: [offsets.y * scan, offsets.x * scan, offsets.z],
            chest: [offsets.y * 0.18, offsets.x * 0.18, offsets.body * 0.18],
          }
        : {}),
    }
    if (ambient) {
      const head = targets.head || zero
      const chest = targets.chest || zero
      const spine = targets.spine || zero
      targets.head = [head[0] + ambient.y, head[1] + ambient.x, head[2] + ambient.z]
      targets.chest = [chest[0], chest[1] + ambient.body, chest[2] + ambient.body * 0.35]
      targets.spine = [spine[0] + ambient.body * 0.4, spine[1] + ambient.body * 0.5, spine[2]]
    }
    if (gaze || gazeOffset.lengthSq() > 1e-6) {
      const head = targets.head || zero
      targets.head = [head[0] + gazeOffset.y, head[1] + gazeOffset.x, head[2]]
    }
    // The native idle mixer runs first. Welcome arms use a normalized pose:
    // adding them to an authored arms-down pose folds palms off screen.
    // Head/body/gaze remain additive. Restore the untouched authored pose
    // when hidden or reduced-motion, without accumulating rotations.
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
      const limit = name.endsWith('LowerArm') ? 150 : 75
      const clamp = (value: number) => Number.isFinite(value) ? Math.max(-limit, Math.min(limit, value)) : 0
      pose.offset.x += (clamp(target[0]) - pose.offset.x) * blend
      pose.offset.y += (clamp(target[1]) - pose.offset.y) * blend
      pose.offset.z += (clamp(target[2]) - pose.offset.z) * blend
      if (!targets[name] && pose.offset.lengthSq() < 1e-8) {
        poses.delete(bone)
        continue
      }
      const rad = Math.PI / 180
      if (welcome && name.endsWith('LowerArm')) {
        // Bend the elbow, then roll around the bent forearm's own axis.
        // XYZ Euler would roll around the upper-arm axis and move the hand.
        delta.setFromEuler(euler.set(0, pose.offset.y * rad, pose.offset.z * rad))
        forearmTwist.setFromAxisAngle(forearmAxis, pose.offset.x * rad)
        delta.multiply(forearmTwist)
      }
      else {
        delta.setFromEuler(euler.set(pose.offset.x * rad, pose.offset.y * rad, pose.offset.z * rad))
      }
      if (welcome && /(?:UpperArm|LowerArm|Hand)$/.test(name))
        bone.quaternion.copy(delta)
      else
        bone.quaternion.multiply(delta)
      pose.after.copy(bone.quaternion)
      poses.set(bone, pose)
    }
  }
  return { update, restore }
}
