<script setup lang="ts">
import type { DisplayModel } from '@proj-airi/stage-ui/stores/display-models'

import { errorMessageFrom } from '@moeru/std'
import { DisplayModelFormat, useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { computed, inject, onMounted, ref, watch } from 'vue'

import gallery from './cloud-model-gallery.json'

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
const shared = ref<{ id: string, name: string, bytes: number }[]>([])
const ownFile = ref<File>()
const ownRights = ref(false)
const ownModels = ref<string[]>([])
const ownEntry = ref('')
const localDigests = ref<Record<string, string>>({})
const localReady = ref(false)
class VroidPreviewError extends Error {
  constructor(message: string, readonly hide: boolean) {
    super(message)
  }
}
interface VroidModel { id: string, name: string, author: string, source: string, terms: string, image: string, bytes: number, sha256: string }
const vroid = ref<VroidModel[]>([])
const visibleCount = ref(60)
interface GalleryModel { id: string, name: string, source: string, archive: string, image: string, bytes: number, sha256: string, license: string, terms: string, individual_terms: string, format?: string, platform?: string }
interface Choice { id: string, name: string, platform: string, format: string, sha256?: string, platforms?: string[], aliases?: string[], image?: string, bytes?: number, model?: DisplayModel, gallery?: GalleryModel, sharedId?: string, vroid?: VroidModel }
const choices = computed(() => {
  const rows: Choice[] = (gallery.models as GalleryModel[]).map(item => ({ id: `gallery:${item.id}`, name: item.name, platform: item.platform || (item.source.includes('live2d.com') ? 'Live2D 官方' : '社群 CC0'), format: item.format || 'live2d-zip', sha256: item.sha256, image: item.image, bytes: item.bytes, gallery: item }))
  for (const item of vroid.value)
    rows.push({ id: `vroid:${item.id}`, name: item.name, platform: 'VRoid Hub', format: 'vrm', sha256: item.sha256, image: item.image, bytes: item.bytes, vroid: item, aliases: [item.author] })
  for (const item of shared.value) {
    const digest = item.id.replace(/^cloud-(?:live2d|vrm)-/, '')
    const reviewed = (gallery.models as GalleryModel[]).find(model => model.sha256 === digest)
    const local = display.displayModels.find(model => model.id === item.id)
    rows.push({ id: item.id, name: item.name, platform: '平台共享', sha256: digest, format: item.id.startsWith('cloud-vrm-') ? 'vrm' : 'live2d-zip', image: local?.previewImage || reviewed?.image, bytes: item.bytes, sharedId: item.id, model: local })
  }
  for (const item of display.displayModels) {
    if (rows.some(row => row.id === item.id) || ![DisplayModelFormat.Live2dZip, DisplayModelFormat.VRM].includes(item.format))
      continue
    if (item.type === 'file' && !localReady.value)
      continue
    const digest = /(?:^cloud-(?:live2d|vrm)-|^display-model-sha256-(?:live2d-zip|vrm)-)([a-f0-9]{64})$/.exec(item.id)?.[1] || localDigests.value[item.id]
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
  status('已選擇模型作預覽；按「儲存至平台」才發佈，Gemma 及曉曼保持不變。')
  emit('pick', model)
  emit('close')
}
onMounted(async () => {
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
  if (busy.value || ((row.gallery || row.vroid) && !accepted.value))
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
    else if (!model && row.vroid) {
      const item = row.vroid
      const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
      const response = await transport.fetch(`/api/v1/service-desk/vroid/models/${encodeURIComponent(item.id)}/preview`, {
        method: 'POST',
        signal: AbortSignal.timeout(90000),
      })
      if (!response.ok || !response.body) {
        const value = await response.json().catch(() => ({}))
        throw new VroidPreviewError(value.detail?.message || 'VRoid 暫時未能下載，沒有自動重試。', response.status === 422 || ['model_changed_requires_review', 'model_not_reviewed'].includes(value.detail?.code))
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
    const hide = !row.vroid || (error instanceof VroidPreviewError && error.hide)
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
      </select>
    </div>
    <label class="model-picker-license"><input v-model="accepted" type="checkbox">我已閱讀所選圖庫模型的授權及署名要求，只作非商業學習使用。</label>
    <p class="model-picker-message" role="status">
      {{ localReady ? message : '正在整理此裝置模型，避免重複顯示…' }}
    </p>
    <div class="model-picker-grid">
      <article v-for="row in visible" :key="row.id" :class="{ current: props.selectedModel?.id === row.id }">
        <button type="button" :disabled="!!busy || (!!row.gallery || !!row.vroid) && !accepted" :aria-label="`選擇 ${row.name}`" @click="choose(row)">
          <img v-if="row.image && !imagesFailed.has(row.id)" :src="row.image" :alt="row.name" loading="lazy" @error="imagesFailed.add(row.id)">
          <span v-else class="model-picker-placeholder" aria-hidden="true">♧</span>
          <strong>{{ row.name }}</strong><span class="model-picker-tag">{{ row.platform }}{{ row.format === 'vrm' ? ' · 3D' : '' }}</span>
          <small>{{ busy === row.id ? '準備中…' : props.selectedModel?.id === row.id ? '目前選擇' : '選擇預覽' }}</small>
        </button>
        <details v-if="row.gallery" class="model-picker-terms">
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
      <summary>匯入自己的 Live2D ZIP</summary>
      <p>自動整理多層資料夾、引用路徑及取景；保留原模型、貼圖及授權。32 MB 以內，整理失敗不改原角色。</p>
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
  </section>
</template>

<style>
.model-picker{display:grid;gap:14px;color:#194f49;min-width:0}.model-picker-heading{display:flex;align-items:start;justify-content:space-between;gap:16px}.model-picker-heading h2{font-size:24px;font-weight:650;margin:0 0 4px}.model-picker-heading p{font-size:13px;color:#687d71;overflow-wrap:anywhere}.model-picker-heading>button,.model-picker-import>button{padding:9px 16px;border:1px solid #cbded4;border-radius:10px;background:#f0f7f2;white-space:nowrap}.model-picker-filters{display:flex;gap:10px}.model-picker-filters input{flex:1;min-width:0}.model-picker-filters input,.model-picker-filters select,.model-picker-import select{padding:11px 12px;border:1px solid #cbded4;border-radius:10px;background:#fff;max-width:100%}.model-picker-license{display:flex;align-items:start;gap:8px;font-size:13px;line-height:1.6}.model-picker-license input{flex:0 0 auto;margin-top:4px}.model-picker-message{font-size:13px;line-height:1.6;color:#627a6a}.model-picker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:12px}.model-picker-grid article{overflow:hidden;border:1px solid #dae7df;border-radius:14px;background:#f8fbf8}.model-picker-grid article.current{border-color:#43957b;box-shadow:0 0 0 2px #b8d9c7}.model-picker-grid article>button{width:100%;display:flex;align-items:center;flex-direction:column;gap:7px;padding:12px;text-align:center;border:0;background:transparent}.model-picker-grid img,.model-picker-placeholder{height:130px;width:100%;object-fit:contain;display:grid;place-items:center;font-size:64px;color:#82aa91}.model-picker-grid strong{font-size:14px;overflow-wrap:anywhere}.model-picker-tag{font-size:11px;padding:3px 8px;border-radius:12px;background:#e6f0e8;color:#557662}.model-picker-grid small{font-size:12px;color:#23765e}.model-picker-grid button:disabled{opacity:.55;cursor:default}.model-picker button:focus-visible,.model-picker input:focus-visible,.model-picker select:focus-visible{outline:3px solid #88bca4;outline-offset:2px}.model-picker-terms{font-size:11px;line-height:1.5;padding:0 12px 10px}.model-picker-terms summary{cursor:pointer;color:#607969}.model-picker-terms a{text-decoration:underline}.model-picker-import{border-top:1px solid #dfebe3;padding-top:12px;font-size:13px;line-height:1.7}.model-picker-import summary{cursor:pointer;font-weight:600}.model-picker-import input[type=file],.model-picker-import>label,.model-picker-import>select{display:block;margin-block:12px;max-width:100%}.model-picker-empty{padding:32px;text-align:center;color:#728579}.cloud-current-model{font-size:14px;font-weight:600;padding:10px 0;overflow-wrap:anywhere}.cloud-model-options>summary{font-size:13px;cursor:pointer;padding:14px 0;color:#607c6b}@media(max-width:500px){.model-picker-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.model-picker-grid img,.model-picker-placeholder{height:100px}.model-picker-filters{flex-direction:column}.model-picker-heading h2{font-size:21px}}
</style>

<style>
.model-picker-filters input[type=search]{width:auto;flex:1 1 0;min-width:0}.model-picker-filters select{width:180px;flex:0 0 180px;min-width:0}.model-picker-grid button:disabled{opacity:1}.model-picker-grid button:disabled small{color:#72877b}@media(max-width:500px){.model-picker-filters input[type=search],.model-picker-filters select{width:100%;flex:0 0 auto}}
</style>
