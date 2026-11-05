import { FREE_SKELETAL_LIMITS, validateFreeSkeletalBundle, validateSkeletalTexture } from './free-skeletal-loader.js'
// SPDX-License-Identifier: MIT
import { atlasLookup } from './free-skeletal-runtime/core/draw.js'
import { readSkeletonJson } from './free-skeletal-runtime/core/interop.js'
import { Pose } from './free-skeletal-runtime/core/pose.js'
import { AnimationState } from './free-skeletal-runtime/core/state.js'
import { WebGLRenderer } from './free-skeletal-runtime/webgl/renderer.js'

const clamp = (value, low, high) => Math.max(low, Math.min(high, Number.isFinite(value) ? value : low))

async function decodeTexture(blob, width, height) {
  await validateSkeletalTexture(blob, width, height)
  if (typeof createImageBitmap === 'function')
    return createImageBitmap(blob, { premultiplyAlpha: 'none' })
  // Safari fallback stays on a supplied, validated local Blob; no model-provided URL is used.
  const url = URL.createObjectURL(blob)
  try {
    const image = new Image()
    image.decoding = 'async'
    await new Promise((resolve, reject) => {
      image.onload = resolve
      image.onerror = () => reject(new Error('免費骨架模型：貼圖未能讀取'))
      image.src = url
    })
    return image
  }
  finally {
    URL.revokeObjectURL(url)
  }
}

function boundsOf(skeleton, pose) {
  const bounds = [Infinity, Infinity, -Infinity, -Infinity]
  let vertices = 0
  for (const quad of pose.quads(skeleton)) {
    for (const [x, y] of quad.positions) {
      if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 1e7 || Math.abs(y) > 1e7 || ++vertices > 100000)
        throw new Error('免費骨架模型：變換超出安全範圍')
      bounds[0] = Math.min(bounds[0], x)
      bounds[1] = Math.min(bounds[1], y)
      bounds[2] = Math.max(bounds[2], x)
      bounds[3] = Math.max(bounds[3], y)
    }
  }
  if (!vertices || bounds[2] - bounds[0] < 0.001 || bounds[3] - bounds[1] < 0.001)
    throw new Error('免費骨架模型：沒有可顯示的圖像')
  return bounds
}

/** Local Blob bundle only. Callers must separately verify asset rights and server-side limits. */
export async function createFreeSkeletalPlayer(canvas, bundle, options = {}) {
  const checked = validateFreeSkeletalBundle(bundle)
  const { skeleton, warnings } = readSkeletonJson(checked.json, 'neighbour-free-skeleton')
  const pose = new Pose(skeleton)
  const initialBounds = boundsOf(skeleton, pose)
  const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true })
  if (!gl)
    throw new Error('裝置暫時無法顯示此免費骨架模型；請選擇 Live2D 或 VRM')
  const renderer = new WebGLRenderer(gl)
  const textures = new Map()
  const images = []
  const state = new AnimationState()
  let disposed = false
  let mouth = 0
  let reducedMotion = Boolean(options.reducedMotion)
  const mouthIndex = skeleton.bones.findIndex(bone => /^(?:mouth|mouth_open|jaw)$/iu.test(bone.name))
  const names = skeleton.animations.map(animation => animation.name)
  const available = new Set(names)
  const aliases = {
    greet: ['wave', 'greet', 'hello'],
    wave: ['wave', 'greet', 'hello'],
    idle: ['idle', 'breath'],
    happy: ['happy', 'wave'],
    care: ['care', 'listen', 'idle'],
    listen: ['listen', 'idle'],
  }

  function dispose() {
    if (disposed)
      return
    disposed = true
    state.stop()
    for (const texture of textures.values())
      renderer.deleteTexture(texture)
    textures.clear()
    for (const image of images)
      image.close?.()
    renderer.dispose()
  }

  try {
    for (const page of checked.atlas.pages) {
      const image = await decodeTexture(bundle.pages[page.name], page.width, page.height)
      images.push(image)
      if (image.width !== page.width || image.height !== page.height
        || image.width * image.height > FREE_SKELETAL_LIMITS.texturePixels) {
        throw new Error('免費骨架模型：實際貼圖尺寸與清單不符')
      }
      textures.set(page.name, renderer.createTexture(image, { pma: page.pma, linear: true }))
    }
  }
  catch (error) {
    dispose()
    throw error
  }
  const textureLookup = atlasLookup(checked.atlas, page => textures.get(page.name) ?? null)

  function playAction(name, loop = false) {
    if (disposed || reducedMotion)
      return false
    const candidates = aliases[name] ?? [name]
    const animation = candidates.find(candidate => available.has(candidate))
    if (!animation)
      return false
    state.setAnimation(skeleton, 0, animation, Boolean(loop), 0.12)
    return true
  }

  function tick(dt = 1 / 60) {
    if (disposed)
      return
    if (!reducedMotion)
      state.update(skeleton, clamp(dt, 0, 0.1))
    state.apply(skeleton, pose)
    if (mouthIndex >= 0) {
      // Apply after animation; reset each frame prevents accumulating scale drift.
      pose.local[mouthIndex].scale_y *= 0.2 + mouth * 0.8
      pose.updateWorld(skeleton)
    }
    boundsOf(skeleton, pose)
    const width = Math.min(4096, Math.max(1, canvas.width))
    const height = Math.min(4096, Math.max(1, canvas.height))
    const [left, bottom, right, top] = initialBounds
    const spanX = Math.max(1, right - left)
    const spanY = Math.max(1, top - bottom)
    // Extra space keeps an animated arm inside the viewport.
    const zoom = 0.70 * Math.min(width / spanX, height / spanY)
    gl.viewport(0, 0, width, height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    renderer.begin(width, height, { x: (left + right) / 2, y: (bottom + top) / 2, zoom })
    renderer.drawSkeleton(skeleton, pose, textureLookup)
    renderer.end()
  }

  playAction('idle', true)
  tick(0)
  return {
    tick,
    dispose,
    playAction,
    setMouthOpen(value) { mouth = clamp(value, 0, 1) },
    setReducedMotion(value) { reducedMotion = Boolean(value) },
    capabilities: Object.freeze({ animations: names, mouth: mouthIndex >= 0, format: bundle.format, warnings }),
    // Numeric snapshot only; useful for isolated animation regressions, not executable model data.
    snapshot() {
      return { disposed, mouth, bones: pose.local.map((bone, index) => ({ name: skeleton.bones[index].name, ...bone })), drawCalls: renderer.drawCalls, width: canvas.width, height: canvas.height }
    },
  }
}
