<script setup lang="ts">
import type { DisplayModel } from '@proj-airi/stage-ui/stores/display-models'

import { errorMessageFrom } from '@moeru/std'
import { loadFreeSkeletalArchive } from '@proj-airi/stage-ui/libs/free-skeletal-zip'
import { DisplayModelFormat, useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { computed, inject, onMounted, ref, watch } from 'vue'

import gallery from './cloud-model-gallery.json'
import reviewedImages from './reviewed-model-thumbnails.json'

import { loadSharedModel, modelHash, sharedModels } from './cloud-shared-models'
import { fileDigest, mergeModelChoices } from './model-dedup'

const props = defineProps<{ selectedModel?: DisplayModel }>()
const emit = defineEmits<{ pick: [model: DisplayModel], close: [], status: [message: string] }>()
const notify = inject<(message: string) => void>('neighbour-model-status', () => {})
const display = useDisplayModelsStore()
const query = ref('')
const platform = ref('all')
const format = ref('all')
const accepted = inject('neighbour-model-license-accepted', ref(false))
const busy = ref('')
const message = ref('選擇後先預覽；按「儲存至平台」才套用到所有裝置。')
const failed = ref(new Set<string>())
const imagesFailed = ref(new Set<string>())
const shared = ref<{ id: string, name: string, bytes: number, format?: string }[]>([])
const ownFile = ref<File>()
const ownRights = ref(false)
const ownModels = ref<string[]>([])
const ownEntry = ref('')
const localDigests = ref<Record<string, string>>({})
const localReady = ref(false)
interface SourceResearch { id: string, name: string, domains: string[], mode: string, note: string }
interface SourceUpdate { source: string, items: unknown[], last_success_ms: number | null, stale: boolean }
interface DiscoveredModel { title: string, url: string, description: string, source: string }
const sourceRegistry = ref<SourceResearch[]>([])
const sourceUpdates = ref<SourceUpdate[]>([])
const sourceLoaded = ref(false)
const sourceBusy = ref(false)
const sourceMessage = ref('')
const verifiedSourceCount = ref<number | null>(null)
const discoverySource = ref('all')
const discoveryQuery = ref('')
const discoveryFormat = ref('all')
const discoveryResults = ref<DiscoveredModel[]>([])
const sourceSuccess = computed(() => sourceUpdates.value.filter(row => row.last_success_ms !== null).length)
function sourceName(id: string) {
  return sourceRegistry.value.find(row => row.id === id)?.name || id
}
function sourceLabel(row: SourceResearch) {
  if (row.mode === 'reviewed_runtime_import')
    return '已核對款式可一鍵預覽；不是全站自動目錄'
  const update = sourceUpdates.value.find(item => item.source === row.id)
  if (update?.last_success_ms)
    return `${update.stale ? '更新暫未完成，保留上次' : '目錄已更新'} · ${update.items.length} 項待核候選`
  if (update)
    return update.stale ? '暫未能取得目錄' : '正在等候首次檢查'
  return row.mode === 'existing_oauth' ? '已接入，已核模型在上方清單' : '尚未接通自動目錄'
}
async function readSources(event: Event) {
  if (!(event.target instanceof HTMLDetailsElement) || !event.target.open || sourceLoaded.value || sourceBusy.value)
    return
  sourceBusy.value = true
  try {
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch('/api/v1/service-desk/model-gallery/catalogue', { signal: AbortSignal.timeout(15000) })
    if (!response.ok)
      throw new Error('source_unavailable')
    const value = await response.json()
    if (!Array.isArray(value.sources) || !Array.isArray(value.registry?.items))
      throw new Error('source_unavailable')
    sourceUpdates.value = value.sources
    sourceRegistry.value = value.registry.items
    verifiedSourceCount.value = Number.isInteger(value.registry.verified_independent_sources)
      && value.registry.verified_independent_sources >= 0
      ? value.registry.verified_independent_sources
      : null
    sourceLoaded.value = true
    sourceMessage.value = '進入後台會在背景檢查已接通目錄；檢查失敗保留舊清單。'
  }
  catch {
    sourceMessage.value = '圖庫更新狀態暫未能載入；上方已核可用模型仍可選擇。'
  }
  finally { sourceBusy.value = false }
}
function safeCandidate(item: DiscoveredModel) {
  try {
    const url = new URL(item.url)
    const source = sourceRegistry.value.find(row => row.id === item.source)
    return url.protocol === 'https:' && !url.username && !url.password && (!url.port || url.port === '443')
      && source?.domains.some(host => url.hostname === host || url.hostname.endsWith(`.${host}`))
  }
  catch { return false }
}
async function discoverModels() {
  if (sourceBusy.value || !sourceLoaded.value)
    return
  sourceBusy.value = true
  discoveryResults.value = []
  try {
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch('/api/v1/service-desk/model-gallery/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(18000),
      body: JSON.stringify({ query: discoveryQuery.value, source: discoverySource.value, format: discoveryFormat.value }),
    })
    const value = await response.json()
    if (!response.ok) {
      sourceMessage.value = typeof value.detail === 'string' ? value.detail.slice(0, 240) : '免費搜尋暫時未能完成。'
      return
    }
    discoveryResults.value = (Array.isArray(value.items) ? value.items.slice(0, 8) : []).filter(safeCandidate)
    sourceMessage.value = discoveryResults.value.length
      ? '以下是待核候選；價格、授權及 AIRI 試載通過後才會加入可用模型，現在不會自動匯入。'
      : '未找到符合來源限制的候選，可換其他名稱或來源。'
  }
  catch { sourceMessage.value = '搜尋暫未完成，沒有自動重試或改動目前角色。' }
  finally { sourceBusy.value = false }
}
class VroidPreviewError extends Error {
  constructor(message: string, readonly hide: boolean) {
    super(message)
  }
}
interface VroidModel { id: string, name: string, author: string, source: string, terms: string, image: string, bytes: number, sha256: string }
const vroid = ref<VroidModel[]>([])
interface ReviewedModel { id: string, name: string, source: string, source_name: string, source_url: string, license_url: string, credit: string, notice: string, bytes: number, sha256: string, application_only: boolean }
const reviewed = ref<ReviewedModel[]>([])
const visibleCount = ref(60)
interface GalleryModel { id: string, name: string, source: string, archive: string, image: string, bytes: number, sha256: string, license: string, terms: string, individual_terms: string, format?: string, platform?: string }
interface Choice { id: string, name: string, platform: string, format: string, sha256?: string, platforms?: string[], aliases?: string[], image?: string, bytes?: number, model?: DisplayModel, gallery?: GalleryModel, sharedId?: string, vroid?: VroidModel, reviewed?: ReviewedModel }
const choices = computed(() => {
  const rows: Choice[] = (gallery.models as GalleryModel[]).map(item => ({ id: `gallery:${item.id}`, name: item.name, platform: item.platform || (item.source.includes('live2d.com') ? 'Live2D 官方' : '社群 CC0'), format: item.format || 'live2d-zip', sha256: item.sha256, image: item.image, bytes: item.bytes, gallery: item }))
  for (const item of vroid.value)
    rows.push({ id: `vroid:${item.id}`, name: item.name, platform: 'VRoid Hub', format: 'vrm', sha256: item.sha256, image: item.image, bytes: item.bytes, vroid: item, aliases: [item.author] })
  for (const item of reviewed.value)
    rows.push({ id: `reviewed:${item.id}`, name: item.name, platform: item.source_name, format: 'vrm', sha256: item.sha256, image: reviewedImages[item.id as keyof typeof reviewedImages], bytes: item.bytes, reviewed: item, aliases: [item.credit] })
  for (const item of shared.value) {
    const digest = item.id.replace(/^cloud-(?:live2d|vrm|rigby)-/, '')
    const reviewed = (gallery.models as GalleryModel[]).find(model => model.sha256 === digest)
    const local = display.displayModels.find(model => model.id === item.id)
    rows.push({ id: item.id, name: item.name, platform: '平台共享', sha256: digest, format: item.format || (item.id.startsWith('cloud-vrm-') ? 'vrm' : 'live2d-zip'), image: local?.previewImage || reviewed?.image, bytes: item.bytes, sharedId: item.id, model: local })
  }
  for (const item of display.displayModels) {
    if (rows.some(row => row.id === item.id) || ![DisplayModelFormat.Live2dZip, DisplayModelFormat.VRM, DisplayModelFormat.RigbyJsonZip].includes(item.format))
      continue
    if (item.type === 'file' && !localReady.value)
      continue
    const digest = /(?:^cloud-(?:live2d|vrm|rigby)-|^display-model-sha256-(?:live2d-zip|vrm|rigby-json-zip)-)([a-f0-9]{64})$/.exec(item.id)?.[1] || localDigests.value[item.id]
    rows.push({ id: item.id, name: item.name, format: item.format, sha256: digest, image: item.previewImage, model: item, platform: item.id.startsWith('preset-') ? 'AIRI 內建' : '此裝置' })
  }
  const excluded = new Set(gallery.excluded_sha256 || [])
  return (mergeModelChoices(rows, props.selectedModel?.id) as Choice[]).filter(row => !failed.value.has(row.id)
    && (!row.sha256 || !excluded.has(row.sha256) || row.id === props.selectedModel?.id))
})
const platforms = computed(() => [...new Set(choices.value.flatMap(row => row.platforms || [row.platform]))])
const filtered = computed(() => choices.value.filter(row => (platform.value === 'all' || row.platforms?.includes(platform.value))
  && (format.value === 'all' || row.format === format.value)
  && `${row.aliases?.join(' ')} ${row.name} ${row.platforms?.join(' ')}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
const visible = computed(() => filtered.value.slice(0, visibleCount.value))
watch([query, platform, format], () => {
  visibleCount.value = 60
})
function status(value: string) {
  message.value = value
  notify(value)
  emit('status', value)
}
function picked(model: DisplayModel) {
  status('已選擇模型作預覽；按「儲存至平台」才發佈，Gemma 及語音設定保持不變。')
  emit('pick', model)
  emit('close')
}
onMounted(async () => {
  void (async () => {
    try {
      const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
      const response = await transport.fetch('/api/v1/service-desk/reviewed-models', { signal: AbortSignal.timeout(15000) })
      if (response.ok) {
        const value = await response.json()
        if (Array.isArray(value.items))
          reviewed.value = value.items
      }
    }
    catch { /* Reviewed-source catalogue is local metadata, never blocks current models. */ }
  })()
  void (async () => {
    try {
      const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
      const response = await transport.fetch('/api/v1/service-desk/vroid/models', { signal: AbortSignal.timeout(20000) })
      if (response.ok) {
        const value = await response.json()
        if (value.connected && Array.isArray(value.items))
          vroid.value = value.items
      }
    }
    catch { /* Optional library never blocks built-in/shared choices. */ }
  })()
  void (async () => {
    const found: Record<string, string> = {}
    // Hash one file at a time, cached by Blob identity; no startup mass reads.
    for (const model of display.displayModels) {
      if (model.type === 'file') {
        try {
          found[model.id] = await fileDigest(model.file)
        }
        catch { /* An unreadable original remains separate, never deleted. */ }
      }
    }
    localDigests.value = found
    localReady.value = true
  })()
  try {
    shared.value = (await sharedModels()).items
  }
  catch { message.value = '共享清單暫未載入；已核對圖庫及此裝置模型仍可選擇。' }
})
async function choose(row: Choice) {
  if (busy.value || ((row.gallery || row.vroid || row.reviewed) && !accepted.value))
    return
  busy.value = row.id
  status(`正在準備 ${row.name}…`)
  try {
    let model = row.model
    if (!model && row.sharedId) {
      model = await loadSharedModel(row.sharedId, row.name)
      if (!display.displayModels.some(item => item.id === model!.id))
        display.displayModels.push(model)
    }
    else if (!model && (row.vroid || row.reviewed)) {
      const item = (row.vroid || row.reviewed)!
      const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
      const endpoint = row.reviewed ? '/api/v1/service-desk/reviewed-models' : '/api/v1/service-desk/vroid/models'
      const response = await transport.fetch(`${endpoint}/${encodeURIComponent(item.id)}/preview`, {
        method: 'POST',
        ...(row.reviewed ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accepted_terms: true, application_use_only: true }) } : {}),
        signal: AbortSignal.timeout(row.reviewed ? 120000 : 90000),
      })
      if (!response.ok || !response.body) {
        const value = await response.json().catch(() => ({}))
        throw new VroidPreviewError(value.detail?.message || '模型暫時未能下載，沒有自動重試。', response.status === 422 || ['model_changed_requires_review', 'model_not_reviewed'].includes(value.detail?.code))
      }
      const reader = response.body.getReader()
      const chunks: Uint8Array[] = []
      let size = 0
      try {
        while (true) {
          const part = await reader.read()
          if (part.done)
            break
          size += part.value.byteLength
          if (size > item.bytes || size > 32 * 1024 * 1024)
            throw new VroidPreviewError('模型下載超過已核對大小。', true)
          chunks.push(part.value)
        }
      }
      finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
      const content = new Blob(chunks as BlobPart[])
      if (content.size !== item.bytes || await modelHash(content) !== item.sha256)
        throw new VroidPreviewError('模型檔案核對未通過，原角色保留。', true)
      model = await display.addDisplayModel(DisplayModelFormat.VRM, new File([content], `${item.name}.vrm`, { type: 'model/gltf-binary' }))
    }
    else if (!model && row.gallery) {
      const item = row.gallery
      const remote = item.format === 'vrm'
      const arweave = /^https:\/\/arweave\.net\/[\w-]{43}$/.test(item.archive)
      const pinnedVRoid = /^https:\/\/raw\.githubusercontent\.com\/madjin\/vrm-samples\/[a-f0-9]{40}\/vroid\/beta\/(?:Sakurada_Fumiriya|Sendagaya_Shino)\.vrm$/.test(item.archive)
      if (remote && !arweave && !pinnedVRoid)
        throw new Error('圖庫來源未能核對。')
      const response = await fetch(item.archive, { credentials: 'omit', redirect: remote && arweave ? 'follow' : 'error', mode: remote ? 'cors' : 'same-origin', referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(60000) })
      if (!response.ok || !response.body)
        throw new Error('模型暫時未能下載。')
      if (remote && (arweave ? !/^https:\/\/(?:[a-z0-9]+\.)?arweave\.net\//.test(response.url) : response.url !== item.archive))
        throw new Error('模型下載來源不正確。')
      const reader = response.body.getReader()
      const chunks: Uint8Array[] = []
      let size = 0
      try {
        while (true) {
          const part = await reader.read()
          if (part.done)
            break
          size += part.value.byteLength
          if (size > item.bytes || size > 32 * 1024 * 1024)
            throw new Error('模型下載超過已核對大小。')
          chunks.push(part.value)
        }
      }
      finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
      const content = new Blob(chunks as BlobPart[])
      if (content.size !== item.bytes || await modelHash(content) !== item.sha256)
        throw new Error('模型檔案核對未通過，沒有更換原角色。')
      model = await display.addDisplayModel(remote ? DisplayModelFormat.VRM : DisplayModelFormat.Live2dZip, new File([content], remote ? `${item.id}.vrm` : `${item.id}-Live2D.zip`, { type: remote ? 'model/gltf-binary' : 'application/zip' }))
    }
    if (!model)
      throw new Error('模型未準備好。')
    picked(model)
  }
  catch (error) {
    const hide = (!row.vroid && !row.reviewed) || (error instanceof VroidPreviewError && error.hide)
    if (hide)
      failed.value.add(row.id)
    status(`${errorMessageFrom(error) ?? '未能完整載入模型。'} 原角色保留，${hide ? '今次清單會先隱藏此項。' : '稍後可再次選擇。'}`)
  }
  finally { busy.value = '' }
}
function chooseArchive(event: Event) {
  ownFile.value = (event.target as HTMLInputElement).files?.[0]
  ownModels.value = []
  ownEntry.value = ''
}
async function prepareOwnArchive() {
  if (!ownFile.value || !ownRights.value || busy.value)
    return
  if (ownFile.value.size > 32 * 1024 * 1024) {
    status('ZIP 最大 32 MB；原檔沒有更改。')
    return
  }
  busy.value = 'own-archive'
  status('正在整理及核對 ZIP，原模型保留…')
  try {
    if (ownFile.value.name.toLowerCase().endsWith('.rigby.zip')) {
      await loadFreeSkeletalArchive(ownFile.value)
      picked(await display.addDisplayModel(DisplayModelFormat.RigbyJsonZip, ownFile.value))
      return
    }
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch(`/api/v1/service-desk/airi-models/prepare${ownEntry.value ? `?entrypoint=${encodeURIComponent(ownEntry.value)}` : ''}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/zip' },
      body: ownFile.value,
      signal: AbortSignal.timeout(90000),
    })
    if (!response.ok) {
      const value = await response.json()
      throw new Error(typeof value.detail === 'string' ? value.detail : '未能完成整理。')
    }
    if (response.headers.get('content-type')?.includes('application/json')) {
      ownModels.value = (await response.json()).models
      status('ZIP 內有多款模型，請選擇其中一款再整理。')
      return
    }
    const content = await response.blob()
    picked(await display.addDisplayModel(DisplayModelFormat.Live2dZip, new File([content], `${ownFile.value.name.replace(/\.zip$/i, '')}-prepared.zip`, { type: 'application/zip' })))
  }
  catch (error) { status(errorMessageFrom(error) ?? '未能完成整理，原角色及檔案保留。') }
  finally { busy.value = '' }
}
</script>

