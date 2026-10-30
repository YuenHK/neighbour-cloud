import { installAssistantMemory } from './assistant-memory.js'

interface ProviderProfile {
  id: string
  model: string
  baseUrl: string
  apiKey?: string
  voice?: string
  speed?: number
  thinking?: boolean
}

interface LocalProfile {
  version: 1
  providers: {
    chat: ProviderProfile
    vision: ProviderProfile
    transcription: ProviderProfile
    speech: ProviderProfile
  }
  audio?: {
    preferredInputLabel?: string
    enableInput?: boolean
  }
  vision?: {
    captureIntervalMs?: number
  }
  hearing?: {
    autoSend?: boolean
    autoSendDelayMs?: number
  }
}

function setValue(key: string, value: string | number | boolean) {
  localStorage.setItem(key, String(value))
}

function savedValue(key: string) {
  return localStorage.getItem?.(key) ?? null
}

function savedRecord(key: string): Record<string, any> {
  const value = savedValue(key)
  const record = value ? JSON.parse(value) : {}
  if (!record || typeof record !== 'object' || Array.isArray(record))
    throw new Error('Existing AIRI settings are invalid; retained without overwriting')
  return record
}

function setDefault(key: string, value: string | number | boolean) {
  if (!savedValue('estate/native-settings-v1') && savedValue(key) === null)
    setValue(key, value)
}

function assertProvider(provider: ProviderProfile, name: string) {
  if (!provider.id || !provider.model || !provider.baseUrl.endsWith('/'))
    throw new Error(`Invalid ${name} provider in local profile`)
}

async function selectPreferredMicrophone(profile: LocalProfile) {
  // Apply false too: an old browser setting must not silently keep capture on.
  setValue('settings/audio/input/enabled', profile.audio?.enableInput === true)
  if (!profile.audio?.enableInput)
    return

  const preferredLabel = profile.audio.preferredInputLabel?.trim().toLowerCase()
  if (!preferredLabel || !navigator.mediaDevices?.enumerateDevices)
    return

  try {
    const devices = await navigator.mediaDevices.enumerateDevices()
    const microphone = devices.find(device =>
      device.kind === 'audioinput' && device.label.toLowerCase().includes(preferredLabel),
    )
    if (microphone?.deviceId)
      setValue('settings/audio/input', microphone.deviceId)
  }
  catch (error) {
    console.warn('[local-profile] Unable to select preferred microphone', error)
  }
}

