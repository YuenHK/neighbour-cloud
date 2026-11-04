import type { ProviderMetadata } from '@proj-airi/stage-ui/stores/providers'

import { useConsciousnessStore } from '@proj-airi/stage-ui/stores/modules/consciousness'
import { useHearingStore } from '@proj-airi/stage-ui/stores/modules/hearing'
import { useSpeechStore } from '@proj-airi/stage-ui/stores/modules/speech'
import { useWebSearchStore } from '@proj-airi/stage-ui/stores/modules/web-search'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { reactive } from 'vue'

import { managedNativeFetch } from './cloud-native-fetch.js'
import { createResidentApi } from './resident-api.js'

export const runtimeDefaults = {
  consciousness: { provider: 'cloudflare-workers-ai', model: 'gemma-4-26b-a4b-it' },
  speech: { provider: 'microsoft-speech', model: 'azure-hiumaan-f0', voice_id: 'zh-HK-HiuMaanNeural', rate: 1, pitch: 0, volume: 0 },
  hearing: { provider: 'openai-compatible-audio-transcription', model: '@cf/openai/whisper-large-v3-turbo', microphone_enabled: true, auto_send: true },
  web_search: { enabled: true },
  memory: { long_term_enabled: true, idle_seconds: 180, context_messages: 60, context_characters: 16000 },
}
export type RuntimePreferences = typeof runtimeDefaults
export const cloudRuntime = reactive(structuredClone(runtimeDefaults))
export const managedProviderIds = ['cloudflare-workers-ai', 'microsoft-speech', 'openai-compatible-audio-transcription']

const voice = { id: 'zh-HK-HiuMaanNeural', name: '香港廣東話', provider: 'microsoft-speech', compatibleModels: ['azure-hiumaan-f0'], gender: 'female', languages: [{ code: 'zh-HK', title: '香港廣東話' }] }

// Native stores use Vue i18n/analytics composables. Construct them during
// setup, before awaiting the authenticated catalog or IndexedDB.
export function prepareCloudAiriRuntime() {
  registerManagedProviders()
  useConsciousnessStore()
  useSpeechStore()
  useHearingStore()
  useWebSearchStore()
}

export function publishedRuntime() {
  const profile = Reflect.get(globalThis, '__NEIGHBOUR_PRESENTATION__')
  const value = profile?.airi?.runtime ?? {}
  return Object.fromEntries(Object.entries(runtimeDefaults).map(([key, fallback]) => [key, { ...fallback, ...value[key] }])) as RuntimePreferences
}

export function speechDraft() {
  const speech = useSpeechStore()
  return { rate: speech.rate, pitch: speech.pitch, volume: cloudRuntime.speech.volume }
}

export function collectRuntime(): RuntimePreferences {
  const mind = useConsciousnessStore()
  const speech = useSpeechStore()
  const hearing = useHearingStore()
  const search = useWebSearchStore()
  return {
    consciousness: { provider: mind.activeProvider, model: mind.activeModel },
    speech: { provider: speech.activeSpeechProvider, model: speech.activeSpeechModel, voice_id: speech.activeSpeechVoiceId, ...speechDraft() },
    hearing: { provider: hearing.activeTranscriptionProvider, model: hearing.activeTranscriptionModel, microphone_enabled: cloudRuntime.hearing.microphone_enabled, auto_send: hearing.autoSendEnabled },
    web_search: { enabled: search.enabled },
    memory: { ...cloudRuntime.memory },
  }
}

