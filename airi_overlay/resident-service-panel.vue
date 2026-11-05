<script setup lang="ts">
import type { ChatProvider } from '@xsai-ext/providers/utils'

import { useAudioContext, useSpeakingStore } from '@proj-airi/stage-ui/stores/audio'
import { useLLM } from '@proj-airi/stage-ui/stores/llm'
import { useAiriCardStore, useConsciousnessStore, useSpeechStore } from '@proj-airi/stage-ui/stores/modules'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { useSpeechOutputControlStore } from '@proj-airi/stage-ui/stores/speech-output-control'
import { useSpeechRuntimeStore } from '@proj-airi/stage-ui/stores/speech-runtime'
import { storeToRefs } from 'pinia'
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { createResidentApi } from './resident-api.js'
import { ResidentGaze } from './resident-gaze.js'
import { residentGesture, residentSpeechGesture, shouldResidentWelcome } from './resident-gestures.js'
import { ResidentIdle } from './resident-idle.js'
import { ResidentPcm, ResidentTiming } from './resident-pcm.js'
import { createResidentTextFilter, readResidentReply, residentMessageParts, residentPlainText, residentSpeechText } from './resident-response.js'
import { ResidentSession } from './resident-session.js'

defineProps<{ listening: boolean, voiceUnavailable?: boolean, voiceRecovering?: boolean, inputStatus?: string }>()
const emit = defineEmits<{ microphone: [], endSession: [], speaking: [boolean] }>()
const cloudResident = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') === true
const presentation = Reflect.get(globalThis, '__NEIGHBOUR_PRESENTATION__') || {}
const creditInHeader = ref(false)
const runtimePreferences = cloudResident ? presentation.airi?.runtime : undefined
const hubOrigin = cloudResident || Reflect.get(globalThis, '__NEIGHBOUR_REMOTE__') === true ? location.origin : 'http://127.0.0.1:8000'
const residentApi = createResidentApi({
  cloud: cloudResident,
  transport: () => {
    const selected = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
    return selected && typeof selected.fetch === 'function' ? selected : undefined
  },
})
const draft = ref('')
const messages = ref<{ role: string, content: string }[]>([])
const busy = ref(false)
const status = ref('可以直接講，或者打字同我傾。')
const followupNotice = ref('')
const gazeState = ref('off')
const casePhotoTarget = ref<{ id: string, number: number }>()
const photoPreview = ref('')
const photoStatus = ref('')
const photoBusy = ref(false)
const photoDialog = ref<HTMLDialogElement>()
let previewCaseId = ''
let photoStartedCamera = false
let gaze: ResidentGaze | undefined
let avatarVisible = window.parent === window
let avatarMounted = Reflect.get(globalThis, '__NEIGHBOUR_AVATAR_READY__') === true
let entranceGreeted = false
let lastWelcome = performance.now()
let welcomeTimer: ReturnType<typeof setInterval> | undefined
function toggleGaze() {
  if (['off', 'unavailable'].includes(gazeState.value))
    void gaze?.start()
  else
    gaze?.stop()
}
function startHandControl() {
  void gaze?.start(true)
}
const transcript = ref<HTMLElement>()
const speechRuntime = useSpeechRuntimeStore()
const consciousness = useConsciousnessStore()
const providers = useProvidersStore()
const airiCard = useAiriCardStore()
const llm = useLLM()
const speechSettings = useSpeechStore()
const speechOutput = useSpeechOutputControlStore()
const { nowSpeaking } = storeToRefs(useSpeakingStore())
const { audioContext: residentAudioContext } = useAudioContext()
const speechActive = ref(false)
let activeCare = false
watch(nowSpeaking, active => residentSpeechGesture(active, activeCare), { flush: 'sync' })
watch(speechActive, (active) => {
  if (active)
    residentGesture(activeCare ? 'care' : 'speaking')
})
const inputControllers = new Set<AbortController>()
let speechIntent: ReturnType<typeof speechRuntime.openIntent> | undefined
let speechStartTimer: ReturnType<typeof setTimeout> | undefined
let speechHealthTimer: ReturnType<typeof setTimeout> | undefined
let speechDidStart = false
let speechFailed = false
let pcmPlayer: ResidentPcm | undefined
let turnTiming: ResidentTiming | undefined
const inactivity = new ResidentIdle(reset, { timeoutMs: (runtimePreferences?.memory?.idle_seconds ?? 180) * 1000 })
const session = new ResidentSession(async (body: unknown, signal: AbortSignal, onDelta: (text: string) => void) => {
  const deadline = AbortSignal.any([signal, AbortSignal.timeout(150000)])
  const selected = { provider: consciousness.activeProvider, model: consciousness.activeModel || consciousness.customModelName }
  const residentBody = body as { session_id?: string, submission_id?: string, messages: { role: string, content: string }[] }
  const history = residentBody.messages.map(message => message.role === 'assistant' ? { ...message, content: residentPlainText(message.content) } : message).filter(message => message.content.trim())
  const response = await residentApi.chat({ ...(body as object), messages: history, airi_system_prompt: Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') === true ? '' : String(airiCard.systemPrompt || '').slice(0, 4000) }, deadline)
  if (response.ok && response.headers?.get('content-type')?.includes('application/json')) {
    const plan = await response.clone().json()
    if (!deadline.aborted && plan.followup?.delivered === true && /^[a-f0-9]{32}$/.test(plan.followup.id)
      && Number.isSafeInteger(plan.followup.case_number)) {
      if (casePhotoTarget.value?.id !== plan.followup.id)
        cancelPhoto()
      casePhotoTarget.value = { id: plan.followup.id, number: plan.followup.case_number }
    }
    if (!deadline.aborted && typeof plan.followup?.notice === 'string')
      followupNotice.value = plan.followup.notice.slice(0, 350)
    if (plan.object === 'resident.plan') {
      if (residentApi.cloud) {
        const completion = await residentApi.completePlan(plan, {
          sessionId: residentBody.session_id || '',
          turnId: residentBody.submission_id || '',
        }, deadline)
        return readResidentReply(completion, onDelta, deadline)
      }
      if (!selected.provider || !selected.model)
        throw new Error('請先在 AIRI 選擇對話供應商及模型。')
      const provider = await providers.getProviderInstance<ChatProvider>(selected.provider)
      let answer = ''
      let pending = ''
      let received = 0
      const textFilter = createResidentTextFilter()
      await llm.stream(selected.model, provider, [{ role: 'system', content: `${plan.system_prompt}\n居民畫面只輸出自然、可直接朗讀的對話文字，不輸出 ACT、DELAY 或其他角色控制標記。` }, ...plan.messages], {
        headers: String(providers.getProviderConfig(selected.provider)?.baseUrl).replace(/\/+$/, '') === 'http://127.0.0.1:8000/api/v1/resident/model/v1'
          ? { 'X-Resident-Session': residentBody.session_id || '', 'X-Resident-Turn': residentBody.submission_id || '' }
          : undefined,
        supportsTools: false,
        abortSignal: deadline,
        onStreamEvent(event) {
          if (event.type !== 'text-delta' || !event.text || deadline.aborted)
            return
          received += event.text.length
          if (received > 4000)
            throw new Error('resident_reply_too_long')
          const clean = textFilter.push(event.text)
          answer += clean
          pending += clean
          let match: RegExpMatchArray | null
          while ((match = pending.match(/^[\s\S]*?[。！？!?\n]/))) {
            onDelta(match[0])
            pending = pending.slice(match[0].length)
          }
        },
      })
      if (deadline.aborted)
        throw new Error('resident_cancelled')
      const tail = textFilter.finish()
      answer += tail
      pending += tail
      if (!answer.trim())
        throw new Error('resident_reply_invalid')
      if (pending)
        onDelta(pending)
      return answer.trim()
    }
  }
  return readResidentReply(response, onDelta, deadline)
}, { maxMessages: runtimePreferences?.memory?.context_messages ?? 60, maxCharacters: runtimePreferences?.memory?.context_characters ?? 16000 })
function cancelPhoto() {
  photoPreview.value = ''
  previewCaseId = ''
  photoDialog.value?.close()
  if (photoStartedCamera)
    gaze?.stop()
  photoStartedCamera = false
}
async function prepareCasePhoto() {
  const target = casePhotoTarget.value
  if (!target || photoBusy.value)
    return
  const generation = session.generation
  photoBusy.value = true
  try {
    if (['off', 'unavailable'].includes(gazeState.value)) {
      photoStartedCamera = true
      await gaze?.start()
    }
    if (generation !== session.generation || target.id !== casePhotoTarget.value?.id) {
      cancelPhoto()
      return
    }
    photoPreview.value = gaze?.capturePreview() || ''
    previewCaseId = target.id
    await nextTick()
    photoDialog.value?.showModal()
  }
  catch { photoStatus.value = '鏡頭未準備好；可以稍後再試，文字個案已保留。' }
  finally { photoBusy.value = false }
}
async function confirmCasePhoto() {
  if (photoBusy.value || !photoPreview.value || casePhotoTarget.value?.id !== previewCaseId)
    return
  const generation = session.generation
  const controller = new AbortController()
  inputControllers.add(controller)
  photoBusy.value = true
  try {
    const reply = await residentApi.uploadCasePhoto({ session_id: session.sessionId, case_id: previewCaseId, jpeg: photoPreview.value.split(',')[1], consent: true, purpose: 'case-followup-v1' }, AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]))
    if (!reply.ok || (await reply.json()).stored !== true)
      throw new Error('case_photo_not_confirmed')
    if (generation === session.generation) {
      photoStatus.value = '相片已附上個案，只供職員跟進；個案完成後 90 日清除。'
      cancelPhoto()
    }
  }
  catch {
    if (generation === session.generation)
      photoStatus.value = '暫時未能確認相片已儲存；可再確認一次，文字個案仍保留。'
  }
  finally {
    inputControllers.delete(controller)
    photoBusy.value = false
  }
}
function clearAudio() {
  if (pcmPlayer)
    nowSpeaking.value = false
  pcmPlayer?.cancel()
  pcmPlayer = undefined
  clearTimeout(speechStartTimer)
  clearTimeout(speechHealthTimer)
  speechIntent?.cancel('resident-session-ended')
  if (speechIntent)
    speechOutput.requestStopSpeaking('manual-chat')
  speechIntent = undefined
  speechActive.value = false
  speechDidStart = false
  emit('speaking', false)
}
watch(nowSpeaking, (value) => {
  if (!speechIntent)
    return
  if (value) {
    speechDidStart = true
    turnTiming?.mark('first_audio_scheduled')
    void turnTiming?.report()
    clearTimeout(speechStartTimer)
    clearTimeout(speechHealthTimer)
    speechActive.value = true
    status.value = '正在朗讀…'
    emit('speaking', true)
  }
  else if (speechDidStart) {
    turnTiming?.mark('audio_complete')
    void turnTiming?.report()
    speechActive.value = false
    status.value = '我喺度，你慢慢講。'
    emit('speaking', false)
  }
})
watch(() => speechOutput.latestStopRequest, (value) => {
  if (!value || !pcmPlayer)
    return
  pcmPlayer.cancel()
  nowSpeaking.value = false
  speechActive.value = false
  emit('speaking', false)
  status.value = '已停止朗讀，文字保留。'
})
function cancelWaiting() {
  const current = draft.value.trim() ? draft.value : [...messages.value].reverse().find(message => message.role === 'user')?.content || ''
  turnTiming?.mark('cancelled')
  void turnTiming?.report()
  session.cancelPending()
  clearAudio()
  draft.value = current
  messages.value = [...session.history]
  busy.value = false
  status.value = '已停止等候，內容已保留；已送達的個案仍會由職員跟進。'
}
function reset() {
  cancelPhoto()
  casePhotoTarget.value = undefined
  photoStatus.value = ''
  if (!gaze?.hands)
    gaze?.stop()
  activeCare = false
  residentGesture('greeting')
  lastWelcome = performance.now()
  followupNotice.value = ''
  inactivity.stop()
  session.reset()
  cancelTranscription()
  messages.value = []
  draft.value = ''
  busy.value = false
  clearAudio()
  speechFailed = false
  status.value = '已結束今次服務。你好，下一位有咩需要？'
  emit('endSession')
  if (residentApi.cloud)
    window.dispatchEvent(new Event('estate:resident-session-ended'))
}
function touch() {
  inactivity.touch()
}
function beginSpeech() {
  if (residentApi.cloud)
    return
  clearAudio()
  speechFailed = false
  if (!speechRuntime.isHost()) {
    status.value = '語音暫時未準備好；你仍可閱讀文字，稍後再按朗讀。'
    return
  }
  const intent = speechRuntime.openIntent({ ownerId: 'estate-resident', behavior: 'queue' })
  speechIntent = intent
  speechActive.value = true
  emit('speaking', true)
  status.value = '正在準備朗讀…'
  const started = Date.now()
  async function checkSpeechStatus() {
    if (speechIntent !== intent || speechDidStart)
      return
    try {
      const response = await fetch('http://127.0.0.1:8765/health', {
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        signal: AbortSignal.timeout(2500),
      })
      if (response.ok) {
        const health = await response.json()
        const failure = health.tts_cloud_last_error
        if (speechIntent === intent && !speechDidStart && failure?.at_ms >= started) {
          clearAudio()
          speechFailed = true
          status.value = failure.reason === 'rate_limited'
            ? 'Google 語音暫時受額度限制，文字已保留；稍後可以再試朗讀。'
            : 'Google 語音暫時未能合成，文字已保留；稍後可以再試朗讀。'
          return
        }
      }
    }
    catch { /* Keep the bounded playback timer if local status is unavailable. */ }
    if (speechIntent === intent && !speechDidStart)
      speechHealthTimer = setTimeout(checkSpeechStatus, 1000)
  }
  const speechConfig = providers.getProviderConfig(speechSettings.activeSpeechProvider)
  if (speechSettings.activeSpeechProvider === 'openai-compatible-audio-speech'
    && /^http:\/\/(?:127\.0\.0\.1|localhost):8765\//.test(String(speechConfig?.baseUrl || ''))
    && ['resident-yue', 'HKSoft'].includes(speechSettings.activeSpeechVoiceId)) {
    speechHealthTimer = setTimeout(checkSpeechStatus, 1000)
  }
  speechStartTimer = setTimeout(() => {
    if (speechIntent === intent && !speechDidStart) {
      clearAudio()
      status.value = '語音暫時未能播放；文字已保留，可以繼續傾談。'
    }
  }, 20000)
  return intent
}
async function sendMessage(text = draft.value, voice = true, inputEndedAt?: number) {
  inactivity.check()
  text = text.trim()
  if (!text || busy.value)
    return
  touch()
  cancelTranscription()
  clearAudio()
  speechFailed = false
  const epoch = session.generation
  activeCare = /壓力|唔開心|難受|擔心|跳樓|自殺|想死|生活困難|好攰|驚/.test(text)
  residentGesture(activeCare ? 'care' : 'listen')
  busy.value = true
  messages.value = [...session.history, { role: 'user', content: text }]
  status.value = '我聽緊，等我整理一下…'
  turnTiming = new ResidentTiming(undefined, inputEndedAt, residentApi.timing)
  if (inputEndedAt !== undefined) {
    turnTiming.mark('asr_ready')
    void turnTiming.report()
  }
  const timing = turnTiming
  let partial = ''
  const pendingStatus = setTimeout(() => {
    if (epoch === session.generation && !partial && !speechActive.value)
      status.value = '我仲喺度整理，你講嘅內容會保留。'
  }, 4000)
  let intent: ReturnType<typeof speechRuntime.openIntent> | undefined
  try {
    const answer = await session.send(text, 'voice', (delta: string) => {
      if (!partial)
        residentGesture(activeCare ? 'care' : 'speaking')
      timing.mark('first_text')
      void timing.report()
      partial += delta
      messages.value = [...session.history, { role: 'user', content: text }, { role: 'assistant', content: partial }]
      if (voice) {
        const cfg = providers.getProviderConfig(speechSettings.activeSpeechProvider)
        const nativePcm = speechSettings.activeSpeechProvider === 'openai-compatible-audio-speech'
          && /^http:\/\/(?:127\.0\.0\.1|localhost):8765\//.test(String(cfg?.baseUrl || ''))
          && speechSettings.activeSpeechVoiceId === 'zh-HK-HiuMaanNeural'
        const pcm = residentApi.cloud || (speechRuntime.isHost() && nativePcm)
        if (pcm) {
          if (!pcmPlayer) {
            clearAudio()
            speechActive.value = true
            emit('speaking', true)
            status.value = '正在準備朗讀…'
            const player = new ResidentPcm({
              ...residentApi.pcm,
              context: residentAudioContext,
              started: () => {
                if (pcmPlayer === player) {
                  nowSpeaking.value = true
                  timing.mark('first_audio_scheduled')
                  void timing.report()
                  status.value = '正在朗讀…'
                }
              },
              failed: () => {
                if (pcmPlayer === player) {
                  nowSpeaking.value = false
                  speechActive.value = false
                  speechFailed = true
                  emit('speaking', false)
                  status.value = '語音暫時未能完成朗讀，文字已保留。'
                }
              },
              ended: () => {
                timing.mark('audio_complete')
                void timing.report()
                if (pcmPlayer === player) {
                  nowSpeaking.value = false
                  speechActive.value = false
                  emit('speaking', false)
                  status.value = '我喺度，你慢慢講。'
                }
              },
            })
            pcmPlayer = player
          }
          pcmPlayer.write(residentSpeechText(delta))
        }
        else if (!residentApi.cloud) {
          if (!intent)
            intent = beginSpeech()
          intent?.writeLiteral(residentSpeechText(delta))
        }
        else {
          speechFailed = true
          status.value = '語音暫時未準備好；文字已保留。'
        }
      }
      void nextTick(() => transcript.value?.scrollTo({ top: transcript.value.scrollHeight }))
    })
    if (epoch !== session.generation || answer === null)
      return
    messages.value = [...session.history]
    intent?.end()
    pcmPlayer?.end()
    timing.mark('response_complete')
    void timing.report()
    draft.value = ''
    if (!speechActive.value && !speechFailed)
      status.value = '我喺度，你慢慢講。'
    await nextTick()
    transcript.value?.scrollTo({ top: transcript.value.scrollHeight, behavior: 'smooth' })
  }
  catch {
    if (epoch !== session.generation)
      return
    timing.mark('failed')
    void timing.report()
    clearAudio()
    draft.value = text
    messages.value = [...session.history]
    status.value = '剛才未能完成回覆，內容仍保留，可以再傳送一次。'
  }
  finally {
    clearTimeout(pendingStatus)
    if (epoch === session.generation)
      busy.value = false
  }
}
function cancelTranscription() {
  for (const controller of inputControllers)
    controller.abort()
  inputControllers.clear()
}
async function transcribeAudio(audio: Blob) {
  if (!residentApi.cloud)
    throw new Error('cloud_transcription_only')
  // Input may warm locally behind the launch screen. Do not send background
  // speech or spend ASR quota before the parent actually reveals this resident.
  if (!avatarVisible)
    return ''
  touch()
  const epoch = session.generation
  const controller = new AbortController()
  inputControllers.add(controller)
  try {
    const text = await residentApi.transcribe(audio, {
      sessionId: session.sessionId,
      inputId: crypto.randomUUID().replaceAll('-', ''),
    }, controller.signal)
    if (epoch !== session.generation || controller.signal.aborted)
      throw new Error('resident_transcription_cancelled')
    if (!text.trim())
      status.value = '未辨識到清楚內容；等朗讀完再講，或者先打字同我傾。'
    if (text.trim() && runtimePreferences?.hearing?.auto_send === false) {
      touch()
      draft.value = text
      status.value = '已放入輸入框；你可以核對後按傳送。'
      return ''
    }
    return text
  }
  catch {
    if (epoch === session.generation && !controller.signal.aborted)
      status.value = '剛才未能辨識清楚，你可以再講一次，或者先打字同我傾。'
    throw new Error('resident_transcription_unavailable')
  }
  finally {
    inputControllers.delete(controller)
  }
}
defineExpose({ sendMessage, transcribeAudio })
function acknowledgeReady(event?: MessageEvent) {
  if (event && (event.origin !== hubOrigin || event.source !== window.parent || event.data?.type !== 'estate-assistant-check'))
    return
  window.parent.postMessage({ type: 'estate-assistant-ready' }, hubOrigin)
}
function greetAvatar() {
  avatarMounted = true
  if (avatarVisible && !entranceGreeted) {
    entranceGreeted = true
    residentGesture('greeting')
    lastWelcome = performance.now()
  }
}
function welcomeIfIdle() {
  if (shouldResidentWelcome({ visible: avatarVisible, mounted: avatarMounted, hidden: document.hidden, busy: busy.value, speaking: speechActive.value || nowSpeaking.value, messages: messages.value.length, draft: draft.value, lastAt: lastWelcome }, performance.now())) {
    residentGesture('greeting')
    lastWelcome = performance.now()
  }
}
function residentVisible(event: MessageEvent) {
  if (event.origin !== location.origin || event.source !== window.parent || event.data?.type !== 'neighbour-resident-visible')
    return
  avatarVisible = true
  if (avatarMounted)
    greetAvatar()
}
function sharedModelUnavailable() {
  if (!busy.value && messages.value.length === 0)
    status.value = '共享模型暫時未能載入，先使用原有角色；對話及語音仍可繼續。'
}
function acknowledgeModelCredit(event: MessageEvent) {
  if (cloudResident && event.origin === location.origin && event.source === window.parent
    && event.data?.type === 'neighbour-model-credit-placed') {
    creditInHeader.value = true
  }
}
onMounted(() => {
  gaze = new ResidentGaze((state: string) => {
    if (state === 'tracking' && gazeState.value !== 'tracking')
      welcomeIfIdle()
    gazeState.value = state
  })
  welcomeTimer = setInterval(welcomeIfIdle, 5000)
  window.addEventListener('message', residentVisible)
  if (avatarMounted && avatarVisible)
    greetAvatar()
  if (cloudResident && window.parent !== window) {
    window.addEventListener('message', acknowledgeModelCredit)
    window.parent.postMessage({ type: 'neighbour-model-credit', credit: presentation.model_credit || null }, location.origin)
  }
  window.addEventListener('estate:shared-model-unavailable', sharedModelUnavailable)
  if (residentApi.cloud)
    Reflect.set(globalThis, '__NEIGHBOUR_RESIDENT_IDLE__', () => !busy.value && !draft.value && messages.value.length === 0 && !session.profile)
  window.addEventListener('resident-avatar-ready', greetAvatar)
  touch()
  window.addEventListener('message', acknowledgeReady)
  window.addEventListener('focus', checkIdle)
  document.addEventListener('visibilitychange', checkIdle)
  acknowledgeReady()
  window.dispatchEvent(new Event('resident-conversation-ready'))
})
onUnmounted(() => {
  clearInterval(welcomeTimer)
  cancelPhoto()
  gaze?.dispose()
  window.removeEventListener('message', residentVisible)
  window.removeEventListener('message', acknowledgeModelCredit)
  window.removeEventListener('estate:shared-model-unavailable', sharedModelUnavailable)
  if (residentApi.cloud)
    Reflect.deleteProperty(globalThis, '__NEIGHBOUR_RESIDENT_IDLE__')
  window.removeEventListener('resident-avatar-ready', greetAvatar)
  residentGesture('clear')
  window.removeEventListener('message', acknowledgeReady)
  session.reset()
  cancelTranscription()
  window.removeEventListener('focus', checkIdle)
  document.removeEventListener('visibilitychange', checkIdle)
  inactivity.stop()
  clearAudio()
})
function checkIdle() {
  inactivity.check()
}
</script>

