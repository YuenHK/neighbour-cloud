import json

import pytest

from edge_hub.cloud_primary import assert_native_writes_allowed, cloud_primary


def marker(tmp_path, **changes):
    info = {'format': 'neighbour-cloud-primary-v1', 'phase': 'preparing',
            'origin': 'https://neighbour-example.onrender.com', 'release_id': 'a' * 32, **changes}
    runtime = tmp_path / '.runtime'
    runtime.mkdir(exist_ok=True)
    path = runtime / 'cloud-primary.json'
    path.write_text(json.dumps(info), encoding='utf-8')
    return path, info


def test_absent_marker_keeps_original_native_mode_without_creating_files(tmp_path):
    assert cloud_primary(tmp_path) is None
    assert assert_native_writes_allowed(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('phase', ['preparing', 'cloud'])
def test_both_cutover_and_active_cloud_block_native_writers_without_changing_data(tmp_path, phase):
    path, expected = marker(tmp_path, phase=phase)
    original = path.read_bytes()
    assert cloud_primary(tmp_path) == expected
    with pytest.raises(RuntimeError, match='use_cloud_service'):
        assert_native_writes_allowed(tmp_path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('change', [{'phase': 'unknown'}, {'format': 'old'}, {'origin': 'http://localhost'},
                                  {'origin': 'https://onrender.com.evil.example'}, {'release_id': ''}])
def test_invalid_marker_never_silently_falls_back_to_native(change, tmp_path):
    marker(tmp_path, **change)
    with pytest.raises(RuntimeError, match='requires_review'):
        assert_native_writes_allowed(tmp_path)


def test_corrupt_json_and_directory_marker_keep_native_writers_fenced(tmp_path):
    path, _ = marker(tmp_path)
    path.write_text('not json')
    with pytest.raises(RuntimeError, match='requires_review'):
        cloud_primary(tmp_path)
    path.unlink()
    path.mkdir()
    with pytest.raises(RuntimeError, match='requires_review'):
        cloud_primary(tmp_path)
