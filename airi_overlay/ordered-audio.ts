// Serialize the entire stateful VAD operation, not only the ONNX inference call.
export function orderedAudio(process: (buffer: Float32Array) => Promise<void>, failed: (error: unknown) => void) {
  let chain = Promise.resolve()
  let queued = 0
  let stopped = false
  return {
    push(buffer: Float32Array) {
      if (stopped) return
      if (++queued > 320) {
        stopped = true
        failed(new Error('VAD cannot keep up with real-time audio; restart microphone'))
        return
      }
      // Keep an owned copy until inference is ready. Never reuse/transcribe a partial buffer.
      const copy = buffer.slice()
      chain = chain.then(async () => {
        try { if (!stopped) await process(copy) }
        catch (error) { stopped = true; failed(error) }
        finally { queued-- }
      })
    },
    stop() { stopped = true },
  }
}