export async function loadLocalProfile() {
  const estateMode = new URLSearchParams(globalThis.location?.search || '').get('estate') === '1'
  if (!estateMode)
    installAssistantMemory()
  if (typeof document !== 'undefined') {
    document.body.classList.add('service-theme')
    if (estateMode)
      document.body.dataset.estateKiosk = 'true'
    if (!document.querySelector('link[data-estate-theme]')) {
      const theme = document.createElement('link')
      theme.rel = 'stylesheet'
      theme.href = '/estate-theme.css'
      theme.dataset.estateTheme = 'true'
      document.head.append(theme)
    }
    document.title = '屋苑服務台 · 數字人'
    const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]') || document.createElement('link')
    icon.rel = 'icon'
    icon.type = 'image/svg+xml'
    icon.href = '/estate-mark.svg'
    document.head.append(icon)
  }
  // A cached page may load while every local service is stopped. Never retain
  // an old capture-on setting while waiting for a missing/invalid profile.
  setValue('settings/audio/input/enabled', false)
  try {
    const response = await fetch('/airi-local-profile.json', {
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    })
    if (!response.ok)
      throw new Error(`HTTP ${response.status}`)

    const profile = await response.json() as LocalProfile
    if (profile.version !== 1)
      throw new Error(`Unsupported profile version: ${String(profile.version)}`)
    if (estateMode)
      profile.audio = { ...profile.audio, enableInput: true }

    const { chat, vision, transcription, speech } = profile.providers
    assertProvider(chat, 'chat')
    assertProvider(vision, 'vision')
    assertProvider(transcription, 'transcription')
    assertProvider(speech, 'speech')

    const credentials: Record<string, Record<string, unknown>> = {
      [chat.id]: {
        apiKey: chat.apiKey ?? 'local',
        baseUrl: chat.baseUrl,
        headers: {},
        thinkingMode: 'disable',
      },
      [vision.id]: {
        baseUrl: vision.baseUrl,
        headers: {},
        thinkingMode: vision.thinking === false ? 'disable' : 'auto',
      },
      [transcription.id]: {
        apiKey: transcription.apiKey ?? 'local',
        baseUrl: transcription.baseUrl,
        model: transcription.model,
      },
      [speech.id]: {
        apiKey: speech.apiKey ?? 'local',
        baseUrl: speech.baseUrl,
        model: speech.model,
        voice: speech.voice ?? 'yue',
        speed: speech.speed ?? 1,
      },
    }

    const existing = savedRecord('settings/credentials/providers')
    const added = savedRecord('settings/providers/added')
    const firstNativeMigration = !savedValue('estate/native-settings-v1')
    if (speech.model === 'mimo-v2.5-tts' && chat.model === 'gemma-4-26b-a4b-it' && !savedValue('estate/mimo-gemma-v1')) {
      localStorage.setItem('estate/chat-before-mimo-v1', JSON.stringify({ credentials: existing, provider: savedValue('settings/consciousness/active-provider'), model: savedValue('settings/consciousness/active-model') }))
      if (!savedValue('estate/native-settings-before-v1'))
        localStorage.setItem('estate/native-settings-before-v1', JSON.stringify({ credentials: existing, chatProvider: savedValue('settings/consciousness/active-provider'), chatModel: savedValue('settings/consciousness/active-model'), speechModel: savedValue('settings/speech/active-model'), speechVoice: savedValue('settings/speech/voice') }))
      if (savedValue('settings/consciousness/active-provider') === 'ollama' && savedValue('settings/consciousness/active-model') === 'qwen3:1.7b' && existing.ollama?.baseUrl === 'http://127.0.0.1:8000/v1/')
        existing.ollama = { ...existing.ollama, baseUrl: 'http://127.0.0.1:11434/v1/' }
      existing[chat.id] = { ...existing[chat.id], ...credentials[chat.id] }
      added[chat.id] = true
      setValue('settings/consciousness/active-provider', chat.id)
      setValue('settings/consciousness/active-model', chat.model)
      setValue('estate/mimo-gemma-v1', true)
    }
    if (speech.model === 'mimo-v2.5-tts' && !savedValue('estate/mimo-bingtang-v1')) {
      localStorage.setItem('estate/speech-before-mimo-v1', JSON.stringify({ credentials: existing, provider: savedValue('settings/speech/active-provider'), model: savedValue('settings/speech/active-model'), voice: savedValue('settings/speech/voice') }))
      existing[speech.id] = { ...existing[speech.id], ...credentials[speech.id], apiKey: existing[speech.id]?.apiKey || speech.apiKey || 'local' }
      added[speech.id] = true
      setValue('settings/speech/active-provider', speech.id)
      setValue('settings/speech/active-model', speech.model)
      setValue('settings/speech/voice', speech.voice ?? '冰糖')
      setValue('estate/mimo-bingtang-v1', true)
    }
    if (speech.model === 'azure-hiumaan-f0' && !savedValue('estate/azure-hiumaan-f0-v1')) {
      localStorage.setItem('estate/speech-before-azure-f0-v1', JSON.stringify({ credentials: existing, provider: savedValue('settings/speech/active-provider'), model: savedValue('settings/speech/active-model'), voice: savedValue('settings/speech/voice') }))
      existing[speech.id] = { ...existing[speech.id], ...credentials[speech.id], apiKey: existing[speech.id]?.apiKey || 'local' }
      added[speech.id] = true
      setValue('settings/speech/active-provider', speech.id)
      setValue('settings/speech/active-model', speech.model)
      setValue('settings/speech/voice', speech.voice ?? 'zh-HK-HiuMaanNeural')
      setValue('estate/azure-hiumaan-f0-v1', true)
    }
    const defaultCompatible = existing[chat.id]
      && !existing[chat.id].apiKey
      && /^https:\/\/api\.openai\.com\/v1\/?$/.test(existing[chat.id].baseUrl || '')
    const legacyChat = !savedValue('estate/native-chat-migration-v2') && savedValue('settings/consciousness/active-provider') === 'ollama'
      && savedValue('settings/consciousness/active-model') === 'qwen3:1.7b'
      && existing.ollama?.baseUrl === 'http://127.0.0.1:8000/v1/'
      && (!existing[chat.id] || defaultCompatible || existing[chat.id].baseUrl === chat.baseUrl)
    const legacySpeech = firstNativeMigration && savedValue('settings/speech/active-provider') === speech.id
      && savedValue('settings/speech/active-model') === 'vits-cantonese-yue'
      && savedValue('settings/speech/voice') === 'yue'
      && existing[speech.id]?.baseUrl === speech.baseUrl
    if ((legacyChat || legacySpeech) && !savedValue('estate/native-settings-before-v1')) {
      // Recoverable snapshot of settings we intentionally migrate; never print keys.
      localStorage.setItem('estate/native-settings-before-v1', JSON.stringify({ credentials: existing, chatProvider: savedValue('settings/consciousness/active-provider'), chatModel: savedValue('settings/consciousness/active-model'), speechModel: savedValue('settings/speech/active-model'), speechVoice: savedValue('settings/speech/voice') }))
    }
    for (const [id, value] of Object.entries(credentials)) {
      if (firstNativeMigration && !existing[id])
        existing[id] = value
    }
    if (legacyChat) {
      localStorage.setItem('estate/native-chat-before-v2', JSON.stringify({ credentials: existing, added, provider: savedValue('settings/consciousness/active-provider'), model: savedValue('settings/consciousness/active-model') }))
      existing[chat.id] = { ...existing[chat.id], ...credentials[chat.id] }
      added[chat.id] = true
      existing.ollama = { ...existing.ollama, baseUrl: 'http://127.0.0.1:11434/v1/' }
      setValue('settings/consciousness/active-provider', chat.id)
      setValue('settings/consciousness/active-model', chat.model)
    }
    if (legacySpeech) {
      existing[speech.id] = { ...existing[speech.id], model: speech.model, voice: speech.voice }
      setValue('settings/speech/active-model', speech.model)
      setValue('settings/speech/voice', speech.voice ?? 'resident-yue')
    }
    localStorage.setItem('settings/credentials/providers', JSON.stringify(existing))
    if (firstNativeMigration) {
      for (const id of [chat.id, vision.id, transcription.id, speech.id]) {
        if (!(id in added))
          added[id] = true
      }
    }
    localStorage.setItem('settings/providers/added', JSON.stringify(added))

    setDefault('settings/consciousness/active-provider', chat.id)
    setDefault('settings/consciousness/active-model', chat.model)
    setDefault('settings/vision/active-provider', vision.id)
    setDefault('settings/vision/active-model', vision.model)
    setDefault('settings/vision/ollama-thinking-enabled', vision.thinking ?? false)
    setDefault('settings/hearing/active-provider', transcription.id)
    setDefault('settings/hearing/active-model', transcription.model)
    setDefault('settings/speech/active-provider', speech.id)
    setDefault('settings/speech/active-model', speech.model)
    setDefault('settings/speech/voice', speech.voice ?? 'resident-yue')
    setDefault('settings/speech/rate', speech.speed ?? 1)
    setDefault('settings/hearing/auto-send-enabled', profile.hearing?.autoSend ?? true)
    setDefault('settings/hearing/auto-send-delay', profile.hearing?.autoSendDelayMs ?? 2000)
    setDefault('settings/vision/capture-interval-ms', profile.vision?.captureIntervalMs ?? 3000)
    setValue('estate/native-settings-v1', true)
    setValue('estate/native-chat-migration-v2', true)
    setValue('onboarding/completed', true)

    if (estateMode)
      setValue('settings/audio/input/enabled', true)
    else
      await selectPreferredMicrophone(profile)
    console.info('[local-profile] AIRI local profile loaded')
  }
  catch (error) {
    console.error('[local-profile] 本機設定未能載入；收音保持關閉。請核對 START-AIRI 及 4173 服務。', error)
  }
}
