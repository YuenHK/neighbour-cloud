// This file replaces local-profile-bootstrap only in an isolated cloud build.
// It contains no provider credentials, local service address or native migration.
import { env } from '@huggingface/transformers'

export async function loadLocalProfile() {
  if (Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') !== true
    || !Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    || new URLSearchParams(location.search).get('estate') !== '1') {
    throw new Error('verified_cloud_resident_entry_required')
  }
  // Match the reviewed runtime copied into the cloud asset manifest. The
  // library CDN default cannot execute under the same-origin script policy.
  const wasm = env.backends.onnx.wasm
  if (!wasm)
    throw new Error('cloud_voice_runtime_unavailable')
  wasm.wasmPaths = '/assets/onnx-3.8.1/'
  wasm.numThreads = 1
  // The tiny VAD weights are shipped with this same-origin deployment too.
  // Capturing a resident's voice must not wait on a third-party model host.
  env.allowLocalModels = true
  env.allowRemoteModels = false
  env.localModelPath = '/assets/models/'
  const settingsMode = new URLSearchParams(location.search).get('settings') === '1'
  try {
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch(settingsMode ? '/api/v1/service-desk/presentation' : '/api/v1/resident/presentation', { signal: AbortSignal.timeout(10000) })
    if (settingsMode && !response.ok)
      throw new Error('cloud_settings_not_loaded')
    if (response.ok) {
      const value = await response.json()
      if (typeof value.name === 'string' && value.name.length <= 40
        && typeof value.greeting === 'string' && value.greeting.length <= 200
        && ['mint', 'sky', 'warm'].includes(value.background)) {
        Reflect.set(globalThis, '__NEIGHBOUR_PRESENTATION__', value)
        const model = value.airi?.stage_model ?? 'preset-live2d-2'
        if (['preset-live2d-1', 'preset-live2d-2', 'preset-vrm-1', 'preset-vrm-2'].includes(model)
          || /^cloud-live2d-[a-f0-9]{64}$/.test(model))
          localStorage.setItem('settings/stage/model', model)
        const colours = { mint: '#e5f3ec', sky: '#e7f1f8', warm: '#f6eee2' }
        // Published colour wins over the resident stylesheet's default even
        // on another device with a different OS colour scheme.
        document.body.style.setProperty('--resident-ambient', colours[value.background as keyof typeof colours])
        document.body.style.setProperty('--resident-wave', colours[value.background as keyof typeof colours])
      }
    }
  }
  catch (error) {
    // Never overwrite a staff profile with defaults after a failed read.
    if (settingsMode)
      throw error
  }
  document.body.classList.add('service-theme')
  document.body.dataset.estateKiosk = 'true'
  document.body.dataset.cloudView = settingsMode ? 'settings' : 'resident'
  document.title = settingsMode ? '鄰伴 · AIRI 設定' : '鄰伴 · 居民服務台'
  const theme = document.createElement('link')
  theme.rel = 'stylesheet'
  theme.href = '/estate-theme.css'
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('cloud_theme_not_loaded')), 12000)
    theme.onload = () => {
      clearTimeout(timer)
      resolve()
    }
    theme.onerror = () => {
      clearTimeout(timer)
      reject(new Error('cloud_theme_not_loaded'))
    }
    document.head.append(theme)
  })
  // Only presentation preferences persist on this cloud origin. Conversation,
  // Google identity and residents' contact details never go into this profile.
  if (!localStorage.getItem('settings/stage/model'))
    localStorage.setItem('settings/stage/model', 'preset-live2d-2')
  localStorage.setItem('onboarding/completed', 'true')
}
