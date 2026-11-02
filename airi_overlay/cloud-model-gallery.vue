<script setup lang="ts">
import { DisplayModelFormat, useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useSettings } from '@proj-airi/stage-ui/stores/settings'
import { ref } from 'vue'

import gallery from './cloud-model-gallery.json'

import { modelHash } from './cloud-shared-models'

const emit = defineEmits<{ status: [message: string] }>()
const display = useDisplayModelsStore()
const settings = useSettings()
const accepted = ref(false)
const busy = ref('')
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
    <p>直接匯入 Live2D 官方模型作預覽，毋須另外找檔案。只下載模型，不使用 AI API 額度。</p>
    <div class="gallery-grid">
      <article v-for="item in gallery.models" :key="item.id">
        <img :src="item.image" :alt="item.name" loading="lazy" width="320" height="180">
        <h3>{{ item.name }}</h3>
        <p>{{ item.description }} · {{ (item.bytes / 1024 / 1024).toFixed(1) }} MB</p>
        <p class="gallery-terms">
          {{ item.individual_terms }} <a :href="item.source" target="_blank" rel="noopener noreferrer">官方介紹</a>
        </p>
        <button type="button" :disabled="!accepted || !!busy" @click="importModel(item)">
          {{ busy === item.id ? '正在匯入…' : '一鍵匯入預覽' }}
        </button>
      </article>
    </div>
    <label class="gallery-agreement"><input v-model="accepted" type="checkbox">我已閱讀並同意 <a :href="gallery.models[0].license" target="_blank" rel="noopener noreferrer">免費素材授權</a>及<a :href="gallery.models[0].terms" target="_blank" rel="noopener noreferrer">角色使用條款</a>，並確認本次用途適用。</label>
    <p class="gallery-terms">
      官方免費素材有用途限制；機構正式對外使用前，請按條款核對適用資格。其他創作者的模型仍可用 AIRI 原有匯入功能加入。
    </p>
    <details>
      <summary>來源及版權</summary>
      <p>{{ gallery.notice }}</p>
      <p>來源：Live2D / CubismWebSamples；只整理為 AIRI 可匯入的 ZIP，移除附帶語音連結以保留曉曼，沒有改動角色圖像。</p>
    </details>
  </section>
</template>

<style>
.cloud-model-gallery{display:grid;gap:14px;margin-bottom:20px;padding:20px;border:1px solid #d5e5da;border-radius:16px;background:#f3f8f4}.cloud-model-gallery h2{font-size:22px}.cloud-model-gallery p{line-height:1.6}.gallery-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.gallery-grid article{display:grid;gap:10px;padding:14px;border:1px solid #d5e5da;border-radius:12px;background:white}.gallery-grid img{width:100%;height:180px;object-fit:contain;background:#f5f8f5;border-radius:8px}.gallery-grid h3{font-weight:600}.gallery-grid button{align-self:end;padding:12px;border-radius:10px;background:#236c60;color:white}.gallery-grid button:disabled{opacity:.5;cursor:default}.cloud-model-gallery a{text-decoration:underline;text-underline-offset:3px}.gallery-agreement{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.gallery-agreement input{width:18px;height:18px}.gallery-terms{font-size:14px;color:#5c776a}@media(max-width:700px){.gallery-grid{grid-template-columns:1fr}.gallery-grid img{height:160px}}
</style>
