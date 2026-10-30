// Rendering only: retain the original history record for inspection/copy.
// A network error in a past turn is not a live service-health indicator.
export function formatLocalConnectionError(content: string): string {
  if (['Failed to fetch', 'TypeError: Failed to fetch', 'NetworkError when attempting to fetch resource.']
    .includes(content.trim())) {
    return '當次請求未能連線，請核對 START-AIRI 及本機服務。此訊息是保留的錯誤紀錄，不代表目前連線狀態。'
  }
  return content
}
