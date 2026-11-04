/// <reference path="./resident-lipsync-assets.d.ts" />
import type { Profile } from 'wlipsync'

import processorURL from 'wlipsync/audio-processor.js?url&no-inline'
import wasmURL from 'wlipsync/wlipsync.wasm?url'

import { configuration, createWLipSyncNode } from 'wlipsync/wlipsync.js'

// AIRI's bundled single-file worklet uses a data: module, which our CSP
// correctly refuses. Serve the same installed library from this origin.
const contexts = new WeakMap<AudioContext, Promise<void>>()
const sinks = new WeakMap<AudioNode, GainNode>()
let wasm: Promise<WebAssembly.Module> | undefined

export async function createResidentLipSync(context: AudioContext, profile: Profile) {
  let ready = contexts.get(context)
  if (!ready) {
    ready = Promise.all([
      context.audioWorklet.addModule(processorURL),
      wasm ??= WebAssembly.compileStreaming(fetch(wasmURL)),
    ]).then(([, module]) => { configuration.wasmModule = module })
    contexts.set(context, ready)
    void ready.catch(() => {
      contexts.delete(context)
      wasm = undefined
    })
  }
  await ready
  const node = await createWLipSyncNode(context, profile)
  // Analysis remains processed on browsers that prune disconnected graphs.
  // The destination receives zero gain, never a second audible voice.
  const sink = context.createGain()
  sink.gain.value = 0
  node.connect(sink)
  sink.connect(context.destination)
  sinks.set(node, sink)
  return node
}

export function releaseResidentLipSync(node?: AudioNode) {
  if (!node)
    return
  const sink = sinks.get(node)
  node.disconnect()
  sink?.disconnect()
  sinks.delete(node)
  const port = (node as AudioWorkletNode).port
  if (port) {
    port.onmessage = null
    port.close()
  }
}
