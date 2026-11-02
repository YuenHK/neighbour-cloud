from pathlib import Path

import numpy as np
import pytest

from edge_hub.vision import PrivacyEvidenceWriter


def save(root, name='evt-new-blurred.jpg'):
    return PrivacyEvidenceWriter(root).save(
        np.zeros((20, 20, 3), np.uint8), [], Path('data/events') / name,
        privacy_check_passed=True,
    )


def test_existing_evidence_is_never_overwritten(tmp_path):
    path = tmp_path / 'data/events/evt-new-blurred.jpg'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'historical evidence must remain')
    with pytest.raises(FileExistsError):
        save(tmp_path)
    assert path.read_bytes() == b'historical evidence must remain'


def test_encoding_failure_does_not_create_file(tmp_path, monkeypatch):
    monkeypatch.setattr('edge_hub.vision.cv2.imencode', lambda *a: (False, None))
    with pytest.raises(OSError, match='encode'):
        save(tmp_path)
    assert not (tmp_path / 'data/events/evt-new-blurred.jpg').exists()


@pytest.mark.parametrize('name', ['evt:stream-blurred.jpg', 'evt?bad-blurred.jpg', 'evt\x01-blurred.jpg'])
def test_unsafe_windows_filename_is_rejected(tmp_path, name):
    with pytest.raises(ValueError, match='filename'):
        save(tmp_path, name)
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('link_check', ['is_symlink', 'is_junction'])
def test_linked_parent_is_rejected_without_writing_outside(tmp_path, monkeypatch, link_check):
    data = tmp_path / 'data'
    data.mkdir()
    # Deterministic on Windows without requiring symlink-creation privileges.
    original = getattr(Path, link_check)
    monkeypatch.setattr(Path, link_check, lambda path: path == data or original(path))
    with pytest.raises(ValueError, match='linked'):
        save(tmp_path)
    assert not (data / 'events').exists()


def test_resolved_parent_outside_project_is_rejected(tmp_path, monkeypatch):
    original = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda path, *a, **k:
                        tmp_path.parent if path == tmp_path / 'data' else original(path, *a, **k))
    with pytest.raises(ValueError, match='escapes'):
        save(tmp_path)
    assert not (tmp_path / 'data').exists()


def test_concurrent_same_name_writers_cannot_overwrite(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import cv2

    barrier = Barrier(2)
    original = cv2.imencode
    def encode(*args):
        barrier.wait(timeout=5)
        return original(*args)
    monkeypatch.setattr('edge_hub.vision.cv2.imencode', encode)
    def attempt():
        try:
            save(tmp_path)
            return 'created'
        except FileExistsError:
            return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ['created', 'refused']
    assert len(list((tmp_path / 'data/events').iterdir())) == 1
