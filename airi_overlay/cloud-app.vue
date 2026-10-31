<script setup lang="ts">
import { useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useAiriCardStore } from '@proj-airi/stage-ui/stores/modules/airi-card'
import { useSettings, useSettingsAudioDevice } from '@proj-airi/stage-ui/stores/settings'
import { ErrorBoundary } from '@proj-airi/ui'
import { defineAsyncComponent, onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'

import '../../../packages/stage-ui-live2d/src/cloud-csp'

// Resident startup must not download the staff card/model editor modules.
const CloudSettings = defineAsyncComponent(() => import('./modules/cloud-settings.vue'))
const display = useDisplayModelsStore()
const settings = useSettings()
const audio = useSettingsAudioDevice()
const card = useAiriCardStore()
const settingsMode = new URLSearchParams(location.search).get('settings') === '1'
onMounted(async () => {
  if (settingsMode)
    return
  await display.loadDisplayModelsFromIndexedDB()
  await settings.initializeStageModel()
  card.initialize()
  const presentation = Reflect.get(globalThis, '__NEIGHBOUR_PRESENTATION__')
  if (card.activeCard && presentation?.airi) {
    // Keep other browser library cards intact, including unpublished edits.
    const base = card.activeCard
    card.cards.set('neighbour-cloud-profile', { ...base, extensions: { ...base.extensions,
      airi: { ...base.extensions.airi, modules: { ...base.extensions.airi.modules,
        displayModelId: presentation.airi.stage_model, activeBackgroundId: presentation.airi.scene_background } } } })
    card.activeCardId = 'neighbour-cloud-profile'
  }
  await audio.initialize()
})
onUnmounted(() => {
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
