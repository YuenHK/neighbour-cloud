const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const { pathToFileURL } = require('node:url')
const { test } = require('node:test')

test('managed old chat migrates past an unused AIRI default without replacing configured credentials', async () => {
  const profile = JSON.parse(readFileSync(resolve(__dirname, '../config/airi-local-profile.json'), 'utf8'))
  const { loadLocalProfile } = await import(pathToFileURL(resolve(__dirname, '../airi_overlay/local-profile-bootstrap.ts')))
  const oldFetch = globalThis.fetch
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  try {
    for (const apiKey of ['', 'synthetic-custom']) {
      const values = new Map([
        ['estate/native-settings-v1', 'true'], ['estate/native-settings-before-v1', 'original-backup'], ['estate/mimo-gemma-v1', 'true'],
        ['settings/credentials/providers', JSON.stringify({ ollama: { baseUrl: 'http://127.0.0.1:8000/v1/' }, 'openai-compatible': { apiKey, baseUrl: 'https://api.openai.com/v1' } })],
        ['settings/consciousness/active-provider', 'ollama'], ['settings/consciousness/active-model', 'qwen3:1.7b'],
      ])
      Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) } })
      globalThis.fetch = async () => ({ ok: true, json: async () => profile })
      await loadLocalProfile()
      assert.equal(values.get('settings/consciousness/active-model'), apiKey ? 'qwen3:1.7b' : profile.providers.chat.model)
      assert.equal(values.get('estate/native-settings-before-v1'), 'original-backup')
      assert.equal(JSON.parse(values.get('settings/credentials/providers'))['openai-compatible'].baseUrl, apiKey ? 'https://api.openai.com/v1' : profile.providers.chat.baseUrl)
      if (!apiKey) assert.ok(values.get('estate/native-chat-before-v2'))
    }
  }
  finally {
    globalThis.fetch = oldFetch
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage)
    else delete globalThis.localStorage
  }
})

test('native AIRI selections survive reload and only the known old managed defaults are migrated', async () => {
  const profile = JSON.parse(readFileSync(resolve(__dirname, '../config/airi-local-profile.json'), 'utf8'))
  const { loadLocalProfile } = await import(pathToFileURL(resolve(__dirname, '../airi_overlay/local-profile-bootstrap.ts')))
  const oldFetch = globalThis.fetch
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const values = new Map([
    ['settings/credentials/providers', JSON.stringify({ ollama: { baseUrl: 'http://127.0.0.1:8000/v1/' },
      'openai-compatible-audio-speech': { baseUrl: 'http://127.0.0.1:8765/v1/', apiKey: 'synthetic-existing' } })],
    ['settings/consciousness/active-provider', 'ollama'], ['settings/consciousness/active-model', 'qwen3:1.7b'],
    ['settings/speech/active-provider', 'openai-compatible-audio-speech'], ['settings/speech/active-model', 'vits-cantonese-yue'],
    ['settings/speech/voice', 'yue'], ['airi-cards', 'existing-character-settings'],
  ])
  try {
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
      getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
    } })
    globalThis.fetch = async () => ({ ok: true, json: async () => profile })
    await loadLocalProfile()
    assert.equal(values.get('settings/consciousness/active-model'), 'gemma-4-26b-a4b-it')
    assert.equal(values.get('settings/speech/voice'), profile.providers.speech.voice)
    assert.ok(values.get('estate/speech-before-azure-f0-v1'))
    assert.equal(JSON.parse(values.get('settings/credentials/providers')).ollama.baseUrl, 'http://127.0.0.1:11434/v1/')
    assert.ok(values.get('estate/native-settings-before-v1'))
    assert.equal(JSON.parse(values.get('settings/credentials/providers'))['openai-compatible-audio-speech'].apiKey, 'synthetic-existing')
    values.set('settings/consciousness/active-provider', 'operator-chosen-provider')
    values.set('settings/consciousness/active-model', 'operator-chosen-model')
    values.set('settings/speech/active-provider', 'operator-chosen-speech')
    values.set('settings/speech/voice', 'operator-chosen-voice')
    await loadLocalProfile()
    assert.equal(values.get('settings/consciousness/active-provider'), 'operator-chosen-provider')
    assert.equal(values.get('settings/consciousness/active-model'), 'operator-chosen-model')
    assert.equal(values.get('settings/speech/active-provider'), 'operator-chosen-speech')
    assert.equal(values.get('settings/speech/voice'), 'operator-chosen-voice')
    assert.equal(values.get('airi-cards'), 'existing-character-settings')
    values.set('settings/consciousness/active-provider', '')
    values.set('settings/credentials/providers', '{}')
    values.set('settings/providers/added', '{}')
    await loadLocalProfile()
    assert.equal(values.get('settings/consciousness/active-provider'), '')
    assert.equal(values.get('settings/credentials/providers'), '{}')
    assert.equal(values.get('settings/providers/added'), '{}')
  }
  finally {
    globalThis.fetch = oldFetch
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage)
    else delete globalThis.localStorage
  }
})

