import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest
import test_cloud_database_profile

from deploy.cloud.runtime_storage import RuntimeStorage
from deploy.cloud.state_store import StateStore
from edge_hub.cloud_allowance import CloudAllowance

prepared = test_cloud_database_profile.prepared
VOICE = 'azure-voice-control.json'
STOP = 'cloudflare-gemma-quota-stop.json'
COOLDOWN = 'cloudflare-gemma-cooldown.json'
OLD = {VOICE: {'paused': False}, STOP: {'until': '2027-01-01T00:00:00+00:00'},
       COOLDOWN: {'until': '2027-01-01T00:00:00+00:00', 'reason': 'network'}}
LIVE = {VOICE: {'paused': True}, STOP: {'until': '2027-01-02T00:00:00+00:00'},
        COOLDOWN: {'until': '2026-12-31T20:00:00-08:00', 'reason': 'rate_limit'}}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def stores(prepared, tmp_path):
    profile, _, settings, remote, _ = prepared
    old = tmp_path / 'closed-controls.sqlite3'
    with closing(sqlite3.connect(old)) as db:
        StateStore(db, initialize=True).seed(copy.deepcopy(OLD))
    db = profile.connect(settings / 'cloud-control.sqlite3')
    controls = StateStore(db, initialize=True)
    controls.seed(copy.deepcopy(LIVE))
    CloudAllowance(settings / 'cloud-usage.sqlite3', connection_factory=profile.connect).reserve({'azure_tts_characters': 123})
    try:
        yield old, RuntimeStorage(profile, controls), remote, tmp_path
    finally:
        db.close()


def restored(path):
    with closing(sqlite3.connect(path)) as db:
        store = StateStore(db)
        return {name: store.read(name) for name in OLD}


def test_restore_preserves_pause_and_longest_timezone_aware_blocks_without_changing_sources(stores):
    from deploy.cloud.control_restore import recover_controls

    old, storage, remote, root = stores
    before = {path.name: digest(path) for path in [old, *remote.glob('*.sqlite3')]}
    target = root / 'new-controls.sqlite3'
    result = recover_controls(old, target, expected_sha256=digest(old), storage=storage)
    values = restored(target)
    assert values[VOICE]['paused'] is True
    assert values[STOP] == LIVE[STOP]
    assert datetime.fromisoformat(values[COOLDOWN]['until']) == datetime.fromisoformat(LIVE[COOLDOWN]['until'])
    assert values[COOLDOWN]['reason'] == 'rate_limit'
    assert result['prepared'] is True and result['cutover_ready'] is False
    assert result['automatic_unpause'] is False and result['production_replaced'] is False
    assert result['sha256'] == digest(target)
    assert {path.name: digest(path) for path in [old, *remote.glob('*.sqlite3')]} == before


def test_older_pause_is_not_silently_unpaused_even_if_live_was_resumed(stores):
    from deploy.cloud.control_restore import recover_controls

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db, db:
        db.execute('UPDATE cloud_state SET payload=? WHERE name=?', (json.dumps({'paused': True}), VOICE))
    storage.controls.write(VOICE, {'paused': False})
    target = root / 'conservative.sqlite3'
    result = recover_controls(old, target, expected_sha256=digest(old), storage=storage)
    assert restored(target)[VOICE]['paused'] is True
    assert storage.controls.read(VOICE)['paused'] is False  # Live preference was not changed.
    assert result['requires_operator_review'] is True


def test_expired_blocks_are_not_restarted_by_restore_time(stores):
    from deploy.cloud.control_restore import recover_controls

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db, db:
        for name in (STOP, COOLDOWN):
            value = {'until': '2000-01-01T00:00:00+00:00'}
            if name == COOLDOWN:
                value['reason'] = 'network'
            db.execute('UPDATE cloud_state SET payload=? WHERE name=?', (json.dumps(value), name))
    # Simulate an imported historical live state; no production flag is touched.
    with storage.controls.db:
        for name in (STOP, COOLDOWN):
            value = {'until': '2001-01-01T00:00:00+00:00'}
            if name == COOLDOWN:
                value['reason'] = 'network'
            storage.controls.db.execute('UPDATE cloud_state SET payload=? WHERE name=?', (json.dumps(value), name))
    target = root / 'expired.sqlite3'
    recover_controls(old, target, expected_sha256=digest(old), storage=storage)
    assert restored(target)[STOP]['until'].startswith('2001-')
    assert restored(target)[COOLDOWN]['until'].startswith('2001-')


@pytest.mark.parametrize('source', ['backup', 'live'])
@pytest.mark.parametrize('damage', ['missing', 'bool', 'naive', 'revision'])
def test_missing_or_invalid_control_cannot_default_to_enabled(stores, source, damage):
    from deploy.cloud.control_restore import ControlRestoreError, recover_controls

    old, storage, _, root = stores
    connection = sqlite3.connect(old) if source == 'backup' else storage.connect(storage.settings_root / 'cloud-control.sqlite3')
    with closing(connection) as db, db:
        if damage == 'missing':
            db.execute('DELETE FROM cloud_state WHERE name=?', (VOICE,))
        elif damage == 'bool':
            db.execute('UPDATE cloud_state SET payload=? WHERE name=?', ('{"paused":"false"}', VOICE))
        elif damage == 'naive':
            db.execute('UPDATE cloud_state SET payload=? WHERE name=?', ('{"until":"2027-01-01T00:00:00"}', STOP))
        else:
            db.execute('UPDATE cloud_state SET revision=0 WHERE name=?', (VOICE,))
    target = root / 'must-not-exist.sqlite3'
    with pytest.raises(ControlRestoreError):
        recover_controls(old, target, expected_sha256=digest(old), storage=storage)
    assert not target.exists()


