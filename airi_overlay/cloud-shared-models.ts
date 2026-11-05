import type { DisplayModelFile } from '@proj-airi/stage-ui/stores/display-models'

import localforage from 'localforage'

import { DisplayModelFormat } from '@proj-airi/stage-ui/stores/display-models'

export const sharedModelPattern = /^cloud-(?:live2d|vrm|rigby)-[a-f0-9]{64}$/
export const maxModelBytes = 32 * 1024 * 1024
const pending = new Map<string, Promise<DisplayModelFile>>()
const ready = new Map<string, DisplayModelFile>()
function transport() {
  const value = Reflect.get(globalThis, '__NEIGHBOUR_CLOUD_TRANSPORT__')
  if (!value || Reflect.get(globalThis, '__NEIGHBOUR_CLOUD__') !== true)
    throw new Error('verified_cloud_model_transport_required')
  return value
}
export async function modelHash(blob: Blob) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))].map(v => v.toString(16).padStart(2, '0')).join('')
}
export async function sharedModels() {
  const response = await transport().fetch('/api/v1/service-desk/airi-models', { signal: AbortSignal.timeout(15000) })
  if (!response.ok)
    throw new Error('未能載入平台模型清單，原有模型保留。')
  return response.json()
}
export async function loadSharedModel(id: string, name?: string): Promise<DisplayModelFile> {
  if (!sharedModelPattern.test(id))
    throw new Error('shared_model_id_invalid')
  if (ready.has(id))
    return ready.get(id)!
  if (pending.has(id))
    return pending.get(id)!
  const task = (async () => {
    const vrm = id.startsWith('cloud-vrm-')
    const rigby = id.startsWith('cloud-rigby-')
    const digest = id.slice(id.lastIndexOf('-') + 1)
    const mime = vrm ? 'model/gltf-binary' : 'application/zip'
    const key = `neighbour-cloud-model-${digest}`
    let cached: Blob | null = null
    try {
      cached = await localforage.getItem<Blob>(key)
    }
    catch { /* Browser cache is optional; never authority. */ }
    let blob: Blob
    if (cached instanceof Blob && cached.size > 0 && cached.size <= maxModelBytes && await modelHash(cached) === digest) {
      blob = cached
    }
    else {
      const response = await transport().fetch(`/api/v1/resident/airi-models/${id}`, { signal: AbortSignal.timeout(120000) })
      if (!response.ok || !response.body)
        throw new Error('共享模型暫時未能載入，原有角色保留。')
      const reader = response.body.getReader()
      const parts: Uint8Array[] = []
      let length = 0
      try {
        while (true) {
          const item = await reader.read()
          if (item.done)
            break
          length += item.value.byteLength
          if (length > maxModelBytes)
            throw new Error('共享模型超出大小限制。')
          parts.push(item.value)
        }
      }
      finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
      const bytes = new Uint8Array(length)
      let offset = 0
      for (const part of parts) {
        bytes.set(part, offset)
        offset += part.length
      }
      blob = new Blob([bytes], { type: mime })
      if (!length || await modelHash(blob) !== digest)
        throw new Error('共享模型未能核對完整內容，沒有切換角色。')
      try {
        await localforage.setItem(key, blob)
      }
      catch { /* Keep this verified in-memory copy if device storage is full. */ }
    }
    const filename = name || (vrm ? '平台 VRM 模型.vrm' : rigby ? '平台免費骨架模型.rigby.zip' : '平台 Live2D 模型.zip')
    const file = new File([blob], filename, { type: mime })
    const model: DisplayModelFile = { id, format: vrm ? DisplayModelFormat.VRM : rigby ? DisplayModelFormat.RigbyJsonZip : DisplayModelFormat.Live2dZip, type: 'file', file, name: filename, importedAt: Date.now() }
    ready.set(id, model)
    return model
  })().finally(() => pending.delete(id))
  pending.set(id, task)
  return task
}
export function installSharedModelLoader() {
  Reflect.set(globalThis, '__NEIGHBOUR_LOAD_SHARED_MODEL__', loadSharedModel)
}
export class ModelUploadRejected extends Error {}
export async function uploadSharedModel(file: File, format?: DisplayModelFormat) {
  const vrm = file.name.toLowerCase().endsWith('.vrm')
  const rigby = format === DisplayModelFormat.RigbyJsonZip || file.name.toLowerCase().endsWith('.rigby.zip')
  if (!file.size || file.size > maxModelBytes || (!vrm && !file.name.toLowerCase().endsWith('.zip')))
    throw new ModelUploadRejected('共享發佈接納不超過 32 MB 的 Live2D ZIP、Rigby JSON ZIP 或 VRM；原檔保留。')
  const digest = await modelHash(file)
  const id = `${vrm ? 'cloud-vrm' : rigby ? 'cloud-rigby' : 'cloud-live2d'}-${digest}`
  const response = await transport().fetch(`/api/v1/service-desk/airi-models/${id}?name=${encodeURIComponent(file.name.slice(0, 100))}`, {
    method: 'PUT',
    headers: { 'Content-Type': vrm ? 'model/gltf-binary' : 'application/zip' },
    body: file,
    signal: AbortSignal.timeout(180000),
  })
  if ([400, 413, 415, 422, 429].includes(response.status)) {
    const value = await response.json().catch(() => ({}))
    throw new ModelUploadRejected(typeof value.detail === 'string' ? value.detail : '上載未獲接納；原有模型及檔案保留。')
  }
  if (!response.ok)
    throw new Error('model_upload_acknowledgement_unknown')
  const result = await response.json()
  if (result.id !== id || result.sha256 !== digest || result.bytes !== file.size)
    throw new Error('model_upload_acknowledgement_unknown')
  ready.set(id, { id, format: vrm ? DisplayModelFormat.VRM : rigby ? DisplayModelFormat.RigbyJsonZip : DisplayModelFormat.Live2dZip, type: 'file', file, name: result.name, importedAt: Date.now() })
  return result
}
