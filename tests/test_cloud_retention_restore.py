import hashlib
import importlib.util
import io
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from PIL import Image

from deploy.cloud.deletion_ledger import DeletionLedger
from deploy.cloud.retention_restore import recover
from edge_hub.events import Event, EventStore
from edge_hub.service_desk import ResidentCase, ReviewCase, ServiceDeskStore

ROOT = Path(__file__).resolve().parents[1] / 'deploy/cloud'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


photos = load('photo_store')


@pytest.fixture
def ledger():
    db = sqlite3.connect(':memory:')
    journal = DeletionLedger(db, b'k' * 32, initialize=True)
    yield journal
    db.close()


def receipt(target, kind='case'):
    return {'kind': kind, 'target': target, 'revision': 3, 'erased_ms': 2000}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_late_wal_writer_is_detected_even_when_case_backup_main_hash_is_unchanged(tmp_path, ledger, monkeypatch):
    from deploy.cloud import retention_restore

    original = tmp_path / 'closed-cases.sqlite3'
    cases = ServiceDeskStore(original)
    cases.create(ResidentCase(submission_id='c' * 32, kind='water', message='PUBLIC-SYNTHETIC', confirmed=True))
    cases.close()
    with closing(sqlite3.connect(original)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    before = digest(original)
    assert not original.with_name(original.name + '-wal').exists()
    snapshot, writers = retention_restore.snapshot, []

    def changing(*args, **kwargs):
        result = snapshot(*args, **kwargs)
        writer = sqlite3.connect(original)
        writers.append(writer)
        writer.execute('UPDATE service_cases SET note=?', ('LATE-SYNTHETIC-UPDATE',))
        writer.commit()
        assert original.with_name(original.name + '-wal').stat().st_size > 0
        assert digest(original) == before
        return result

    monkeypatch.setattr(retention_restore, 'snapshot', changing)
    try:
        with pytest.raises(ValueError, match='source_changed'):
            retention_restore.recover(original, tmp_path / 'late-wal.sqlite3', expected_sha256=before,
                ledger=ledger, live_checkpoint=ledger.checkpoint(), scope='cases')
    finally:
        for writer in writers:
            writer.close()


def test_closed_wal_header_case_backup_does_not_gain_sidecars(tmp_path, ledger):
    original = tmp_path / 'closed-wal-cases.sqlite3'
    cases = ServiceDeskStore(original)
    cases.create(ResidentCase(submission_id='c' * 32, kind='water', message='PUBLIC-SYNTHETIC', confirmed=True))
    cases.close()
    with closing(sqlite3.connect(original)) as db:
        db.execute('PRAGMA journal_mode=WAL')
    before = digest(original)
    result = recover(original, tmp_path / 'new-cases.sqlite3', expected_sha256=before,
                     ledger=ledger, live_checkpoint=ledger.checkpoint(), scope='cases')
    assert result['ready'] and digest(original) == before
    assert not any(original.with_name(original.name + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


def test_old_unresolved_case_backup_is_scrubbed_without_losing_numbers_other_cases_or_notes(tmp_path, ledger):
    original = tmp_path / 'old.sqlite3'
    store = ServiceDeskStore(original)
    first = store.create(ResidentCase(submission_id='a' * 32, kind='human_support',
                                     location='PRIVATE-UNIT', contact='PRIVATE-CONTACT',
                                     message='PRIVATE-RESIDENT', confirmed=True))
    second = store.create(ResidentCase(submission_id='b' * 32, kind='water',
                                      message='KEEP-UNRELATED', confirmed=True))
    store.review(first['id'], ReviewCase(status='acknowledged', expected_revision=1, note='PRIVATE-STAFF-NOTE'))
    store.close()
    sha = digest(original)
    current = ledger.append([receipt(first['id'])])
    output = tmp_path / 'recovered.sqlite3'
    result = recover(original, output, expected_sha256=sha, ledger=ledger, live_checkpoint=current, scope='cases')
    assert result['ready'] and result['reconciled_records'] == 1
    assert digest(original) == sha
    assert b'PRIVATE-RESIDENT' not in output.read_bytes() and b'PRIVATE-STAFF-NOTE' not in output.read_bytes()
    with sqlite3.connect(output) as db:
        row = db.execute('SELECT message,location,contact,status FROM service_cases WHERE id=?', (first['id'],)).fetchone()
        assert row == ('已按保存期限清除', '', '', 'acknowledged')
        assert db.execute('SELECT message FROM service_cases WHERE id=?', (second['id'],)).fetchone()[0] == 'KEEP-UNRELATED'
    reopened = ServiceDeskStore(output)
    try:
        assert reopened.list()['items'][0]['case_number'] in (1, 2)
        third = reopened.create(ResidentCase(submission_id='c' * 32, kind='water', message='NEW', confirmed=True))
        assert third['case_number'] == 3
    finally:
        reopened.close()


def test_stale_live_checkpoint_and_wrong_source_hash_never_create_destination(tmp_path, ledger):
    original = tmp_path / 'old.sqlite3'
    store = ServiceDeskStore(original)
    store.close()
    old = ledger.checkpoint()
    ledger.append([receipt('synthetic-case')])
    with pytest.raises(ValueError, match='checkpoint_changed'):
        recover(original, tmp_path / 'new', expected_sha256=digest(original), ledger=ledger, live_checkpoint=old, scope='cases')
    assert not (tmp_path / 'new').exists()
    with pytest.raises(ValueError, match='hash_mismatch'):
        recover(original, tmp_path / 'new', expected_sha256='0' * 64, ledger=ledger,
                live_checkpoint=ledger.checkpoint(), scope='cases')
    assert not (tmp_path / 'new').exists()


def test_old_photo_snapshot_cannot_resurrect_erased_event_under_new_key(tmp_path, ledger):
    original = tmp_path / 'old-photos.sqlite3'
    db = sqlite3.connect(original)
    store = photos.PhotoStore(db)
    output = io.BytesIO()
    Image.new('RGB', (16, 16), 'green').save(output, format='JPEG')
    store.put('synthetic', 'event', 'events/synthetic/old.jpg', output.getvalue(), reviewed=True, now_ms=1)
    db.close()
    sha = digest(original)
    current = ledger.append([receipt('synthetic', kind='event')])
    destination = tmp_path / 'recovered-photos.sqlite3'
    recover(original, destination, expected_sha256=sha, ledger=ledger, live_checkpoint=current, scope='photos')
    restored = sqlite3.connect(destination)
    try:
        photo_store = photos.PhotoStore(restored)
        with pytest.raises(KeyError):
            photo_store.get('events/synthetic/old.jpg')
        with pytest.raises(ValueError, match='event_was_erased'):
            photo_store.put('synthetic', 'left', 'events/synthetic/new.jpg', output.getvalue(), reviewed=True, now_ms=3000)
    finally:
        restored.close()


def test_event_metadata_erasure_preserves_unrelated_events_and_stream_identity(tmp_path, ledger):
    original = tmp_path / 'old-events.sqlite3'
    events = EventStore(original)
    events.add(Event(id='synthetic', type='litter_detected', zone='PRIVATE-EVENT-UNIT', at_ms=1,
                     severity='notice', details={'note': 'PRIVATE-EVENT-NOTE'}))
    events.add(Event(id='other', type='litter_detected', zone='KEEP-ZONE', at_ms=2, severity='notice'))
    events.close()
    current = ledger.append([receipt('synthetic', kind='event')])
    restored = tmp_path / 'recovered-events.sqlite3'
    recover(original, restored, expected_sha256=digest(original), ledger=ledger, live_checkpoint=current, scope='events')
    assert b'PRIVATE-EVENT-NOTE' not in restored.read_bytes()
    with sqlite3.connect(restored) as db:
        assert db.execute('SELECT zone FROM events WHERE id=?', ('other',)).fetchone()[0] == 'KEEP-ZONE'
        assert db.execute('SELECT evidence FROM events WHERE id=?', ('synthetic',)).fetchone()[0] is None
        assert db.execute('SELECT stream_id FROM event_stream_metadata').fetchone()[0]


def test_existing_destination_and_mid_recovery_ledger_change_cannot_report_ready(tmp_path, ledger):
    original = tmp_path / 'old.sqlite3'
    store = ServiceDeskStore(original)
    store.close()
    existing = tmp_path / 'existing'
    existing.write_bytes(b'PRESERVE')
    current = ledger.checkpoint()
    with pytest.raises(ValueError, match='must_be_new'):
        recover(original, existing, expected_sha256=digest(original), ledger=ledger, live_checkpoint=current, scope='cases')
    assert existing.read_bytes() == b'PRESERVE'

    class ChangingLedger:
        def records(self, checkpoint):
            return ledger.records(checkpoint)
        def checkpoint(self):
            return ledger.append([receipt('newly-expired')])
    with pytest.raises(ValueError, match='source_changed'):
        recover(original, tmp_path / 'unready', expected_sha256=digest(original), ledger=ChangingLedger(),
                live_checkpoint=current, scope='cases')


def test_managed_host_signing_key_is_loaded_without_key_files(tmp_path, monkeypatch):
    from edge_hub import cloud_host_credentials as credentials

    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'managed-environment')
    monkeypatch.setenv('NEIGHBOUR_SECRET_RETENTION_LEDGER', 'synthetic-signing-key-' + 'k' * 32)
    key = credentials.decrypt_reference(credentials.reference('retention-ledger-key', mode='managed-environment'))
    db = sqlite3.connect(':memory:')
    try:
        live = DeletionLedger(db, key, initialize=True)
        assert live.append([receipt('synthetic')])['seq'] == 1
    finally:
        db.close()
    assert list(tmp_path.iterdir()) == []
