import json
import sqlite3
from contextlib import closing

import pytest

from edge_hub.case_retention import expire_cases
from edge_hub.service_backup import DAY, NAMES, ServiceBackups, recover_to_new_directory, verify
from edge_hub.service_desk import ResidentCase, ReviewCase, ServiceDeskStore


def populate(root):
    root.mkdir()
    for name in NAMES:
        with closing(sqlite3.connect(root/name)) as db, db:
            db.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY,text TEXT)')
            db.execute("INSERT INTO sample VALUES(1,'synthetic')")


def test_daily_backup_verified_recovery_no_overwrite_and_rotates_only_owned_sets(tmp_path):
    root = tmp_path/'runtime'
    populate(root)
    clock = [1700000000000]
    backups = ServiceBackups(root, now=lambda: clock[0])
    backups.tick()
    assert backups.state['last_success']
    sets = list(backups.root.iterdir())
    assert len(sets) == 1 and verify(sets[0], root)['retention_adjusted_files'] == 0
    assert recover_to_new_directory(sets[0], tmp_path/'recovery', root)['production_replaced'] is False
    with closing(sqlite3.connect(tmp_path/'recovery'/NAMES[0])) as db:
        assert db.execute('SELECT text FROM sample').fetchone()[0] == 'synthetic'
    with pytest.raises(ValueError, match='must_be_new'):
        recover_to_new_directory(sets[0], root, root)
    backups.tick()
    assert list(backups.root.iterdir()) == sets
    for _ in range(8):
        clock[0] += DAY
        backups.tick()
        assert backups.state['last_success']
    assert len(list(backups.root.iterdir())) == 7
    assert (root/NAMES[0]).exists()


def test_backup_hash_damage_is_not_accepted_or_rotated(tmp_path):
    root = tmp_path/'runtime'
    populate(root)
    backups = ServiceBackups(root)
    backups.tick()
    first = next(backups.root.iterdir())
    with closing(sqlite3.connect(first/NAMES[0])) as db, db:
        db.execute("UPDATE sample SET text='unexpected corruption'")
    backups.tick()
    assert not backups.state['last_success'] and first.exists()
    with pytest.raises(ValueError, match='hash_mismatch'):
        recover_to_new_directory(first, tmp_path/'should-not-exist', root)
    assert not (tmp_path/'should-not-exist').exists()


def test_backup_missing_source_is_visible_not_success(tmp_path):
    root = tmp_path/'runtime'
    populate(root)
    (root/NAMES[-1]).unlink()
    backups = ServiceBackups(root)
    backups.tick()
    assert not backups.state['last_success'] and backups.state['last_backup_ms'] is None
    backups.tick()
    assert not backups.state['last_success']


def test_low_disk_never_removes_prior_backup_or_starts_partial_copy(tmp_path, monkeypatch):
    from collections import namedtuple
    root = tmp_path/'runtime'
    populate(root)
    clock = [1700000000000]
    backups = ServiceBackups(root, now=lambda: clock[0])
    backups.tick()
    first = next(backups.root.iterdir())
    clock[0] += DAY
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr('edge_hub.service_backup.shutil.disk_usage', lambda _: usage(100, 99, 1))
    backups.tick()
    assert not backups.state['last_success']
    assert list(backups.root.iterdir()) == [first]


def test_retention_changes_snapshot_and_recovery_never_brings_back_expired_contact(tmp_path):
    root = tmp_path/'runtime'
    populate(root)
    cases = ServiceDeskStore(root/NAMES[0])
    try:
        item = cases.create(ResidentCase(submission_id='a'*32, kind='general', message='synthetic private', contact='synthetic contact', confirmed=True))
        cases.review(item['id'], ReviewCase(status='resolved', expected_revision=1))
        with cases.db:
            cases.db.execute('UPDATE service_cases SET updated_at_ms=1')
        backups = ServiceBackups(root)
        backups.tick()
        first = next(backups.root.iterdir())
        assert expire_cases(cases, root, now_ms=91*DAY)['erased_cases'] == 1
        assert verify(first, root)['retention_adjusted_files'] == 1
        recover_to_new_directory(first, tmp_path/'clean-recovery', root)
        with closing(sqlite3.connect(tmp_path/'clean-recovery'/NAMES[0])) as db:
            assert db.execute('SELECT contact FROM service_cases').fetchone()[0] == ''
        backups.tick()
        assert backups.state['last_success']
    finally:
        cases.close()


def test_manifest_cannot_select_other_files(tmp_path):
    root = tmp_path/'runtime'
    populate(root)
    backups = ServiceBackups(root)
    backups.tick()
    first = next(backups.root.iterdir())
    path = first/'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['files']['../operator-key.txt'] = 'fake'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='invalid_backup_manifest'):
        verify(first, root)


def test_crash_before_recovery_completion_cannot_be_shown_as_verified(tmp_path):
    root = tmp_path/'runtime'
    populate(root)
    backups = ServiceBackups(root)
    backups.tick()
    first = next(backups.root.iterdir())
    path = first/'manifest.json'
    metadata = json.loads(path.read_text())
    metadata['recovery_verified'] = False
    path.write_text(json.dumps(metadata))
    restarted = ServiceBackups(root)
    restarted.tick()
    assert restarted.state['last_success'] is False
    with pytest.raises(ValueError, match='invalid_backup_manifest'):
        recover_to_new_directory(first, tmp_path/'invalid-recovery', root)


def test_maintenance_runs_backup_after_retention_and_failed_retention_skips_it(tmp_path, monkeypatch):
    from edge_hub.events import EventStore
    from edge_hub.governance import AccessJournal, GovernanceMaintenance
    root = tmp_path/'runtime'
    populate(root)
    cases, events = ServiceDeskStore(root/NAMES[0]), EventStore(root/NAMES[1])
    journal = AccessJournal(root/NAMES[-1])
    backups = ServiceBackups(root)
    maintenance = GovernanceMaintenance(cases, events, root, tmp_path/'data', journal, backups)
    try:
        maintenance.run_once()
        assert maintenance.state['last_success'] and backups.state['last_success']
        before = dict(backups.state)
        def fail(*_):
            raise ValueError('synthetic retention failure')
        monkeypatch.setattr('edge_hub.case_retention.expire_cases', fail)
        maintenance.run_once()
        assert maintenance.state['last_success'] is False and backups.state == before
    finally:
        cases.close(); events.close()


def test_symlink_source_never_copied(tmp_path):
    root = tmp_path/'runtime'
    populate(root)
    path = root/NAMES[0]
    original = root/'original.sqlite3'
    path.rename(original)
    try:
        path.symlink_to(original)
    except OSError:
        pytest.skip('host does not grant symlink creation')
    backups = ServiceBackups(root)
    backups.tick()
    assert backups.state['last_success'] is False
