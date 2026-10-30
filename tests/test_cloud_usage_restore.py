import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest
import test_cloud_database_profile

from deploy.cloud.runtime_storage import RuntimeStorage
from deploy.cloud.state_store import StateStore
from edge_hub.cloud_allowance import AllowanceExceeded, CloudAllowance

prepared = test_cloud_database_profile.prepared
STAMP = datetime(2026, 10, 29, tzinfo=UTC)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def amounts(path):
    with closing(sqlite3.connect(path)) as db:
        return {(meter, period): amount for meter, period, amount in db.execute('SELECT * FROM usage')}


@pytest.fixture
def stores(prepared, tmp_path):
    profile, _, settings, remote, _ = prepared
    old = tmp_path / 'closed-old-usage.sqlite3'
    backup = CloudAllowance(old)
    backup.reserve({'azure_tts_characters': 3, 'cloudflare_gemma_neuron_reservations': 20}, now=STAMP)
    backup.reserve({'azure_tts_characters': 8}, now=datetime(2026, 9, 1, tzinfo=UTC))
    live = CloudAllowance(settings / 'cloud-usage.sqlite3', connection_factory=profile.connect)
    live.reserve({'azure_tts_characters': 11, 'cloudflare_gemma_neuron_reservations': 13}, now=STAMP)
    live.reserve({'cloudflare_gemma_neuron_reservations': 2}, now=datetime(2026, 10, 28, tzinfo=UTC))
    db = profile.connect(settings / 'cloud-control.sqlite3')
    controls = StateStore(db, initialize=True)
    controls.seed({'azure-voice-control.json': {'paused': True},
        'cloudflare-gemma-quota-stop.json': {'until': '2027-01-01T00:00:00+00:00'},
        'cloudflare-gemma-cooldown.json': {'until': '2027-01-01T00:00:00+00:00', 'reason': 'rate_limit'}})
    try:
        yield old, RuntimeStorage(profile, controls), remote, tmp_path
    finally:
        db.close()


def test_restore_never_lowers_any_counter_and_preserves_history_sources_and_pause(stores):
    from deploy.cloud.usage_restore import recover_usage

    old, storage, remote, root = stores
    before = {path.name: digest(path) for path in [old, *remote.glob('*.sqlite3')]}
    result = recover_usage(old, root / 'new-recovery.sqlite3', expected_sha256=digest(old), storage=storage)
    assert result['prepared'] is True and result['cutover_ready'] is False
    assert result['official_balance_verified'] is False and result['production_replaced'] is False
    assert amounts(root / 'new-recovery.sqlite3') == {
        ('azure_tts_characters', '2026-10'): 11, ('azure_tts_characters', '2026-09'): 8,
        ('cloudflare_gemma_neuron_reservations', '2026-10-29'): 20,
        ('cloudflare_gemma_neuron_reservations', '2026-10-28'): 2}
    assert {path.name: digest(path) for path in [old, *remote.glob('*.sqlite3')]} == before
    assert storage.controls.read('azure-voice-control.json')['paused'] is True
    assert storage.controls.read('cloudflare-gemma-quota-stop.json')['until'].startswith('2027')
    assert not (storage.settings_root / 'cloud-usage.sqlite3').exists()
    assert result['sha256'] == digest(root / 'new-recovery.sqlite3')


def test_already_over_guard_usage_is_preserved_and_new_requests_remain_blocked(stores):
    from deploy.cloud.usage_restore import recover_usage

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db, db:
        db.execute("UPDATE usage SET amount=500000 WHERE meter='azure_tts_characters' AND period='2026-10'")
    target = root / 'over-limit.sqlite3'
    recover_usage(old, target, expected_sha256=digest(old), storage=storage)
    assert amounts(target)[('azure_tts_characters', '2026-10')] == 500000
    with pytest.raises(AllowanceExceeded):
        CloudAllowance(target).reserve({'azure_tts_characters': 1}, now=STAMP)


