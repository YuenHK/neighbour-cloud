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
  try {
    const transport = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    const response = await transport.fetch('/api/v1/resident/presentation', { signal: AbortSignal.timeout(5000) })
    if (response.ok) {
      const value = await response.json()
      if (typeof value.name === 'string' && value.name.length <= 40
        && typeof value.greeting === 'string' && value.greeting.length <= 200
        && ['mint', 'sky', 'warm'].includes(value.background)) {
        Reflect.set(globalThis, '__NEIGHBOUR_PRESENTATION__', value)
        const colours = { mint: '#e5f3ec', sky: '#e7f1f8', warm: '#f6eee2' }
        const style = document.createElement('style')
        style.textContent = `.estate-avatar-canvas{background:${colours[value.background as keyof typeof colours]};border-radius:18px}`
        document.head.append(style)
      }
    }
  }
  catch { /* Presentation lookup must not prevent conversation or voice startup. */ }
  document.body.classList.add('service-theme')
  document.body.dataset.estateKiosk = 'true'
  document.title = '鄰伴 · 居民服務台'
  const theme = document.createElement('link')
  theme.rel = 'stylesheet'
  theme.href = '/estate-theme.css'
  document.head.append(theme)
  // Only presentation preferences persist on this cloud origin. Conversation,
  // Google identity and residents' contact details never go into this profile.
  if (!localStorage.getItem('settings/stage/model'))
    localStorage.setItem('settings/stage/model', 'preset-live2d-2')
  localStorage.setItem('settings/audio/input/enabled', 'true')
  localStorage.setItem('onboarding/completed', 'true')
}