def test_changed_live_controls_prevent_a_prepared_receipt(stores, monkeypatch):
    from deploy.cloud import control_restore

    old, storage, _, root = stores
    original = control_restore.snapshot

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        storage.controls.write(VOICE, {'paused': False})
        return result

    monkeypatch.setattr(control_restore, 'snapshot', changing)
    with pytest.raises(control_restore.ControlRestoreError, match='live_changed'):
        control_restore.recover_controls(old, root / 'incomplete.sqlite3', expected_sha256=digest(old), storage=storage)


def test_hash_sidecar_and_existing_output_fail_without_overwrite(stores):
    from deploy.cloud.control_restore import ControlRestoreError, recover_controls

    old, storage, _, root = stores
    target = root / 'keep.bin'
    target.write_bytes(b'KEEP')
    with pytest.raises(ControlRestoreError):
        recover_controls(old, target, expected_sha256=digest(old), storage=storage)
    assert target.read_bytes() == b'KEEP'
    with pytest.raises(ControlRestoreError):
        recover_controls(old, root / 'bad-hash.sqlite3', expected_sha256='0' * 64, storage=storage)
    assert not (root / 'bad-hash.sqlite3').exists()
    (root / (old.name + '-wal')).write_bytes(b'SYNTHETIC-WRITER')
    with pytest.raises(ControlRestoreError):
        recover_controls(old, root / 'active.sqlite3', expected_sha256=digest(old), storage=storage)
    assert not (root / 'active.sqlite3').exists()


def test_last_valid_revision_is_preserved_without_overflow_on_the_next_restore(stores):
    from deploy.cloud.control_restore import ControlRestoreError, recover_controls

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db, db:
        db.execute('UPDATE cloud_state SET revision=? WHERE name=?', (2**63 - 2, VOICE))
    target = root / 'last-revision.sqlite3'
    recover_controls(old, target, expected_sha256=digest(old), storage=storage)
    with closing(sqlite3.connect(target)) as db:
        assert db.execute('SELECT revision FROM cloud_state WHERE name=?', (VOICE,)).fetchone()[0] == 2**63 - 1
    next_target = root / 'overflow.sqlite3'
    with pytest.raises(ControlRestoreError):
        recover_controls(target, next_target, expected_sha256=digest(target), storage=storage)
    assert not next_target.exists()


def test_schema_version_change_and_total_deadline_stop_before_output(stores):
    from deploy.cloud.control_restore import ControlRestoreError, recover_controls

    old, storage, _, root = stores
    ticks = [0]

    def clock():
        ticks[0] += 1
        return ticks[0]

    with pytest.raises(ControlRestoreError, match='deadline'):
        recover_controls(old, root / 'timeout.sqlite3', expected_sha256=digest(old),
                         storage=storage, timeout=.5, clock=clock)
    assert not (root / 'timeout.sqlite3').exists()
    with closing(sqlite3.connect(old)) as db:
        db.execute('PRAGMA user_version=1')
    with pytest.raises(ControlRestoreError, match='schema_version'):
        recover_controls(old, root / 'version.sqlite3', expected_sha256=digest(old), storage=storage)
    assert not (root / 'version.sqlite3').exists()


def test_changed_backup_and_equal_deadline_rate_limit_are_not_weakened(stores, monkeypatch):
    from deploy.cloud import control_restore

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db, db:
        db.execute('UPDATE cloud_state SET payload=? WHERE name=?',
            (json.dumps({'until': '2027-01-01T04:00:00+00:00', 'reason': 'network'}), COOLDOWN))
    target = root / 'equal-time.sqlite3'
    control_restore.recover_controls(old, target, expected_sha256=digest(old), storage=storage)
    assert restored(target)[COOLDOWN]['reason'] == 'rate_limit'
    original = control_restore.snapshot

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        with closing(sqlite3.connect(old)) as db, db:
            db.execute('UPDATE cloud_state SET revision=revision+1 WHERE name=?', (VOICE,))
        return result

    monkeypatch.setattr(control_restore, 'snapshot', changing)
    with pytest.raises(control_restore.ControlRestoreError, match='backup_changed'):
        control_restore.recover_controls(old, root / 'changed.sqlite3', expected_sha256=digest(old), storage=storage)


def test_late_wal_writer_is_detected_even_when_control_backup_main_hash_is_unchanged(stores, monkeypatch):
    from deploy.cloud import control_restore

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    before = digest(old)
    assert not old.with_name(old.name + '-wal').exists()
    original, writers = control_restore.snapshot, []

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        writer = sqlite3.connect(old)
        writers.append(writer)
        writer.execute('UPDATE cloud_state SET revision=revision+1 WHERE name=?', (VOICE,))
        writer.commit()
        assert old.with_name(old.name + '-wal').stat().st_size > 0
        assert digest(old) == before
        return result

    monkeypatch.setattr(control_restore, 'snapshot', changing)
    try:
        with pytest.raises(control_restore.ControlRestoreError, match='backup_changed'):
            control_restore.recover_controls(old, root / 'late-wal.sqlite3', expected_sha256=before, storage=storage)
    finally:
        for writer in writers:
            writer.close()


def test_closed_wal_header_control_backup_does_not_gain_sidecars(stores):
    from deploy.cloud.control_restore import recover_controls

    old, storage, _, root = stores
    with closing(sqlite3.connect(old)) as db:
        db.execute('PRAGMA journal_mode=WAL')
    before = digest(old)
    result = recover_controls(old, root / 'closed-wal.sqlite3', expected_sha256=before, storage=storage)
    assert result['prepared'] and digest(old) == before
    assert not any(old.with_name(old.name + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))
