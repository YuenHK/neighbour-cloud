// Startup checks describe this browser and configured services. No provider probes.
export function createReadiness(send) {
  const checks = { interface: 'pending', runtime: 'pending', avatar: 'pending', input: 'pending' }
  let closed = false
  function update(name, state) {
    if (closed || !(name in checks) || !['pending', 'ready', 'action', 'failed'].includes(state))
      return
    checks[name] = state
    const textReady = checks.interface === 'ready' && checks.runtime === 'ready'
    const ready = Object.values(checks).every(value => value === 'ready')
    send({ type: 'neighbour-readiness', area: 'resident', checks: { ...checks }, textReady, ready })
  }
  return { update, close() {
    closed = true
  } }
}
