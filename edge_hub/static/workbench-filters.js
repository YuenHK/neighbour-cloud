// Shared staff filters. Visitor data is never persisted in browser storage.
(() => {
  function create(host, { events = false, onChange = () => {} } = {}) {
    if (!host) return null
    const defaults = { q: '', state: 'all', sort: 'created_desc', date_field: 'created', date_from: '', date_to: '' }
    let applied = { ...defaults }, scope = 'default'
    const saved = new Map(), buttons = new Map()
    const make = (parent, tag, text, cls) => {
      const item = document.createElement(tag)
      if (text) item.textContent = text
      if (cls) item.className = cls
      parent.append(item)
      return item
    }
    const form = make(host, 'form', '', 'workbench-filters')
    form.setAttribute('aria-label', events ? '現場回報檢索' : '個案檢索')
    const main = make(form, 'div', '', 'workbench-filter-main')
    const searchLabel = make(main, 'label', '搜尋')
    const search = make(searchLabel, 'input')
    search.type = 'search'; search.maxLength = 120
    search.placeholder = events ? '位置、事件編號或內容' : '個案編號、單位或內容'
    search.setAttribute('aria-label', events ? '搜尋現場回報' : '搜尋個案')
    function select(parent, label, choices) {
      const wrapper = make(parent, 'label', label), item = make(wrapper, 'select')
      item.setAttribute('aria-label', label)
      for (const [value, title] of choices) {
        const option = make(item, 'option', title); option.value = value
      }
      return item
    }
    const sort = select(main, '排序', events
      ? [['created_desc', '最新回報'], ['created_asc', '最早回報'], ['completed_desc', '最近完成'], ['priority', '優先處理']]
      : [['created_desc', '最新建立'], ['created_asc', '最早建立'], ['updated_desc', '最近更新'], ['due_asc', '跟進期限最先'], ['priority', '待辦優先']])
    const actions = make(main, 'div', '', 'workbench-filter-actions')
    const submit = make(actions, 'button', '搜尋'); submit.type = 'submit'
    const clear = make(actions, 'button', '清除篩選', 'service-button-secondary'); clear.type = 'button'
    const states = make(form, 'div', '', 'workbench-filter-states')
    states.setAttribute('role', 'group'); states.setAttribute('aria-label', '按處理狀態篩選')
    const choices = events
      ? [['all', '全部'], ['open', '未完成'], ['pending', '待核實'], ['confirmed', '已確認'], ['resolved', '已完成'], ['false_positive', '誤報']]
      : [['all', '全部'], ['open', '未完成'], ['new', '等待接手'], ['acknowledged', '跟進中'], ['resolved', '已完成']]
    for (const [value, label] of choices) {
      const button = make(states, 'button', label); button.type = 'button'; buttons.set(value, button)
      button.addEventListener('click', () => apply(value))
    }
    const advanced = make(form, 'details', '', 'workbench-filter-dates')
    make(advanced, 'summary', '按日期範圍檢索')
    const dates = make(advanced, 'div', '', 'workbench-filter-date-fields')
    const field = select(dates, '日期依據', events
      ? [['created', '回報日期'], ['completed', '完成記錄日期']]
      : [['created', '建立日期'], ['updated', '最近更新日期'], ['due', '跟進期限']])
    const from = make(make(dates, 'label', '由'), 'input'); from.type = 'date'
    const to = make(make(dates, 'label', '至（包括當日）'), 'input'); to.type = 'date'
    make(advanced, 'small', '日期可留空；選好日期後按「搜尋」。', 'service-muted')
    const error = make(form, 'p', '', 'workbench-filter-error'); error.setAttribute('role', 'alert')
    function paint() {
      search.value = applied.q; sort.value = applied.sort; field.value = applied.date_field
      from.value = applied.date_from; to.value = applied.date_to
      buttons.forEach((button, value) => button.setAttribute('aria-pressed', String(value === applied.state)))
      error.textContent = ''
    }
    function apply(state = applied.state) {
      if (from.value && to.value && from.value > to.value) {
        error.textContent = '開始日期不可遲於結束日期，請調整後再搜尋。'
        return
      }
      applied = { q: search.value.trim(), state, sort: sort.value, date_field: field.value,
        date_from: from.value, date_to: to.value }
      saved.set(scope, { ...applied }); paint(); onChange()
    }
    form.addEventListener('submit', event => { event.preventDefault(); apply() })
    sort.addEventListener('change', () => apply())
    clear.addEventListener('click', () => { applied = { ...defaults }; saved.set(scope, applied); paint(); onChange() })
    paint()
    return {
      query() {
        const values = { ...applied, ...(events ? { live_only: 'true' } : {}) }
        return new URLSearchParams(Object.entries(values).filter(([, value]) => value !== '')).toString()
      },
      scope(value) {
        saved.set(scope, { ...applied }); scope = value; applied = { ...(saved.get(value) || defaults) }; paint()
      },
    }
  }
  globalThis.ZhiweiWorkFilters = { create }
})()
