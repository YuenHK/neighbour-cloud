<script setup lang="ts">
import { BackgroundProvider } from '@proj-airi/stage-layouts/components/Backgrounds'
import { useBackgroundStore } from '@proj-airi/stage-layouts/stores/background'
import { ModelSettings } from '@proj-airi/stage-ui/components/scenarios/settings/model-settings'
import { Vibrant } from 'node-vibrant/browser'
import { storeToRefs } from 'pinia'
import { ref } from 'vue'

const modelSettingsRef = ref<{ capturePreviewFrame: () => Promise<Blob | undefined> }>()
const palette = ref<string[]>([])
const embeddedSettings = window.self !== window.top
const { selectedOption, sampledColor } = storeToRefs(useBackgroundStore())

async function extractColorsFromModel() {
  const frame = await modelSettingsRef.value?.capturePreviewFrame()
  if (!frame) {
    console.error('No frame captured')
    return
  }

  const frameUrl = URL.createObjectURL(frame)
  try {
    const vibrant = new Vibrant(frameUrl)

    const paletteFromVibrant = await vibrant.getPalette()
    palette.value = Object.values(paletteFromVibrant).map(color => color?.hex).filter(it => typeof it === 'string')
  }
  finally {
    URL.revokeObjectURL(frameUrl)
  }
}
</script>

<template>
  <div flex class="relative h-full flex-col-reverse md:flex-row" :class="{ 'estate-model-settings': embeddedSettings }">
    <BackgroundProvider v-if="embeddedSettings" class="estate-model-background" :background="selectedOption" :top-color="sampledColor" />
    <ModelSettings
      ref="modelSettingsRef"
      settings-class="estate-model-controls w-100% md:w-40% lg:w-40% xl:w-25% 2xl:w-30% h-fit sm:max-h-80dvh overflow-y-scroll relative"
      live-2d-scene-class="estate-model-preview absolute max-h-[calc(100dvh-100px-56px)] w-full h-full"
      vrm-scene-class="estate-model-preview absolute max-h-[calc(100dvh-100px-56px)] w-full h-full"
      :palette="palette" @extract-colors-from-model="extractColorsFromModel"
    />
  </div>

  <div
    v-motion
    text="neutral-200/50 dark:neutral-600/20" pointer-events-none
    fixed top="[calc(100dvh-15rem)]" bottom-0 right--5 z--1
    :initial="{ scale: 0.9, opacity: 0, y: 15 }"
    :enter="{ scale: 1, opacity: 1, y: 0 }"
    :duration="500"
    size-60
    flex items-center justify-center
  >
    <div text="60" i-solar:people-nearby-bold-duotone />
  </div>
</template>

<route lang="yaml">
meta:
  layout: settings
  titleKey: settings.pages.models.title
  subtitleKey: settings.title
  descriptionKey: settings.pages.models.description
  icon: i-solar:people-nearby-bold-duotone
  settingsEntry: true
  order: 4
  stageTransition:
    name: slide
    pageSpecificAvailable: true
</route>