<template>
  <section class="resident-assistant-panel" aria-label="居民數字人對話">
    <header>
      <div><h2>你好，慢慢傾。</h2></div><button type="button" class="resident-end" data-hand-action="next" aria-label="結束本輪對話，迎接下一位" @click="reset">
        下一位
      </button>
    </header>
    <details v-if="cloudResident" class="resident-gaze-options">
      <summary data-hand-action="camera-options">
        視線互動{{ gazeState === 'tracking' ? ' · 已跟隨你' : gazeState === 'searching' ? ' · 尋找位置中' : '' }}
      </summary>
      <p>允許鏡頭後，角色會望向你。影像只喺此裝置即時處理，不拍照、不上傳、不儲存，亦不辨認身份。視線模式按「下一位」會關閉；手勢導覽模式會保持鏡頭，直到關閉或離開居民頁。</p>
      <button type="button" data-hand-action="camera-toggle" :aria-pressed="!['off', 'unavailable'].includes(gazeState)" @click="toggleGaze">
        {{ ['off', 'unavailable'].includes(gazeState) ? '允許鏡頭並啟用視線互動' : '關閉鏡頭及視線互動' }}
      </button>
      <button v-if="!gaze?.hands" type="button" @click="startHandControl">
        啟用鏡頭手勢導覽
      </button>
      <p v-if="gaze?.hands">
        手掌移動游標；停留在按鈕後捏合拇指與食指確認。握拳暫停，畫面上下邊緣可捲動對話。首次鏡頭及語音權限需由現場職員預先允許。
      </p>
      <p v-if="gazeState === 'starting'" role="status">
        正在準備，請留意瀏覽器鏡頭權限提示。
      </p>
      <p v-else-if="gazeState === 'unavailable'" role="status">
        鏡頭未能啟用或已中斷；對話及語音可照常使用。
      </p>
    </details>
    <div ref="transcript" class="resident-transcript" aria-live="polite" aria-relevant="additions">
      <p v-if="!messages.length" class="resident-greeting">
        {{ presentation.greeting || '查資料、傾偈、跟進事情，直接同我講就得。' }}
      </p>
      <div v-for="(message, index) in messages" :key="index" class="resident-bubble" :class="message.role">
        <span>{{ message.role === 'user' ? '你' : presentation.name || '服務台' }}</span><p>
          <template v-for="(part, partIndex) in residentMessageParts(message.content)" :key="partIndex">
            <a v-if="part.url" :href="part.url" target="_blank" rel="noopener noreferrer">{{ part.text }}</a><template v-else>
              {{ part.text }}
            </template>
          </template>
        </p>
      </div>
    </div>
    <div class="resident-panel-notices" tabindex="0" aria-label="服務提示">
      <p class="resident-panel-status" role="status">
        {{ status }}
      </p>
      <p v-if="followupNotice" class="resident-panel-status" role="status">
        {{ followupNotice }}
      </p>
      <div v-if="cloudResident && casePhotoTarget" class="resident-case-photo">
        <p>個案 {{ casePhotoTarget.number }}：可自願拍照，方便已登入職員跟進時認到你；不拍照亦可求助。完成後 90 日清除，包括平台管理的備份。</p>
        <button type="button" data-hand-action="photo-preview" :disabled="photoBusy" @click="prepareCasePhoto">
          拍照並預覽（未上傳）
        </button>
        <p v-if="photoStatus" role="status">
          {{ photoStatus }}
        </p>
      </div>
      <p v-if="voiceRecovering" class="resident-panel-status">
        正在自動恢復語音連接；你可以繼續打字。
      </p>
      <p v-else-if="voiceUnavailable" class="resident-panel-status">
        語音暫時未能使用，請先用文字傾談。
      </p>
      <p v-else-if="listening && inputStatus === 'starting'" class="resident-panel-status">
        正在準備收音，未開始聆聽；你可以先打字。
      </p>
      <p v-else-if="listening && inputStatus === 'waiting'" class="resident-panel-status">
        收音未啟動或已中斷，點一下語音掣重新啟動。
      </p>
      <p v-else-if="listening && inputStatus === 'speaking'" class="resident-panel-status">
        朗讀完會繼續聆聽；想先講可以按「停止朗讀」。
      </p>
    </div>
    <form @submit.prevent="sendMessage()">
      <label class="resident-input-label" for="residentDraft">想講啲咩？</label><textarea id="residentDraft" v-model="draft" rows="2" maxlength="2000" required placeholder="直接講，或者喺度打字…" @input="touch" />
      <div class="resident-panel-actions">
        <button type="button" data-hand-action="microphone" :aria-pressed="listening" @click="emit('microphone')">
          {{ listening ? inputStatus === 'starting' ? '準備收音中 · 暫停' : inputStatus === 'failed' ? '重新準備語音' : inputStatus === 'waiting' ? '點一下啟動收音' : inputStatus === 'speaking' ? '朗讀中 · 暫停收音' : '正在聆聽 · 暫停' : '開始語音傾談' }}
        </button><button v-if="speechActive" type="button" data-hand-action="stop-voice" @click="clearAudio">
          停止朗讀
        </button><button v-if="busy" type="button" data-hand-action="stop-wait" @click="cancelWaiting">
          停止等候
        </button><button class="primary" type="submit" data-hand-action="send" :disabled="busy || !draft.trim()">
          {{ busy ? '回覆中…' : '傳送' }}
        </button>
      </div>
    </form>
    <dialog ref="photoDialog" class="resident-photo-dialog" aria-label="確認個案相片" @cancel.prevent="cancelPhoto">
      <h3>拍照方便職員跟進個案</h3>
      <p>確認後，相片會附上個案 {{ casePhotoTarget?.number }}，只供已登入職員查看；個案完成後 90 日清除。不確認則不上傳。</p>
      <img v-if="photoPreview" :src="photoPreview" alt="你準備附上個案的相片預覽">
      <button type="button" data-hand-action="photo-confirm" :disabled="photoBusy" @click="confirmCasePhoto">
        確認附上個案
      </button>
      <button type="button" data-hand-action="photo-cancel" :disabled="photoBusy" @click="cancelPhoto">
        取消，不上傳
      </button>
    </dialog>
  </section>
  <details v-if="presentation.model_credit && !creditInHeader" class="resident-model-credit">
    <summary>角色來源</summary>
    <p><a :href="presentation.model_credit.source" target="_blank" rel="noopener noreferrer">{{ presentation.model_credit.name }} · {{ presentation.model_credit.author }}</a></p>
    <p v-if="presentation.model_credit.notice">
      {{ presentation.model_credit.notice }}
    </p>
    <a v-if="presentation.model_credit.terms" :href="presentation.model_credit.terms" target="_blank" rel="noopener noreferrer">原作者使用條款</a>
  </details>
