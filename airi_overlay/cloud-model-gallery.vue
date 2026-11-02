<script setup lang="ts">
import { errorMessageFrom } from '@moeru/std'
import { DisplayModelFormat, useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useSettings } from '@proj-airi/stage-ui/stores/settings'
import { computed, onMounted, onUnmounted, ref } from 'vue'

import gallery from './cloud-model-gallery.json'

import { modelHash } from './cloud-shared-models'

const emit = defineEmits<{ status: [message: string] }>()
const display = useDisplayModelsStore()
const settings = useSettings()
const accepted = ref(false)
const busy = ref('')
const source = ref('all')
const query = ref('')
const searching = ref(false)
const searchStatus = ref('搜尋官方及社群作者頁；未核對授權的模型不會自動轉存或發佈。')
const results = ref<{ title: string, url: string, description: string }[]>([])
interface SourceItem { title: string, url: string, author?: string, format: string, license_status: string }
interface SourceIndex { source: string, items: SourceItem[], last_success_ms: number | null, error: string }
const sourceIndexes = ref<SourceIndex[]>([])
const discoverySource = ref('all')
const discoveryFilter = ref('')
const discoveryCount = ref(24)
const discoveryStatus = ref('正在讀取已保存的圖庫目錄…')
let discoveryTimer: ReturnType<typeof setTimeout> | undefined
let discoveryClosed = false
let discoveryPolls = 0
const discovered = computed(() => sourceIndexes.value
  .filter(index => discoverySource.value === 'all' || index.source === discoverySource.value)
  .flatMap(index => index.items.map(item => ({ ...item, sourceName: index.source, reviewed: gallery.models.find(model => model.source.replace(/\/$/, '') === item.url.replace(/\/$/, '')) })))
  .filter(item => `${item.title} ${item.author ?? ''}`.toLowerCase().includes(discoveryFilter.value.toLowerCase())))