function registerManagedProviders(configured?: Record<string, boolean>) {
  const providers = useProvidersStore()
  const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
  if (!transport || Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') !== true)
    throw new Error('verified_cloud_runtime_required')
  const resident = createResidentApi({ cloud: true, transport: () => transport })
  const fetchFor = (kind: 'chat' | 'speech' | 'hearing') => managedNativeFetch(kind, {
    transport,
    speech: speechDraft,
    transcribe: (audio: Blob, signal?: AbortSignal) => resident.transcribe(audio, {
      sessionId: crypto.randomUUID().replaceAll('-', ''),
      inputId: crypto.randomUUID().replaceAll('-', ''),
    }, signal),
  })
  const baseURL = `${location.origin}/cloud/managed/`

  const definitions: ProviderMetadata[] = [
    {
      id: 'cloudflare-workers-ai',
      category: 'chat',
      tasks: ['chat'],
      nameKey: 'neighbour.gemma',
      name: 'Cloudflare Gemma · Free',
      descriptionKey: 'neighbour.gemma.description',
      description: '居民對話、上下文與關懷；沿用每日免費額度。',
      createProvider: () => ({ chat: (model: string) => ({ apiKey: '', baseURL, model, fetch: fetchFor('chat') }) }),
      capabilities: { listModels: async () => [{ id: 'gemma-4-26b-a4b-it', name: 'Gemma 4 26B A4B', provider: 'cloudflare-workers-ai' }] },
      validators: { chatPingCheckAvailable: false, validateProviderConfig: () => ({ errors: [], reason: '', valid: configured?.['cloudflare-workers-ai'] ?? true }) },
    },
    {
      id: 'microsoft-speech',
      category: 'speech',
      tasks: ['text-to-speech'],
      nameKey: 'neighbour.hiumaan',
      name: 'Microsoft 語音服務',
      descriptionKey: 'neighbour.hiumaan.description',
      description: '香港廣東話朗讀；使用已接通的免費 F0 資源。',
      createProvider: () => ({ speech: (model: string) => ({ apiKey: '', baseURL, model, fetch: fetchFor('speech') }) }),
      capabilities: { listModels: async () => [{ id: 'azure-hiumaan-f0', name: 'Microsoft 語音服務', provider: 'microsoft-speech' }], listVoices: async () => [voice] },
      validators: { chatPingCheckAvailable: false, validateProviderConfig: () => ({ errors: [], reason: '', valid: configured?.['microsoft-speech'] ?? true }) },
    },
    {
      id: 'openai-compatible-audio-transcription',
      category: 'transcription',
      tasks: ['speech-to-text'],
      nameKey: 'neighbour.whisper',
      name: 'Cloudflare Whisper · Free',
      descriptionKey: 'neighbour.whisper.description',
      description: '香港廣東話語音輸入；與 Gemma 共用免費額度。',
      createProvider: () => ({ transcription: (model: string) => ({ apiKey: '', baseURL, model, fetch: fetchFor('hearing') }) }),
      capabilities: { listModels: async () => [{ id: '@cf/openai/whisper-large-v3-turbo', name: 'Whisper Large v3 Turbo', provider: 'openai-compatible-audio-transcription' }] },
      validators: { chatPingCheckAvailable: false, validateProviderConfig: () => ({ errors: [], reason: '', valid: configured?.['openai-compatible-audio-transcription'] ?? true }) },
    },
  ]
  for (const metadata of definitions) {
    metadata.requiresCredentials = false
    metadata.defaultOptions = () => ({ managed: true })
    metadata.pricing = 'free'
    metadata.deployment = 'cloud'
    providers.providerMetadata[metadata.id] = metadata
    providers.initializeProvider(metadata.id)
    // No key or credential marker is written to browser storage.
    providers.markProviderAdded(metadata.id)
    if (configured?.[metadata.id] !== false)
      providers.forceProviderConfigured(metadata.id)
    else
      providers.providerRuntimeState[metadata.id].isConfigured = false
  }
}

export function installCloudAiriRuntime(configured?: Record<string, boolean>) {
  const prefs = publishedRuntime()
  for (const key of Object.keys(runtimeDefaults) as (keyof RuntimePreferences)[])
    Object.assign(cloudRuntime[key], prefs[key])
  registerManagedProviders(configured)
  const mind = useConsciousnessStore()
  const speech = useSpeechStore()
  const hearing = useHearingStore()
  const search = useWebSearchStore()
  mind.activeProvider = prefs.consciousness.provider
  mind.activeModel = prefs.consciousness.model
  speech.activeSpeechProvider = prefs.speech.provider
  speech.activeSpeechModel = prefs.speech.model
  speech.activeSpeechVoiceId = prefs.speech.voice_id
  speech.pitch = prefs.speech.pitch
  speech.rate = prefs.speech.rate
  speech.availableVoices['microsoft-speech'] = [voice]
  hearing.activeTranscriptionProvider = prefs.hearing.provider
  hearing.activeTranscriptionModel = prefs.hearing.model
  hearing.autoSendEnabled = prefs.hearing.auto_send
  search.managed = configured?.tavily ?? true
  search.enabled = prefs.web_search.enabled
}
