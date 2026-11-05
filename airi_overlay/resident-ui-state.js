// Presentation only: never retries a request or starts audio/media.
export function residentUiPhase({ busy, streaming, preparingSpeech, speaking, status = '' }) {
  if (/未能|未準備好|未完成|已停止等候/.test(status))
    return 'attention'
  if (speaking)
    return 'speaking'
  if (preparingSpeech)
    return 'preparing'
  if (busy)
    return streaming ? 'replying' : 'thinking'
  return 'ready'
}
