from pathlib import Path

import pytest

from edge_hub.events import Event, EventStore
from tools.backup_events import backup


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.sqlite3'
    store = EventStore(path)
    store.add(Event(id='fixture', type='robot_fault', zone='test', at_ms=1, severity='notice'))
    store.close()
    return path


def test_destination_resolution_never_follows_output_leaf(source, tmp_path, monkeypatch):
    destination, redirected = tmp_path / 'backup.sqlite3', tmp_path / 'unexpected.sqlite3'
    resolve = Path.resolve
    resolved = []
    def tracked_resolve(path, *args, **kwargs):
        resolved.append(path)
        if path == destination:
            return redirected  # Simulate a leaf redirect; it must never be consulted.
        return resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', tracked_resolve)
    report = backup(source, destination)
    assert destination not in resolved and tmp_path in resolved
    assert destination.is_file() and not redirected.exists()
    assert report['backup'] == str(destination) and report['events'] == 1


@pytest.mark.parametrize('target_exists', [False, True])
def test_output_symlink_is_refused_without_creating_or_changing_target(source, tmp_path,
                                                                      target_exists):
    destination, target = tmp_path / 'link.sqlite3', tmp_path / 'target.sqlite3'
    if target_exists:
        target.write_bytes(b'keep existing target')
    try:
        destination.symlink_to(target)
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows account lacks symbolic-link privilege')
        raise
    with pytest.raises(FileExistsError):
        backup(source, destination)
    assert destination.is_symlink()
    if target_exists:
        assert target.read_bytes() == b'keep existing target'
    else:
        assert not target.exists()


def test_competing_output_created_at_reservation_is_not_overwritten(source, tmp_path, monkeypatch):
    destination = tmp_path / 'backup.sqlite3'
    touch = Path.touch
    def concurrent_touch(path, *args, **kwargs):
        if path == destination:
            path.write_bytes(b'other owner')
        return touch(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'touch', concurrent_touch)
    with pytest.raises(FileExistsError):
        backup(source, destination)
    assert destination.read_bytes() == b'other owner'
    store = EventStore(source)
    try:
        assert store.all()[0].id == 'fixture'
    finally:
        store.close()


def test_empty_existing_output_is_also_preserved(source, tmp_path):
    destination = tmp_path / 'empty.sqlite3'
    destination.touch()
    with pytest.raises(FileExistsError):
        backup(source, destination)
    assert destination.stat().st_size == 0
