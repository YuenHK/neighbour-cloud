import { clearResidentGaze, selectResidentFace } from './resident-gaze-state.js'
import { ResidentHandPointer } from './resident-hand.js'

export async function createResidentFaceDetector() {
  const vision = await import(/* @vite-ignore */ `${location.origin}/assets/face-1.2.2/vision_bundle.mjs`)
  const files = await vision.FilesetResolver.forVisionTasks('/assets/face-1.2.2')
  return vision.FaceDetector.createFromOptions(files, {
    canvas: document.createElement('canvas'),
    baseOptions: { modelAssetPath: '/assets/face-1.2.2/blaze_face_short_range.tflite', delegate: 'CPU' },
    runningMode: 'VIDEO',
    minDetectionConfidence: 0.65,
  })
}
export async function createResidentHandDetector() {
  const vision = await import(/* @vite-ignore */ `${location.origin}/assets/face-1.2.2/vision_bundle.mjs`)
  return vision.HandLandmarker.createFromOptions(await vision.FilesetResolver.forVisionTasks('/assets/face-1.2.2'), {
    canvas: document.createElement('canvas'),
    baseOptions: { modelAssetPath: '/assets/face-1.2.2/hand_landmarker.task', delegate: 'CPU' },
    runningMode: 'VIDEO',
    numHands: 1,
    minHandDetectionConfidence: 0.65,
    minHandPresenceConfidence: 0.65,
    minTrackingConfidence: 0.65,
  })
}

/** Camera is requested only from a deliberate resident click, never on import. */
export class ResidentGaze {
  constructor(onState) {
    this.onState = onState
    this.generation = 0
    this.hidden = () => {
      if (document.hidden)
        this.stop()
    }
    this.pageExit = () => this.stop()
    document.addEventListener('visibilitychange', this.hidden)
    window.addEventListener('pagehide', this.pageExit)
  }

  async start(hands = false) {
    this.stop()
    this.hands = hands
    if (hands)
      this.pointer = new ResidentHandPointer()
    const epoch = this.generation
    this.onState('starting')
    if (!navigator.mediaDevices?.getUserMedia) {
      this.stop('unavailable')
      return
    }
    // Keep native permission UX attached to the click, even while assets prepare.
    const requested = navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: 'user', width: { ideal: 320 }, height: { ideal: 240 }, frameRate: { ideal: 8, max: 10 } } })
    requested.then((stream) => {
      if (epoch !== this.generation)
        stream.getTracks().forEach(track => track.stop())
    }).catch(() => {})
    this.deadline = setTimeout(() => this.stop('unavailable'), 30000)
    try {
      const stream = await requested
      if (epoch !== this.generation)
        return
      this.stream = stream
      for (const track of stream.getTracks()) {
        track.addEventListener('ended', () => {
          if (epoch === this.generation)
            this.stop('unavailable')
        }, { once: true })
      }
      const video = document.createElement('video')
      this.video = video
      video.muted = true
      video.setAttribute('playsinline', '')
      video.srcObject = stream
      await video.play()
      if (epoch !== this.generation)
        return
      if (!globalThis.OffscreenCanvas || !globalThis.Worker || !globalThis.createImageBitmap) {
        // Safari compatibility: low-rate CPU detection, never on the render loop.
        const detector = await createResidentFaceDetector()
        if (epoch !== this.generation) {
          detector.close()
          return
        }
        this.detector = detector
        if (hands) {
          const handDetector = await createResidentHandDetector()
          if (epoch !== this.generation) {
            handDetector.close()
            return
          }
          this.handDetector = handDetector
        }
        clearTimeout(this.deadline)
        this.onState('searching')
        void this.frame(epoch)
        return
      }
      const worker = new Worker('/cloud/resident-gaze-worker.js')
      this.worker = worker
      worker.onerror = () => {
        if (epoch === this.generation)
          this.stop('unavailable')
      }
      worker.onmessage = ({ data }) => {
        if (epoch !== this.generation)
          return
        if (data?.type === 'failed') {
          this.stop('unavailable')
          return
        }
        clearTimeout(this.deadline)
        if (data?.type === 'ready') {
          this.onState('searching')
          void this.frame(epoch)
        }
        else if (data?.type === 'faces') {
          this.acceptFaces(data, epoch)
        }
      }
      worker.postMessage({ type: 'init', hands })
    }
    catch {
      if (epoch === this.generation)
        this.stop('unavailable')
    }
  }

  async frame(epoch) {
    if (epoch !== this.generation || !this.video)
      return
    try {
      if (this.detector) {
        const data = this.detector.detectForVideo(this.video, performance.now())
        const landmarks = this.handDetector?.detectForVideo(this.video, performance.now()).landmarks[0]
        this.acceptFaces({ detections: data.detections, landmarks, width: this.video.videoWidth, height: this.video.videoHeight }, epoch)
        return
      }
      if (!this.worker)
        return
      const bitmap = await createImageBitmap(this.video, { resizeWidth: 320, resizeHeight: 240 })
      if (epoch !== this.generation) {
        bitmap.close()
        return
      }
      this.deadline = setTimeout(() => this.stop('unavailable'), 6000)
      this.worker.postMessage({ type: 'frame', image: bitmap, at: performance.now() }, [bitmap])
    }
    catch {
      if (epoch === this.generation)
        this.stop('unavailable')
    }
  }

  acceptFaces(data, epoch) {
    this.pointer?.update(data.landmarks)
    const face = selectResidentFace(data.detections, data.width, data.height, this.previous)
    if (face) {
      this.previous = face
      Reflect.set(globalThis, '__NEIGHBOUR_RESIDENT_GAZE__', Object.freeze({ x: face.x * 2 - 1, y: face.y * 2 - 1, at: performance.now() }))
    }
    else {
      this.previous = undefined
      clearResidentGaze()
    }
    this.onState(face ? 'tracking' : 'searching')
    this.timer = setTimeout(() => {
      void this.frame(epoch)
    }, this.detector ? 450 : 200)
  }

  capturePreview() {
    if (!this.video || this.video.readyState < 2)
      throw new Error('camera_not_ready')
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, 320 / this.video.videoWidth, 320 / this.video.videoHeight)
    canvas.width = Math.max(1, Math.round(this.video.videoWidth * scale))
    canvas.height = Math.max(1, Math.round(this.video.videoHeight * scale))
    canvas.getContext('2d').drawImage(this.video, 0, 0, canvas.width, canvas.height)
    const result = canvas.toDataURL('image/jpeg', 0.65)
    if (!result.startsWith('data:image/jpeg;base64,') || result.length > 53360)
      throw new Error('camera_photo_size')
    return result
  }

  stop(state = 'off') {
    this.generation++
    clearTimeout(this.timer)
    clearTimeout(this.deadline)
    this.worker?.terminate()
    this.worker = undefined
    this.detector?.close()
    this.detector = undefined
    this.handDetector?.close()
    this.handDetector = undefined
    this.pointer?.dispose()
    this.pointer = undefined
    this.hands = false
    this.stream?.getTracks().forEach(track => track.stop())
    this.stream = undefined
    if (this.video) {
      this.video.pause()
      this.video.srcObject = null
      this.video = undefined
    }
    this.previous = undefined
    clearResidentGaze()
    this.onState(state)
  }

  dispose() {
    this.stop()
    document.removeEventListener('visibilitychange', this.hidden)
    window.removeEventListener('pagehide', this.pageExit)
  }
}
