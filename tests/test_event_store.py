from pathlib import Path

import pytest
from pydantic import ValidationError

from edge_hub.events import Event, EventStore


def sample_event(event_id: str = "evt-1", evidence: str = "events/evt-1-blurred.jpg") -> Event:
    return Event(
        id=event_id,
        type="litter_detected",
        zone="A1",
        at_ms=10,
        severity="notice",
        evidence=evidence,
    )


def test_sqlite_event_store_survives_reopen(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    EventStore(database).add(sample_event())

    reopened = EventStore(database)

    assert reopened.all() == [sample_event()]


def test_event_store_tracks_operator_status_and_stats() -> None:
    store = EventStore()
    store.add(sample_event())

    updated = store.update_status("evt-1", "confirmed")

    assert updated is not None and updated.status == "confirmed"
    assert store.stats() == {
        "pending": 0,
        "confirmed": 1,
        "false_positive": 0,
        "resolved": 0,
        "total": 1,
    }


def test_listener_failure_does_not_reverse_commit_or_skip_other_listeners(caplog):
    store = EventStore()
    received = []

    def broken(_):
        raise RuntimeError('secret-do-not-log')

    store.subscribe(broken)
    store.subscribe(received.append)
    try:
        assert store.add(sample_event()) == sample_event()
        assert store.latest_cursor() == 1 and store.stats()['total'] == 1
        assert received == [sample_event()]
        assert 'notification failed' in caplog.text
        assert 'secret-do-not-log' not in caplog.text
    finally:
        store.close()


@pytest.mark.parametrize(
    "unsafe_path",
    ["events/evt-1-original.jpg", "raw/evt-1-blurred.jpg", "events/../raw-blurred.jpg", "C:\\raw.jpg"],
)
def test_event_rejects_non_blurred_or_unsafe_evidence(unsafe_path: str) -> None:
    with pytest.raises(ValidationError):
        sample_event(evidence=unsafe_path)
