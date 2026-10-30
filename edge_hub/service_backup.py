"""Local daily SQLite snapshots, with isolated recovery verification.

No keys, robot safety state or raw photographs are copied. Each DB is a
consistent SQLite snapshot; the five DBs are not one cross-DB transaction.
Never restore over a running service: recovery only writes a NEW directory.
"""
import hashlib
import json
import re
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

NAMES = ('service-desk.sqlite3', 'events.sqlite3', 'estate-information.sqlite3',
         'assistant-memory.sqlite3', 'staff-access.sqlite3')
SCHEMA = 'neighbour-daily-sqlite-v1'
DAY = 86400000


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_file(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('unsafe_backup_path')
    if any(parent.is_symlink() for parent in path.parents if parent != root.parent):
        raise ValueError('unsafe_backup_path')
    return path


def check_sqlite(path):
    deadline = time.monotonic()+15
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('backup_integrity_failed')


def verify(directory, runtime, *, _pending=False):
    directory, runtime = Path(directory).resolve(), Path(runtime).resolve()
    manifest = json.loads(safe_file(directory/'manifest.json', runtime).read_text(encoding='utf-8'))
    if (manifest.get('schema') != SCHEMA or set(manifest.get('files', {})) != set(NAMES)
            or not isinstance(manifest.get('at_ms'), int)
            or (not _pending and manifest.get('recovery_verified') is not True)):
        raise ValueError('invalid_backup_manifest')
    adjusted = 0
    for name, expected in manifest['files'].items():
        path = safe_file(directory/name, runtime)
        current = digest(path)
        # The 90-day cleaner intentionally changes old snapshots too. Accept
        # only a continuous, recorded hash chain, never arbitrary new bytes.
        if current != expected:
            receipts = sorted((runtime/'retention-receipts').glob('*.json'))
            if len(receipts) > 10000:
                raise ValueError('retention_receipts_require_review')
            for receipt in receipts:
                record = json.loads(safe_file(receipt, runtime).read_text(encoding='utf-8'))
                if (record.get('schema') == 'retention-v1'
                        and record.get('backup_relative') == path.relative_to(runtime).as_posix()
                        and record.get('before_sha256') == expected):
                    expected = record.get('after_sha256')
            if current != expected:
                raise ValueError('backup_hash_mismatch')
            adjusted += 1
        check_sqlite(path)
    return {**manifest, 'retention_adjusted_files': adjusted}


def recover_to_new_directory(directory, destination, runtime, *, _pending=False):
    """Offline recovery drill/export. Never writes an existing path or live DB."""
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('recovery_destination_must_be_new')
    verify(directory, runtime, _pending=_pending)
    destination.mkdir(parents=False, exist_ok=False)
    # A partial isolated recovery is left for diagnosis on failure.
    for name in NAMES:
        source = Path(directory)/name
        before = digest(source)
        target = destination/name
        with source.open('rb') as incoming, target.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if before != digest(target) or before != digest(source):
            raise ValueError('backup_changed_during_recovery')
        check_sqlite(target)
    return {'verified_databases': len(NAMES), 'production_replaced': False}


class ServiceBackups:
    def __init__(self, runtime, *, now=None):
        self.runtime = Path(runtime).resolve()
        self.root = self.runtime/'daily-backups'
        self.now = now or (lambda: int(time.time()*1000))
        self.state = {'last_success': None, 'last_checked_ms': None, 'last_backup_ms': None,
                      'last_error': None, 'scope': 'service_databases_only', 'retained_sets': 0}

    def tick(self):
        try:
            self._tick()
        except (OSError, ValueError, sqlite3.Error):
            self.state.update(last_success=False, last_checked_ms=self.now(), last_error='backup_check_failed')

    def _tick(self):
        safe_file(self.root, self.runtime).mkdir(exist_ok=True)
        entries = list(self.root.iterdir())
        if len(entries) > 16:
            raise ValueError('backup_inventory_requires_review')
        sets = []
        for path in entries:
            safe_file(path, self.runtime)
            if not re.fullmatch(r'\d{13}-[a-f0-9]{8}', path.name):
                raise ValueError('unfinished_backup_requires_review')
            metadata = verify(path, self.runtime)
            sets.append((metadata['at_ms'], path))
        sets.sort()
        now = self.now()
        if not sets or now-sets[-1][0] >= DAY:
            sources = [safe_file(self.runtime/name, self.runtime) for name in NAMES]
            if any(not source.is_file() or source.stat().st_size > 128*1024*1024 for source in sources):
                raise ValueError('backup_source_requires_review')
            required = 2*sum(source.stat().st_size for source in sources)+100*1024*1024
            if shutil.disk_usage(self.root).free < required:
                raise ValueError('backup_disk_capacity')
            # A unique directory and exclusive creates never overwrite a prior
            # snapshot. Incomplete writes remain visible and block false success.
            target = self.root/f'{now:013d}-{uuid4().hex[:8]}'
            target.mkdir(exist_ok=False)
            hashes = {}
            for name, source in zip(NAMES, sources, strict=True):
                output = target/name
                deadline = time.monotonic()+20
                def progress(*_, limit=deadline):
                    if time.monotonic() > limit:
                        raise ValueError('backup_deadline')
                with (closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, timeout=2)) as live,
                      closing(sqlite3.connect(output)) as copied):
                    live.backup(copied, pages=128, progress=progress, sleep=.01)
                check_sqlite(output)
                hashes[name] = digest(output)
            metadata = {'schema': SCHEMA, 'at_ms': now, 'files': hashes, 'recovery_verified': False,
                        'excludes': ['photos', 'keys', 'robot_control', 'model_files']}
            with (target/'manifest.json').open('x', encoding='utf-8') as stream:
                json.dump(metadata, stream)
            verify(target, self.runtime, _pending=True)
            # Actually copy and query the copies, then remove ONLY this newly
            # created drill directory after success; never restore live databases.
            drill = self.root/f'drill-{uuid4().hex}'
            recover_to_new_directory(target, drill, self.runtime, _pending=True)
            for name in NAMES:
                (drill/name).unlink()
            drill.rmdir()
            metadata['recovery_verified'] = True
            # The completion marker is published last; a crash before the
            # isolated drill finishes must not report a usable backup.
            pending_manifest = target/'manifest.completed'
            with pending_manifest.open('x', encoding='utf-8') as stream:
                json.dump(metadata, stream)
            pending_manifest.replace(target/'manifest.json')
            sets.append((now, target))
        # Rotate only our fully verified snapshots. No rmtree or external paths.
        for _, old in sets[:-7]:
            if {p.name for p in old.iterdir()} != {*NAMES, 'manifest.json'}:
                raise ValueError('unexpected_backup_files')
            for name in (*NAMES, 'manifest.json'):
                safe_file(old/name, self.runtime).unlink()
            old.rmdir()
        self.state.update(last_success=True, last_checked_ms=now, last_error=None,
                          last_backup_ms=sets[-1][0], retained_sets=min(7, len(sets)))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Copy a verified service backup into a NEW isolated directory; never restore production.')
    parser.add_argument('backup')
    parser.add_argument('destination')
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    print(json.dumps(recover_to_new_directory(args.backup, args.destination, args.runtime)))
