import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace

import pytest
import test_cloud_bootstrap

from deploy.cloud.backup_store import DAY, BackupStore
from deploy.cloud.bootstrap import open_services
from deploy.cloud.maintenance import CloudMaintenance, MaintenanceGate
from deploy.cloud.operations import Operations
from deploy.cloud.operations import migrate as migrate_operations

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
KEY = test_cloud_bootstrap.KEY


def test_gate_drains_live_requests_and_shielded_background_before_any_snapshot():
    async def scenario():
        gate = MaintenanceGate()
        assert await gate.enter() is False
        gate.blocked = False
        assert await gate.enter() is True
        pending = asyncio.get_running_loop().create_future()
        entered = asyncio.Event()

        async def maintenance():
            async with gate.exclusive(lambda: [pending]) as fence:
                assert fence()
                entered.set()
                assert await gate.enter() is False

        task = asyncio.create_task(maintenance())
        await asyncio.sleep(0)
        assert gate.blocked and not entered.is_set()
        await gate.leave()
        await asyncio.sleep(0)
        assert not entered.is_set()  # Late ASR quota reservation still running.
        pending.set_result(None)
        await task
        assert entered.is_set() and await gate.enter()
        await gate.leave()

    asyncio.run(scenario())


def test_gate_never_runs_two_maintenance_writers_and_stays_closed_after_failure():
    async def scenario():
        gate = MaintenanceGate()
        running, maximum = 0, 0

        async def writer():
            nonlocal running, maximum
            async with gate.exclusive(list):
                running += 1
                maximum = max(maximum, running)
                await asyncio.sleep(0)
                running -= 1

        await asyncio.gather(writer(), writer())
        assert maximum == 1
        with pytest.raises(ValueError):
            async with gate.exclusive(list):
                raise ValueError('synthetic backup failure')
        assert await gate.enter() is False

    asyncio.run(scenario())


def test_cancelling_maintenance_waits_for_its_sql_worker_and_never_reopens_requests():
    async def scenario():
        gate = MaintenanceGate()
        started, release = threading.Event(), threading.Event()

        def run(fence):
            assert fence()
            started.set()
            assert release.wait(3)

        job = SimpleNamespace(gate=gate, run_once=run)
        task = asyncio.create_task(CloudMaintenance.cycle(job, list))
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert await gate.enter() is False and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.stopping and gate.blocked and await gate.enter() is False

    asyncio.run(scenario())


