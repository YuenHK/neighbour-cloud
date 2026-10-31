<script setup lang="ts">
// AIRI's actual editors and stores. No credentials or resident records.

import { useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useAiriCardStore } from '@proj-airi/stage-ui/stores/modules/airi-card'
import { useSettings } from '@proj-airi/stage-ui/stores/settings'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'

const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
const saved = Reflect.get(globalThis, '__NEIGHBOUR_PRESENTATION__')
if (!saved?.revision || !transport)
  throw new Error('verified_staff_profile_required')
const card = useAiriCardStore()
const display = useDisplayModelsStore()
const settings = useSettings()
const router = useRouter()
const route = useRoute()
const tab = ref('airi')
const deviceOnly = computed(() => !['/settings', '/settings/airi-card', '/settings/models', '/settings/scene'].includes(route.path))
const status = ref('角色及模型編輯後，按「儲存至平台」套用到所有居民裝置。')
const busy = ref(false)
const ready = ref(false)
const greeting = ref(saved.greeting)
const persona = ref(saved.persona)
const colour = ref(saved.background)
const scene = ref(saved.airi?.scene_background ?? 'none')
let revision = saved.revision
let uncertain = false
let observer: ResizeObserver | undefined
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
  await display.loadDisplayModelsFromIndexedDB()
  await settings.initializeStageModel()
  card.initialize()
  // Sync the active character only; never delete other browser library cards.
  const stored = saved.airi?.card
  const current = card.activeCard
  if (current) {
    card.cards.set('neighbour-cloud-profile', { ...current, name: stored?.name ?? saved.name, description: stored?.description ?? '', personality: stored?.personality ?? '', scenario: stored?.scenario ?? '', systemPrompt: stored?.system_prompt ?? '', extensions: { ...current.extensions, airi: { ...current.extensions.airi, modules: { ...current.extensions.airi.modules, displayModelId: saved.airi?.stage_model ?? 'preset-live2d-2', activeBackgroundId: scene.value } } } })
    card.activeCardId = 'neighbour-cloud-profile'
  }
  settings.disableTransitions = true
  await router.replace('/settings')
  ready.value = true
  parent.postMessage({ type: 'estate:settings-ready' }, location.origin)
  window.addEventListener('wheel', forwardWheel, { passive: false })
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
  window.removeEventListener('wheel', forwardWheel)
})

async function save() {
  if (busy.value || !ready.value || uncertain)
    return
  const current = card.activeCard
  if (!current)
    return
  if (!['preset-live2d-1', 'preset-live2d-2', 'preset-vrm-1', 'preset-vrm-2'].includes(settings.stageModelSelected)) {
    status.value = '匯入模型仍只保存在本瀏覽器；請選內建模型才可同步至雲端。原檔會保留。'
    return
  }
  const background = current.extensions?.airi?.modules?.activeBackgroundId ?? scene.value
  if (!['none', 'builtin:cozy-tea-corner', 'builtin:cute-streaming-room'].includes(background)) {
    status.value = '自訂背景仍只保存在此裝置；同步至平台請先選內建背景。原檔會保留。'
    return
  }
  const payload = { expected_revision: revision, name: current.name, greeting: greeting.value, persona: persona.value, background: colour.value, airi: { stage_model: settings.stageModelSelected, scene_background: background, card: { name: current.name, description: current.description ?? '', personality: current.personality ?? '', scenario: current.scenario ?? '', system_prompt: current.systemPrompt ?? '' } } }
  busy.value = true
  status.value = '正在儲存…'
  try {
    const response = await transport.fetch('/api/v1/service-desk/presentation', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(15000) })
    if (!response.ok) {
      if (response.status === 422) {
        status.value = '名稱最多 40 字；角色說明、性格及情境各最多 1,200 字，角色指示最多 4,000 字。請調整後儲存。'
        return
      }
      throw new Error('save_unconfirmed')
    }
    const value = await response.json()
    if (value.revision !== revision + 1)
      throw new Error('save_unconfirmed')
    revision = value.revision
    status.value = '已儲存；重新進入居民服務台會使用這個角色、模型及背景。'
  }
  catch {
    uncertain = true
    status.value = '未能確認儲存結果，草稿保留。請先重新開啟設定核對，避免覆蓋另一位職員的更新。'
  }
  finally { busy.value = false }
}
</script>

