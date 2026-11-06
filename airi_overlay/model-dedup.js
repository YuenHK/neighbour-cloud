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
function admissionTime(value) {
  return Number.isSafeInteger(value) && value > 0 && value <= 8640000000000000 ? value : 0
}
export function newestModelChoices(rows) {
  // Stable ties preserve the catalogue's own order. Never mutate its records,
  // use a filename as a date, or manufacture freshness from page-load time.
  return rows.slice().sort((a, b) => admissionTime(b.addedAt) - admissionTime(a.addedAt))
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
    const addedAt = Math.max(admissionTime(prior.addedAt), admissionTime(row.addedAt))
    if (addedAt)
      prior.addedAt = addedAt
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
