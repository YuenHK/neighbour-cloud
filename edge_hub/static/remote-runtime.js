// Loaded only by the authenticated gateway, before AIRI's application modules.
(() => {
  globalThis.__NEIGHBOUR_REMOTE__ = true
  const base = location.origin
  const paths = new Map([['8000',''],['4173',''],['8765','/_audio'],['6121','/_airi'],['11434','/_ollama']])
  function rewrite(value) {
    const url = new URL(String(value), base)
    if (!['127.0.0.1','localhost'].includes(url.hostname) || !paths.has(url.port)
      || !['http:','ws:'].includes(url.protocol))
      return String(value)
    const target = new URL(base)
    if (url.protocol === 'ws:') target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:'
    target.pathname = paths.get(url.port)+url.pathname
    target.search = url.search
    target.hash = url.hash
    return target.href
  }
  const nativeFetch = globalThis.fetch.bind(globalThis)
  globalThis.fetch = async (input, init = {}) => {
    const original = input instanceof Request ? input.url : String(input)
    const target = rewrite(original)
    const internal = new URL(target, base).origin === base
    if (input instanceof Request && target !== original) {
      const next = new Request(target, input)
      // Preserve a Request's POST body as bytes. Leaving a transferred readable
      // stream here changes Chrome upload/interception behavior on some clients.
      input = ['GET','HEAD'].includes(next.method) ? next : new Request(next, {body:await next.arrayBuffer()})
    }
    else if (!(input instanceof Request))
      input = target
    return nativeFetch(input, internal ? {...init,credentials:'same-origin'} : init)
  }
  const NativeSocket = globalThis.WebSocket
  if (NativeSocket) {
    globalThis.WebSocket = class extends NativeSocket {
      constructor(url, protocols) { super(rewrite(url), protocols) }
    }
  }
  const NativeEvents = globalThis.EventSource
  if (NativeEvents) {
    globalThis.EventSource = class extends NativeEvents {
      constructor(url, options) { super(rewrite(url), options) }
    }
  }
  const open = XMLHttpRequest.prototype.open
  XMLHttpRequest.prototype.open = function(method,url,...rest) { return open.call(this,method,rewrite(url),...rest) }
})()