test('network history error is actionable without hiding or altering other errors', async () => {
  const { formatLocalConnectionError } = await import(pathToFileURL(resolve(__dirname, '../airi_overlay/local-connection-error.ts')))
  for (const message of ['Failed to fetch', 'TypeError: Failed to fetch', ' NetworkError when attempting to fetch resource. ']) {
    assert.match(formatLocalConnectionError(message), /當次請求未能連線/)
    assert.match(formatLocalConnectionError(message), /不代表目前連線狀態/)
  }
  for (const message of ['', 'model_not_found', 'Remote sent 503 response', 'a Failed to fetch suffix'])
    assert.equal(formatLocalConnectionError(message), message)
})

test('profile bootstrap disables stale microphone settings without requesting devices', async () => {
  const profile = JSON.parse(readFileSync(resolve(__dirname, '../config/airi-local-profile.json'), 'utf8'))
  const { loadLocalProfile } = await import(pathToFileURL(resolve(__dirname, '../airi_overlay/local-profile-bootstrap.ts')))
  const oldFetch = globalThis.fetch
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const oldNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  let deviceReads = 0
  try {
    Object.defineProperty(globalThis, 'navigator', {
      configurable: true,
      get() { deviceReads++; throw new Error('capture/device access forbidden in this test') },
    })
    for (const audio of [{ enableInput: false }, {}, undefined]) {
      const values = new Map([['settings/audio/input/enabled', 'true']])
      Object.defineProperty(globalThis, 'localStorage', {
        configurable: true, value: { setItem: (key, value) => values.set(key, value) },
      })
      globalThis.fetch = async (url, options) => {
        assert.equal(url, '/airi-local-profile.json')
        assert.equal(options.cache, 'no-store')
        return { ok: true, json: async () => ({ ...profile, audio }) }
      }
      await loadLocalProfile()
      assert.equal(values.get('settings/audio/input/enabled'), 'false')
      assert.equal(values.get('settings/consciousness/active-provider'), profile.providers.chat.id)
      assert.equal(values.get('settings/consciousness/active-model'), profile.providers.chat.model)
    }
    assert.equal(deviceReads, 0)
  }
  finally {
    globalThis.fetch = oldFetch
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage)
    else delete globalThis.localStorage
    if (oldNavigator) Object.defineProperty(globalThis, 'navigator', oldNavigator)
    else delete globalThis.navigator
  }
})

test('unreachable or malformed profile cannot retain capture-on state', async () => {
  const { loadLocalProfile } = await import(pathToFileURL(resolve(__dirname, '../airi_overlay/local-profile-bootstrap.ts')))
  const oldFetch = globalThis.fetch
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const oldError = console.error
  try {
    console.error = () => {}
    for (const failure of ['network', 'json', 'http', 'version']) {
      const values = new Map([['settings/audio/input/enabled', 'true']])
      Object.defineProperty(globalThis, 'localStorage', {
        configurable: true, value: { setItem: (key, value) => values.set(key, value) },
      })
      globalThis.fetch = async (_url, options) => {
        assert.equal(values.get('settings/audio/input/enabled'), 'false')
        assert.ok(options.signal instanceof AbortSignal)
        if (failure === 'network') throw new TypeError('Failed to fetch')
        return { ok: failure !== 'http', status: 503, json: async () => {
          if (failure === 'json') throw new SyntaxError('bad json')
          return { version: 2 }
        } }
      }
      await loadLocalProfile()
      assert.equal(values.get('settings/audio/input/enabled'), 'false')
    }
  }
  finally {
    globalThis.fetch = oldFetch
    console.error = oldError
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage)
    else delete globalThis.localStorage
  }
})

test('valid resident profile enables voice by default without probing devices in bootstrap', async () => {
  const profile = JSON.parse(readFileSync(resolve(__dirname, '../config/airi-local-profile.json'), 'utf8'))
  const { loadLocalProfile } = await import(pathToFileURL(resolve(__dirname, '../airi_overlay/local-profile-bootstrap.ts')))
  const oldFetch = globalThis.fetch
  const saved = new Map(['location', 'navigator', 'localStorage'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const values = new Map()
  let devices = 0
  try {
    Object.defineProperty(globalThis, 'location', { configurable: true, value: { search: '?estate=1' } })
    Object.defineProperty(globalThis, 'navigator', { configurable: true, get() { devices++; throw new Error('no automatic device access') } })
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { setItem: (key, value) => values.set(key, value) } })
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ ...profile, audio: { enableInput: false } }) })
    await loadLocalProfile()
    assert.equal(values.get('settings/audio/input/enabled'), 'true')
    assert.equal(devices, 0)
  }
  finally {
    globalThis.fetch = oldFetch
    for (const [key, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else delete globalThis[key]
    }
  }
})