def test_missing_live_usage_never_creates_empty_ledger_or_output(stores):
    from deploy.cloud.usage_restore import UsageRestoreError, recover_usage

    old, storage, _, root = stores
    with closing(storage.connect(storage.settings_root / 'cloud-usage.sqlite3')) as db, db:
        db.execute('DROP TABLE usage')
    target = root / 'must-not-exist.sqlite3'
    with pytest.raises(UsageRestoreError):
        recover_usage(old, target, expected_sha256=digest(old), storage=storage)
    assert not target.exists()
    assert not (storage.settings_root / 'cloud-usage.sqlite3').exists()


@pytest.mark.parametrize('damage', ['negative', 'unknown_meter', 'invalid_period', 'wrong_interval'])
def test_corrupt_or_unreviewed_usage_is_not_silently_dropped(stores, damage):
    from deploy.cloud.usage_restore import UsageRestoreError, recover_usage

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db, db:
        column, value = {'negative': ('amount', -1), 'unknown_meter': ('meter', 'unreviewed'),
                         'invalid_period': ('period', '2026-13'),
                         'wrong_interval': ('period', '2026-10-29')}[damage]
        db.execute(f'UPDATE usage SET {column}=? WHERE meter=? AND period=?',
                   (value, 'azure_tts_characters', '2026-10'))
    target = root / 'invalid.sqlite3'
    with pytest.raises(UsageRestoreError):
        recover_usage(old, target, expected_sha256=digest(old), storage=storage)
    assert not target.exists()


def test_existing_destination_bad_hash_and_sidecar_are_never_overwritten(stores):
    from deploy.cloud.usage_restore import UsageRestoreError, recover_usage

    old, storage, _, root = stores
    existing = root / 'keep.txt'
    existing.write_text('KEEP')
    with pytest.raises(UsageRestoreError):
        recover_usage(old, existing, expected_sha256=digest(old), storage=storage)
    assert existing.read_text() == 'KEEP'
    for bad_hash in ('0' * 64, 'invalid'):
        with pytest.raises(UsageRestoreError):
            recover_usage(old, root / 'bad-hash.sqlite3', expected_sha256=bad_hash, storage=storage)
    assert not (root / 'bad-hash.sqlite3').exists()
    sidecar = root / (old.name + '-wal')
    sidecar.write_bytes(b'SYNTHETIC-ACTIVE-WRITER')
    with pytest.raises(UsageRestoreError):
        recover_usage(old, root / 'active.sqlite3', expected_sha256=digest(old), storage=storage)
    assert not (root / 'active.sqlite3').exists()


def test_live_change_during_preparation_cannot_issue_cutover_receipt(stores, monkeypatch):
    from deploy.cloud import usage_restore

    old, storage, _, root = stores
    original = usage_restore.snapshot

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        with closing(storage.connect(storage.settings_root / 'cloud-usage.sqlite3')) as db, db:
            db.execute("UPDATE usage SET amount=amount+1 WHERE meter='azure_tts_characters'")
        return result

    monkeypatch.setattr(usage_restore, 'snapshot', changing)
    with pytest.raises(usage_restore.UsageRestoreError, match='live_changed'):
        usage_restore.recover_usage(old, root / 'incomplete.sqlite3', expected_sha256=digest(old), storage=storage)


def test_failed_live_connection_is_closed_and_does_not_fall_back_to_files(stores, monkeypatch):
    from deploy.cloud.usage_restore import UsageRestoreError, recover_usage

    old, storage, _, root = stores
    original = storage.profile.connect
    handles = []

    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        handles.append(db)
        return db

    monkeypatch.setattr(storage.profile, 'connect', connect)
    # An unexpected schema is a real read failure, not an absent zero counter.
    with closing(original(storage.settings_root / 'cloud-usage.sqlite3')) as db, db:
        db.execute('ALTER TABLE usage ADD COLUMN unreviewed TEXT')
    with pytest.raises(UsageRestoreError):
        recover_usage(old, root / 'unavailable.sqlite3', expected_sha256=digest(old), storage=storage)
    assert handles
    for db in handles:
        with pytest.raises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
    assert not (root / 'unavailable.sqlite3').exists()


