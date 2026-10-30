import hashlib
import json
import sqlite3

import pytest

from deploy.cloud import native_export


@pytest.fixture
def native(tmp_path):
    runtime, settings = tmp_path / 'runtime', tmp_path / 'settings'
    runtime.mkdir()
    settings.mkdir()
    for role, name in native_export.DATABASES.items():
        path = (settings if role == 'usage' else runtime) / name
        with sqlite3.connect(path) as db:
            if role == 'memory':
                db.execute('CREATE TABLE memories(id TEXT PRIMARY KEY,text TEXT,revision INTEGER,updated_ms INTEGER)')
                db.execute('INSERT INTO memories VALUES(?,?,1,1)', ('a' * 32, '公開驗證 MB842，保留。'))
            elif role == 'usage':
                db.execute('CREATE TABLE usage(meter TEXT,period TEXT,amount INTEGER,PRIMARY KEY(meter,period))')
                db.execute('INSERT INTO usage VALUES(?,?,?)', ('azure_tts_characters', '2026-10', 12345))
                db.execute('INSERT INTO usage VALUES(?,?,?)', ('gemini_chat_requests', '2026-09-01', 77))
            else:
                db.execute('CREATE TABLE records(id INTEGER PRIMARY KEY AUTOINCREMENT,content BLOB)')
                db.execute('INSERT INTO records VALUES(8,?)', (b'\x00\x01\xff',))
                db.execute('UPDATE sqlite_sequence SET seq=99 WHERE name=?', ('records',))
    (settings / 'azure-voice-control.json').write_text('{"paused":true}', encoding='utf-8')
    receipts = runtime / 'retention-receipts'
    receipts.mkdir()
    (receipts / '123.json').write_text('{"schema":"retention-v1","expired_record_count":1}', encoding='utf-8')
    (runtime / 'robot-control.sqlite3').write_bytes(b'RETAIN-ORIGINAL-ROBOT-AUDIT')
    return runtime, settings, tmp_path / 'private-export'


def fingerprints(native):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for base in native[:2] for path in base.rglob('*') if path.is_file()}


def test_preview_preserves_all_rows_old_quota_sequence_pause_and_uuid_memory(native):
    before = fingerprints(native)
    result = native_export.prepare(*native)
    assert result['phase'] == 'preview' and not result['cutover_ready']
    assert not result['cross_database_consistent'] and not result['source_fence_verified']
    assert result['controls']['azure-voice-control.json'] == {'paused': True}
    assert result['control_sources']['cloudflare-gemma-cooldown.json'] == {'exists': False}
    assert result['protected_memory_marker_matches'] == 1
    assert result['native_retention_receipts']['123.json']['sha256']
    assert not result['original_cloud_ledger_exists'] and not result['original_cloud_signing_key_exists']
    assert not result['photos_migrated'] and not result['private_data_uploaded']
    assert fingerprints(native) == before
    with sqlite3.connect(native[2] / 'events.sqlite3') as db:
        assert db.execute('SELECT id,content FROM records').fetchall() == [(8, b'\x00\x01\xff')]
        db.execute('INSERT INTO records(content) VALUES(?)', (b'new isolated row',))
        assert db.execute('SELECT MAX(id) FROM records').fetchone()[0] == 100
    with sqlite3.connect(native[2] / 'cloud-usage.sqlite3') as db:
        assert db.execute('SELECT amount FROM usage ORDER BY meter').fetchall() == [(12345,), (77,)]


def test_fenced_export_requires_live_check_and_does_not_claim_cutover(native):
    with pytest.raises(native_export.NativeExportError, match='fence_required'):
        native_export.prepare(*native, phase='fenced')
    assert not native[2].exists()
    with pytest.raises(native_export.NativeExportError, match='not_fenced'):
        native_export.prepare(*native, phase='fenced', writer_fence=lambda: False)
    checks = []
    result = native_export.prepare(*native, phase='fenced', writer_fence=lambda: checks.append(1) or True)
    assert result['source_fence_verified'] and result['cross_database_consistent']
    assert not result['cutover_ready'] and len(checks) >= 8


def test_a_new_native_cooldown_during_export_invalidates_final_copy(native, monkeypatch):
    original = native_export.snapshot

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        (native[1] / 'cloudflare-gemma-cooldown.json').write_text(
            '{"until":"2099-01-01T00:00:00+00:00","reason":"rate_limit"}', encoding='utf-8')
        return result

    monkeypatch.setattr(native_export, 'snapshot', change)
    with pytest.raises(native_export.NativeExportError, match='sources_changed'):
        native_export.prepare(*native, phase='fenced', writer_fence=lambda: True)
    assert (native[2] / 'INCOMPLETE.json').exists()
    assert not (native[2] / 'NATIVE-EXPORT.json').exists()
    assert json.loads((native[1] / 'cloudflare-gemma-cooldown.json').read_text())['reason'] == 'rate_limit'


def test_source_writer_reappearing_leaves_no_acceptance_manifest(native):
    times = [0]

    def fence():
        times[0] += 1
        return times[0] < 4

    with pytest.raises(native_export.NativeExportError, match='not_fenced'):
        native_export.prepare(*native, phase='fenced', writer_fence=fence)
    assert not (native[2] / 'NATIVE-EXPORT.json').exists()


def test_export_never_overwrites_or_uses_a_directory_inside_the_live_runtime(native):
    native[2].mkdir()
    (native[2] / 'preserve.txt').write_text('preserve')
    with pytest.raises(native_export.NativeExportError):
        native_export.prepare(*native)
    with pytest.raises(native_export.NativeExportError):
        native_export.prepare(*native[:2], native[0] / 'export')
    assert (native[2] / 'preserve.txt').read_text() == 'preserve'


@pytest.mark.parametrize('name', ['cloud-control.sqlite3', 'cloud-deletion-ledger.sqlite3', 'retention-ledger-key.dpapi'])
def test_an_existing_original_cloud_adapter_or_signing_key_is_not_replaced(native, name):
    (native[1] / name).write_bytes(b'PRESERVE-EXISTING')
    with pytest.raises(native_export.NativeExportError, match='exact_import'):
        native_export.prepare(*native)
    assert (native[1] / name).read_bytes() == b'PRESERVE-EXISTING'
    assert not native[2].exists()


def test_mb842_is_a_text_marker_not_an_assumed_literal_row_id(native):
    result = native_export.prepare(*native)
    with sqlite3.connect(native[2] / 'assistant-memory.sqlite3') as db:
        assert db.execute('SELECT id FROM memories').fetchone()[0] == 'a' * 32
    assert result['protected_memory_marker_matches'] == 1
