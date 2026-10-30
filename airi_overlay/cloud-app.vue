<script setup lang="ts">
import { useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useSettings, useSettingsAudioDevice } from '@proj-airi/stage-ui/stores/settings'
import { ErrorBoundary } from '@proj-airi/ui'
import { onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'

import '../../../packages/stage-ui-live2d/src/cloud-csp'

const display = useDisplayModelsStore()
const settings = useSettings()
const audio = useSettingsAudioDevice()
onMounted(async () => {
  await display.loadDisplayModelsFromIndexedDB()
  await settings.initializeStageModel()
  await audio.initialize()
})
onUnmounted(() => {
  audio.enabled = false
})
</script>

<template>
  <RouterView v-slot="{ Component }">
    <ErrorBoundary title="畫面暫時未能顯示，請重新進入居民服務台。">
      <component :is="Component" />
    </ErrorBoundary>
  </RouterView>
</template>
