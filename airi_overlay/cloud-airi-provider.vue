<script setup lang="ts">
import { ProviderBasicSettings, ProviderSettingsContainer, ProviderSettingsLayout } from '@proj-airi/stage-ui/components'
import { useSpeechStore } from '@proj-airi/stage-ui/stores/modules/speech'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { FieldRange } from '@proj-airi/ui'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { cloudRuntime } from './cloud-airi-runtime'

const props = defineProps<{ providerId: string }>()
const router = useRouter()
const providers = useProvidersStore()
const speech = useSpeechStore()
const { rate, pitch } = storeToRefs(speech)
const metadata = computed(() => providers.getProviderMetadata(props.providerId))
const configured = computed(() => providers.configuredProviders[props.providerId] === true)
const modulePath = computed(() => props.providerId === 'microsoft-speech' ? '/settings/modules/speech' : props.providerId === 'cloudflare-workers-ai' ? '/settings/modules/consciousness' : '/settings/modules/hearing')
</script>

<template>
  <ProviderSettingsLayout :provider-name="metadata.name" :on-back="() => router.back()">
    <ProviderSettingsContainer>
      <ProviderBasicSettings title="已接入的服務" description="沿用平台已有的免費服務，設定由 AIRI 統一保存。">
        <p>{{ configured ? '平台已接通；登入憑證由伺服器保管，毋須重複輸入。' : '平台暫時未能確認這項服務的設定，原有資料保留。' }}</p>
        <p v-if="providerId === 'microsoft-speech'">
          Microsoft Azure Speech F0 · 曉曼 · 香港廣東話
        </p>
        <p v-else-if="providerId === 'cloudflare-workers-ai'">
          Cloudflare Workers AI · Gemma 4 26B A4B · Free
        </p>
        <p v-else>
          Cloudflare Workers AI · Whisper Large v3 Turbo · 廣東話辨識
        </p>
        <p>免費額度用完即停；此頁不會啟用付費、轉換帳戶或重置用量。</p>
        <button type="button" @click="router.push(modulePath)">
          前往模組設定{{ providerId === 'microsoft-speech' ? '及試聽' : '' }}
        </button>
      </ProviderBasicSettings>
      <section v-if="providerId === 'microsoft-speech'" class="cloud-airi-prosody">
        <h2>曉曼的說話方式</h2>
        <p>儲存至平台後，居民朗讀會使用同一組設定；可前往語音合成模組試聽草稿。聲線仍是曉曼。</p>
        <FieldRange v-model="rate" label="說話速度" description="1 為正常速度。" :min="0.5" :max="2" :step="0.01" :format-value="value => `${value} 倍`" />
        <FieldRange v-model="pitch" label="音調" description="預設 0，保留原有音調。" :min="-30" :max="30" :step="1" :format-value="value => `${value}%`" />
        <FieldRange v-model="cloudRuntime.speech.volume" label="音量調整" description="相對於曉曼預設音量。" :min="-30" :max="30" :step="1" :format-value="value => `${value}%`" />
      </section>
    </ProviderSettingsContainer>
  </ProviderSettingsLayout>
</template>

<style>
.cloud-airi-prosody{display:grid;gap:22px}.cloud-airi-prosody h2{font-size:22px}.cloud-airi-prosody p{line-height:1.7;color:#5c776a}
</style>