def test_changed_backup_during_preparation_cannot_issue_receipt(stores, monkeypatch):
    from deploy.cloud import usage_restore

    old, storage, _, root = stores
    original = usage_restore.snapshot

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        with closing(sqlite3.connect(old)) as db, db:
            db.execute("UPDATE usage SET amount=amount+1 WHERE meter='azure_tts_characters'")
        return result

    monkeypatch.setattr(usage_restore, 'snapshot', changing)
    with pytest.raises(usage_restore.UsageRestoreError, match='backup_changed'):
        usage_restore.recover_usage(old, root / 'incomplete.sqlite3', expected_sha256=digest(old), storage=storage)


def test_schema_version_mismatch_and_union_budget_require_review(stores, monkeypatch):
    from deploy.cloud import usage_restore

    old, storage, _, root = stores
    monkeypatch.setattr(usage_restore, 'MAX_RECORDS', 3)
    with pytest.raises(usage_restore.UsageRestoreError, match='record_budget'):
        usage_restore.recover_usage(old, root / 'too-many.sqlite3', expected_sha256=digest(old), storage=storage)
    assert not (root / 'too-many.sqlite3').exists()
    with closing(sqlite3.connect(old)) as db:
        db.execute('PRAGMA user_version=1')
    with pytest.raises(usage_restore.UsageRestoreError, match='schema_version'):
        usage_restore.recover_usage(old, root / 'old-version.sqlite3', expected_sha256=digest(old), storage=storage)
    assert not (root / 'old-version.sqlite3').exists()


def test_corrupt_live_counter_is_not_assumed_to_be_zero(stores):
    from deploy.cloud.usage_restore import UsageRestoreError, recover_usage

    old, storage, _, root = stores
    with closing(storage.connect(storage.settings_root / 'cloud-usage.sqlite3')) as db, db:
        db.execute("UPDATE usage SET amount=-1 WHERE meter='azure_tts_characters'")
    with pytest.raises(UsageRestoreError):
        recover_usage(old, root / 'bad-live.sqlite3', expected_sha256=digest(old), storage=storage)
    assert not (root / 'bad-live.sqlite3').exists()


def test_total_budget_closes_live_read_before_creating_output(stores):
    from deploy.cloud.usage_restore import UsageRestoreError, recover_usage

    old, storage, _, root = stores
    ticks = [0]

    def clock():
        ticks[0] += 1
        return ticks[0]

    with pytest.raises(UsageRestoreError, match='deadline'):
        recover_usage(old, root / 'timeout.sqlite3', expected_sha256=digest(old),
                      storage=storage, timeout=.5, clock=clock)
    assert not (root / 'timeout.sqlite3').exists()


def test_late_wal_writer_is_detected_even_when_backup_main_hash_does_not_change(stores, monkeypatch):
    from deploy.cloud import usage_restore

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    before = digest(old)
    assert not old.with_name(old.name + '-wal').exists()
    original, writers = usage_restore.snapshot, []

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        writer = sqlite3.connect(old)
        writers.append(writer)
        writer.execute("UPDATE usage SET amount=amount+1 WHERE meter='azure_tts_characters'")
        writer.commit()
        assert old.with_name(old.name + '-wal').stat().st_size > 0
        assert digest(old) == before
        return result

    monkeypatch.setattr(usage_restore, 'snapshot', changing)
    try:
        with pytest.raises(usage_restore.UsageRestoreError, match='backup_changed'):
            usage_restore.recover_usage(old, root / 'late-wal.sqlite3', expected_sha256=before, storage=storage)
    finally:
        for writer in writers:
            writer.close()


def test_closed_wal_header_usage_backup_remains_readable_without_input_sidecars(stores):
    from deploy.cloud.usage_restore import recover_usage

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db:
        db.execute('PRAGMA journal_mode=WAL')
    before = digest(old)
    result = recover_usage(old, root / 'closed-wal.sqlite3', expected_sha256=before, storage=storage)
    assert result['prepared'] and digest(old) == before
    assert not any(old.with_name(old.name + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))
