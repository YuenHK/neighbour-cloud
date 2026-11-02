import hashlib
import io
from pathlib import Path

import pytest

from edge_hub.events import EventStore
from tools import check_event_backup_recovery as recovery


@pytest.mark.parametrize('extra', [0, 1])
def test_hash_has_actual_byte_cap_and_fixed_size_reads(tmp_path, monkeypatch, extra):
    limit = 1024 * 1024 + 17
    raw = b'x' * (limit + extra)
    sizes = []

    class Reader(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            assert 0 < size <= 1024 * 1024
            return super().read(size)

    monkeypatch.setattr(recovery, 'MAX_BYTES', limit)
    monkeypatch.setattr(Path, 'open', lambda *a, **k: Reader(raw))
    if extra:
        with pytest.raises(ValueError, match='byte budget'):
            recovery.source_sha256(tmp_path / 'fixture', lambda: None)
    else:
        assert recovery.source_sha256(tmp_path / 'fixture', lambda: None) == hashlib.sha256(raw).hexdigest()
    assert sizes == ([1024 * 1024, 18] if extra else [1024 * 1024, 18, 1])


def test_hash_checks_deadline_between_chunks_and_after_eof(tmp_path):
    path = tmp_path / 'fixture'
    path.write_bytes(b'x' * (1024 * 1024 + 1))
    calls = []
    recovery.source_sha256(path, lambda: calls.append(True))
    assert len(calls) == 4


def test_initial_hash_is_inside_drill_deadline_before_temporary_restore(tmp_path, monkeypatch):
    path = tmp_path / 'offline.sqlite3'
    EventStore(path).close()
    raw = path.read_bytes()
    ticks = iter([0., 31.])
    monkeypatch.setattr(recovery.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(recovery.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: pytest.fail('must expire before creating restore'))
    with pytest.raises(TimeoutError, match='deadline'):
        recovery.check(path, hashlib.sha256(raw).hexdigest())
    assert path.read_bytes() == raw


def test_entire_drill_never_uses_whole_file_reads(tmp_path, monkeypatch):
    path = tmp_path / 'offline.sqlite3'
    EventStore(path).close()
    raw = path.read_bytes()
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('whole-file read forbidden'))
    report = recovery.check(path, hashlib.sha256(raw).hexdigest())
    assert report['source_sha256_unchanged'] is True


def test_final_source_hash_cannot_report_success_after_deadline(tmp_path, monkeypatch):
    path = tmp_path / 'offline.sqlite3'
    EventStore(path).close()
    raw = path.read_bytes()
    clock, calls = [0.], []
    monkeypatch.setattr(recovery.time, 'monotonic', lambda: clock[0])
    original = recovery.source_sha256

    def hash_source(source, progress):
        calls.append(True)
        if len(calls) == 2:
            clock[0] = 31.
        return original(source, progress)

    monkeypatch.setattr(recovery, 'source_sha256', hash_source)
    with pytest.raises(TimeoutError, match='deadline'):
        recovery.check(path, hashlib.sha256(raw).hexdigest())
    assert len(calls) == 2 and path.read_bytes() == raw
