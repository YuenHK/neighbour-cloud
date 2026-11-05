<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

import { createFreeSkeletalPlayer } from './free-skeletal-player.js'
import { loadFreeSkeletalArchive } from './free-skeletal-zip'

interface FreeSkeletalBundle {
  format: 'rigby-json-zip/v1'
  skeletonText: string
  atlasText: string
  pages: Record<string, Blob>
}

const props = withDefaults(defineProps<{
  bundle?: FreeSkeletalBundle
  modelSrc?: string
  modelId?: string
  audioSource?: AudioNode
  nowSpeaking?: boolean
  mouthOpen?: number
  paused?: boolean
  reducedMotion?: boolean
}>(), { mouthOpen: 0, paused: false, reducedMotion: false })

const emit = defineEmits<{
  ready: [capabilities: { animations: string[], mouth: boolean, format: string }]
  error: [message: string]
}>()

const canvas = ref<HTMLCanvasElement>()
const errorMessage = ref('')
const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })
let player: Awaited<ReturnType<typeof createFreeSkeletalPlayer>> | undefined
let frame = 0
let generation = 0
let observer: ResizeObserver | undefined
let previous = 0
let stopped = false
let analyser: AnalyserNode | undefined
let analysedSource: AudioNode | undefined
const samples = new Float32Array(256)
let lastGesture = ''

function clearAudio() {
  try {
    if (analyser)
      analysedSource?.disconnect(analyser)
  }
  catch { /* Only our analysis edge is disconnected; playback is untouched. */ }
  analyser?.disconnect()
  analyser = undefined
  analysedSource = undefined
}

function bindAudio(source?: AudioNode) {
  clearAudio()
  if (!source)
    return
  analyser = source.context.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)
  analysedSource = source
}

function release() {
  cancelAnimationFrame(frame)
  player?.dispose()
  player = undefined
}

function resize() {
  if (!canvas.value)
    return
  const bounds = canvas.value.getBoundingClientRect()
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  canvas.value.width = Math.min(4096, Math.max(1, Math.round(bounds.width * dpr)))
  canvas.value.height = Math.min(4096, Math.max(1, Math.round(bounds.height * dpr)))
  player?.tick(0)
}

function render(now: number) {
  const dt = previous ? (now - previous) / 1000 : 0
  previous = now
  if (!props.paused && !document.hidden) {
    try {
      if (analyser && props.nowSpeaking) {
        analyser.getFloatTimeDomainData(samples)
        const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length)
        player?.setMouthOpen(Math.min(1, Math.max(0, (rms - 0.006) * 12)))
      }
      else {
        player?.setMouthOpen(props.mouthOpen)
      }
      const gesture = Reflect.get(globalThis, '__NEIGHBOUR_RESIDENT_GESTURE__')
      if (gesture && `${gesture.kind}:${gesture.start}` !== lastGesture) {
        lastGesture = `${gesture.kind}:${gesture.start}`
        player?.playAction(gesture.kind === 'greeting' ? 'greet' : gesture.kind)
      }
      player?.tick(dt)
    }
    catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '模型暫時未能顯示'
      emit('error', errorMessage.value)
      release()
      return
    }
  }
  frame = requestAnimationFrame(render)
}

async function load() {
  const current = ++generation
  release()
  componentState.value = 'loading'
  errorMessage.value = ''
  if (!canvas.value || stopped)
    return
  try {
    let bundle = props.bundle
    if (!bundle) {
      if (!props.modelSrc?.startsWith('blob:'))
        throw new Error('免費骨架模型只可從已核對的本機模型檔載入。')
      const response = await fetch(props.modelSrc)
      const archive = await response.blob()
      bundle = await loadFreeSkeletalArchive(archive)
    }
    const next = await createFreeSkeletalPlayer(canvas.value, bundle, { reducedMotion: props.reducedMotion })
    if (current !== generation || stopped) {
      next.dispose()
      return
    }
    player = next
    player.setMouthOpen(props.mouthOpen)
    resize()
    previous = 0
    frame = requestAnimationFrame(render)
    componentState.value = 'mounted'
    emit('ready', next.capabilities)
  }
  catch (error) {
    if (current === generation && !stopped) {
      errorMessage.value = error instanceof Error ? error.message : '模型暫時未能顯示'
      emit('error', errorMessage.value)
    }
  }
}

watch([() => props.bundle, () => props.modelSrc], () => {
  void load()
})
watch(() => props.mouthOpen, value => player?.setMouthOpen(value))
watch(() => props.reducedMotion, value => player?.setReducedMotion(value))
watch(() => props.audioSource, source => bindAudio(source))

onMounted(() => {
  observer = new ResizeObserver(resize)
  if (canvas.value)
    observer.observe(canvas.value)
  bindAudio(props.audioSource)
  void load()
})

onUnmounted(() => {
  stopped = true
  generation += 1
  observer?.disconnect()
  clearAudio()
  release()
})

defineExpose({
  canvasElement: () => canvas.value,
  playAction: (name: string) => player?.playAction(name) ?? false,
  setMouthOpen: (amount: number) => player?.setMouthOpen(amount),
  setEmotion: (value: string | { emotion?: string }, _intensity?: number) => player?.playAction(typeof value === 'string' ? value : value.emotion ?? 'idle'),
  captureFrame: () => new Promise<Blob | undefined>((resolve) => {
    if (!canvas.value)
      return resolve(undefined)
    canvas.value.toBlob(blob => resolve(blob ?? undefined), 'image/png')
  }),
})
</script>

<template>
  <div class="free-skeletal-scene">
    <canvas ref="canvas" aria-label="免費骨架數字人" />
    <p v-if="errorMessage" role="status">
      {{ errorMessage }}
    </p>
  </div>
</template>

<style scoped>
.free-skeletal-scene { position: relative; width: 100%; height: 100%; min-height: 220px; }
canvas { display: block; width: 100%; height: 100%; }
p { position: absolute; inset: auto 1rem 1rem; padding: .75rem; border-radius: .75rem; background: #fffef2ed; color: #5a4137; }
</style>
