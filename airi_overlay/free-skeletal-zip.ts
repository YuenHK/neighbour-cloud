// SPDX-License-Identifier: MIT
import JSZip from 'jszip'

import { FREE_SKELETAL_FORMAT, validateFreeSkeletalBundle } from './free-skeletal-loader.js'

export interface FreeSkeletalBundle {
  format: 'rigby-json-zip/v1'
  skeletonText: string
  atlasText: string
  pages: Record<string, Blob>
}

interface BoundedZipStream {
  on: {
    (event: 'data', callback: (data: Uint8Array) => void): void
    (event: 'end', callback: () => void): void
    (event: 'error', callback: (error: unknown) => void): void
  }
  pause: () => void
  resume: () => void
}

function boundedStream(member: object): BoundedZipStream {
  // JSZip 3.10.1 implements this API, but its bundled declaration omits it.
  // Check the API at runtime instead of erasing type checking or decompressing unboundedly.
  const factory: unknown = Reflect.get(member, 'internalStream')
  if (typeof factory !== 'function')
    throw new Error('目前 ZIP 工具不支援有界串流讀取。')
  const stream: unknown = Reflect.apply(factory, member, ['uint8array'])
  if (!stream || typeof stream !== 'object'
    || !['on', 'pause', 'resume'].every(key => typeof Reflect.get(stream, key) === 'function')) {
    throw new Error('ZIP 串流介面未能核對。')
  }
  return stream as BoundedZipStream
}

const maximum = 32 * 1024 * 1024
const crcTable = Array.from({ length: 256 }, (_, number) => {
  for (let bit = 0; bit < 8; bit++)
    number = number & 1 ? (number >>> 1) ^ 0xEDB88320 : number >>> 1
  return number >>> 0
})
function crc32(data: Uint8Array) {
  let value = 0xFFFFFFFF
  for (const byte of data)
    value = crcTable[(value ^ byte) & 255] ^ (value >>> 8)
  return (value ^ 0xFFFFFFFF) >>> 0
}

function directory(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let end = -1
  for (let position = bytes.length - 22; position >= Math.max(0, bytes.length - 65557); position--) {
    if (view.getUint32(position, true) === 0x06054B50) {
      end = position
      break
    }
  }
  if (end < 0 || view.getUint16(end + 4, true) || view.getUint16(end + 6, true))
    throw new Error('需要完整、非分卷的 Rigby JSON ZIP。')
  const count = view.getUint16(end + 10, true)
  const size = view.getUint32(end + 12, true)
  const offset = view.getUint32(end + 16, true)
  if (!count || count > 64 || count !== view.getUint16(end + 8, true) || offset + size !== end
    || size > 65536 || end + 22 + view.getUint16(end + 20, true) !== bytes.length) {
    throw new Error('免費骨架 ZIP 的檔案清單超限或不完整。')
  }
  const entries = new Map<string, { size: number, crc: number }>()
  let position = offset
  let total = 0
  for (let index = 0; index < count; index++) {
    if (position + 46 > end || view.getUint32(position, true) !== 0x02014B50)
      throw new Error('ZIP 目錄不完整。')
    const flags = view.getUint16(position + 8, true)
    const compression = view.getUint16(position + 10, true)
    const length = view.getUint32(position + 24, true)
    const nameLength = view.getUint16(position + 28, true)
    const extra = view.getUint16(position + 30, true)
    const comment = view.getUint16(position + 32, true)
    const attributes = view.getUint32(position + 38, true)
    const name = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(position + 46, position + 46 + nameLength))
    position += 46 + nameLength + extra + comment
    const path = name.replace(/\/$/u, '')
    if (position > end || flags & 1 || ![0, 8].includes(compression) || ((attributes >>> 16) & 0xF000) === 0xA000
      || !path || path.length > 240 || /[\\:%?#\u0000-\u0020\u007F]/u.test(path) || path.startsWith('/')
      || path.split('/').some(part => !part || part === '.' || part === '..')) {
      throw new Error('ZIP 含有不安全路徑、加密、連結或未支援格式。')
    }
    if (name.endsWith('/'))
      continue
    const folded = name.toLowerCase()
    if ([...entries.keys()].some(key => key.toLowerCase() === folded) || length > 16 * 1024 * 1024)
      throw new Error('ZIP 有重複或過大的檔案。')
    entries.set(name, { size: length, crc: view.getUint32(position - (46 + nameLength + extra + comment) + 16, true) })
    total += length
  }
  if (position !== end || total > 40 * 1024 * 1024)
    throw new Error('免費骨架 ZIP 解壓後過大。')
  return entries
}