<template>
  <section class="model-picker" :aria-busy="!!busy">
    <header class="model-picker-heading">
      <div><h2>選擇模型</h2><p>{{ choices.length }} 款可用 · {{ props.selectedModel?.name ? `目前：${props.selectedModel.name}` : '選擇一款先預覽' }}</p></div>
      <button type="button" aria-label="關閉模型選單" :disabled="!!busy" @click="emit('close')">
        關閉
      </button>
    </header>
    <div class="model-picker-filters">
      <input v-model="query" type="search" aria-label="搜尋模型" placeholder="搜尋模型名稱或平台" maxlength="100">
      <select v-model="platform" aria-label="模型來源">
        <option value="all">
          所有來源
        </option><option v-for="name in platforms" :key="name" :value="name">
          {{ name }}
        </option>
      </select>
      <select v-model="format" aria-label="模型格式">
        <option value="all">
          所有格式
        </option>
        <option value="live2d-zip">
          Live2D · 2D
        </option>
        <option value="vrm">
          VRM · 3D
        </option>
        <option value="rigby-json-zip">
          免費骨架 · Rigby JSON
        </option>
      </select>
    </div>
    <label class="model-picker-license"><input v-model="accepted" type="checkbox">我已閱讀所選模型的授權及署名要求，只在鄰伴作數字人學習使用，保留原條款，不作素材轉發。</label>
    <p class="model-picker-message" role="status">
      {{ localReady ? message : '正在整理此裝置模型，避免重複顯示…' }}
    </p>
    <div class="model-picker-grid">
      <article v-for="row in visible" :key="row.id" :class="{ current: props.selectedModel?.id === row.id }">
        <button type="button" :disabled="!!busy || (!!row.gallery || !!row.vroid || !!row.reviewed) && !accepted" :aria-label="`選擇 ${row.name}`" @click="choose(row)">
          <img v-if="row.image && !imagesFailed.has(row.id)" :src="row.image" :alt="row.name" loading="lazy" @error="imagesFailed.add(row.id)">
          <span v-else class="model-picker-placeholder" aria-hidden="true">♧</span>
          <strong>{{ row.name }}</strong><span class="model-picker-tag">{{ row.platform }}{{ row.format === 'vrm' ? ' · 3D' : '' }}</span>
          <small>{{ busy === row.id ? '準備中…' : props.selectedModel?.id === row.id ? '目前選擇' : '選擇預覽' }}</small>
        </button>
        <details v-if="row.reviewed" class="model-picker-terms">
          <summary>作者及使用條款</summary><p>{{ row.reviewed.credit }} · {{ row.reviewed.notice }}</p><a :href="row.reviewed.source_url" target="_blank" rel="noopener noreferrer">作者來源</a> · <a :href="row.reviewed.license_url" target="_blank" rel="noopener noreferrer">原作者條款</a>
        </details>
        <details v-else-if="row.gallery" class="model-picker-terms">
          <summary>授權及來源</summary><p>{{ row.gallery.individual_terms }}</p><a :href="row.gallery.source" target="_blank" rel="noopener noreferrer">作者來源</a> · <a :href="row.gallery.license" target="_blank" rel="noopener noreferrer">授權</a> · <a :href="row.gallery.terms" target="_blank" rel="noopener noreferrer">條款</a>
        </details>
        <details v-else-if="row.vroid" class="model-picker-terms">
          <summary>作者及授權</summary><p>{{ row.vroid.author }} · {{ row.vroid.terms }}</p><a :href="row.vroid.source" target="_blank" rel="noopener noreferrer">作者來源及最新條款</a>
        </details>
      </article>
    </div>
    <button v-if="filtered.length > visible.length" type="button" class="model-picker-more" :disabled="!!busy" @click="visibleCount += 60">
      顯示更多（{{ visible.length }} / {{ filtered.length }}）
    </button>
    <p v-if="!filtered.length" class="model-picker-empty">
      未找到可用模型，試吓其他名稱或來源。
    </p>
    <details class="model-picker-import">
      <summary>匯入自己的 Live2D／免費骨架 ZIP</summary>
      <p>自動整理多層資料夾、引用路徑及取景；保留原模型、貼圖及授權。32 MB 以內，整理失敗不改原角色。</p>
      <p>免費骨架請使用 .rigby.zip：只限 Rigby JSON、region／unweighted mesh 及 PNG 貼圖；不是 Spine 格式，不接受或轉換 .skel。</p>
      <input type="file" accept=".zip,application/zip" aria-label="自己的模型 ZIP" :disabled="!!busy" @change="chooseArchive">
      <label v-if="ownFile"><input v-model="ownRights" type="checkbox">我有權在本平台使用及儲存這個模型。</label>
      <select v-if="ownModels.length" v-model="ownEntry" aria-label="ZIP 內的模型">
        <option value="">
          請選擇模型
        </option><option v-for="name in ownModels" :key="name" :value="name">
          {{ name }}
        </option>
      </select>
      <button type="button" :disabled="!!busy || !ownFile || !ownRights || ownModels.length > 0 && !ownEntry" @click="prepareOwnArchive">
        {{ busy === 'own-archive' ? '整理中…' : '整理並預覽' }}
      </button>
    </details>
    <details class="model-picker-sources" @toggle="readSources">
      <summary>圖庫更新狀態及尋找新資源</summary>
      <p v-if="verifiedSourceCount !== null">
        已核可一鍵匯入來源 {{ verifiedSourceCount }} / 20；獨立原創庫可計入，同一團隊只計一次。
      </p>
      <p role="status">
        {{ sourceBusy ? '正在查閱圖庫…' : sourceMessage }}
      </p>
      <template v-if="sourceLoaded">
        <p>{{ sourceSuccess }} 個公開目錄已有檢查紀錄，另有已接入的 VRoid Hub。共 {{ sourceRegistry.length }} 個研究來源；未代表全部已接通或可一鍵匯入。</p>
        <div class="model-source-search">
          <input v-model="discoveryQuery" type="search" maxlength="80" placeholder="尋找日系角色、貓、鄰居…" aria-label="新圖庫候選名稱">
          <select v-model="discoverySource" aria-label="搜尋新候選的來源">
            <option value="all">
              全部研究來源
            </option>
            <option v-for="row in sourceRegistry" :key="row.id" :value="row.id">
              {{ row.name }}
            </option>
          </select>
          <select v-model="discoveryFormat" aria-label="搜尋新候選的格式">
            <option value="all">
              Live2D 或 VRM
            </option><option value="live2d">
              Live2D
            </option><option value="vrm">
              VRM
            </option>
          </select>
          <button type="button" :disabled="sourceBusy" @click="discoverModels">
            搜尋候選
          </button>
        </div>
        <p class="model-source-note">
          按「搜尋候選」才使用免費搜尋額度；用完即停。結果不會混入上方可用模型。
        </p>
        <ul v-if="discoveryResults.length" class="model-source-results">
          <li v-for="item in discoveryResults" :key="item.url">
            <a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }}</a><small>{{ sourceName(item.source) }} · 待核對</small>
          </li>
        </ul>
        <details class="model-source-review">
          <summary>查看各來源的接入狀態</summary>
          <ul>
            <li v-for="row in sourceRegistry" :key="row.id">
              <strong>{{ row.name }}</strong><span>{{ sourceLabel(row) }}</span><small>{{ row.note }}</small>
            </li>
          </ul>
        </details>
      </template>
    </details>
  </section>
