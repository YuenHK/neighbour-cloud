<script setup lang="ts">
// AIRI's actual editors and stores. No credentials or resident records.

import { DisplayModelFormat, useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useAiriCardStore } from '@proj-airi/stage-ui/stores/modules/airi-card'
import { useSettings } from '@proj-airi/stage-ui/stores/settings'
import { computed, nextTick, onMounted, onUnmounted, provide, ref } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'

import CloudAiriMemory from './cloud-airi-memory.vue'
import CloudAiriProvider from './cloud-airi-provider.vue'
import CloudModelGallery from './cloud-model-gallery.vue'

import { cloudRuntime, collectRuntime, installCloudAiriRuntime, managedProviderIds, prepareCloudAiriRuntime, publishedRuntime } from './cloud-airi-runtime'
import { ModelUploadRejected, sharedModelPattern, uploadSharedModel } from './cloud-shared-models'

const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
const saved = Reflect.get(globalThis, '__NEIGHBOUR_PRESENTATION__')
if (!saved?.revision || !transport)
  throw new Error('verified_staff_profile_required')
prepareCloudAiriRuntime()
const card = useAiriCardStore()
const display = useDisplayModelsStore()
const settings = useSettings()
const router = useRouter()
const route = useRoute()
const tab = ref('airi')
const managedProvider = computed(() => route.path.startsWith('/settings/providers/') ? managedProviderIds.find(id => route.path.endsWith(`/${id}`)) : undefined)
const memoryPage = computed(() => ['/settings/memory', '/settings/modules/memory-short-term', '/settings/modules/memory-long-term'].includes(route.path))
const deviceOnly = computed(() => !managedProvider.value && !memoryPage.value && !['/settings', '/settings/airi-card', '/settings/models', '/settings/scene', '/settings/modules', '/settings/modules/speech', '/settings/modules/consciousness', '/settings/modules/hearing', '/settings/modules/web-search'].includes(route.path))
const status = ref('角色及模型編輯後，按「儲存至平台」套用到所有居民裝置。')
provide('neighbour-model-selector', CloudModelGallery)
provide('neighbour-model-license-accepted', ref(false))
provide('neighbour-model-status', (message: string) => {
  status.value = message
})
const busy = ref(false)
const ready = ref(false)
const greeting = ref(saved.greeting)
const persona = ref(saved.persona)
const colour = ref(saved.background)
const scene = ref(saved.airi?.scene_background ?? 'none')
let revision = saved.revision
let uncertain = false
let observer: ResizeObserver | undefined
let dialogs: MutationObserver | undefined
function positionDialogs() {
  const frame = window.frameElement
  if (!frame || parent === window)
    return
  const bounds = frame.getBoundingClientRect()
  const top = Math.max(0, -bounds.top) + 16
  const bottom = Math.min(window.innerHeight, parent.innerHeight - bounds.top) - 16
  if (bottom - top < 120)
    return
  document.querySelectorAll<HTMLElement>('[role="dialog"][data-state="open"]').forEach((dialog) => {
    dialog.style.top = `${(top + bottom) / 2}px`
    dialog.style.bottom = 'auto'
    dialog.style.left = '50%'
    dialog.style.transform = 'translate(-50%, -50%)'
    dialog.style.maxHeight = `${bottom - top}px`
    dialog.style.overflowY = 'auto'
  })
}
function forwardWheel(event: WheelEvent) {
  if (event.ctrlKey || event.defaultPrevented || !event.deltaY)
    return
  for (const node of event.composedPath()) {
    if (!(node instanceof HTMLElement) || node === document.body || node === document.documentElement)
      continue
    const style = getComputedStyle(node)
    if (/auto|scroll/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1
      && (event.deltaY < 0 ? node.scrollTop > 0 : node.scrollTop + node.clientHeight < node.scrollHeight - 1)) {
      return
    }
  }
  event.preventDefault()
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1
  parent.postMessage({ type: 'estate:settings-wheel', deltaY: Math.max(-2000, Math.min(2000, event.deltaY * unit)) }, location.origin)
}

