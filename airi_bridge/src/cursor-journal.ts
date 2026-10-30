import { createHash, randomUUID } from 'node:crypto'
import * as fs from 'node:fs'
import { dirname, join, resolve } from 'node:path'

export interface StreamPosition { stream_id: string, cursor: number }
const MAX_BYTES = 1024 * 1024
const MAX_RECORDS = 4096
const ZERO = '0'.repeat(64)
const digest = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex')

function position(value: StreamPosition): void {
  if (!value || typeof value.stream_id !== 'string' || !/^[0-9a-f]{32}$/.test(value.stream_id)
    || !Number.isSafeInteger(value.cursor) || value.cursor < 0)
    throw new Error('Invalid stream position')
}

function regular(path: string, directory = false) {
  const stat = fs.lstatSync(path)
  if (stat.isSymbolicLink() || (directory ? !stat.isDirectory() : !stat.isFile()))
    throw new Error('Cursor journal requires regular local paths')
}

// A bounded append-only LOCAL TRANSPORT cursor, not a receiver ACK/outbox.
// Single writer, no stale-lock reclaim, no automatic truncation or generation reset.
export function openCursorJournal(directory: string) {
  const root = resolve(directory)
  for (let current = root;; current = dirname(current)) {
    regular(current, true)
    if (dirname(current) === current) break
  }
  const lockPath = join(root, 'cursor-writer.lock')
  const journalPath = join(root, 'cursor-journal.ndjson')
  const owner = randomUUID()
  const lock = fs.openSync(lockPath, 'wx') // Existing/stale lock is an explicit recovery gate.
  let file: number | undefined
  let closed = false, poisoned = false
  let saved: StreamPosition | undefined
  let chain = ZERO, bytes = 0, records = 0
  function close() {
    if (closed) return
    closed = true
    try { if (file !== undefined) fs.closeSync(file) }
    finally {
      fs.closeSync(lock)
      // Never unlink a lock whose identity changed or whose contents are unexpected.
      try {
        regular(lockPath)
        if (fs.statSync(lockPath).size === owner.length && fs.readFileSync(lockPath, 'utf8') === owner)
          fs.unlinkSync(lockPath)
      }
      catch { /* Preserve unexpected files for explicit recovery; do not delete them. */ }
    }
  }
  try {
    fs.writeFileSync(lock, owner)
    fs.fsyncSync(lock)
    if (fs.existsSync(journalPath)) {
      regular(journalPath)
      file = fs.openSync(journalPath, 'r+')
      const buffer = Buffer.alloc(MAX_BYTES + 1)
      bytes = fs.readSync(file, buffer, 0, buffer.length, 0)
      if (bytes > MAX_BYTES) throw new Error('Cursor journal size budget exceeded')
      if (!bytes) throw new Error('Empty existing cursor journal; explicit recovery required')
      const raw = buffer.subarray(0, bytes).toString('utf8')
      if (raw && (!raw.endsWith('\n') || !Buffer.from(raw, 'utf8').equals(buffer.subarray(0, bytes))))
        throw new Error('Partial or invalid UTF-8 cursor journal; explicit recovery required')
      for (const line of raw ? raw.slice(0, -1).split('\n') : []) {
        if (!line || Buffer.byteLength(line) > 512 || ++records > MAX_RECORDS)
          throw new Error('Cursor journal record budget exceeded')
        const row = JSON.parse(line)
        if (!row || typeof row !== 'object'
          || Object.keys(row).sort().join(',') !== 'cursor,previous_sha256,sha256,stream_id,v')
          throw new Error('Invalid cursor journal schema')
        position(row)
        const base = { v: 1, stream_id: row.stream_id, cursor: row.cursor, previous_sha256: chain }
        if (row.v !== 1 || row.previous_sha256 !== chain || row.sha256 !== digest(base)
          || (saved && (saved.stream_id !== row.stream_id || saved.cursor >= row.cursor)))
          throw new Error('Cursor journal chain or position mismatch; explicit recovery required')
        saved = { stream_id: row.stream_id, cursor: row.cursor }
        chain = row.sha256
      }
    }
    else {
      file = fs.openSync(journalPath, 'wx+')
    }
  }
  catch (error) { close(); throw error }

  return {
    state(): StreamPosition | undefined { return saved ? { ...saved } : undefined },
    resume(remote: StreamPosition): { mode: 'first-tail' | 'resume-local-transport', cursor: number } {
      if (closed || poisoned) throw new Error('Cursor journal unavailable')
      position(remote)
      if (saved && (saved.stream_id !== remote.stream_id || saved.cursor > remote.cursor))
        throw new Error('Stream changed or cursor ahead; explicit recovery required')
      return { mode: saved ? 'resume-local-transport' : 'first-tail', cursor: saved?.cursor ?? remote.cursor }
    },
    append(next: StreamPosition): boolean {
      if (closed || poisoned || file === undefined) throw new Error('Cursor journal unavailable')
      position(next)
      if (saved && (saved.stream_id !== next.stream_id || saved.cursor > next.cursor))
        throw new Error('Stream changed or cursor rewound; explicit recovery required')
      if (saved?.cursor === next.cursor) return false
      const base = { v: 1, stream_id: next.stream_id, cursor: next.cursor, previous_sha256: chain }
      const hash = digest(base)
      const raw = Buffer.from(JSON.stringify({ ...base, sha256: hash }) + '\n')
      if (records >= MAX_RECORDS || bytes + raw.length > MAX_BYTES)
        throw new Error('Cursor journal full; explicit rotation required')
      try {
        if (fs.fstatSync(file).size !== bytes) throw new Error('Cursor journal changed externally')
        if (fs.writeSync(file, raw, 0, raw.length, bytes) !== raw.length)
          throw new Error('Partial cursor journal write')
        fs.fsyncSync(file)
      }
      catch { poisoned = true; throw new Error('Cursor journal write failed; stop and recover explicitly') }
      saved = { ...next }
      chain = hash
      records++
      bytes += raw.length
      return true
    },
    close,
  }
}
