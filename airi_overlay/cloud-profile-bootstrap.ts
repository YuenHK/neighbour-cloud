// This file replaces local-profile-bootstrap only in an isolated cloud build.
// It contains no provider credentials, local service address or native migration.
export async function loadLocalProfile() {
  if (Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') !== true
    || !Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    || new URLSearchParams(location.search).get('estate') !== '1') {
    throw new Error('verified_cloud_resident_entry_required')
  }
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