</template>

<style>
.resident-model-credit{font-size:11px;line-height:1.4;color:#60786d;margin:0;overflow-wrap:anywhere}.resident-model-credit a{text-decoration:underline}
</style>

<style scoped>
.resident-assistant-panel {
position: absolute;
top: 16px;
right: 16px;
bottom: 16px;
z-index: 30;
display: flex;
flex-direction: column;
width: min(46%, 480px);
min-width: 320px;
padding: 22px;
border: 1px solid #dce5df;
border-radius: var(--service-radius, 18px);
color: var(--service-ink, #193d37);
background: var(--service-panel, #fff);
box-shadow: 0 12px 35px #173c3710;
font-family: "Segoe UI", "Microsoft JhengHei", system-ui, sans-serif;
font-size: 15px;
line-height: 1.65;
backdrop-filter: blur(12px);
}
.resident-assistant-panel header, .resident-panel-actions {
display: flex;
align-items: center;
justify-content: space-between;
gap: 10px;
}
.resident-panel-eyebrow {
color: #21695d;
font-size: 11px;
font-weight: 700;
letter-spacing: 1px;
}
.resident-assistant-panel h2 {
font-size: 22px;
margin: 5px 0 0;
}
.resident-transcript {
flex: 1;
min-height: 90px;
overflow-y: auto;
margin: 18px 0 10px;
padding-right: 4px;
}
.resident-greeting {
background: #edf4ef;
border-radius: 12px;
padding: 16px;
}
.resident-bubble {
max-width: 95%;
margin: 0 0 12px;
padding: 11px 14px;
background: #edf4ef;
border-radius: 13px 13px 13px 3px;
}
.resident-bubble.user {
background: #21695d;
color: #fff;
margin-left: auto;
border-radius: 13px 13px 3px 13px;
}
.resident-bubble span {
display: block;
font-size: 10px;
opacity: .75;
margin-bottom: 4px;
}
.resident-bubble p {
white-space: pre-wrap;
overflow-wrap: anywhere;
margin: 0;
}
.resident-panel-status {
font-size: 12px;
color: #61756f;
margin: 0 0 10px;
}
.resident-panel-status:empty { display: none; }
.resident-assistant-panel form {
display: grid;
gap: 8px;
}
.resident-assistant-panel label {
font-size: 13px;
font-weight: 600;
}
.resident-assistant-panel textarea {
width: 100%;
padding: 10px 12px;
background: #fff;
border: 1px solid #cbd9d0;
border-radius: 10px;
color: inherit;
resize: vertical;
font: inherit;
}
.resident-assistant-panel button {
padding: 9px 13px;
min-height: 42px;
border: 1px solid #dce5df;
border-radius: 9px;
background: #fff;
color: #193d37;
cursor: pointer;
font: inherit;
font-size: 13px;
}
.resident-assistant-panel button.primary {
background: #21695d;
color: #fff;
border-color: #21695d;
flex: 1;
}
.resident-assistant-panel button:disabled {
opacity: .5;
cursor: not-allowed;
}
.resident-assistant-panel .resident-end {
font-size: 11px;
padding: 7px 10px;
}
.resident-secondary {
margin-top: 12px;
font-size: 12px;
}
.resident-secondary a {
color: #21695d;
}
.resident-assistant-panel small {
color: #61756f;
font-size: 10px;
margin-top: 12px;
}
.resident-input-label {
position: absolute;
width: 1px;
height: 1px;
overflow: hidden;
clip-path: inset(50%);
}
.resident-assistant-panel {
overflow-y: auto;
}
.resident-secondary {
justify-content: flex-end;
}
.resident-assistant-panel audio {
width: 100%;
margin-top: 8px;
height: 34px;
}
@media (max-width: 760px) {
.resident-assistant-panel {
top: 38%;
left: 10px;
right: 10px;
bottom: 10px;
min-width: 0;
width: auto;
padding: 16px;
} .resident-assistant-panel h2 {
font-size: 19px;
} .resident-assistant-panel small {
margin-top: 6px;
}
}
</style>
