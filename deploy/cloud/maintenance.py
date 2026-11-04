"""Coordinated cloud retention/backups; explicit assembly only, no auto start.

The async gate belongs to ONE service instance. It drains requests and tracked
background ASR before the maintenance writer runs. It is not a distributed
lease: formal cutover/deploy must still prove no second native/cloud writer.
"""
import asyncio
import sqlite3
import tempfile
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path
from uuid import uuid4

from deploy.cloud.backup_store import DAY, ROLES, BackupStore
from deploy.cloud.bootstrap import CloudServices
from deploy.cloud.database_profile import ROLE_FILES, DatabaseProfile
from deploy.cloud.retention_restore import reconcile
from deploy.cloud.sql_snapshot import snapshot


class MaintenanceGate:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.writer = asyncio.Lock()
        self.active = 0
        self.blocked = True  # Cold boot must check expiry before first use.
        self.stopping = False

    async def enter(self):
        async with self.condition:
            if self.blocked or self.stopping:
                return False
            self.active += 1
            return True

    async def leave(self):
        async with self.condition:
            if self.active <= 0:
                raise RuntimeError('cloud_request_gate_unbalanced')
            self.active -= 1
            self.condition.notify_all()

    def fenced(self):
        return self.blocked and self.active == 0

    @asynccontextmanager
    async def exclusive(self, pending_tasks):
        async with self.writer:
            async with self.condition:
                self.blocked = True
                await self.condition.wait_for(lambda: self.active == 0)
            # Shielded transcription can outlive its HTTP caller. Its quota
            # reserve must finish before the eight-store consistent snapshot.
            tasks = [task for task in pending_tasks() if not task.done()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            success = False
            try:
                yield self.fenced
                success = True
            finally:
                async with self.condition:
                    self.blocked = not success or self.stopping
                    self.condition.notify_all()


class CloudMaintenance:
    def __init__(self, services, profile, backup_connect, signing_key, *, scratch_root, now=None):
        if (not isinstance(services, CloudServices) or services.closed or not isinstance(profile, DatabaseProfile)
                or not callable(backup_connect) or (now is not None and not callable(now))):
            raise ValueError('explicit_cloud_maintenance_configuration_required')
        root = Path(scratch_root).absolute()
        if not root.is_dir() or any(item.is_symlink() for item in (root, *root.parents)):
            raise ValueError('private_cloud_maintenance_scratch_required')
        self.services, self.profile, self.backup_connect, self.key = services, profile, backup_connect, signing_key
        self.root, self.now = root, now or (lambda: int(time.time() * 1000))
        self.gate = MaintenanceGate()
        self.scheduled = False  # Set only by the explicit service lifecycle.
        self.state = {'last_run_ms': None, 'last_success': None, 'last_error': None,
                      'backups': {'last_success': None, 'last_backup_ms': None, 'retained_sets': 0}}

    def _path(self, role):
        area, filename = ROLE_FILES[role]
        return (self.profile.runtime_root if area == 'runtime' else self.profile.settings_root) / filename

    def run_once(self, writer_fence):
        if not callable(writer_fence) or writer_fence() is not True:
            raise ValueError('live_request_and_background_writer_fence_required')
        stamp = self.now()
        cutoff = stamp - 90 * DAY
        services = self.services
        ledger = services.ledger
        with services.scope(), closing(self.backup_connect()) as backup_db:
            backups = BackupStore(backup_db, self.key)  # Never initialize an empty backup DB at boot.
            records = ledger.records(ledger.checkpoint())
            done_cases = {row['target'] for row in records if row['kind'] == 'case'}
            done_events = {row['target'] for row in records if row['kind'] == 'event'}
            due = []
            rows = services.cases.db.execute("SELECT c.id,c.revision FROM service_cases c WHERE c.status='resolved' "
                'AND c.updated_at_ms<=? AND NOT EXISTS (SELECT 1 FROM case_privacy_expiry x WHERE x.id=c.id) '
                'ORDER BY c.id LIMIT 500', (cutoff,)).fetchall()
            for row in rows:
                if row[0] not in done_cases:
                    due.append({'kind': 'case', 'target': row[0], 'revision': row[1], 'erased_ms': stamp})
            rows = services.events._connection.execute('SELECT e.id FROM events e JOIN event_completion c ON c.event_id=e.id '
                "WHERE e.status IN ('resolved','false_positive') AND c.completed_at_ms<=? "
                "AND COALESCE(json_extract(e.details_json,'$.retention_erased'),0)!=1 ORDER BY e.id LIMIT 500", (cutoff,)).fetchall()
            for row in rows:
                if row[0] not in done_events:
                    # Native events have no integer review revision. This is the
                    # first immutable erasure intent, not a fabricated update.
                    due.append({'kind': 'event', 'target': row[0], 'revision': 1, 'erased_ms': stamp})
            if due:
                ledger.append(due)  # Commit intent BEFORE changing any private data.
            head = ledger.checkpoint()
            records = ledger.records(head)
            if writer_fence() is not True:
                raise ValueError('cloud_maintenance_writer_fence_lost')
            # Reapplying old intents is intentional after a partial/unknown
            # commit: never use a fresh empty ledger or revive completed data.
            for role, db in (('cases', services.cases.db), ('events', services.events._connection), ('photos', services.photos.db)):
                if db.in_transaction:
                    raise ValueError('cloud_maintenance_requires_idle_stores')
                if role == 'cases':
                    applied = {row[0] for row in db.execute('SELECT id FROM case_privacy_expiry')}
                elif role == 'events':
                    applied = {row[0] for row in db.execute("SELECT id FROM events WHERE json_extract(details_json,'$.retention_erased')=1")}
                else:
                    applied = {row[0] for row in db.execute('SELECT event_id FROM cloud_erased_events')}
                selected = [row for row in records if row['kind'] == ('case' if role == 'cases' else 'event')
                            and row['target'] not in applied]
                if not selected:
                    continue
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    reconcile(db, role, selected)
            existing = backup_db.execute("SELECT id FROM cloud_backup_sets WHERE status='ready' ORDER BY created_ms").fetchall()
            # Case-photo ciphertext lives in the existing estate extension table.
            # Reapply all independent case-erasure intents even after partial work.
            with closing(self.profile.connect(self._path('estate').as_uri() + '?mode=rw', uri=True, timeout=10)) as estate, estate:
                estate.execute('BEGIN IMMEDIATE')
                reconcile(estate, 'estate', records)
            for row in existing:
                backups.reconcile_erasure(row[0], ledger=ledger, scratch_root=self.root, now_ms=stamp,
                                           writer_fence=writer_fence)
            more_cases = services.cases.db.execute("SELECT 1 FROM service_cases c WHERE c.status='resolved' "
                'AND c.updated_at_ms<=? AND NOT EXISTS (SELECT 1 FROM case_privacy_expiry x WHERE x.id=c.id) LIMIT 1',
                (cutoff,)).fetchone()
            more_events = services.events._connection.execute('SELECT 1 FROM events e JOIN event_completion c ON c.event_id=e.id '
                "WHERE e.status IN ('resolved','false_positive') AND c.completed_at_ms<=? "
                "AND COALESCE(json_extract(e.details_json,'$.retention_erased'),0)!=1 LIMIT 1", (cutoff,)).fetchone()
            if more_cases or more_events:
                # Keep admission closed while the next bounded batch drains a
                # large offline backlog; never expose the remaining expired rows.
                raise ValueError('retention_backlog_needs_next_bounded_batch')
            summary = backups.status()
            if summary['pending']:
                raise ValueError('pending_cloud_backup_requires_reconciliation')
            latest = summary['last_completed_ms']
            if latest is not None and latest > stamp:
                raise ValueError('future_cloud_backup_requires_clock_review')
            if latest is None or latest // DAY < stamp // DAY:
                with tempfile.TemporaryDirectory(prefix='neighbour-daily-backup-', dir=self.root) as directory:
                    files = {}
                    for role in sorted(ROLES):
                        if writer_fence() is not True or ledger.checkpoint() != head:
                            raise ValueError('cloud_maintenance_writer_fence_lost')
                        output = Path(directory) / ROLE_FILES[role][1]
                        with closing(self.profile.connect(self._path(role).as_uri() + '?mode=ro', uri=True, timeout=10)) as source:
                            snapshot(source, output, timeout=120)
                        files[role] = output
                    if writer_fence() is not True or ledger.checkpoint() != head:
                        raise ValueError('cloud_maintenance_writer_fence_lost')
                    backups.publish(uuid4().hex, files, created_ms=stamp, ledger_checkpoint=head,
                                    source_fence_verified=True)
                backups.rotate(now_ms=stamp)
                summary = backups.status()
            if writer_fence() is not True or ledger.checkpoint() != head:
                raise ValueError('cloud_maintenance_writer_fence_lost')
            result = {'last_run_ms': stamp, 'last_success': True, 'last_error': None,
                      'retention_days': 90, 'new_erasure_intents': len(due), 'ledger_sequence': head['seq'],
                      'backups': {'last_success': True, 'last_backup_ms': summary['last_completed_ms'],
                                  'retained_sets': summary['completed'], 'includes_patrol_photos': True,
                                  'includes_keys_or_robot_control': False, 'automatic_restore': False}}
            self.state = result
            return result

    async def cycle(self, pending_tasks, after=None):
        async with self.gate.exclusive(pending_tasks) as fence:
            worker = asyncio.create_task(asyncio.to_thread(self.run_once, fence))
            try:
                result = await asyncio.shield(worker)
                if after is not None:
                    await after()
                return result
            except asyncio.CancelledError:
                self.gate.stopping = True
                # Do not reopen requests while a cancelled to_thread is still
                # copying/committing. Await its own bounded DB operations.
                try:
                    await worker
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    pass
                raise
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                self.state = {**self.state, 'last_run_ms': self.now(), 'last_success': False,
                              'last_error': type(error).__name__}
                raise

    def public_status(self):
        return {'retention_days': 90, 'clock': 'completion_time',
                'automatic_deletion_enabled': self.scheduled and not self.gate.stopping,
                'backup_cleanup_verified': self.state['last_success'] is True,
                'maintenance': {key: value for key, value in self.state.items() if key != 'backups'},
                'backups': dict(self.state['backups']), 'excluded': ['long_term_memories', 'MB842', 'robot_safety_and_audit'],
                'notice': '完成後90日清除個案私人欄位及巡查相片，同步處理平台管理的雲端備份，保留個案編號。'
                          '明確記憶及機體安全紀錄保留；不包括原Notebook、離線搬機包及手動匯出。'}
