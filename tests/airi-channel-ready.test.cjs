const assert = require('node:assert/strict')
const { readFileSync, existsSync } = require('node:fs')
const { resolve } = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')

const sourceFile = resolve(__dirname, '../.vendor/airi/packages/stage-ui/src/stores/mods/api/channel-server.ts')
const speechFile = resolve(__dirname, '../.vendor/airi/packages/stage-ui/src/components/scenes/Stage.vue')

test('actual initialize promise waits through authentication and finishes at SDK ready',
  { skip: !existsSync(sourceFile) }, async () => {
    const ts = require('../airi_bridge/node_modules/typescript')
    const source = readFileSync(sourceFile, 'utf8')
    const start = source.indexOf('  async function initialize(options?:')
    const end = source.indexOf('  async function ensureConnected()', start)
    assert.ok(start >= 0 && end > start)
    const javascript = ts.transpile(source.slice(start, end).replaceAll('import.meta.env.DEV', 'false'),
      { target: ts.ScriptTarget.ES2022 })
    let options
    const listeners = new Map()
    const context = { connected: { value: false }, client: { value: undefined },
      initializing: { value: null }, textConnectorFactory: { value: undefined },
      basePossibleEvents: [], websocketUrl: { value: 'ws://127.0.0.1:6121/ws' },
      defaultWebSocketUrl: 'ws://127.0.0.1:6121/ws', websocketAuthToken: { value: '' },
      hasEverConnected: { value: false }, reconnectedCallbacks: [],
      isStageWeb: () => true, isStageTamagotchi: () => false,
      WebSocketEventSource: { StageWeb: 'test-stage' },
      flush: () => {}, initializeListeners: () => {}, console,
      Client: class {
        constructor(value) { options = value }
        onEvent(type, listener) { listeners.set(type, listener) }
      } }
    vm.createContext(context)
    vm.runInContext(`${javascript}\nthis.startInitialization = initialize`, context)
    let settled = false
    // Vendor initialize() creates but does not return the shared promise;
    // ensureConnected() explicitly awaits initializing.value.
    await context.startInitialization()
    const completion = context.initializing.value.then(() => { settled = true })
    listeners.get('module:authenticated')({ data: { authenticated: true } })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(settled, false, 'authentication must not release consumer registration early')
    assert.equal(context.connected.value, false)
    options.onReady()
    await completion
    assert.equal(settled, true)
    assert.equal(context.connected.value, true)
  })

test('local CPU speech pipeline admits only one synthesis task at a time',
  { skip: !existsSync(speechFile) }, () => {
    const source = readFileSync(speechFile, 'utf8')
    const options = source.match(/const speechPipeline = createSpeechPipeline<AudioBuffer>\(\{([\s\S]*?)\n\s*tts: async/)
    assert.ok(options, 'native speech pipeline options must remain inspectable')
    assert.match(options[1], /ttsMaxConcurrent: 1,/)
  })

test('authentication alone cannot flush or release consumer initialization',
  { skip: !existsSync(sourceFile) }, () => {
    const source = readFileSync(sourceFile, 'utf8').replaceAll('\r\n', '\n')
    const start = source.indexOf("      client.value.onEvent('module:authenticated', (event) => {")
    const end = source.indexOf('\n      })', start)
    assert.ok(start >= 0 && end > start)
    const callback = source.slice(start, end)
    assert.doesNotMatch(callback, /resolve\(\)|flush\(\)|connected\.value = true/)
  })

test('actual vendor ready callback completes initialization without replaying handshake auth',
  { skip: !existsSync(sourceFile) }, () => {
    const source = readFileSync(sourceFile, 'utf8').replaceAll('\r\n', '\n')
    const begin = source.indexOf('        onReady: () => {')
    const end = source.indexOf('\n        },', begin)
    assert.ok(begin >= 0 && end > begin, 'pinned vendor ready callback must remain identifiable')
    const callback = source.slice(begin + '        onReady: '.length, end + 10)
      .replaceAll('import.meta.env.DEV', 'false')
    const counts = { flushed: 0, listeners: 0, resolved: 0, reconnected: 0 }
    const context = { hasEverConnected: { value: false }, connected: { value: false },
      flush: () => counts.flushed++, initializeListeners: () => counts.listeners++,
      resolve: () => counts.resolved++, reconnectedCallbacks: [() => counts.reconnected++], console }
    const onReady = vm.runInNewContext(`(${callback})`, context)
    // SDK may consume module:authenticated during prepare; only onReady is delivered.
    onReady()
    assert.equal(context.connected.value, true)
    assert.equal(counts.listeners, 1)
    assert.equal(counts.resolved, 1, 'initialize() must not wait forever after SDK readiness')
    onReady()
    assert.equal(counts.reconnected, 1, 'keep existing consumer re-registration on reconnect')
  })