export async function loadFreeSkeletalArchive(file: Blob): Promise<FreeSkeletalBundle> {
  if (!file.size || file.size > maximum)
    throw new Error('免費骨架 ZIP 最大 32 MB。')
  const bytes = new Uint8Array(await file.arrayBuffer())
  const entries = directory(bytes)
  for (const required of ['rigby-manifest.json', 'model.rigby.json', 'model.atlas']) {
    if (!entries.has(required))
      throw new Error('缺少 Rigby 格式清單、JSON 或貼圖清單；不能以此匯入二進位 Spine。')
  }
  const zip = await JSZip.loadAsync(bytes, { checkCRC32: false })
  async function read(name: string, limit: number) {
    const metadata = entries.get(name)
    const member = zip.file(name)
    if (!metadata || metadata.size > limit || !member)
      throw new Error('免費骨架 ZIP 欠缺資源或檔案過大。')
    const content = await new Promise<Uint8Array>((resolve, reject) => {
      const stream = boundedStream(member)
      const parts: Uint8Array[] = []
      let length = 0
      stream.on('data', (chunk: Uint8Array) => {
        if (!(chunk instanceof Uint8Array)) {
          stream.pause()
          reject(new Error('ZIP 串流資料格式不正確。'))
          return
        }
        length += chunk.length
        if (length > limit || length > metadata.size) {
          stream.pause()
          reject(new Error('ZIP 實際解壓量超出限制。'))
          return
        }
        parts.push(chunk)
      })
      stream.on('error', reject)
      stream.on('end', () => {
        const result = new Uint8Array(length)
        let offset = 0
        for (const part of parts) {
          result.set(part, offset)
          offset += part.length
        }
        if (length !== metadata.size || crc32(result) !== metadata.crc)
          reject(new Error('免費骨架資源未能核對完整內容。'))
        else resolve(result)
      })
      stream.resume()
    })
    return content
  }
  const decode = (value: Uint8Array) => new TextDecoder('utf-8', { fatal: true }).decode(value)
  const manifest = JSON.parse(decode(await read('rigby-manifest.json', 8192)))
  if (manifest?.format !== FREE_SKELETAL_FORMAT || manifest.skeleton !== 'model.rigby.json' || manifest.atlas !== 'model.atlas'
    || typeof manifest.license?.name !== 'string' || !manifest.license.name || typeof manifest.license?.author !== 'string' || !manifest.license.author) {
    throw new Error('需要免費骨架格式標記及原作者授權資料。')
  }
  const pages: Record<string, Blob> = {}
  for (const name of entries.keys()) {
    if (name.toLowerCase().endsWith('.png')) {
      const data = await read(name, 16 * 1024 * 1024)
      const buffer = new ArrayBuffer(data.byteLength)
      new Uint8Array(buffer).set(data)
      pages[name] = new Blob([buffer], { type: 'image/png' })
    }
    else if (!['rigby-manifest.json', 'model.rigby.json', 'model.atlas'].includes(name) && !/\.(?:md|txt)$/iu.test(name)) {
      throw new Error('免費骨架 ZIP 含有未使用檔案或程式。')
    }
  }
  const bundle: FreeSkeletalBundle = { format: 'rigby-json-zip/v1', skeletonText: decode(await read('model.rigby.json', 3 * 1024 * 1024)), atlasText: decode(await read('model.atlas', 65536)), pages }
  validateFreeSkeletalBundle(bundle)
  return bundle
}

export async function freeSkeletalPreview(file: File) {
  const { createFreeSkeletalPlayer } = await import('./free-skeletal-player.js')
  const canvas = document.createElement('canvas')
  canvas.width = 320
  canvas.height = 320
  const player = await createFreeSkeletalPlayer(canvas, await loadFreeSkeletalArchive(file))
  try {
    return canvas.toDataURL('image/png')
  }
  finally { player.dispose() }
}
