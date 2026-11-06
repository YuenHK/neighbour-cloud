"""Pure opt-in transformation for an isolated AIRI cloud frontend build.

Does not write native vendor files, build output or restart any service.
The native SenseVoice path remains the branch when cloud boot is absent.
"""


def resident_page(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    marker = 'const cloudResidentInput = Reflect.get(globalThis, \'__NEIGHBOUR_CLOUD__\') === true'
    old = 'const voiceTurn = new VoiceTurn(async (audio) => {' + newline
    new = marker + newline + old + (
        '  if (cloudResidentInput) {\n'
        '    if (!estateMode || !residentPanel.value)\n'
        "      throw new Error('cloud_resident_entry_required')\n"
        '    return residentPanel.value.transcribeAudio(audio)\n'
        '  }\n').replace('\n', newline)
    if new in source:
        return source
    if marker in source or source.count(old) != 1:
        raise ValueError('cloud_frontend_input_anchor_requires_review')
    return source.replace(old, new, 1)


def cloud_resident_layout(source):
    layout = '<div relative flex="~ 1 row gap-y-0 gap-x-2 <md:col">'
    replaced = '<div class="estate-resident-layout" relative flex="~ 1 row gap-y-0 gap-x-2 <md:col">'
    if replaced in source:
        return source
    if source.count(layout) != 1:
        raise ValueError('cloud_resident_layout_anchor_requires_review')
    return source.replace(layout, replaced, 1)


def cloud_main(source):
    """Keep the cloud resident build on its sole supported Vue route.

    The caller separately replaces App/profile with cloud-only counterparts.
    Native source/build remains byte-for-byte unchanged after verification.
    """
    replacements = {
        'const routeRecords = setupLayouts(routes as RouteRecordRaw[])':
            "const cloudSettingsMode = new URLSearchParams(location.search).get('settings') === '1'\n"
            "  const routeRecords = cloudSettingsMode ? (routes as RouteRecordRaw[]).filter(route => route.path.startsWith('/settings')) : setupLayouts((routes as RouteRecordRaw[]).filter(route => route.path === '/'))",
        'history: createWebHistory()': "history: cloudSettingsMode ? createMemoryHistory() : createWebHistory('/cloud/resident')",
        'createRouter, createWebHashHistory, createWebHistory': 'createRouter, createMemoryHistory, createWebHashHistory, createWebHistory',
        "import '@proj-airi/font-cjkfonts-allseto/index.css'": '// Cloud uses the service desk system font.',
        "import '@proj-airi/font-xiaolai/index.css'": '// No 50 MB font preload in the cloud entry.',
        'void bootstrapLocalProfile()': """void bootstrapLocalProfile().catch(() => {
  const app = document.getElementById('app')
  if (app)
    app.replaceChildren(Object.assign(document.createElement('p'), { textContent: '畫面資料暫時未能載入，請由平台重新開啟此頁。未載入的設定不會覆蓋原有資料。' }))
  parent.postMessage({ type: 'neighbour-service-error', area: 'resident' }, location.origin)
})""",
    }
    for old, new in replacements.items():
        if new in source:
            continue
        if source.count(old) != 1:
            raise ValueError('cloud_frontend_main_anchor_requires_review')
        source = source.replace(old, new, 1)
    return source


def cloud_scene(source):
    """Remove native-only instrumentation and the unused 100 MB DB stub.

    Keep animation, lip sync, the resident PCM graph and rendering intact.
    """
    newline = '\r\n' if '\r\n' in source else '\n'
    for old in (
        "import { useDuckDb } from '../../composables/use-duck-db'\n",
        "import { useIOTraceBridge } from '../../composables/use-io-trace-bridge'\n",
        "import { initIOTracer } from '../../composables/use-io-tracer'\n",
        "import { useSpeechPipelineAnalytics } from '../../composables/use-speech-pipeline-analytics'\n",
        'const { getDb } = useDuckDb()\n',
        'initIOTracer()\n', 'useIOTraceBridge(speechPipeline)\n', 'useSpeechPipelineAnalytics()\n',
        'void speechRuntimeStore.registerHost(speechPipeline)\n',
        'onMounted(async () => {\n  await getDb() // stub for future update\n})\n',
    ):
        old = old.replace('\n', newline)
        if source.count(old) != 1:
            raise ValueError('cloud_frontend_scene_anchor_requires_review')
        source = source.replace(old, '', 1)
    while newline * 3 in source:
        source = source.replace(newline * 3, newline * 2)
    anchor = "const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })"
    if source.count(anchor) != 1:
        raise ValueError('cloud_stage_readiness_anchor_requires_review')
    source = source.replace(anchor, anchor + newline + (
        "watch(componentState, (state) => {\n"
        "  if (Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') === true)\n"
        "    parent.postMessage({ type: 'neighbour-service-stage', state }, location.origin)\n"
        "  Reflect.set(globalThis, '__NEIGHBOUR_AVATAR_READY__', state === 'mounted')\n"
        "  if (state === 'mounted') window.dispatchEvent(new Event('resident-avatar-ready'))\n"
        "}, { immediate: true })").replace('\n', newline), 1)
    late = 'watch([stageModelRenderer, () => props.paused]'
    if source.count(late) != 1:
        raise ValueError('cloud_vrm_readiness_anchor_requires_review')
    source = source.replace(late, (
        "watch(componentState, (state) => {\n"
        "  if (state === 'mounted' && stageModelRenderer.value !== 'live2d')\n"
        "    window.dispatchEvent(new CustomEvent('resident-render-state', { detail: { state: 'ready' } }))\n"
        "}, { immediate: true })\n\n").replace('\n', newline) + late, 1)
    return cloud_free_skeletal_scene(cloud_avatar_audio(source))


def cloud_avatar_audio(source):
    """Stable resident stream graph, independent of per-chunk playback nodes."""
    old = source[source.index('async function residentPcmGraph(event: Event) {'):source.index('</script>', source.index('async function residentPcmGraph(event: Event) {'))]
    if old.count("window.addEventListener('resident-pcm-node'") != 1:
        raise ValueError('cloud_avatar_audio_anchor_requires_review')
    new = """let residentSource: AudioNode | undefined
let residentGraphGeneration = 0
async function residentPcmGraph(event: Event) {
  const data = (event as CustomEvent<{ source: AudioNode, context: AudioContext }>).detail
  if (!data || data.context !== audioContext || stageDisposed)
    return
  residentSource = data.source
  const generation = ++residentGraphGeneration
  currentAudioSource.value = data.source
  setupAnalyser()
  try {
    await setupLipSync()
    if (stageDisposed || generation !== residentGraphGeneration || residentSource !== data.source)
      return
    if (audioAnalyser.value)
      data.source.connect(audioAnalyser.value)
    if (lipSyncNode.value)
      data.source.connect(lipSyncNode.value)
  }
  catch { /* Audio playback remains available if avatar analysis cannot start. */ }
}
function residentPcmEnded(event: Event) {
  const data = (event as CustomEvent<{ source: AudioNode }>).detail
  if (data?.source !== residentSource)
    return
  residentGraphGeneration++
  if (currentAudioSource.value === residentSource)
    currentAudioSource.value = undefined
  residentSource = undefined
}
onMounted(() => {
  window.addEventListener('resident-pcm-node', residentPcmGraph)
  window.addEventListener('resident-pcm-ended', residentPcmEnded)
})
onUnmounted(() => {
  stageDisposed = true
  residentGraphGeneration++
  window.removeEventListener('resident-pcm-node', residentPcmGraph)
  window.removeEventListener('resident-pcm-ended', residentPcmEnded)
})
"""
    source = source.replace(old, new)
    for old, new in (
        ('const currentAudioSource = ref<AudioBufferSourceNode>()', 'const currentAudioSource = ref<AudioNode>()\nlet stageDisposed = false'),
        ("import { animations } from '@proj-airi/stage-ui-three/assets/vrm'", "import { animations } from '@proj-airi/stage-ui-three/assets/vrm'\nimport { releaseResidentLipSync } from '../../../../model-driver-lipsync/src/resident-lipsync'"),
        ('    lipSyncNode.value?.disconnect()', '    releaseResidentLipSync(lipSyncNode.value)'),
        ('async function setupLipSync() {', 'let lipSyncPreparing: Promise<void> | undefined\nasync function setupLipSync() {\n  if (lipSyncPreparing) return lipSyncPreparing\n  lipSyncPreparing = prepareLipSync().finally(() => {\n    lipSyncPreparing = undefined\n  })\n  return lipSyncPreparing\n}\nasync function prepareLipSync() {'),
        ('    live2dLipSync.value = lipSync', "    if (stageDisposed || stageModelRenderer.value !== 'live2d') {\n      releaseResidentLipSync(lipSync.node)\n      return\n    }\n    live2dLipSync.value = lipSync"),
    ):
        if source.count(old) != 1:
            raise ValueError('cloud_avatar_scene_anchor_requires_review')
        source = source.replace(old, new, 1)
    return source


def cloud_audio_node_type(source):
    if source.count('currentAudioSource?: AudioBufferSourceNode') != 1:
        raise ValueError('cloud_avatar_node_type_requires_review')
    source = source.replace('currentAudioSource?: AudioBufferSourceNode', 'currentAudioSource?: AudioNode', 1)
    if 'function runVrmFrameRuntimeHook(' in source:
        # The native MediaPipe driver owns/replaces the external pose hook.
        # Resident motion must run after it, rather than competing for it.
        old = '''function runVrmFrameRuntimeHook(vrm: VRM, delta: number) {
  try {
    vrmFrameRuntimeHook.value?.(vrm, delta)
  }
  catch (error) {
    console.error(error)
    emit('error', error)
  }
}'''
        new = '''const residentDisplay = residentVrmDisplay()
const residentMotion = residentVrmGesture()
watch(() => props.paused, (paused) => { if (paused) residentMotion.restore() })
''' + old[:-1] + '''  finally {
    residentDisplay.update(vrm, camera.value)
    residentMotion.update(vrm, delta)
  }
}'''
        for before, after in (
            ("import { VRMUtils } from '@pixiv/three-vrm'", "import { VRMUtils } from '@pixiv/three-vrm'\nimport { residentVrmDisplay, residentVrmGesture } from '../../cloud-vrm-gestures'"),
            (old, new),
            ("onUnmounted(() => {\n  componentCleanUp('component-unmount')", "onUnmounted(() => {\n  residentDisplay.restore()\n  residentMotion.restore()\n  componentCleanUp('component-unmount')"),
        ):
            if source.count(before) != 1:
                raise ValueError('cloud_resident_motion_hook_requires_review')
            source = source.replace(before, after, 1)
    return source


def cloud_live2d_lip_sync(source):
    old = "import { createWLipSyncNode } from 'wlipsync'"
    if source.count(old) != 1:
        raise ValueError('cloud_live2d_worklet_requires_review')
    return source.replace(old, "import { createResidentLipSync as createWLipSyncNode } from '../resident-lipsync'", 1)


def cloud_vrm_lip_sync(source):
    for old, new in (
        ("import { createWLipSyncNode } from 'wlipsync'", "import { createResidentLipSync as createWLipSyncNode, releaseResidentLipSync } from '../../../../model-driver-lipsync/src/resident-lipsync'"),
        ('Ref<AudioBufferSourceNode | undefined, AudioBufferSourceNode | undefined>', 'Ref<AudioNode | undefined, AudioNode | undefined>'),
        ('  const { audioContext } = useAudioContext()', '  const { audioContext } = useAudioContext()\n  let disposed = false'),
        ('useAsyncState(createWLipSyncNode(audioContext, profile as Profile), undefined)', 'useAsyncState(createWLipSyncNode(audioContext, profile as Profile).then(node => {\n    if (disposed) releaseResidentLipSync(node)\n    return node\n  }), undefined)'),
        ('        oldAudioNode.disconnect()', '        if (lipSyncNode.value) oldAudioNode.disconnect(lipSyncNode.value)'),
        ('  onUnmounted(() => audioNode.value?.disconnect())', "  onUnmounted(() => {\n    disposed = true\n    if (lipSyncNode.value) {\n      try {\n        audioNode.value?.disconnect(lipSyncNode.value)\n      } catch {}\n      releaseResidentLipSync(lipSyncNode.value)\n    }\n  })"),
        ('    if (!ready || !newAudioNode || !lipSyncNode.value)', '    if (disposed || !ready || !newAudioNode || !lipSyncNode.value)'),
        ('    const vol = node.volume ?? 0', '    const vol = audioNode.value ? (node.volume ?? 0) : 0'),
    ):
        if source.count(old) != 1:
            raise ValueError('cloud_vrm_worklet_requires_review')
        source = source.replace(old, new, 1)
    return source


def cloud_model_gestures(source):
    """Cloud build only: add a bounded head/shoulder gesture after native lip sync."""
    anchor = "import { Emotion, EmotionNeutralMotionName } from '../../../constants/emotions'"
    binding = "    motionManagerUpdate.register(useMotionUpdatePluginLipSync(mouthOpenSize, nowSpeaking), 'final')"
    if source.count(anchor) != 1 or source.count(binding) != 1:
        raise ValueError('cloud_model_gesture_anchor_requires_review')
    source = source.replace(anchor, "import { residentGesturePlugin } from '../../../cloud-gestures'\nimport { galleryFraming, installGalleryMouthAlias } from '../../../gallery-fit.js'\nimport { isLedResident } from '../../../resident-display.js'\n" + anchor, 1)
    frame = '  const normalized = modelNormalizeParams.value'
    if source.count(frame) != 1:
        raise ValueError('cloud_gallery_framing_anchor_requires_review')
    source = source.replace(frame, '  const normalized = galleryFraming(model.value, { width: props.width, height: props.height }, modelNormalizeParams.value, props.modelId)\n  const displayScale = isLedResident() ? 1 : scale.value\n  const displayOffset = isLedResident() ? { x: 0, y: 0 } : offset.value', 1)
    for before, after in (('normalized.scale * scale.value', 'normalized.scale * displayScale'),
                          ('normalized.x + offset.value.x', 'normalized.x + displayOffset.x'),
                          ('normalized.y + offset.value.y', 'normalized.y + displayOffset.y')):
        expected = 3 if before.endswith('scale.value') else 2
        if source.count(before) != expected:
            raise ValueError('cloud_led_live2d_transform_requires_review')
        source = source.replace(before, after)
    source = source.replace(binding, binding + "\n    motionManagerUpdate.register(residentGesturePlugin(), 'final')", 1)
    capture = "  try {\n    if (isUnmounted) {"
    setup = '    await Live2DFactory.setupLive2DModel(live2DModel, { url: modelSrcRef.value, id: props.modelId }, { autoInteract: false })'
    if source.count(capture) != 1 or source.count(setup) != 1:
        raise ValueError('cloud_model_generation_anchor_requires_review')
    source = source.replace(capture, "  const loadingModelId = props.modelId\n  const loadingModelSource = modelSrcRef.value\n" + capture, 1)
    source = source.replace(setup, (
        '    await Live2DFactory.setupLive2DModel(live2DModel, { url: loadingModelSource, id: loadingModelId }, { autoInteract: false })\n'
        '    if (isUnmounted || !pixiApp.value?.stage || loadingModelId !== props.modelId || loadingModelSource !== modelSrcRef.value) {\n'
        '      live2DModel.destroy()\n      return\n    }\n    installGalleryMouthAlias(live2DModel)'), 1)
    # These returns precede the try/finally that normally releases the mutex.
    for old in (
        "      componentState.value = 'mounted'\n      return\n    }\n  }\n\n  // REVIEW:",
        "    componentState.value = 'mounted'\n    return\n  }\n\n  const loadingModelId",
    ):
        if source.count(old) != 1:
            raise ValueError('cloud_model_early_release_anchor_requires_review')
        source = source.replace(old, old.replace('return', 'modelLoadMutex.release()\n' + ('      ' if old.startswith('      ') else '    ') + 'return', 1), 1)
    for old, new in (
        ("  componentState.value = 'loading'", "  componentState.value = 'loading'\n  window.dispatchEvent(new CustomEvent('resident-render-state', { detail: { state: 'pending', modelId: props.modelId } }))"),
        ("    emits('modelLoaded')", "    emits('modelLoaded')\n    window.dispatchEvent(new CustomEvent('resident-render-state', { detail: { state: 'ready', modelId: loadingModelId } }))"),
        ("    console.error('[Live2D] Failed to load model:', error)", "    if (loadingModelId === props.modelId && loadingModelSource === modelSrcRef.value)\n      window.dispatchEvent(new CustomEvent('resident-render-state', { detail: { state: 'failed', modelId: loadingModelId } }))\n    console.error('[Live2D] Failed to load model:', error)"),
    ):
        if source.count(old) != 1:
            raise ValueError('cloud_live2d_readiness_anchor_requires_review')
        source = source.replace(old, new, 1)
    return source


def cloud_input_recovery(source):
    """Cloud-only bounded VAD reinitialization; never replays recorded audio."""
    newline = '\r\n' if '\r\n' in source else '\n'
    normal = source.replace('\r\n', '\n')
    anchor = "import { VoiceTurn } from '../modules/voice-turn'"
    old = """watch(vadInferenceError, (error) => {
  if (error)
    console.error('Voice activity detection failed:', error)
})"""
    new = """const inputRecovery = new InputRecovery()
const inputRecovering = ref(false)
const inputStatus = ref('starting')
watch(enabled, value => {
  inputStatus.value = value ? 'starting' : 'paused'
}, { flush: 'sync' })
watch(inputStatus, state => {
  if (cloudResidentInput)
    window.dispatchEvent(new CustomEvent('resident-input-state', { detail: state }))
}, { immediate: true })
let inputFrameAt = 0
watch(vadFrames, () => {
  if (enabled.value && stream.value?.getAudioTracks().some(track => track.readyState === 'live')) {
    inputFrameAt = Date.now()
    inputStatus.value = 'ready'
  }
})
function resumeMicrophone() {
  if (!enabled.value) {
    enabled.value = true
    return
  }
  // This synchronous call preserves the resident's click activation when a
  // browser suspends the input AudioContext. It opens no second microphone.
  if (inputStatus.value !== 'ready') {
    if (vadInferenceError.value) {
      disposeVAD()
      void initVAD()
      return
    }
    void resumeVAD()
    if (!stream.value || !stream.value.getAudioTracks().some(track => track.readyState === 'live')) {
      settingsAudioDeviceStore.stopStream()
      void settingsAudioDeviceStore.startStream().catch(() => {
        enabled.value = false
      })
    }
    return
  }
  enabled.value = false
}
const inputWatchdog = setInterval(() => {
  if (!enabled.value) {
    inputStatus.value = 'paused'
    return
  }
  if (vadInferenceError.value) {
    inputStatus.value = 'failed'
    return
  }
  if (!vadLoaded.value || !stream.value) {
    inputStatus.value = 'starting'
    return
  }
  const alive = stream.value.getAudioTracks().some(track => track.readyState === 'live' && track.enabled && !track.muted)
  if (!alive) {
    inputStatus.value = 'waiting'
    return
  }
  if (Date.now() - inputFrameAt > 5000) {
    inputStatus.value = 'waiting'
    if (inputFrameAt && !document.hidden) void inputRecovery.run('resume', async () => {
      await Promise.race([resumeVAD(), new Promise((_, reject) => setTimeout(() => reject(new Error('input_resume_timeout')), 2000))])
    })
  }
}, 1000)
watch(vadInferenceError, (error) => {
  if (error)
    console.error('Voice activity detection failed:', error)
  if (!error || !cloudResidentInput || !enabled.value)
    return
  inputRecovering.value = true
  void inputRecovery.run('vad', async () => {
    if (!enabled.value)
      return
    disposeVAD()
    await initVAD()
    if (!enabled.value) {
      disposeVAD()
      return
    }
    if (vadInferenceError.value)
      throw new Error('vad_recovery_incomplete')
  }).finally(() => { inputRecovering.value = false })
})
onUnmounted(() => {
  inputRecovery.close()
  clearInterval(inputWatchdog)
})"""
    if normal.count(anchor) != 1 or normal.count(old) != 1:
        raise ValueError('cloud_input_recovery_anchor_requires_review')
    normal = normal.replace(anchor, "import { InputRecovery } from '../modules/resident-recovery.js'\n" + anchor, 1)
    normal = normal.replace(old, new, 1)
    capture = 'inferenceError: vadInferenceError } = useVAD'
    if normal.count(capture) != 1:
        raise ValueError('cloud_input_progress_anchor_requires_review')
    normal = normal.replace(capture, 'inferenceError: vadInferenceError, processedFrames: vadFrames, resume: resumeVAD } = useVAD')
    binding = ':voice-unavailable="!!vadInferenceError || !!hearingPipeline.error"'
    if normal.count(binding) != 1:
        raise ValueError('cloud_input_recovery_binding_requires_review')
    normal = normal.replace(binding, ':voice-unavailable="!!vadInferenceError" :voice-recovering="inputRecovering" :input-status="residentSpeaking ? \'speaking\' : inputStatus"')
    normal = normal.replace('@microphone="enabled = !enabled"', '@microphone="resumeMicrophone"')
    return normal.replace('\n', newline)


def cloud_vad_runtime(source):
    """Add an explicit user-gesture resume without changing native source."""
    newline = '\r\n' if '\r\n' in source else '\n'
    normal = source.replace('\r\n', '\n')
    anchor = '  function stop() {\n'
    if normal.count(anchor) != 1:
        raise ValueError('cloud_vad_resume_anchor_requires_review')
    normal = normal.replace(anchor, "  function resume() {\n    return audioContext?.state !== 'closed' ? audioContext.resume() : Promise.resolve()\n  }\n\n" + anchor)
    normal = normal.replace('    initialize,\n    start,', '    initialize,\n    resume,\n    start,')
    return normal.replace('\n', newline)


def cloud_vad_store(source):
    """Expose actual processed input frames, not merely an enabled switch."""
    newline = '\r\n' if '\r\n' in source else '\n'
    normal = source.replace('\r\n', '\n')
    anchor = '  const isSpeechProb = ref(0)'
    if normal.count(anchor) != 1:
        raise ValueError('cloud_vad_progress_anchor_requires_review')
    normal = normal.replace(anchor, anchor + '\n  const processedFrames = ref(0)')
    normal = normal.replace('          isSpeechProb.value = data.probability', '          processedFrames.value++\n          isSpeechProb.value = data.probability')
    normal = normal.replace('    isSpeechProb,\n', '    isSpeechProb,\n    processedFrames,\n')
    normal = normal.replace('    init,\n    start,', '    init,\n    resume: () => manager.value?.resume() ?? Promise.resolve(),\n    start,')
    return normal.replace('\n', newline)


def cloud_audio_device(source):
    """Each cloud frame owns its mic switch; staff/teardown cannot mute peers."""
    old = "const audioInputEnabled = useLocalStorageManualReset<boolean>('settings/audio/input/enabled', false)"
    new = "const audioInputEnabled = refManualReset<boolean>(new URLSearchParams(location.search).get('settings') !== '1' && Reflect.get(globalThis, '__NEIGHBOUR_PRESENTATION__')?.airi?.runtime?.hearing?.microphone_enabled !== false)"
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError('cloud_input_local_state_anchor_requires_review')
    source = source.replace(old, new)
    if "import { defineStore } from 'pinia'" in source:
        source = source.replace("import { defineStore } from 'pinia'",
                                "import { refManualReset } from '@vueuse/core'\nimport { defineStore } from 'pinia'")
    return source


def cloud_audio_default(source):
    """Keep an already captured default mic when device enumeration completes.

    Explicit device changes still use native autoSwitch. Ended/unplugged inputs
    still fall through to native selection and recovery.
    """
    old = '  watch(audioInputs, () => {\n    selectAvailableAudioInput()\n  })'
    new = ('  watch(audioInputs, () => {\n'
           "    if (!selectedAudioInput.value && stream.value?.getAudioTracks().some(track => track.readyState === 'live'))\n"
           '      return\n'
           '    selectAvailableAudioInput()\n  })')
    newline = '\r\n' if '\r\n' in source else '\n'
    normal = source.replace('\r\n', '\n')
    if new in normal:
        return source
    if normal.count(old) != 1:
        raise ValueError('cloud_default_microphone_anchor_requires_review')
    return normal.replace(old, new, 1).replace('\n', newline)


def cloud_web_search_tool(source):
    old = "const response = await fetch(managed ? 'http://127.0.0.1:8000/api/v1/resident/search' : TAVILY_SEARCH_URL, {"
    new = """const cloud = managed && Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') === true
  const request = cloud ? Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__').fetch : fetch
  const response = await request(managed ? (cloud ? '/api/v1/resident/search' : 'http://127.0.0.1:8000/api/v1/resident/search') : TAVILY_SEARCH_URL, {"""
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError('cloud_search_transport_anchor_requires_review')
    return source.replace(old, new)


def cloud_web_search_editor(source):
    old = "const webSearchStore = useWebSearchStore()"
    new = old + "\nconst cloud = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') === true"
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError('cloud_search_editor_anchor_requires_review')
    return source.replace(old, new).replace('<p v-if="managed">', '<p v-if="managed || cloud">').replace(
        '已連接本機 Tavily 金鑰，與居民服務台共用搜尋及快取；毋須重複輸入。',
        "{{ cloud ? (managed ? 'Tavily 已由平台接通，與居民服務台共用搜尋及快取；毋須輸入金鑰。' : '平台暫時未能確認 Tavily 設定；原有資料保留。') : '已連接本機 Tavily 金鑰，與居民服務台共用搜尋及快取；毋須重複輸入。' }}")


def cloud_display_models(source):
    """Resolve immutable shared IDs before native missing-file fallback."""
    old = '  async function getDisplayModel(id: string) {\n    await until(displayModelsFromIndexedDBLoading).toBe(false)'
    new = old + """
    if (Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') === true && /^cloud-(?:live2d|vrm|rigby)-[a-f0-9]{64}$/.test(id)) {
      try {
        const loader = Reflect.get(globalThis, '__NEIGHBOUR_LOAD_SHARED_MODEL__')
        if (typeof loader !== 'function')
          throw new Error('cloud_model_loader_required')
        const model = await loader(id)
        displayModels.value = [...displayModels.value.filter(item => item.id !== id), model]
        return model
      }
      catch {
        window.dispatchEvent(new Event('estate:shared-model-unavailable'))
        return displayModelsPresets.find(model => model.id === 'preset-live2d-2')
      }
    }"""
    normal = source.replace('\r\n', '\n')
    format_anchor = "  SpineZip = 'spine-zip',"
    if normal.count(format_anchor) != 1:
        raise ValueError('free_skeletal_display_format_requires_review')
    normal = normal.replace(format_anchor, "  RigbyJsonZip = 'rigby-json-zip',\n" + format_anchor, 1)
    for licensed_line in (
        '  let generateSpinePreview: (file: File) => Promise<string | undefined>\n',
        "    const { loadSpineModelPreview } = await import('@proj-airi/stage-ui-spine/utils/spine-preview')\n",
        '    generateSpinePreview = loadSpineModelPreview\n',
    ):
        normal = _free_replace(normal, licensed_line, '')
    normal = _free_replace(normal, '  const loadSpineModelPreview = (file: File) => generateSpinePreview(file)',
        "  const loadSpineModelPreview = (_file: File): Promise<string | undefined> => Promise.reject(new Error('此平台免費方案不啟用官方 Spine Runtime，請使用 Rigby JSON、Live2D 或 VRM。'))")
    if normal.count(old) != 1:
        raise ValueError('cloud_display_model_anchor_requires_review')
    normal = normal.replace(old, new)
    import_anchor = "import localforage from 'localforage'"
    add_anchor = "    const newDisplayModel: DisplayModelFile = { id: `display-model-${nanoid()}`, format, type: 'file', file, name: file.name, importedAt: Date.now() }"
    insert_anchor = '    displayModels.value.unshift(newDisplayModel)'
    if any(normal.count(anchor) != 1 for anchor in (import_anchor, add_anchor, insert_anchor)):
        raise ValueError('cloud_model_import_dedup_anchor_requires_review')
    normal = normal.replace(import_anchor, import_anchor + "\nimport { fileDigest, findSameModel } from './model-dedup.js'")
    normal = normal.replace(add_anchor, """    const cloud = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') === true
    let contentId: string | undefined
    if (cloud) {
      const digest = await fileDigest(file)
      const existing = await findSameModel(displayModels.value, format, file, digest)
      if (existing)
        return existing
      contentId = `display-model-sha256-${format}-${digest}`
    }
    const newDisplayModel: DisplayModelFile = { id: contentId || `display-model-${nanoid()}`, format, type: 'file', file, name: file.name, importedAt: Date.now() }""")
    preview_anchor = '    if (format === DisplayModelFormat.Live2dZip) {'
    if normal.count(preview_anchor) != 1:
        raise ValueError('free_skeletal_display_preview_requires_review')
    normal = normal.replace(preview_anchor,
        "    if (format === DisplayModelFormat.RigbyJsonZip) {\n"
        "      const { freeSkeletalPreview } = await import('../libs/free-skeletal-zip')\n"
        "      newDisplayModel.previewImage = await freeSkeletalPreview(file)\n"
        "    }\n    else if (format === DisplayModelFormat.Live2dZip) {", 1)
    return normal.replace(insert_anchor, "    if (cloud)\n      displayModels.value = displayModels.value.filter(item => item.id !== newDisplayModel.id)\n" + insert_anchor)


def cloud_model_selector(source):
    """Use the cloud catalogue INSIDE the native accessible model dialog."""
    if source.count("import { onMounted } from 'vue'") != 1 or source.count('<ModelManager ') != 2:
        raise ValueError('native_model_selector_anchor_requires_review')
    source = source.replace("import { onMounted } from 'vue'", "import { inject, onMounted } from 'vue'", 1)
    source = source.replace('const props = defineProps<',
        "const ModelManagerComponent = inject('neighbour-model-selector', ModelManager)\n\nconst props = defineProps<", 1)
    source = source.replace('v-if="isDesktop"', 'v-if="isDesktop || ModelManagerComponent !== ModelManager"', 1)
    return source.replace('<ModelManager ', '<component :is="ModelManagerComponent" ')


def cloud_model_panel(source):
    """Keep the selected preview clean without removing native adjustments."""
    begin = '    <Callout :label="t(\'settings.model-select.panel-callout.support-status-header\')">'
    if source.count(begin) != 1 or source.count('    </Callout>') != 1:
        raise ValueError('native_model_panel_anchor_requires_review')
    before, tail = source.split(begin, 1)
    source = before + ('    <p class="cloud-current-model">目前模型：{{ stageModelSelectedDisplayModel?.name ?? "正在準備" }}</p>') + tail.split('    </Callout>', 1)[1]
    source = source.replace('{ Button, Callout }', '{ Button }', 1)
    source = source.replace("{{ t('settings.model-select.select-model.button') }}", '選擇模型', 1)
    source = source.replace("import { useI18n } from 'vue-i18n'\n", '').replace("const { t } = useI18n()\n", '')
    if source.count('    <Live2D\n') != 1 or source.count('    />\n  </div>') != 1:
        raise ValueError('native_model_adjustments_anchor_requires_review')
    source = source.replace('    <Live2D\n', '    <details class="cloud-model-options" open><summary>調整模型外觀與動作</summary>\n    <Live2D\n', 1)
    source = source.replace('    />\n  </div>', '    />\n    </details>\n  </div>', 1)
    source = source.replace("import Spine from './spine.vue'\n", '')
    begin = source.index('    <Spine\n')
    end = source.index('    />', begin) + len('    />')
    return source[:begin] + ('    <p v-if="effectiveRenderer === \'rigby\'" class="cloud-current-model">'
        '免費骨架（Rigby JSON）：按模型原有動作播放，支援嘴形與揮手；不使用官方 Spine Runtime。'
        '</p>') + source[end:]


def _free_replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('free_skeletal_frontend_anchor_requires_review: ' + old[:65])
    return source.replace(old, new, 1)


def cloud_free_stage_model(source):
    """Distinct renderer identifier; never route Rigby through paid Spine code."""
    normal = source.replace('\r\n', '\n')
    normal = _free_replace(normal, "'live2d' | 'vrm' | 'spine' | 'godot'",
                           "'live2d' | 'vrm' | 'rigby' | 'spine' | 'godot'")
    return _free_replace(normal, "      case DisplayModelFormat.SpineZip:\n        return 'spine'",
                         "      case DisplayModelFormat.RigbyJsonZip:\n        return 'rigby'\n"
                         "      case DisplayModelFormat.SpineZip:\n        return 'disabled'")


def cloud_free_model_selector_labels(source):
    return _free_replace(source, "  [DisplayModelFormat.SpineZip]: 'Spine',",
                         "  [DisplayModelFormat.RigbyJsonZip]: 'Rigby JSON',\n"
                         "  [DisplayModelFormat.SpineZip]: 'Spine',")


def cloud_free_skeletal_scene(source):
    normal = source.replace('\r\n', '\n')
    normal = _free_replace(normal, "import { SpineScene } from '@proj-airi/stage-ui-spine'",
                           "import FreeSkeletalScene from '../../libs/free-skeletal-scene.vue'")
    normal = normal.replace('spineSceneRef', 'freeSkeletalSceneRef').replace('typeof SpineScene', 'typeof FreeSkeletalScene')
    state_anchor = 'const { mouthOpenSize, nowSpeaking } = storeToRefs(useSpeakingStore())'
    normal = _free_replace(normal, state_anchor, state_anchor + "\nfunction onFreeSkeletalError() {\n"
        "  window.dispatchEvent(new CustomEvent('resident-render-state', { detail: { state: 'failed', modelId: stageModelSelected.value } }))\n}")
    normal = normal.replace("stageModelRenderer.value === 'spine'", "stageModelRenderer.value === 'rigby'")
    settings = ("const {\n  spinePremultipliedAlpha,\n  spineDefaultMixDuration,\n  spineIdleAnimationEnabled,\n"
                "  spineMaxFps,\n  spineRenderScale,\n} = storeToRefs(settingsStore)\n")
    normal = _free_replace(normal, settings, '')
    start = normal.index('      <SpineScene\n')
    end = normal.index('      />', start) + len('      />')
    replacement = """      <FreeSkeletalScene
        v-if="stageModelRenderer === 'rigby' && showStage"
        ref="freeSkeletalSceneRef"
        v-model:state="componentState"
        min-w="50% <lg:full" min-h="100 sm:100"
        h-full w-full flex-1
        :model-src="stageModelSelectedUrl"
        :model-id="stageModelSelected"
        :paused="paused"
        :mouth-open="mouthOpenSize"
        :audio-source="currentAudioSource"
        :now-speaking="nowSpeaking"
        @error="onFreeSkeletalError"
      />"""
    return normal[:start] + replacement + normal[end:]


def cloud_free_model_runtime(source):
    return _free_replace(source, "'disabled' | 'live2d' | 'vrm' | 'spine' | 'godot'",
                         "'disabled' | 'live2d' | 'vrm' | 'rigby' | 'spine' | 'godot'")


def cloud_free_model_preview(source):
    normal = source.replace('\r\n', '\n')
    normal = _free_replace(normal, "import { SpineScene } from '@proj-airi/stage-ui-spine'",
                           "import FreeSkeletalScene from '../../../../libs/free-skeletal-scene.vue'")
    normal = normal.replace('spineSceneRef', 'freeSkeletalSceneRef')
    normal = normal.replace("stageModelRenderer.value === 'spine'", "stageModelRenderer.value === 'rigby'")
    normal = normal.replace("renderer: 'spine'", "renderer: 'rigby'")
    normal = normal.replace('normalizeClassList(props.spineSceneClass)', 'normalizeClassList(props.spineSceneClass || props.live2dSceneClass)')
    settings = ("const {\n  spinePremultipliedAlpha,\n  spineDefaultMixDuration,\n  spineIdleAnimationEnabled,\n"
                "  spineMaxFps,\n  spineRenderScale,\n} = storeToRefs(settingsStore)\n")
    normal = _free_replace(normal, settings, '')
    start = normal.index('  <template v-if="stageModelRenderer === \'spine\'">')
    end = normal.index('  </template>', start) + len('  </template>')
    replacement = """  <template v-if="stageModelRenderer === 'rigby'">
    <div :class="spineSceneClassList">
      <FreeSkeletalScene
        ref="freeSkeletalSceneRef"
        v-model:state="spineComponentState"
        :model-src="stageModelSelectedUrl"
        :model-id="stageModelSelected"
      />
    </div>
  </template>"""
    return normal[:start] + replacement + normal[end:]