<template>
  <div class="cloud-airi-settings estate-inline-settings">
    <nav class="cloud-airi-tabs" aria-label="AIRI 設定項目">
      <button v-for="item in [['airi', '所有 AIRI 設定'], ['opening', '居民開場'], ['services', '雲端服務']]" :key="item[0]" type="button" :aria-pressed="tab === item[0]" @click="tab = item[0]">
        {{ item[1] }}
      </button>
    </nav>
    <div class="cloud-airi-save">
      <button type="button" :disabled="busy || !ready || uncertain" @click="save">
        儲存至平台
      </button>
      <p role="status">
        {{ status }}
      </p>
    </div>
    <p v-if="!ready">
      正在載入 AIRI 設定…
    </p>
    <template v-else>
      <section v-if="tab === 'airi'" class="cloud-model-editor">
        <nav class="cloud-airi-shortcuts" aria-label="AIRI 設定導航">
          <button type="button" @click="router.push('/settings')">
            ← 所有設定
          </button>
          <button type="button" @click="router.push('/settings/system/general')">
            一般設定
          </button>
          <button type="button" @click="router.push('/settings/system/color-scheme')">
            外觀及色彩
          </button>
        </nav>
        <p v-if="deviceOnly" class="cloud-device-notice">
          以下為 AIRI 原版的此裝置設定；不會更換平台的 Gemma、曉曼、Whisper 或 Tavily，亦不會取得平台金鑰。資料匯出／重設只影響此瀏覽器，不會清除雲端居民個案。
        </p>
        <p v-else>
          角色卡、內建模型及內建場景可按「儲存至平台」同步；匯入的自訂檔案及其餘原版設定保留在此裝置。
        </p>
        <RouterView v-slot="{ Component }">
          <component :is="Component" />
        </RouterView>
      </section>
      <section v-else-if="tab === 'opening'" class="cloud-opening">
        <label>開場白<textarea v-model="greeting" rows="2" maxlength="200" /></label>
        <label>補充聊天風格<textarea v-model="persona" rows="3" maxlength="1200" /></label>
        <label>畫面色調<select v-model="colour"><option value="mint">柔和薄荷綠</option><option value="sky">清新淺藍</option><option value="warm">溫暖米色</option></select></label>
      </section>
      <section v-else>
        <h2>平台管理的免費服務</h2>
        <p>對話：Cloudflare Gemma；廣東話朗讀：Microsoft Azure 曉曼 F0；語音輸入：Cloudflare Whisper；網上搜尋：Tavily。</p>
        <p>本頁不會更換這些供應商或啟用收費服務。角色卡內其他服務選擇不會套用到居民對話。用量可在「服務用量」查看。</p>
      </section>
    </template>
  </div>
</template>

<style>
.cloud-airi-settings{padding:16px;width:100%;height:auto!important;min-height:600px;color:#194f49}
.cloud-airi-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:16px}
.cloud-airi-tabs button,.cloud-airi-save button{border:1px solid #cadbd3;border-radius:12px;padding:12px;background:#fff}
body.service-theme .cloud-airi-tabs button[aria-pressed=true],body.service-theme .cloud-airi-save button{background:#21695d;color:white}
.cloud-airi-save{display:flex;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.cloud-airi-save p{flex:1;min-width:180px;font-size:14px}
.cloud-opening label{display:grid;gap:8px;margin-block:20px}.cloud-opening textarea,.cloud-opening select{padding:12px;border:1px solid #cadbd3;border-radius:10px}
.cloud-model-editor{position:relative;min-height:650px}
.cloud-airi-shortcuts{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}.cloud-airi-shortcuts button{padding:10px;border:1px solid #cadbd3;border-radius:10px}.cloud-device-notice{padding:12px;background:#fff4d9;border-radius:12px;margin-bottom:16px}
@media(max-width:680px){.cloud-airi-tabs{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
