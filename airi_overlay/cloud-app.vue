<script setup lang="ts">
import { useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useAiriCardStore } from '@proj-airi/stage-ui/stores/modules/airi-card'
import { useSettings, useSettingsAudioDevice } from '@proj-airi/stage-ui/stores/settings'
import { ErrorBoundary } from '@proj-airi/ui'
import { defineAsyncComponent, h, onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'

import '../../../packages/stage-ui-live2d/src/cloud-csp'
import './modules/cloud-resident.css'
import { installCloudAiriRuntime, prepareCloudAiriRuntime, publishedRuntime } from './modules/cloud-airi-runtime'
import { installSharedModelLoader, loadSharedModel, sharedModelPattern } from './modules/cloud-shared-models'
import { createReadiness } from './modules/cloud-readiness.js'

// Resident startup must not download the staff card/model editor modules.
const CloudSettings = defineAsyncComponent({ loader: () => import('./modules/cloud-settings.vue'),
  loadingComponent: { render: () => h('p', { role: 'status' }, '正在載入 AIRI 設定…') }, delay: 0, timeout: 45000 })
installSharedModelLoader()
prepareCloudAiriRuntime()
const display = useDisplayModelsStore()
const settings = useSettings()
const audio = useSettingsAudioDevice()
const card = useAiriCardStore()
const settingsMode = new URLSearchParams(location.search).get('settings') === '1'
const startup = createReadiness((value: object) => parent.postMessage(value, location.origin))
function avatarReady(event: Event) {
  startup.update('avatar', (event as CustomEvent).detail.state)
}
function interfaceReady() {
  startup.update('interface', 'ready')
}
function inputReady(event: Event) {
  const state = (event as CustomEvent).detail
  const intentionallyPaused = publishedRuntime().hearing.microphone_enabled === false
  startup.update('input', state === 'ready' || (state === 'paused' && intentionallyPaused) ? 'ready' : ['failed', 'paused', 'waiting'].includes(state) ? 'action' : 'pending')
}
if (!settingsMode) {
  window.addEventListener('resident-render-state', avatarReady)
  window.addEventListener('resident-conversation-ready', interfaceReady)
  window.addEventListener('resident-input-state', inputReady)
}
let modelTimer: ReturnType<typeof setInterval> | undefined
let refreshingModel = false
async function refreshPublishedModel() {
  const idle = Reflect.get(globalThis, '__NEIGHBOUR_RESIDENT_IDLE__')
  if (settingsMode || refreshingModel || document.hidden || typeof idle !== 'function' || !idle())
    return
  refreshingModel = true
  try {
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch('/api/v1/resident/presentation', { signal: AbortSignal.timeout(10000) })
    if (!response.ok)
      return
    const profile = await response.json()
    const model = profile.airi?.stage_model
    if (model === settings.stageModelSelected && settings.stageModelSelectedDisplayModel?.id === model)
      return
    if (sharedModelPattern.test(model))
      await loadSharedModel(model)
    else if (!['preset-live2d-1', 'preset-live2d-2', 'preset-vrm-1', 'preset-vrm-2'].includes(model))
      return
    if (!idle() || document.hidden)
      return
    settings.stageModelSelected = model
    await settings.updateStageModel()
  }
  catch { /* Keep the current rendered character, never interrupt a conversation. */ }
  finally { refreshingModel = false }
}
onMounted(async () => {
  if (settingsMode)
    return
  // Initialize alongside the child's shared request, before network waits.
  // A live stream already belongs to this frame and must not be reopened.
  const audioStartup = audio.stream?.getAudioTracks().some(track => track.readyState === 'live') ? undefined : audio.initialize()
  try {
  const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
  const response = await transport.fetch('/api/v1/resident/readiness', { signal: AbortSignal.timeout(12000) })
  if (!response.ok)
    throw new Error('runtime_configuration_unavailable')
  const services = await response.json()
  if (services.configured?.['cloudflare-workers-ai'] !== true || services.configured?.['microsoft-speech'] !== true
    || (publishedRuntime().hearing.microphone_enabled && services.configured?.['openai-compatible-audio-transcription'] !== true))
    throw new Error('runtime_configuration_incomplete')
  await display.loadDisplayModelsFromIndexedDB()
  await settings.initializeStageModel()
  card.initialize()
  const presentation = Reflect.get(globalThis, '__NEIGHBOUR_PRESENTATION__')
  if (card.activeCard && presentation?.airi) {
    // Keep other browser library cards intact, including unpublished edits.
    const base = card.activeCard
    const runtime = publishedRuntime()
    card.cards.set('neighbour-cloud-profile', { ...base, extensions: { ...base.extensions,
      airi: { ...base.extensions.airi, modules: { ...base.extensions.airi.modules,
        consciousness: runtime.consciousness, speech: runtime.speech,
        displayModelId: presentation.airi.stage_model, activeBackgroundId: presentation.airi.scene_background } } } })
    card.activeCardId = 'neighbour-cloud-profile'
  }
  installCloudAiriRuntime()
  await audioStartup
  startup.update('runtime', 'ready')
  modelTimer = setInterval(refreshPublishedModel, 60000)
  window.addEventListener('estate:resident-session-ended', refreshPublishedModel)
  }
  catch { startup.update('runtime', 'failed') }
})
onUnmounted(() => {
  startup.close()
  window.removeEventListener('resident-render-state', avatarReady)
  window.removeEventListener('resident-conversation-ready', interfaceReady)
  window.removeEventListener('resident-input-state', inputReady)
  clearInterval(modelTimer)
  window.removeEventListener('estate:resident-session-ended', refreshPublishedModel)
  audio.enabled = false
})
</script>

<template>
  <ErrorBoundary :title="settingsMode ? '設定暫時未能顯示，請重新開啟數字人設定。' : '畫面暫時未能顯示，請重新進入居民服務台。'">
    <CloudSettings v-if="settingsMode" />
    <RouterView v-else v-slot="{ Component }">
      <component :is="Component" />
    </RouterView>
  </ErrorBoundary>
</template>
