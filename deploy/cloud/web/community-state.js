// Readiness is evidence from this launch, never elapsed time or a live AI probe.
export function createCommunityState(publish = () => {}) {
  let systems, checks = {}, repairing = new Set()
  const entry = (state, detail) => ({ state, detail })
  const emit = () => publish(Object.fromEntries(Object.entries(systems).map(([k, v]) => [k, { ...v }])))
  function reset() {
    checks = {}; repairing = new Set()
    systems = {
      minerva: entry('loading', '正在核對服務連接與存取'),
      hades: entry('ready', '啟動保護已備妥；不會重送對話'),
      hephaestus: entry('offline', '機械人待現場連接；不會自行連機'),
      poseidon: entry('offline', '水務回報待載入；影像辨識待實景驗收'),
      demeter: entry('offline', '環境回報待載入；巡查待實景驗收'),
      artemis: entry('planned', '動物及社區生態服務屬未來發展'),
      eleuthia: entry('loading', '正在準備數字人與輸入'),
      aether: entry('offline', '煙火線索待現場核實；空氣感測屬規劃'),
      apollo: entry('loading', '正在讀取對話、知識與記憶設定'),
    }
    emit()
  }
  function applyChecks(value) {
    checks = { ...checks, ...value }
    const group = (key, names, ready, pending) => {
      if (repairing.has(key)) return
      const states = names.map(name => checks[name])
      systems[key] = states.some(state => ['failed', 'action'].includes(state))
        ? entry('error', names.includes('input') && ['failed', 'action'].includes(checks.input)
          ? '語音輸入需處理；可先用文字，按咪掣重試' : '部分載入未完成；保留資料，可重新連接')
        : states.every(state => state === 'ready') ? entry('ready', ready) : entry('loading', pending)
    }
    group('eleuthia', ['interface', 'runtime', 'avatar', 'input'],
      '數字人與輸入已就緒；未試用雲端 AI 額度', '正在準備數字人、語音及輸入')
    group('apollo', ['interface', 'runtime'],
      '知識及記憶設定已讀取；查詢時再連接服務', '正在讀取知識及記憶設定')
    emit()
  }
  function repair(key, state) {
    if (!Object.hasOwn(systems, key)) return
    if (state === 'retrying') {
      repairing.add(key)
      systems[key] = entry('repairing', '正在安全重連一次；不重送對話或個案')
      systems.hades = entry('repairing', '正在處理未完成的載入，原有資料保留')
    }
    else {
      repairing.delete(key)
      systems[key] = entry(state === 'unavailable' ? 'error' : 'loading',
        state === 'unavailable' ? '自動重連未完成；需要手動重試' : '已重新連接，正在等待就緒確認')
      if (!repairing.size) systems.hades = entry(state === 'unavailable' ? 'error' : 'ready',
        state === 'unavailable' ? '已停止自動重試；資料及其餘功能保留' : '安全重連已完成；等待功能確認')
    }
    emit()
  }
  function connected() {
    repairing.delete('minerva')
    systems.minerva = entry('ready', '本次存取已核對；職員操作仍需管理口令')
    if (!repairing.size) systems.hades = entry('ready', '啟動保護就緒；不會自動重送已送內容')
    emit()
  }
  function module(key, state) {
    const target = key === 'services' ? 'eleuthia' : key === 'robots' ? 'hephaestus' : 'apollo'
    if (state === 'repairing') { repair(target, 'retrying'); return }
    if (['loaded', 'failed'].includes(state) && repairing.has(target)) repair(target, state === 'failed' ? 'unavailable' : 'retried')
    if (key === 'services') {
      for (const name of ['poseidon', 'demeter']) systems[name] = entry(state === 'failed' ? 'error' : 'offline',
        state === 'failed' ? '回報程式未能預載；開啟時可再試' : state === 'loaded'
          ? '回報程式已預載；巡查影像仍待現場驗收' : '正在預載回報程式；不會啟動巡查')
    }
    if (key === 'robots') systems.hephaestus = entry(state === 'failed' ? 'error' : 'offline',
      state === 'failed' ? '控制台程式未能預載；不影響居民對話' : state === 'loaded'
        ? '控制台程式已預載；機械人待現場連接' : '正在預載程式；不會自行連接機械人')
    emit()
  }
  function fail(key = 'minerva') { repair(key, 'unavailable') }
  function boot(value = {}) {
    systems.minerva = entry(value.public_ready === true ? 'ready' : value.rollout_failed === true ? 'error' : 'loading',
      value.public_ready === true ? '服務已啟動，正在進入' : '正在等候主機與資料服務；未開啟居民功能')
    systems.hades = entry(value.rollout_failed === true ? 'error' : 'loading',
      value.rollout_failed === true ? '主機啟動未完成，需要職員處理' : '正在等候安全啟動；不會自行恢復備份或清除用量')
    emit()
  }
  reset()
  return { reset, connected, checks: applyChecks, repair, module, fail, boot,
    snapshot: () => Object.fromEntries(Object.entries(systems).map(([k, v]) => [k, { ...v }])) }
}