def test_daily_snapshot_retention_backup_scrub_and_original_quota_memory_survive(seeded, tmp_path):
    profile = seeded[0]
    backup_path = tmp_path / 'durable-backup.sqlite3'
    with closing(sqlite3.connect(backup_path)) as db:
        BackupStore(db, KEY, initialize=True)
    with open_services(profile, signing_key_loader=lambda: KEY) as services:
        cases, events, photos = services.cases.db, services.events._connection, services.photos.db
        case_id = cases.execute('SELECT id FROM service_cases').fetchone()[0]
        with closing(profile.connect(services.estate.path)) as estate:
            migrate_operations(estate)
            operations = Operations(estate, KEY)
            operations.put('resident-case-photo-v1', case_id, {'sealed': 'SYNTHETIC-CASE-PHOTO-CIPHERTEXT'})
            operations.put('vroid-library', case_id, {'must_survive': True})
        with cases:
            cases.execute('CREATE TABLE IF NOT EXISTS case_privacy_expiry(id TEXT PRIMARY KEY,erased_at_ms INTEGER NOT NULL)')
        with photos:
            photos.execute('CREATE TABLE native_evidence_blobs(key TEXT PRIMARY KEY,digest TEXT,content BLOB)')
            photos.execute('CREATE TABLE native_evidence_bindings(event_id TEXT,key TEXT)')
            photos.execute('CREATE TABLE native_evidence_missing(event_id TEXT,key TEXT)')
            photos.execute('INSERT INTO native_evidence_blobs VALUES(?,?,?)', ('events/public-blurred.jpg', 'x', b'SYNTHETIC-PRIVATE-LEGACY'))
            photos.execute('INSERT INTO native_evidence_bindings VALUES(?,?)', ('synthetic-event', 'events/public-blurred.jpg'))
        job = CloudMaintenance(services, profile, lambda: sqlite3.connect(backup_path), KEY,
                               scratch_root=tmp_path, now=lambda: 100 * DAY)
        # The existing stage ledger mentions a different erased event; preserve
        # it and the original usage amounts rather than seeding fresh state.
        first = job.run_once(lambda: True)
        assert first['backups']['retained_sets'] == 1 and first['backups']['last_backup_ms'] == 100 * DAY
        assert job.run_once(lambda: True)['backups']['retained_sets'] == 1
        with cases:
            cases.execute("UPDATE service_cases SET status='resolved',updated_at_ms=?", (9 * DAY,))
        with events:
            events.execute("UPDATE events SET status='resolved',evidence=?", ('events/public-blurred.jpg',))
            events.execute('INSERT INTO event_completion VALUES(?,?,0)', ('synthetic-event', 9 * DAY))
        job.now = lambda: 101 * DAY
        result = job.run_once(lambda: True)
        assert result['new_erasure_intents'] == 2 and result['backups']['retained_sets'] == 2
        assert cases.execute('SELECT message FROM service_cases').fetchone()[0] == '已按保存期限清除'
        assert json.loads(events.execute('SELECT details_json FROM events').fetchone()[0])['retention_erased'] is True
        assert photos.execute('SELECT COUNT(*) FROM native_evidence_blobs').fetchone()[0] == 0
        assert len(services.memory.items()) == 1
        with services.scope(), closing(profile.connect(profile.settings_root / 'cloud-usage.sqlite3')) as usage:
            assert usage.execute('SELECT amount FROM usage WHERE meter=?', ('azure_tts_characters',)).fetchone()[0] == 123
        with closing(sqlite3.connect(backup_path)) as db:
            backups = BackupStore(db, KEY)
            for (identity,) in db.execute('SELECT id FROM cloud_backup_sets').fetchall():
                archive = backups.download(identity, tmp_path / ('restored-' + identity))
                with closing(sqlite3.connect(archive['files']['cases'])) as recovered:
                    assert recovered.execute('SELECT message FROM service_cases').fetchone()[0] == '已按保存期限清除'
                with closing(sqlite3.connect(archive['files']['photos'])) as recovered:
                    assert recovered.execute('SELECT COUNT(*) FROM native_evidence_blobs').fetchone()[0] == 0
                with closing(sqlite3.connect(archive['files']['estate'])) as recovered:
                    assert recovered.execute('SELECT COUNT(*) FROM cloud_operations WHERE namespace=?', ('resident-case-photo-v1',)).fetchone()[0] == 0
                    assert recovered.execute('SELECT COUNT(*) FROM cloud_operations WHERE namespace=?', ('vroid-library',)).fetchone()[0] == 1
        with closing(profile.connect(services.estate.path)) as estate:
            assert estate.execute('SELECT COUNT(*) FROM cloud_operations WHERE namespace=?', ('resident-case-photo-v1',)).fetchone()[0] == 0
        assert job.public_status()['backup_cleanup_verified'] is True


def test_missing_backup_store_and_unfenced_source_do_not_silently_initialize(seeded, tmp_path):
    profile = seeded[0]
    with open_services(profile, signing_key_loader=lambda: KEY) as services:
        path = tmp_path / 'empty-not-authority.sqlite3'
        job = CloudMaintenance(services, profile, lambda: sqlite3.connect(path), KEY, scratch_root=tmp_path)
        with pytest.raises(ValueError, match='writer_fence'):
            job.run_once(lambda: False)
        assert not path.exists()
        with pytest.raises(ValueError, match='requires_exact_initialization'):
            job.run_once(lambda: True)
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT 1 FROM sqlite_master').fetchone() is None
