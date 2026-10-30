<script setup lang="ts">
import { useL2dViewControl } from '@proj-airi/stage-ui-live2d'
import { useModelStore, useThreeViewControl } from '@proj-airi/stage-ui-three'
import { useSettings } from '@proj-airi/stage-ui/stores/settings'
import { computed, onUnmounted, ref } from 'vue'

import uncleSam from './resident-uncle-sam.svg?url'

import { inspectResidentView, isCameraGesture } from './resident-view-guard.js'

const model = useModelStore()
const settings = useSettings()
const view = useThreeViewControl()
const live2d = useL2dViewControl()
const gestureBlocked = ref(false)
let start: { x: number, y: number } | undefined
let timer: ReturnType<typeof setTimeout> | undefined
const unsafeView = computed(() => !['safe', 'pending'].includes(inspectResidentView({
  renderer: settings.stageModelRenderer,
  camera: model.cameraPosition,
  origin: model.modelOrigin,
  height: model.modelSize.y,
  fov: view.cameraFOV.value,
  scale: live2d.scale.value,
})))
function block() {
  gestureBlocked.value = true
  clearTimeout(timer)
  timer = setTimeout(() => {
    gestureBlocked.value = false
  }, 3000)
}
function down(event: PointerEvent) {
  start = { x: event.clientX, y: event.clientY }
}
function move(event: PointerEvent) {
  if (event.pointerType === 'touch' && start && Math.abs(event.clientY - start.y) > Math.abs(event.clientX - start.x))
    return
  if (event.buttons && isCameraGesture(start, { x: event.clientX, y: event.clientY })) {
    start = undefined
    block()
  }
}
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div class="resident-camera-boundary" @pointerdown="down" @pointermove="move" @pointerup="start = undefined" @pointercancel="start = undefined" @wheel.prevent="block" @contextmenu.prevent="block">
    <div v-if="gestureBlocked || unsafeView" class="resident-camera-stop" role="status" aria-live="polite">
      <img :src="uncleSam" alt="山姆大叔示意停止" width="180" height="203">
      <strong>請尊重數字人</strong>
      <p>鏡頭保持正常視角，唔可以偷睇或放大敏感部位。</p>
      <p v-if="unsafeView">
        請職員在數字人設定調整視角；你仍可繼續對話。
      </p>
      <button v-else type="button" @click.stop="gestureBlocked = false">
        返回對話
      </button>
    </div>
  </div>
</template>

<style scoped>
.resident-camera-boundary { position: absolute; inset: 0; z-index: 30; touch-action: pan-y; }
.resident-camera-stop { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 24px; background: #edf4ef; color: #17434a; text-align: center; }
.resident-camera-stop img { max-height: 40%; width: auto; }
.resident-camera-stop p { max-width: 28em; margin: 0; }
.resident-camera-stop strong { font-size: 1.4rem; }
.resident-camera-stop button { padding: 10px 22px; border: 1px solid #317567; border-radius: 12px; background: white; color: #17434a; cursor: pointer; }
</style>