async function readSources() {
  try {
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch('/api/v1/service-desk/model-gallery/catalogue')
    if (!response.ok)
      throw new Error('catalogue_unavailable')
    const value = await response.json()
    if (discoveryClosed)
      return
    sourceIndexes.value = value.sources ?? []
    discoveryStatus.value = value.cache_unavailable
      ? '外站目錄暫未準備好；上方已核對模型仍可使用。'
      : value.refreshing
        ? '先顯示已保存目錄，正在背景檢查新模型；不影響對話或消耗 AI 額度。'
        : '啟動時自動檢查，外站讀取最多每六小時一次；失敗時保留上次目錄。'
    if (value.refreshing && discoveryPolls++ < 8)
      discoveryTimer = setTimeout(readSources, 6000)
  }
  catch {
    if (!discoveryClosed)
      discoveryStatus.value = '外站目錄未能更新；上方已核對模型不受影響。'
  }
}
onMounted(readSources)
onUnmounted(() => {
  discoveryClosed = true
  clearTimeout(discoveryTimer)
})
async function search() {
  if (searching.value)
    return
  searching.value = true
  searchStatus.value = '正在搜尋作者平台…'
  try {
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch('/api/v1/service-desk/model-gallery/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: source.value, query: query.value }), signal: AbortSignal.timeout(20000) })
    const value = await response.json()
    if (!response.ok)
      throw new Error(typeof value.detail === 'string' ? value.detail : '暫時未能搜尋；可直接使用下方平台入口。')
    results.value = value.items
    searchStatus.value = value.items.length ? `${value.cached ? '已載入快取' : '搜尋完成'}。請先到作者頁核對免費版本、AI 用途及轉發權限，再用下方 AIRI 原版 ZIP 匯入。` : '未找到合適結果；可更換關鍵字或直接瀏覽平台。'
  }
  catch (error) { searchStatus.value = errorMessageFrom(error) ?? '搜尋暫未完成。' }
  finally { searching.value = false }
}
async function importModel(item: typeof gallery.models[number]) {
  if (!accepted.value || busy.value)
    return
  busy.value = item.id
  emit('status', `正在匯入 ${item.name}，完成後可預覽；尚未更換平台角色。`)
  try {
    const response = await fetch(item.archive, { credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(60000) })
    if (!response.ok)
      throw new Error('gallery_download_failed')
    const content = await response.blob()
    if (content.size !== item.bytes || await modelHash(content) !== item.sha256)
      throw new Error('gallery_digest_mismatch')
    const model = await display.addDisplayModel(DisplayModelFormat.Live2dZip, new File([content], `${item.id}-Live2D.zip`, { type: 'application/zip' }))
    settings.stageModelSelected = model.id
    await settings.updateStageModel()
    emit('status', '已匯入並選擇預覽。按「儲存至平台」才會套用到所有裝置，Gemma 及曉曼保持不變。')
  }
  catch { emit('status', '圖庫模型未能完成匯入；平台原有角色保留，可以稍後再試或匯入自己的 ZIP。') }
  finally { busy.value = '' }
}
</script>

<template>
  <section class="cloud-model-gallery" :aria-busy="!!busy">
    <h2>免費模型圖庫</h2>
    <p>共 {{ gallery.models.length }} 款已核對的官方及社群模型可直接匯入預覽。匯入不使用 AI API 額度，按「儲存至平台」才發佈。</p>
    <div class="gallery-grid">
      <article v-for="item in gallery.models" :key="item.id">
        <img :src="item.image" :alt="item.name" loading="lazy" width="320" height="180">
        <h3>{{ item.name }}</h3>
        <p>{{ item.description }} · {{ (item.bytes / 1024 / 1024).toFixed(1) }} MB</p>
        <p class="gallery-terms">
          {{ item.individual_terms }} <a :href="item.source" target="_blank" rel="noopener noreferrer">作者／來源</a> · <a :href="item.license" target="_blank" rel="noopener noreferrer">授權</a> · <a :href="item.terms" target="_blank" rel="noopener noreferrer">使用條款</a>
        </p>
        <button type="button" :disabled="!accepted || !!busy" @click="importModel(item)">
          {{ busy === item.id ? '正在匯入…' : '一鍵匯入預覽' }}
        </button>
      </article>
    </div>
    <label class="gallery-agreement"><input v-model="accepted" type="checkbox">我已閱讀所選模型的來源、授權及使用條款，並確認本次用途適用。</label>
    <details class="discovered-models">
      <summary>自動更新的外站圖庫 · {{ sourceIndexes.reduce((sum, index) => sum + index.items.length, 0) }} 個條目</summary>
      <p role="status">
        {{ discoveryStatus }}
      </p>
      <p>已通過授權及實際顯示檢查的模型可直接匯入；新發現不等於已獲轉存授權，不會自動替居民換角色。</p>
      <div class="gallery-source-filter">
        <select v-model="discoverySource" aria-label="自動圖庫來源" @change="discoveryCount = 24">
          <option value="all">
            全部來源
          </option><option value="live2d">
            Live2D 官方
          </option>
          <option value="vtubernook">
            VTuber Nook
          </option><option value="aplaybox">
            模之屋 Live2D
          </option>
        </select>
        <input v-model="discoveryFilter" aria-label="篩選外站模型" placeholder="搜尋名稱或作者" @input="discoveryCount = 24">
      </div>
      <p v-for="index in sourceIndexes" :key="index.source" class="gallery-terms">
        {{ index.source }} · {{ index.items.length }} 個 · {{ index.last_success_ms ? new Date(index.last_success_ms).toLocaleString('zh-HK') : '首次更新中' }}
        {{ index.error ? '（更新未完成，保留上次目錄）' : '' }}
      </p>
      <div class="gallery-grid">
        <article v-for="item in discovered.slice(0, discoveryCount)" :key="item.url">
          <h3>{{ item.title }}</h3><p v-if="item.author">
            {{ item.author }}
          </p>
          <p class="gallery-terms">
            {{ item.sourceName }} · {{ item.format }} · {{ item.reviewed ? '已核對，可匯入' : item.license_status === 'redistribution_prohibited' ? '作者禁止平台轉存' : '授權／執行檔待核對' }}
          </p>
          <button v-if="item.reviewed" type="button" :disabled="!accepted || !!busy" @click="importModel(item.reviewed)">
            一鍵匯入預覽
          </button>
          <a :href="item.url" target="_blank" rel="noopener noreferrer">查看來源與授權</a>
        </article>
      </div>
      <button v-if="discovered.length > discoveryCount" type="button" @click="discoveryCount += 24">
        顯示更多（共 {{ discovered.length }} 個）
      </button>
    </details>
    <p class="gallery-terms">
      官方免費素材有用途限制；機構正式對外使用前，請按條款核對適用資格。其他創作者的模型仍可用 AIRI 原有匯入功能加入。
    </p>
    <details>
      <summary>來源及版權</summary>
      <p>{{ gallery.notice }}</p>
      <p>官方來源：Live2D 官方樣本包及 CubismWebSamples，移除附帶語音連結以保留曉曼。社群來源：puercatena / kenkipi（CC0），整理執行檔案並將 8K 貼圖縮為 4K，保留角色與授權。</p>
    </details>
    <details class="gallery-community">
      <summary>其他官方示例（{{ gallery.official_catalogue.length }} 款）</summary>
      <p class="gallery-terms">
        官方清單的其他項目亦保留入口。未完成兼容核對或條款限制轉發的項目，不會顯示一鍵轉存。這不表示作者沒有提供下載。
      </p>
      <div class="gallery-results">
        <article v-for="item in gallery.official_catalogue" :key="item.source">
          <h3>{{ item.name }}</h3><p>{{ item.reason }}</p><a :href="item.source" target="_blank" rel="noopener noreferrer">前往官方示例頁</a>
        </article>
      </div>
    </details>
    <details class="gallery-community" open>
      <summary>更多社群模型</summary>
      <form class="gallery-search" @submit.prevent="search">
        <label>平台<select v-model="source" aria-label="圖庫平台"><option value="all">全部</option><option value="live2d">Live2D 官方</option><option value="vtubernook">VTuber Nook</option><option value="aplaybox">模之屋 AplayBox</option><option value="booth">BOOTH</option><option value="itch">itch.io</option><option value="nizima">nizima</option></select></label>
        <label>模型關鍵字<input v-model="query" maxlength="80" placeholder="例如：cat、鄰家女孩、chibi"></label>
        <button type="submit" :disabled="searching">
          {{ searching ? '搜尋中…' : '搜尋社群圖庫' }}
        </button>
      </form>
      <p class="gallery-terms">
        只在按搜尋時使用既有免費 Tavily：基本搜尋每次 1 credit，相同搜尋 6 小時內用快取；另設每月最多 30 次圖庫搜尋預留，用完即停。只會搜尋你輸入的模型關鍵字，不附居民對話。
      </p>
      <p role="status">
        {{ searchStatus }}
      </p>
      <div class="gallery-results">
        <article v-for="item in results" :key="item.url">
          <h3>{{ item.title }}</h3><p>{{ item.description }}</p><a :href="item.url" target="_blank" rel="noopener noreferrer">到作者頁核對及下載</a>
        </article>
      </div>
      <p class="gallery-platforms">
        <a href="https://booth.pm/en/search/Live2D?max_price=0" target="_blank" rel="noopener noreferrer">BOOTH 免費模型</a><a href="https://itch.io/game-assets/free/tag-live2d" target="_blank" rel="noopener noreferrer">itch.io 免費模型</a><a href="https://nizima.com/" target="_blank" rel="noopener noreferrer">nizima 圖庫</a>
      </p>
      <p class="gallery-terms">
        免費下載不一定准許用於 AI 數字人或轉發檔案；部分只有 PSD／編輯原稿。平台共享需要可執行的 model3.json、moc3 及貼圖 ZIP，不會替你購買或繞過作者下載限制。
      </p>
      <p class="gallery-platforms">
        <a href="https://www.live2d.com/zh-CHS/learn/sample/" target="_blank" rel="noopener noreferrer">Live2D 官方示例</a><a href="https://vtuber-nook.com/category/live2d-3d-pngtuber-models/" target="_blank" rel="noopener noreferrer">VTuber Nook 綜合圖庫</a><a href="https://www.aplaybox.com/model/model" target="_blank" rel="noopener noreferrer">模之屋 AplayBox</a>
      </p>
      <p class="gallery-terms">
        VTuber Nook 同時收錄 Live2D、VRM 及 PNGtuber；模之屋亦有 PMX／MMD。PNGtuber 圖組或 PMX 不可直接當作 Live2D 模型使用。
      </p>
    </details>
  </section>
</template>

<style>
.cloud-model-gallery{display:grid;gap:14px;margin-bottom:20px;padding:20px;border:1px solid #d5e5da;border-radius:16px;background:#f3f8f4}.cloud-model-gallery h2{font-size:22px}.cloud-model-gallery p{line-height:1.6}.gallery-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.gallery-grid article{display:grid;gap:10px;padding:14px;border:1px solid #d5e5da;border-radius:12px;background:white}.gallery-grid img{width:100%;height:180px;object-fit:contain;background:#f5f8f5;border-radius:8px}.gallery-grid h3{font-weight:600}.gallery-grid button{align-self:end;padding:12px;border-radius:10px;background:#236c60;color:white}.gallery-grid button:disabled{opacity:.5;cursor:default}.cloud-model-gallery a{text-decoration:underline;text-underline-offset:3px}.gallery-agreement{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.gallery-agreement input{width:18px;height:18px}.gallery-terms{font-size:14px;color:#5c776a}@media(max-width:700px){.gallery-grid{grid-template-columns:1fr}.gallery-grid img{height:160px}}
</style>

<style>
.gallery-grid{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}.gallery-grid img{height:150px}.gallery-community summary{font-weight:600;cursor:pointer}.gallery-search{display:flex;align-items:end;flex-wrap:wrap;gap:12px;margin-block:16px}.gallery-search label{display:grid;gap:6px}.gallery-search input,.gallery-search select{padding:10px;border:1px solid #cadbd3;border-radius:8px;max-width:100%}.gallery-search button{padding:12px;border-radius:10px;background:#236c60;color:white}.gallery-results{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.gallery-results article{padding:14px;background:white;border:1px solid #d5e5da;border-radius:12px}.gallery-results h3{font-weight:600}.gallery-results p{font-size:14px}.gallery-platforms{display:flex;flex-wrap:wrap;gap:16px;margin-block:16px}
.gallery-source-filter{display:flex;gap:12px;flex-wrap:wrap;margin-block:14px}.gallery-source-filter input,.gallery-source-filter select{padding:10px;border:1px solid #cadbd3;border-radius:8px;max-width:100%}.discovered-models summary{font-weight:600;cursor:pointer}.discovered-models button{padding:10px;border-radius:10px;background:#236c60;color:white}
</style>
