// Classic worker: MediaPipe and its WASM/model are pinned same-origin assets.
// No network upload, recording, logging, identity recognition or storage.
let detector
let hands
let frameCount = 0
let detections = []
let previousSize
self.exports = {}
self.onmessage = async ({ data }) => {
  if (data?.type === 'init') {
    try {
      importScripts('/assets/face-1.2.2/vision_bundle.js')
      const { FilesetResolver, FaceDetector } = self.exports
      const files = await FilesetResolver.forVisionTasks('/assets/face-1.2.2')
      detector = await FaceDetector.createFromOptions(files, {
        canvas: new OffscreenCanvas(320, 240),
        baseOptions: { modelAssetPath: '/assets/face-1.2.2/blaze_face_short_range.tflite', delegate: 'CPU' },
        runningMode: 'VIDEO', minDetectionConfidence: 0.65,
      })
      if (data.hands) {
        hands = await self.exports.HandLandmarker.createFromOptions(files, {
          canvas: new OffscreenCanvas(320, 240),
          baseOptions: { modelAssetPath: '/assets/face-1.2.2/hand_landmarker.task', delegate: 'CPU' },
          runningMode: 'VIDEO', numHands: 1, minHandDetectionConfidence: 0.65,
          minHandPresenceConfidence: 0.65, minTrackingConfidence: 0.65,
        })
      }
      self.postMessage({ type: 'ready' })
    }
    catch { self.postMessage({ type: 'failed' }) }
    return
  }
  if (data?.type === 'frame' && data.image) {
    try {
      const size = `${data.image.width}x${data.image.height}`
      // A single in-flight frame, no queue. The cheaper spatial face pass
      // is shared across three hand samples while the cursor renders at rAF.
      if (!hands || frameCount % 3 === 0 || previousSize !== size)
        detections = detector.detectForVideo(data.image, data.at).detections
      previousSize = size
      frameCount++
      const landmarks = hands?.detectForVideo(data.image, data.at).landmarks[0]
      self.postMessage({ type: 'faces', detections, landmarks, width: data.image.width, height: data.image.height })
    }
    catch { self.postMessage({ type: 'failed' }) }
    finally { data.image.close() }
  }
}
