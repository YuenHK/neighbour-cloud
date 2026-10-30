import hashlib

import pytest

from deploy.cloud import closed_backup


@pytest.mark.parametrize('change', ['sidecar', 'main_file'])
def test_final_closed_check_detects_change_during_hash_without_deleting_anything(tmp_path, monkeypatch, change):
    source = tmp_path / 'synthetic.sqlite3'
    source.write_bytes(b'PUBLIC-SYNTHETIC')
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    original = closed_backup.hashlib.file_digest

    def changing(stream, algorithm):
        result = original(stream, algorithm)
        if change == 'sidecar':
            source.with_name(source.name + '-shm').write_bytes(b'PUBLIC-SIDECAR')
        else:
            source.write_bytes(b'PUBLIC-CHANGED-CONTENT')
        return result

    monkeypatch.setattr(closed_backup.hashlib, 'file_digest', changing)
    assert not closed_backup.unchanged_closed_backup(source, expected)
    assert source.exists()
    if change == 'sidecar':
        assert source.with_name(source.name + '-shm').read_bytes() == b'PUBLIC-SIDECAR'
