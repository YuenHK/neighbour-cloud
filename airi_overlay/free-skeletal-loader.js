// SPDX-License-Identifier: MIT
// Deliberately narrow free format. This does not enable AIRI's licensed Spine runtime.
import { parseAtlas } from './free-skeletal-runtime/core/atlas.js'

export const FREE_SKELETAL_FORMAT = 'rigby-json-zip/v1'
export const FREE_SKELETAL_LIMITS = Object.freeze({
  jsonBytes: 3 * 1024 * 1024,
  atlasBytes: 64 * 1024,
  textureBytes: 16 * 1024 * 1024,
  totalTextureBytes: 32 * 1024 * 1024,
  texturePixels: 16 * 1024 * 1024,
  pages: 8,
  bones: 256,
  slots: 512,
  regions: 1024,
  keys: 20000,
  nodes: 100000,
})

function fail(reason) {
  throw new Error(`免費骨架模型：${reason}`)
}
const own = (object, key) => Object.hasOwn(object, key)
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
function plainName(name) {
  return typeof name === 'string' && name.length > 0 && name.length <= 160
    && !/[\u0000-\u001F\u007F]/u.test(name) && !['__proto__', 'prototype', 'constructor'].includes(name)
}

function numericFields(object, fields) {
  for (const name of fields) {
    if (own(object, name) && typeof object[name] !== 'number')
      fail('數值欄位不可使用文字或空值')
  }
}

