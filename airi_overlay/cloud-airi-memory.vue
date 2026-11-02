<script setup lang="ts">
import { FieldCheckbox, FieldInput, FieldRange } from '@proj-airi/ui'
import { computed, onUnmounted, ref } from 'vue'

import { cloudRuntime } from './cloud-airi-runtime'

const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
const memory = cloudRuntime.memory
const minutes = computed({
  get: () => memory.idle_seconds / 60,
  set: (value) => {
    memory.idle_seconds = value * 60
  },
})
const profile = ref('')
const message = ref('')
const busy = ref(false)
const confirming = ref('')
const items = ref<{ id: string, text: string }[]>([])
let controller: AbortController | undefined
let loadedProfile = ''
onUnmounted(() => {
  controller?.abort()
  items.value = []
})
async function load() {
  if (busy.value || !profile.value.trim())
    return
  busy.value = true
  controller?.abort()
  controller = new AbortController()
  message.value = '正在查閱指定稱呼的記憶…'
  try {
    const response = await transport.fetch(`/api/v1/service-desk/resident-memories?profile=${encodeURIComponent(profile.value.trim())}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]) })
    if (!response.ok)
      throw new Error('unconfirmed')
    const result = await response.json()
    if (!Array.isArray(result.items))
      throw new Error('invalid')
    items.value = result.items
    loadedProfile = profile.value.trim()
    confirming.value = ''
    message.value = items.value.length ? `找到 ${items.value.length} 項由居民明確要求保存的記憶。` : '這個稱呼暫時沒有明確保存的記憶。'
  }
  catch { message.value = '暫時未能查閱；沒有改動或清除任何記憶。' }
  finally { busy.value = false }
}
async function forget(id: string) {
  if (busy.value || confirming.value !== id || !loadedProfile)
    return
  busy.value = true
  try {
    const response = await transport.fetch(`/api/v1/service-desk/resident-memories/${encodeURIComponent(id)}?profile=${encodeURIComponent(loadedProfile)}`, { method: 'DELETE', signal: AbortSignal.timeout(12000) })
    if (!response.ok)
      throw new Error('unconfirmed')
    items.value = items.value.filter(item => item.id !== id)
    confirming.value = ''
    message.value = '已按要求忘記這一項；其他記憶保留。'
  }
  catch {
    confirming.value = ''
    message.value = '未能確認更改結果；請先重新查閱，沒有自動再刪除。'
  }
  finally { busy.value = false }
}
</script>

<template>
  <div class="cloud-memory-settings">
    <section>
      <h2>本輪對話記憶</h2>
      <p>讓數字人記得今次傾過的內容；交接下一位居民時，只清除本輪對話及稱呼。</p>
      <FieldRange v-model="minutes" label="閒置後交接下一位居民" description="預設三分鐘；可縮短，避免下一位看到上一輪內容。" :min="1" :max="3" :step="1" :format-value="value => `${value} 分鐘`" />
      <FieldRange v-model="memory.context_messages" label="本輪上下文訊息上限" description="包括居民及數字人的訊息，預設保留最近 60 則。" :min="4" :max="60" :step="2" />
      <FieldRange v-model="memory.context_characters" label="本輪上下文字數上限" description="預設 16,000 字；縮短可減少每輪傳送內容。" :min="2000" :max="16000" :step="1000" />
    </section>
    <section>
      <h2>按稱呼保存的長期記憶</h2>
      <FieldCheckbox v-model="memory.long_term_enabled" label="使用居民明確要求保存的記憶" description="只有居民主動說『記住』並提供稱呼才保存。暫停不會刪除現有記憶，仍可按要求忘記指定內容。" />
      <p>以上設定按「儲存至平台」後，套用到居民服務台。</p>
    </section>
    <section>
      <h2>查閱及更正記憶</h2>
      <p>只查閱指定稱呼，避免列出其他居民資料；不會把記憶送去模型作測試。</p>
      <form class="cloud-memory-lookup" @submit.prevent="load">
        <FieldInput v-model="profile" label="居民使用的稱呼" placeholder="輸入居民明確提供的稱呼" :maxlength="20" />
        <button type="submit" :disabled="busy || !profile.trim()">
          查閱記憶
        </button>
      </form>
      <p role="status">
        {{ message }}
      </p>
      <ul class="cloud-memory-items">
        <li v-for="item in items" :key="item.id">
          <p>{{ item.text }}</p>
          <template v-if="confirming === item.id">
            <p>確定按居民要求忘記這一項？</p>
            <button type="button" :disabled="busy" @click="forget(item.id)">
              確認忘記
            </button>
            <button type="button" :disabled="busy" @click="confirming = ''">
              取消
            </button>
          </template>
          <button v-else type="button" :disabled="busy" @click="confirming = item.id">
            忘記這一項
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style>
.cloud-memory-settings{display:grid;gap:24px}.cloud-memory-settings section{display:grid;gap:18px;padding:20px;border:1px solid #d9e5df;border-radius:16px;background:#ffffffb0}.cloud-memory-settings h2{font-size:22px}.cloud-memory-settings p{line-height:1.7;color:#5c776a}.cloud-memory-lookup{display:grid;grid-template-columns:1fr auto;gap:16px;align-items:end}.cloud-memory-items{display:grid;gap:14px}.cloud-memory-items li{padding:16px;border:1px solid #d9e5df;border-radius:12px}.cloud-memory-settings button{padding:11px 16px;border:1px solid #cadbd3;border-radius:10px;margin-right:8px;background:white}@media(max-width:600px){.cloud-memory-lookup{grid-template-columns:1fr}}
</style>