onMounted(async () => {
  // Resolve the native top-level editor chunks without mounting hardware or
  // provider editors. Later tab visits reuse the same module promises.
  const routes = router.getRoutes().filter(item => item.meta?.settingsEntry || ['/settings', '/settings/system/general', '/settings/system/color-scheme'].includes(item.path))
  const loaders = routes.flatMap(item => Object.values(item.components ?? {}).filter(value => typeof value === 'function'))
  let cursor = 0
  await Promise.all(Array.from({ length: Math.min(3, loaders.length) }, async () => {
    while (cursor < loaders.length) {
      const loader = loaders[cursor++] as () => Promise<unknown>
      await loader()
    }
  }))
  await display.initialize()
  await display.loadDisplayModelsFromIndexedDB()
  await settings.initializeStageModel()
  card.initialize()
  try {
    const response = await transport.fetch('/api/v1/service-desk/airi-services', { signal: AbortSignal.timeout(12000) })
    if (!response.ok)
      throw new Error('services_not_verified')
    const services = await response.json()
    installCloudAiriRuntime(services.configured)
  }
  catch {
    status.value = '未能核對已接入的服務，原有設定保留；請重新開啟此頁再試。'
    return
  }
  // Sync the active character only; never delete other browser library cards.
  const stored = saved.airi?.card
  const current = card.activeCard
  if (current) {
    const runtime = publishedRuntime()
    card.cards.set('neighbour-cloud-profile', { ...current, name: stored?.name ?? saved.name, description: stored?.description ?? '', personality: stored?.personality ?? '', scenario: stored?.scenario ?? '', systemPrompt: stored?.system_prompt ?? '', extensions: { ...current.extensions, airi: { ...current.extensions.airi, modules: { ...current.extensions.airi.modules, consciousness: runtime.consciousness, speech: runtime.speech, displayModelId: saved.airi?.stage_model ?? 'preset-live2d-2', activeBackgroundId: scene.value } } } })
    card.activeCardId = 'neighbour-cloud-profile'
  }
  settings.disableTransitions = true
  await router.replace('/settings')
  ready.value = true
  parent.postMessage({ type: 'estate:settings-ready' }, location.origin)
  window.addEventListener('wheel', forwardWheel, { passive: false })
  parent.addEventListener('scroll', positionDialogs, { passive: true })
  parent.addEventListener('resize', positionDialogs)
  dialogs = new MutationObserver(positionDialogs)
  dialogs.observe(document.body, { childList: true, subtree: true })
  await nextTick()
  const root = document.querySelector('.cloud-airi-settings')
  if (root) {
    observer = new ResizeObserver(() => {
      const height = Math.ceil(root.getBoundingClientRect().height) + 24
      if (height > 100)
        parent.postMessage({ type: 'estate:settings-size', height }, location.origin)
    })
    observer.observe(root)
  }
})
onUnmounted(() => {
  observer?.disconnect()
  dialogs?.disconnect()
  parent.removeEventListener('scroll', positionDialogs)
  parent.removeEventListener('resize', positionDialogs)
  window.removeEventListener('wheel', forwardWheel)
})

async function save() {
  if (busy.value || !ready.value || uncertain)
    return
  const current = card.activeCard
  if (!current)
    return
  const selected = settings.stageModelSelected
  const builtin = ['preset-live2d-1', 'preset-live2d-2', 'preset-vrm-1', 'preset-vrm-2'].includes(selected)
  const localModel = !builtin && !sharedModelPattern.test(selected) ? await display.getDisplayModel(selected) : undefined
  if (!builtin && !sharedModelPattern.test(selected)
    && (!localModel || localModel.type !== 'file' || ![DisplayModelFormat.Live2dZip, DisplayModelFormat.VRM, DisplayModelFormat.RigbyJsonZip].includes(localModel.format))) {
    status.value = '共享匯入支援 Live2D、VRM 及免費 Rigby JSON ZIP；其他格式的原檔仍保存在此裝置。'
    return
  }
  const background = current.extensions?.airi?.modules?.activeBackgroundId ?? scene.value
  if (!['none', 'builtin:cozy-tea-corner', 'builtin:cute-streaming-room'].includes(background)) {
    status.value = '自訂背景仍只保存在此裝置；同步至平台請先選內建背景。原檔會保留。'
    return
  }
  busy.value = true
  status.value = '正在儲存…'
  const payload = { expected_revision: revision, name: current.name, greeting: greeting.value, persona: persona.value, background: colour.value, airi: { stage_model: selected, scene_background: background, runtime: collectRuntime(), card: { name: current.name, description: current.description ?? '', personality: current.personality ?? '', scenario: current.scenario ?? '', system_prompt: current.systemPrompt ?? '' } } }
  try {
    let model = selected
    if (localModel?.type === 'file') {
      status.value = '正在上載及核對模型，完成後發佈到平台；請保留此頁。'
      model = (await uploadSharedModel(localModel.file, localModel.format)).id
    }
    payload.airi.stage_model = model
    const response = await transport.fetch('/api/v1/service-desk/presentation', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(15000) })
    if (!response.ok) {
      if (response.status === 422) {
        status.value = '請核對設定：平台已接入免費 Gemma、Microsoft 語音服務及 Whisper；其他供應商尚未啟用。語速 0.5–2 倍、音調／音量 ±30%，交接 1–3 分鐘。角色指示最多 4,000 字。未覆蓋原設定。'
        return
      }
      throw new Error('save_unconfirmed')
    }
    const value = await response.json()
    if (value.revision !== revision + 1)
      throw new Error('save_unconfirmed')
    revision = value.revision
    settings.stageModelSelected = model
    status.value = '已儲存至平台；新進入的裝置會用這組設定。已開啟的居民畫面會在閒置或下一位交接時更新模型，不中斷對話。'
  }
  catch (error) {
    if (error instanceof ModelUploadRejected) {
      status.value = error.message
      return
    }
    uncertain = true
    status.value = '未能確認儲存結果，草稿保留。請先重新開啟設定核對，避免覆蓋另一位職員的更新。'
  }
  finally { busy.value = false }
}
</script>

