import { afterEach, describe, expect, it } from 'vitest'
import { appendFileSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { openCursorJournal } from '../src/cursor-journal.js'

const roots: string[] = []
const directory = () => { const root = mkdtempSync(join(tmpdir(), 'zhiwei-cursor-journal-')); roots.push(root); return root }
const id = 'a'.repeat(32)
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }) })

describe('local transport cursor journal, never a delivery ACK', () => {
  it('initializes from tail once and resumes the saved cursor after reopening', () => {
    const root = directory()
    let journal = openCursorJournal(root)
    expect(journal.resume({ stream_id: id, cursor: 50 })).toEqual({ mode: 'first-tail', cursor: 50 })
    expect(journal.state()).toBeUndefined()
    journal.append({ stream_id: id, cursor: 50 })
    journal.append({ stream_id: id, cursor: 60 })
    expect(journal.append({ stream_id: id, cursor: 60 })).toBe(false)
    journal.close()
    journal = openCursorJournal(root)
    try {
      expect(journal.resume({ stream_id: id, cursor: 70 })).toEqual({ mode: 'resume-local-transport', cursor: 60 })
      expect(readFileSync(join(root, 'cursor-journal.ndjson'), 'utf8').trim().split('\n')).toHaveLength(2)
    }
    finally { journal.close() }
  })

  it('blocks a second writer without deleting another owner lock', () => {
    const root = directory(), journal = openCursorJournal(root)
    try {
      const lock = readFileSync(join(root, 'cursor-writer.lock'))
      expect(() => openCursorJournal(root)).toThrow()
      expect(readFileSync(join(root, 'cursor-writer.lock'))).toEqual(lock)
    }
    finally { journal.close() }
    expect(existsSync(join(root, 'cursor-writer.lock'))).toBe(false)
  })

  it('refuses stream mismatch, rewind and ahead-of-backup resume without changing the journal', () => {
    const root = directory(), journal = openCursorJournal(root)
    try {
      journal.append({ stream_id: id, cursor: 10 })
      const raw = readFileSync(join(root, 'cursor-journal.ndjson'))
      for (const state of [{ stream_id: 'b'.repeat(32), cursor: 10 }, { stream_id: id, cursor: 9 }]) {
        expect(() => journal.resume(state)).toThrow('explicit recovery')
        expect(() => journal.append(state)).toThrow('explicit recovery')
      }
      expect(readFileSync(join(root, 'cursor-journal.ndjson'))).toEqual(raw)
    }
    finally { journal.close() }
  })

  it('rejects a partial crash tail or edited chain and preserves original bytes', () => {
    for (const suffix of ['{"partial":', 'garbage\n']) {
      const root = directory(), journal = openCursorJournal(root)
      journal.append({ stream_id: id, cursor: 1 }); journal.close()
      appendFileSync(join(root, 'cursor-journal.ndjson'), suffix)
      const raw = readFileSync(join(root, 'cursor-journal.ndjson'))
      expect(() => openCursorJournal(root)).toThrow()
      expect(readFileSync(join(root, 'cursor-journal.ndjson'))).toEqual(raw)
      expect(existsSync(join(root, 'cursor-writer.lock'))).toBe(false)
    }
    const root = directory(), journal = openCursorJournal(root)
    journal.append({ stream_id: id, cursor: 1 }); journal.close()
    const path = join(root, 'cursor-journal.ndjson')
    writeFileSync(path, readFileSync(path, 'utf8').replace('"cursor":1', '"cursor":2'))
    expect(() => openCursorJournal(root)).toThrow('chain')
  })

  it('treats external modification as a poisoned writer, not a reason to overwrite', () => {
    const root = directory(), journal = openCursorJournal(root)
    try {
      journal.append({ stream_id: id, cursor: 1 })
      appendFileSync(join(root, 'cursor-journal.ndjson'), 'unexpected')
      expect(() => journal.append({ stream_id: id, cursor: 2 })).toThrow('write failed')
      expect(() => journal.resume({ stream_id: id, cursor: 3 })).toThrow('unavailable')
    }
    finally { journal.close(); journal.close() }
  })

  it('rejects oversized journals and stale locks without silently recovering either', () => {
    const root = directory()
    writeFileSync(join(root, 'cursor-writer.lock'), 'stale-owner')
    expect(() => openCursorJournal(root)).toThrow()
    expect(readFileSync(join(root, 'cursor-writer.lock'), 'utf8')).toBe('stale-owner')
    const oversized = directory()
    writeFileSync(join(oversized, 'cursor-journal.ndjson'), Buffer.alloc(1024 * 1024 + 1))
    expect(() => openCursorJournal(oversized)).toThrow('size budget')
    const empty = directory()
    writeFileSync(join(empty, 'cursor-journal.ndjson'), '')
    expect(() => openCursorJournal(empty)).toThrow('Empty existing')
  })

  it('rejects invalid positions and returns independent state copies', () => {
    const root = directory(), journal = openCursorJournal(root)
    try {
      for (const cursor of [NaN, -1, 1.1, Infinity, Number.MAX_SAFE_INTEGER + 1])
        expect(() => journal.append({ stream_id: id, cursor })).toThrow('Invalid')
      expect(() => journal.append({ stream_id: 'bad', cursor: 0 })).toThrow('Invalid')
      journal.append({ stream_id: id, cursor: 0 })
      journal.state()!.cursor = 500
      expect(journal.state()!.cursor).toBe(0)
    }
    finally { journal.close() }
  })

  it('never deletes a writer lock whose ownership was changed externally', () => {
    const root = directory(), journal = openCursorJournal(root)
    writeFileSync(join(root, 'cursor-writer.lock'), 'replacement-owner')
    journal.close()
    expect(readFileSync(join(root, 'cursor-writer.lock'), 'utf8')).toBe('replacement-owner')
  })

  it('resumes and advances in a separate normally-exiting Node process', () => {
    const root = directory(), journal = openCursorJournal(root)
    journal.append({ stream_id: id, cursor: 10 }); journal.close()
    const moduleUrl = JSON.stringify(new URL('../src/cursor-journal.ts', import.meta.url).href)
    const child = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e',
      `const {openCursorJournal}=await import(${moduleUrl});
       const journal=openCursorJournal(process.argv[1]);
       const state=journal.resume({stream_id:'${id}',cursor:20});
       journal.append({stream_id:'${id}',cursor:11}); journal.close();
       process.stdout.write(JSON.stringify(state));`, root],
    { encoding: 'utf8', timeout: 10_000, maxBuffer: 4096, windowsHide: true })
    expect(child.error).toBeUndefined()
    expect(child.status).toBe(0)
    expect(JSON.parse(child.stdout)).toEqual({ mode: 'resume-local-transport', cursor: 10 })
    const reopened = openCursorJournal(root)
    try { expect(reopened.state()!.cursor).toBe(11) }
    finally { reopened.close() }
  })

  it('does not silently reclaim the lock after a disposable child exits without cleanup', () => {
    const root = directory()
    const moduleUrl = JSON.stringify(new URL('../src/cursor-journal.ts', import.meta.url).href)
    const child = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e',
      `const {openCursorJournal}=await import(${moduleUrl});
       const journal=openCursorJournal(process.argv[1]);
       journal.append({stream_id:'${id}',cursor:1}); process.exit(73);`, root],
    { encoding: 'utf8', timeout: 10_000, maxBuffer: 4096, windowsHide: true })
    expect(child.error).toBeUndefined()
    expect(child.status).toBe(73)
    const raw = readFileSync(join(root, 'cursor-journal.ndjson'))
    expect(() => openCursorJournal(root)).toThrow()
    expect(readFileSync(join(root, 'cursor-journal.ndjson'))).toEqual(raw)
    expect(existsSync(join(root, 'cursor-writer.lock'))).toBe(true)
  })
})