export function safeSkeletalPath(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 240
    && !/[\\:%?#\u0000-\u0020\u007F]/u.test(value)
    && !value.startsWith('/')
    && value.split('/').every(part => part !== '' && part !== '.' && part !== '..')
}

function checkedText(text, bytes, label) {
  if (typeof text !== 'string' || new TextEncoder().encode(text).byteLength > bytes)
    fail(`${label}太大或格式不正確`)
}

function inspectTree(root) {
  let nodes = 0
  const stack = [{ value: root, depth: 0 }]
  while (stack.length) {
    const { value, depth } = stack.pop()
    if (++nodes > FREE_SKELETAL_LIMITS.nodes || depth > 32)
      fail('內容過大或層次過深')
    if (typeof value === 'number' && (!Number.isFinite(value) || Math.abs(value) > 1e7))
      fail('數值無效或超出範圍')
    if (typeof value === 'string' && value.length > 4096)
      fail('文字欄位過長')
    if (Array.isArray(value)) {
      if (value.length > FREE_SKELETAL_LIMITS.keys)
        fail('資料陣列過大')
      for (const child of value)
        stack.push({ value: child, depth: depth + 1 })
    }
    else if (record(value)) {
      for (const [key, child] of Object.entries(value)) {
        if (!plainName(key))
          fail('欄位名稱不安全')
        stack.push({ value: child, depth: depth + 1 })
      }
    }
  }
}

function uniqueNames(items, limit, label) {
  if (!Array.isArray(items) || !items.length || items.length > limit)
    fail(`${label}數量不正確`)
  const names = new Set()
  for (const item of items) {
    if (!record(item) || !plainName(item.name) || names.has(item.name))
      fail(`${label}名稱重複或無效`)
    names.add(item.name)
  }
  return names
}

function checkAttachment(attachment, regionNames) {
  if (!record(attachment))
    fail('貼圖區域格式不正確')
  const kind = attachment.type ?? 'region'
  numericFields(attachment, ['x', 'y', 'rotation', 'scaleX', 'scaleY', 'width', 'height', 'hull'])
  if (!['region', 'mesh'].includes(kind))
    fail('此免費格式暫只接受區域及無權重網格；請用 Rigby 匯出已支援格式')
  const path = attachment.path ?? attachment.name
  if (!safeSkeletalPath(path) || !regionNames.has(path))
    fail('貼圖區域遺失或包含外部網址')
  if (kind === 'region') {
    if (attachment.width <= 0 || attachment.width > 8192 || attachment.height <= 0 || attachment.height > 8192)
      fail('貼圖區域尺寸不正確')
  }
  else {
    const { uvs, vertices, triangles } = attachment
    if (!Array.isArray(uvs) || uvs.length < 6 || uvs.length > 8192 || uvs.length % 2
      || uvs.some(value => typeof value !== 'number' || value < 0 || value > 1)
      || !Array.isArray(vertices) || vertices.length !== uvs.length || vertices.some(value => typeof value !== 'number')
      || !Array.isArray(triangles) || !triangles.length || triangles.length > 12288 || triangles.length % 3
      || triangles.some(value => !Number.isInteger(value) || value < 0 || value >= uvs.length / 2)) {
      fail('網格不完整、過大或帶有尚未支援的權重')
    }
  }
  if (attachment.sequence)
    fail('此格式暫不接受圖片序列')
}

function checkAnimations(animations, boneNames, slotNames, availableAttachments) {
  if (!record(animations) || Object.keys(animations).length > 64)
    fail('動作清單格式不正確')
  let count = 0
  const boneChannels = new Set(['rotate', 'translate', 'translatex', 'translatey', 'scale', 'scalex', 'scaley', 'shear', 'shearx', 'sheary'])
  const slotChannels = new Set(['attachment', 'color', 'rgba', 'rgb', 'alpha', 'twoColor', 'rgba2', 'rgb2'])
  for (const [name, animation] of Object.entries(animations)) {
    if (!plainName(name) || !record(animation))
      fail('動作名稱或格式不正確')
    for (const field of Object.keys(animation)) {
      if (!['bones', 'slots'].includes(field))
        fail('此免費格式暫不接受變形、事件或約束動作')
    }
    for (const [field, names, channels] of [['bones', boneNames, boneChannels], ['slots', slotNames, slotChannels]]) {
      if (animation[field] !== undefined && !record(animation[field]))
        fail('動作骨架格式不正確')
      for (const [target, timelines] of Object.entries(animation[field] ?? {})) {
        if (!names.has(target) || !record(timelines))
          fail('動作引用不存在的骨架或貼圖')
        for (const [channel, keys] of Object.entries(timelines)) {
          if (!channels.has(channel) || !Array.isArray(keys))
            fail('動作類型尚未支援')
          let previous = -1
          for (const key of keys) {
            const time = key?.time ?? 0
            if (!record(key) || typeof time !== 'number' || time < 0 || time > 120 || time <= previous)
              fail('動作時間順序或長度不正確')
            previous = time
            numericFields(key, ['time', 'value', 'angle', 'x', 'y', 'c2', 'c3', 'c4'])
            if (key.curve !== undefined && key.curve !== 'stepped' && key.curve !== 'linear'
              && (!Array.isArray(key.curve) || key.curve.length !== 4 || !key.curve.every(value => typeof value === 'number'))) {
              fail('動作曲線格式不正確')
            }
            if (field === 'slots' && channel === 'attachment' && key.name != null
              && !availableAttachments.get(target)?.has(key.name)) {
              fail('動作引用不存在的皮膚貼圖')
            }
            if (++count > FREE_SKELETAL_LIMITS.keys)
              fail('動作關鍵點過多')
          }
        }
      }
    }
  }
}

export function validateFreeSkeletalBundle(bundle) {
  if (!record(bundle) || bundle.format !== FREE_SKELETAL_FORMAT)
    fail('請匯入標示 rigby-json-zip/v1 的免費骨架模型；不接受二進位 Spine 檔')
  checkedText(bundle.skeletonText, FREE_SKELETAL_LIMITS.jsonBytes, '骨架檔案')
  checkedText(bundle.atlasText, FREE_SKELETAL_LIMITS.atlasBytes, '貼圖清單')
  let json
  try {
    json = JSON.parse(bundle.skeletonText)
  }
  catch { fail('骨架 JSON 無法讀取') }
  inspectTree(json)
  if (!record(json) || !record(json.skeleton) || !/^(?:3\.8|4\.[23])(?:\.|$)/u.test(String(json.skeleton.spine ?? '')))
    fail('請用 Rigby 匯出已支援的 JSON 格式')
  for (const field of ['images', 'audio']) {
    if (json.skeleton[field] && !safeSkeletalPath(json.skeleton[field]))
      fail('骨架不可引用外部網址')
  }
  for (const field of ['ik', 'transform', 'path', 'physics', 'constraints', 'events']) {
    if (json[field] && Object.keys(json[field]).length)
      fail('此免費格式暫不接受約束或音效事件')
  }
  const boneNames = uniqueNames(json.bones, FREE_SKELETAL_LIMITS.bones, '骨架')
  const seenBones = new Set()
  for (const bone of json.bones) {
    numericFields(bone, ['x', 'y', 'rotation', 'scaleX', 'scaleY', 'shearX', 'shearY', 'length'])
    if (bone.parent !== undefined && !seenBones.has(bone.parent))
      fail('骨架父節點遺失、次序不正確或形成循環')
    seenBones.add(bone.name)
  }
  const slotNames = uniqueNames(json.slots, FREE_SKELETAL_LIMITS.slots, '貼圖插槽')
  for (const slot of json.slots) {
    if (!boneNames.has(slot.bone) || (slot.attachment != null && !plainName(slot.attachment)))
      fail('貼圖插槽引用無效骨架')
  }
  const atlas = parseAtlas(bundle.atlasText)
  if (!atlas.pages.length || atlas.pages.length > FREE_SKELETAL_LIMITS.pages || !record(bundle.pages))
    fail('貼圖頁數不正確')
  const pages = new Set()
  const regions = new Set()
  let totalBytes = 0
  for (const page of atlas.pages) {
    const key = page.name.toLowerCase()
    if (!safeSkeletalPath(page.name) || !/\.png$/iu.test(page.name) || pages.has(key)
      || !own(bundle.pages, page.name) || !(bundle.pages[page.name] instanceof Blob)) {
      fail('貼圖遺失、重複或包含外部網址')
    }
    pages.add(key)
    const blob = bundle.pages[page.name]
    if (!['image/png', ''].includes(blob.type) || !blob.size
      || blob.size > FREE_SKELETAL_LIMITS.textureBytes) {
      fail('貼圖種類或大小不正確')
    }
    totalBytes += blob.size
    if (!Number.isInteger(page.width) || !Number.isInteger(page.height) || page.width <= 0 || page.height <= 0
      || page.width > 8192 || page.height > 8192 || page.width * page.height > FREE_SKELETAL_LIMITS.texturePixels) {
      fail('貼圖像素過大或尺寸無效')
    }
    for (const region of page.regions) {
      if (!safeSkeletalPath(region.name) || regions.has(region.name) || regions.size >= FREE_SKELETAL_LIMITS.regions
        || ![region.x, region.y, region.width, region.height, region.originalWidth, region.originalHeight, region.offsetX, region.offsetY].every(Number.isFinite)
        || region.x < 0 || region.y < 0 || region.width <= 0 || region.height <= 0
        || region.x + region.width > page.width || region.y + region.height > page.height
        || ![0, 90].includes(region.rotate)) {
        fail('貼圖區域無效、重複或超出圖片範圍')
      }
      regions.add(region.name)
    }
  }
  if (totalBytes > FREE_SKELETAL_LIMITS.totalTextureBytes || Object.keys(bundle.pages).length !== pages.size
    || atlas.pages.reduce((sum, page) => sum + page.width * page.height, 0) > FREE_SKELETAL_LIMITS.texturePixels * 2) {
    fail('貼圖總量超限或包含未使用檔案')
  }
  const skins = Array.isArray(json.skins) ? json.skins : Object.entries(json.skins ?? {}).map(([name, attachments]) => ({ name, attachments }))
  if (!skins.length || skins.length > 32)
    fail('皮膚清單不正確')
  let attachments = 0
  const skinNames = new Set()
  const availableAttachments = new Map()
  for (const skin of skins) {
    if (!record(skin) || !plainName(skin.name) || skinNames.has(skin.name) || !record(skin.attachments))
      fail('皮膚名稱重複或格式不正確')
    skinNames.add(skin.name)
    for (const [slotName, values] of Object.entries(skin.attachments)) {
      if (!slotNames.has(slotName) || !record(values))
        fail('皮膚引用不存在的貼圖插槽')
      for (const [name, value] of Object.entries(values)) {
        if (!plainName(name) || ++attachments > 2048)
          fail('皮膚貼圖數量過多或名稱不正確')
        checkAttachment({ ...value, name: value?.path ?? value?.name ?? name }, regions)
        const known = availableAttachments.get(slotName) ?? new Set()
        known.add(name)
        availableAttachments.set(slotName, known)
      }
    }
  }
  for (const slot of json.slots) {
    if (slot.attachment != null && !availableAttachments.get(slot.name)?.has(slot.attachment))
      fail('預設貼圖插槽沒有對應皮膚')
  }
  checkAnimations(json.animations ?? {}, boneNames, slotNames, availableAttachments)
  return { json, atlas, textureNames: atlas.pages.map(page => page.name), totalTextureBytes: totalBytes }
}

export async function validateSkeletalTexture(blob, expectedWidth, expectedHeight) {
  const bytes = new Uint8Array(await blob.slice(0, 24).arrayBuffer())
  const png = bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4E && bytes[3] === 0x47
    && bytes[4] === 0x0D && bytes[5] === 0x0A && bytes[6] === 0x1A && bytes[7] === 0x0A
  if (!png || bytes.length < 24 || bytes[12] !== 0x49 || bytes[13] !== 0x48 || bytes[14] !== 0x44 || bytes[15] !== 0x52)
    fail('此免費格式目前只接受 PNG 貼圖')
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const width = view.getUint32(16)
  const height = view.getUint32(20)
  if (!width || !height || width > 8192 || height > 8192 || width * height > FREE_SKELETAL_LIMITS.texturePixels
    || (expectedWidth !== undefined && width !== expectedWidth) || (expectedHeight !== undefined && height !== expectedHeight)) {
    fail('實際 PNG 尺寸與清單不符或過大')
  }
  return { width, height }
}
