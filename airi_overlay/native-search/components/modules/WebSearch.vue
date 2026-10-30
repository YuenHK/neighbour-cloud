<script setup lang="ts">
import { FieldCheckbox, FieldInput } from '@proj-airi/ui'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'

import { useWebSearchStore } from '../../stores/modules/web-search'

const { t } = useI18n()
const webSearchStore = useWebSearchStore()
// Settings persist to localStorage on change (useLocalStorageManualReset), and
// the tool + prompt react to `configured` — so there is no explicit save step.
const { enabled, apiKey, configured, managed } = storeToRefs(webSearchStore)
</script>

<template>
  <div flex="~ col gap-6">
    <FieldCheckbox
      v-model="enabled"
      :label="t('settings.pages.modules.web-search.enable')"
      :description="t('settings.pages.modules.web-search.enable-description')"
    />

    <p v-if="managed">
      已連接本機 Tavily 金鑰，與居民服務台共用搜尋及快取；毋須重複輸入。
    </p>
    <FieldInput
      v-else
      v-model="apiKey"
      type="password"
      :label="t('settings.pages.modules.web-search.api-key')"
      :description="t('settings.pages.modules.web-search.api-key-description')"
      :placeholder="t('settings.pages.modules.web-search.api-key-placeholder')"
    />

    <div v-if="configured" class="rounded-lg bg-green-100 p-4 text-green-800 dark:bg-green-900 dark:text-green-100">
      {{ t('settings.pages.modules.web-search.configured') }}
    </div>
  </div>
</template>
