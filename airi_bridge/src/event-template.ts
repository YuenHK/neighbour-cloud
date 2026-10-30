type EventType = 'litter_detected' | 'leak_detected' | 'temperature_drill' | 'robot_fault'

export interface SafeEvent {
  type: EventType
  zone: string
  details?: unknown
  evidence?: unknown
}

export function eventToAiriText(event: SafeEvent): string {
  // Metadata is untrusted: select facts, never relay arbitrary instructions/details.
  const details = event.details && typeof event.details === 'object' && !Array.isArray(event.details)
    ? event.details as Record<string, unknown> : {}
  const zone = event.zone.length <= 80 && /^[\p{L}\p{M}\p{N} _()（）-]+$/u.test(event.zone)
    && event.zone.trim() ? event.zone.trim() : '未核實區域'
  const prefix = details.simulation === true || details.is_test === true || details.source === 'software_validation'
    ? '【軟件模擬／測試，非現場確認】' : ''
  const safeBlurredEvidence = typeof event.evidence === 'string'
    && /^events\/[A-Za-z0-9][A-Za-z0-9._-]*-blurred\.(jpg|jpeg|png)$/i.test(event.evidence)
  const privacy = details.privacy === 'text_only'
    ? '本次只保留文字紀錄，請管理人員覆核。'
    : details.privacy === 'blurred' && safeBlurredEvidence
      ? '事件紀錄附有標示為已模糊的影像，仍須管理人員覆核。'
      : '影像私隱狀態尚未核實，請管理人員覆核。'
  const templates: Record<EventType, string> = {
    litter_detected: `在${zone}發現疑似新垃圾，${privacy}`,
    leak_detected: `在${zone}收到漏水感測警報，請管理人員檢查，切勿只依賴AI判斷。`,
    temperature_drill: `在${zone}進行模擬溫度警報，這不是已確認火警，請按演練程序處理。`,
    robot_fault: `在${zone}收到機械人故障通報，請操作員核對連線及停止狀態，勿只依賴本訊息確認安全。`,
  }
  return prefix + templates[event.type]
}