<template>
  <div class="cloud-airi-settings estate-inline-settings">
    <nav class="cloud-airi-toolbar" aria-label="AIRI 設定項目">
      <button type="button" :aria-pressed="tab === 'airi' && route.path === '/settings'" @click="tab = 'airi'; router.push('/settings')">
        所有 AIRI 設定
      </button>
      <button type="button" :aria-pressed="tab === 'opening'" @click="tab = 'opening'">
        居民開場
      </button>
      <button type="button" :aria-pressed="tab === 'airi' && route.path === '/settings/system/general'" @click="tab = 'airi'; router.push('/settings/system/general')">
        一般設定
      </button>
      <button type="button" :aria-pressed="tab === 'airi' && route.path === '/settings/system/color-scheme'" @click="tab = 'airi'; router.push('/settings/system/color-scheme')">
        外觀及色彩
      </button>
      <button class="cloud-airi-save" type="button" :disabled="busy || !ready || uncertain" @click="save">
        儲存至平台
      </button>
    </nav>
    <p class="cloud-airi-status" role="status">
      {{ status }}
    </p>
    <p v-if="!ready">
      正在載入 AIRI 設定…
    </p>
    <template v-else>
      <section v-if="tab === 'airi'" class="cloud-model-editor" :inert="busy">
        <p v-if="deviceOnly" class="cloud-device-notice">
          此頁為裝置專用設定；匯入檔案、硬件裝置與瀏覽器資料管理保留在本裝置。居民角色、語音、搜尋及記憶則由 AIRI 儲存至平台統一套用。
        </p>
        <p v-else>
          在 AIRI 編輯角色、語音、思維、聽覺、網上搜尋及記憶後，按「儲存至平台」套用到居民服務台。
        </p>
        <CloudAiriMemory v-if="memoryPage" />
        <CloudAiriProvider v-else-if="managedProvider" :provider-id="managedProvider" />
        <RouterView v-else v-slot="{ Component }">
          <label v-if="route.path === '/settings/modules/hearing'" class="cloud-microphone-default"><input v-model="cloudRuntime.hearing.microphone_enabled" type="checkbox">居民服務台預設啟用語音輸入（此設定頁不會開咪）</label>
          <component :is="Component" />
        </RouterView>
      </section>
      <section v-else-if="tab === 'opening'" class="cloud-opening">
        <label>開場白<textarea v-model="greeting" rows="2" maxlength="200" /></label>
        <label>補充聊天風格<textarea v-model="persona" rows="3" maxlength="1200" /></label>
        <label>畫面色調<select v-model="colour"><option value="mint">柔和薄荷綠</option><option value="sky">清新淺藍</option><option value="warm">溫暖米色</option></select></label>
      </section>
    </template>
  </div>
</template>

<style>
.cloud-airi-settings{padding:16px;width:100%;height:auto!important;min-height:600px;color:#194f49}
.cloud-airi-toolbar{display:flex;flex-wrap:nowrap;gap:6px;padding:6px;border:1px solid #d9e5df;border-radius:16px;background:#eaf1ed;overflow-x:auto;scrollbar-width:thin;max-width:100%;align-items:stretch}
.cloud-airi-toolbar button{flex:1 0 auto;white-space:nowrap;border:0;border-radius:11px;padding:13px 15px;background:transparent;min-height:48px;font-size:14px}
body.service-theme .cloud-airi-toolbar button[aria-pressed=true]{background:white;box-shadow:0 2px 8px #194f4908}
body.service-theme .cloud-airi-toolbar .cloud-airi-save{background:#21695d;color:white;flex-grow:0;margin-left:4px}
.cloud-airi-toolbar button:focus-visible{outline:3px solid #86b7a4;outline-offset:-3px}.cloud-airi-status{font-size:13px;color:#638075;margin:12px 2px 18px}
.cloud-opening label{display:grid;gap:8px;margin-block:20px}.cloud-opening textarea,.cloud-opening select{padding:12px;border:1px solid #cadbd3;border-radius:10px}
.cloud-model-editor{position:relative;min-height:650px}
.cloud-device-notice{padding:12px;background:#fff4d9;border-radius:12px;margin-bottom:16px}
</style>