</template>

<style>
.model-picker{display:grid;gap:14px;color:#194f49;min-width:0}.model-picker-heading{display:flex;align-items:start;justify-content:space-between;gap:16px}.model-picker-heading h2{font-size:24px;font-weight:650;margin:0 0 4px}.model-picker-heading p{font-size:13px;color:#687d71;overflow-wrap:anywhere}.model-picker-heading>button,.model-picker-import>button{padding:9px 16px;border:1px solid #cbded4;border-radius:10px;background:#f0f7f2;white-space:nowrap}.model-picker-filters{display:flex;gap:10px}.model-picker-filters input{flex:1;min-width:0}.model-picker-filters input,.model-picker-filters select,.model-picker-import select{padding:11px 12px;border:1px solid #cbded4;border-radius:10px;background:#fff;max-width:100%}.model-picker-license{display:flex;align-items:start;gap:8px;font-size:13px;line-height:1.6}.model-picker-license input{flex:0 0 auto;margin-top:4px}.model-picker-message{font-size:13px;line-height:1.6;color:#627a6a}.model-picker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:12px}.model-picker-grid article{overflow:hidden;border:1px solid #dae7df;border-radius:14px;background:#f8fbf8}.model-picker-grid article.current{border-color:#43957b;box-shadow:0 0 0 2px #b8d9c7}.model-picker-grid article>button{width:100%;display:flex;align-items:center;flex-direction:column;gap:7px;padding:12px;text-align:center;border:0;background:transparent}.model-picker-grid img,.model-picker-placeholder{height:130px;width:100%;object-fit:contain;display:grid;place-items:center;font-size:64px;color:#82aa91}.model-picker-grid strong{font-size:14px;overflow-wrap:anywhere}.model-picker-tag{font-size:11px;padding:3px 8px;border-radius:12px;background:#e6f0e8;color:#557662}.model-picker-grid small{font-size:12px;color:#23765e}.model-picker-grid button:disabled{opacity:.55;cursor:default}.model-picker button:focus-visible,.model-picker input:focus-visible,.model-picker select:focus-visible{outline:3px solid #88bca4;outline-offset:2px}.model-picker-terms{font-size:11px;line-height:1.5;padding:0 12px 10px}.model-picker-terms summary{cursor:pointer;color:#607969}.model-picker-terms a{text-decoration:underline}.model-picker-import{border-top:1px solid #dfebe3;padding-top:12px;font-size:13px;line-height:1.7}.model-picker-import summary{cursor:pointer;font-weight:600}.model-picker-import input[type=file],.model-picker-import>label,.model-picker-import>select{display:block;margin-block:12px;max-width:100%}.model-picker-empty{padding:32px;text-align:center;color:#728579}.cloud-current-model{font-size:14px;font-weight:600;padding:10px 0;overflow-wrap:anywhere}.cloud-model-options>summary{font-size:13px;cursor:pointer;padding:14px 0;color:#607c6b}@media(max-width:500px){.model-picker-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.model-picker-grid img,.model-picker-placeholder{height:100px}.model-picker-filters{flex-direction:column}.model-picker-heading h2{font-size:21px}}
</style>

<style>
.model-picker-sources{border-top:1px solid #d9e6df;padding-top:14px;font-size:13px;line-height:1.7}.model-picker-sources summary{cursor:pointer}.model-picker-sources p{margin-block:10px}.model-source-search{display:grid;grid-template-columns:minmax(120px,1fr) minmax(100px,160px) minmax(90px,130px) auto;gap:8px}.model-source-search input,.model-source-search select,.model-source-search button{min-width:0;max-width:100%;padding:9px;border:1px solid #cbded4;border-radius:10px;background:#fff}.model-source-note{color:#657c70}.model-source-results,.model-source-review ul{list-style:none;padding:0;display:grid;gap:10px}.model-source-results li,.model-source-review li{display:grid;gap:3px;padding:9px;border-radius:10px;background:#f1f7f3;overflow-wrap:anywhere}.model-source-results small,.model-source-review small{color:#657c70}@media(max-width:650px){.model-source-search{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.model-source-search input{grid-column:1/-1}}
</style>

<style>
.model-picker-filters input[type=search]{width:auto;flex:1 1 0;min-width:0}.model-picker-filters select{width:180px;flex:0 0 180px;min-width:0}.model-picker-grid button:disabled{opacity:1}.model-picker-grid button:disabled small{color:#72877b}@media(max-width:500px){.model-picker-filters input[type=search],.model-picker-filters select{width:100%;flex:0 0 auto}}
</style>
