from pathlib import Path

import pytest

from edge_hub.events import Event
from edge_hub.evidence import delete_event_evidence


def event(evidence: str | None) -> Event:
    return Event(
        id="evt-cleanup",
        type="litter_detected",
        zone="A1",
        at_ms=1,
        severity="notice",
        evidence=evidence,
    )


def test_cleanup_deletes_only_referenced_blurred_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "events" / "evt-cleanup-blurred.jpg"
    evidence.parent.mkdir()
    evidence.write_bytes(b"blurred")
    unrelated = tmp_path / "events" / "keep-blurred.jpg"
    unrelated.write_bytes(b"keep")

    deleted = delete_event_evidence([event("events/evt-cleanup-blurred.jpg")], tmp_path)

    assert deleted == 1
    assert not evidence.exists()
    assert unrelated.read_bytes() == b"keep"


def test_cleanup_ignores_missing_evidence_and_text_only_events(tmp_path: Path) -> None:
    assert delete_event_evidence(
        [event("events/missing-blurred.jpg"), event(None)], tmp_path
    ) == 0


def test_shared_evidence_is_deleted_once_and_counted_as_one_file(tmp_path):
    path = tmp_path / 'events' / 'shared-blurred.jpg'
    path.parent.mkdir()
    path.write_bytes(b'fixture')
    assert delete_event_evidence([event('events/shared-blurred.jpg'),
                                  event('events/./shared-blurred.jpg')], tmp_path) == 1
    assert not path.exists()


def test_file_disappearing_after_preflight_does_not_inflate_deleted_count(tmp_path, monkeypatch):
    first, second = tmp_path / 'events' / 'gone-blurred.jpg', tmp_path / 'events' / 'keep-blurred.jpg'
    first.parent.mkdir()
    first.write_bytes(b'fixture')
    second.write_bytes(b'fixture')
    unlink = Path.unlink
    def concurrent_unlink(path, *args, **kwargs):
        if path == first:
            unlink(path)
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', concurrent_unlink)
    assert delete_event_evidence([event('events/gone-blurred.jpg'),
                                  event('events/keep-blurred.jpg')], tmp_path) == 1
    assert not first.exists() and not second.exists()


def test_permission_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    path = tmp_path / 'events' / 'blocked-blurred.jpg'
    path.parent.mkdir()
    path.write_bytes(b'preserve')
    unlink = Path.unlink
    def denied(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError('fixture denial')
        return unlink(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', denied)
    with pytest.raises(PermissionError):
        delete_event_evidence([event('events/blocked-blurred.jpg')], tmp_path)
    assert path.read_bytes() == b'preserve'


def test_all_paths_are_validated_before_any_deletion(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    valid, escape = root / 'events' / 'valid-blurred.jpg', root / 'events' / 'escape-blurred.jpg'
    valid.parent.mkdir(parents=True)
    valid.write_bytes(b'preserve referenced')
    outside = tmp_path / 'outside-blurred.jpg'
    outside.write_bytes(b'preserve outside')
    resolve = Path.resolve
    def redirected(path, *args, **kwargs):
        return outside if path == escape else resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', redirected)
    with pytest.raises(ValueError, match='escapes'):
        delete_event_evidence([event('events/valid-blurred.jpg'),
                               event('events/escape-blurred.jpg')], root)
    assert valid.read_bytes() == b'preserve referenced'
    assert outside.read_bytes() == b'preserve outside'


def test_api_clear_shared_evidence_keeps_orphans_and_cursor_high_water(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    from edge_hub.events import EventStore

    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    shared = tmp_path / 'events' / 'shared-blurred.jpg'
    shared.parent.mkdir()
    shared.write_bytes(b'fixture')
    orphan = shared.parent / 'historical-orphan-blurred.jpg'
    orphan.write_bytes(b'preserve orphan')
    for identifier in ('first', 'second'):
        store.add(event('events/shared-blurred.jpg').model_copy(update={'id': identifier}))
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'EVENT_DATA_ROOT', tmp_path)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'cleanup-fixture-operator')
    try:
        response = TestClient(hub.app, raise_server_exceptions=False).delete(
            '/api/v1/events', headers={'X-Operator-Key': 'cleanup-fixture-operator'})
        assert response.status_code == 200
        assert response.json() == {'deleted': 2, 'deleted_evidence': 1}
        assert store.all() == [] and store.latest_cursor() == 2
        assert not shared.exists() and orphan.read_bytes() == b'preserve orphan'
    finally:
        store.close()
