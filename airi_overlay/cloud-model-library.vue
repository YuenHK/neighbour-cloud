<script setup lang="ts">
import { useDisplayModelsStore } from '@proj-airi/stage-ui/stores/display-models'
import { useSettings } from '@proj-airi/stage-ui/stores/settings'
import { onMounted, ref } from 'vue'

import { loadSharedModel, sharedModels } from './cloud-shared-models'

const emit = defineEmits<{ status: [message: string] }>()
const display = useDisplayModelsStore()
const settings = useSettings()
const items = ref<{ id: string, name: string, bytes: number }[]>([])
const current = ref('')
const used = ref(0)
const message = ref('正在查閱平台共享模型…')
const busy = ref(false)
onMounted(async () => {
  try {
    const value = await sharedModels()
    items.value = value.items
    current.value = value.active_model
    used.value = value.used_bytes
    message.value = ''
  }
  catch (error) { message.value = (error as Error).message }
})
async function choose(id: string, name: string) {
  if (busy.value)
    return
  busy.value = true
  try {
    const model = await loadSharedModel(id, name)
    if (!display.displayModels.some(item => item.id === id))
      display.displayModels.push(model)
    settings.stageModelSelected = id
    await settings.updateStageModel()
    emit('status', '已選擇共享模型作預覽；按「儲存至平台」才會發佈到其他裝置。')
  }
  catch { emit('status', '模型暫時未能完整載入，原有選擇保留，沒有發佈。') }
  finally { busy.value = false }
}
</script>

<template>
  <section class="cloud-model-library">
    <h2>平台共享模型</h2>
    <p>選擇圖庫模型，或在下方 AIRI 匯入自己的 Live2D 3 ZIP，再按「儲存至平台」上載並發佈。其他裝置會使用同一模型；正在進行的居民對話不會中途換角色。</p>
    <p>每個 ZIP 最多 32 MB；模型儲存預留共 64 MB，舊版本保留方便還原。這是平台預留上限，並非官方免費餘額。</p>
    <p>目前已用 {{ (used / 1024 / 1024).toFixed(1) }} MB。{{ message }}</p>
    <ul v-if="items.length">
      <li v-for="item in items" :key="item.id">
        <span>{{ item.name }} · {{ (item.bytes / 1024 / 1024).toFixed(1) }} MB {{ current === item.id ? '· 正在使用' : '' }}</span>
        <button type="button" :disabled="busy" @click="choose(item.id, item.name)">
          選擇預覽
        </button>
      </li>
    </ul>
    <p v-else-if="!message">
      尚未發佈自訂模型；仍使用原有內建角色。
    </p>
  </section>
</template>

<style>
.cloud-model-library{padding:20px;margin-bottom:20px;background:#eef6ef;border:1px solid #d5e5da;border-radius:16px;display:grid;gap:14px}.cloud-model-library h2{font-size:22px}.cloud-model-library p{line-height:1.7;color:#5c776a}.cloud-model-library ul{display:grid;gap:12px}.cloud-model-library li{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.cloud-model-library button{padding:10px 16px;border-radius:10px;border:1px solid #cadbd3;background:white}
</style>
