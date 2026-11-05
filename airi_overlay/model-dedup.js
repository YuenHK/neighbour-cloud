// Content identity, never a filename: preserve all original records and files.
const digests = new WeakMap()
export function fileDigest(file) {
  if (!digests.has(file)) {
    digests.set(file, file.arrayBuffer().then(bytes => crypto.subtle.digest('SHA-256', bytes))
      .then(bytes => Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, '0')).join('')))
  }
  return digests.get(file)
}
export async function findSameModel(models, format, file, digest) {
  for (const model of models) {
    if (model.format !== format || model.type !== 'file' || model.file.size !== file.size)
      continue
    try {
      if (await fileDigest(model.file) === digest)
        return model
    }
    catch { /* Preserve an unreadable original; do not merge it. */ }
  }
}
export function mergeModelChoices(rows, selectedId) {
  const groups = new Map()
  for (const row of rows) {
    const key = `${row.format}:${row.sha256 || row.id}`
    const prior = groups.get(key)
    if (!prior) {
      groups.set(key, { ...row, platforms: [row.platform], aliases: [...new Set([row.name, ...(row.aliases || [])])] })
      continue
    }
    prior.platforms = [...new Set([...prior.platforms, row.platform])]
    prior.aliases = [...new Set([...prior.aliases, row.name, ...(row.aliases || [])])]
    prior.gallery ||= row.gallery
    prior.vroid ||= row.vroid
    prior.reviewed ||= row.reviewed
    prior.sharedId ||= row.sharedId
    prior.image ||= row.image
    if (row.id === selectedId) {
      prior.id = row.id
      prior.model = row.model || prior.model
    }
    else {
      prior.model ||= row.model
    }
  }
  return [...groups.values()]
}
