import hashlib
import io
import json
import sqlite3

import pytest
from PIL import Image

from deploy.cloud import native_adapters
from deploy.cloud.deletion_ledger import DeletionLedger
from deploy.cloud.native_export import DATABASES, file_identity


@pytest.fixture
def archived(tmp_path):
    export, data = tmp_path / 'private-export', tmp_path / 'native-data'
    export.mkdir()
    (data / 'events').mkdir(parents=True)
    for role, name in DATABASES.items():
        with sqlite3.connect(export / name) as db:
            db.execute('CREATE TABLE marker(value TEXT)')
            db.execute('INSERT INTO marker VALUES(?)', ('PRIVATE-SYNTHETIC-' + role,))
    with sqlite3.connect(export / DATABASES['cases']) as db:
        db.execute('CREATE TABLE service_cases(id TEXT PRIMARY KEY,revision INTEGER)')
        db.execute('CREATE TABLE case_privacy_expiry(id TEXT PRIMARY KEY,erased_at_ms INTEGER)')
        db.execute('INSERT INTO service_cases VALUES(?,5)', ('expired-case',))
        db.execute('INSERT INTO case_privacy_expiry VALUES(?,1234)', ('expired-case',))
    image = io.BytesIO()
    Image.new('RGB', (16, 16), 'green').save(image, format='JPEG')
    (data / 'events/shared-blurred.jpg').write_bytes(image.getvalue())
    with sqlite3.connect(export / DATABASES['events']) as db:
        db.execute('CREATE TABLE events(id TEXT PRIMARY KEY,evidence TEXT,details_json TEXT)')
        db.executemany('INSERT INTO events VALUES(?,?,?)', [
            ('a', 'events/shared-blurred.jpg', '{}'), ('b', 'events/shared-blurred.jpg', '{}'),
            ('missing', 'events/old-blurred.jpg', '{}'),
            ('erased', None, '{"retention_erased":true,"erased_at_ms":4321}')])
    receipt = {'format': 'neighbour-native-export-v1', 'phase': 'preview', 'cross_database_consistent': False,
               'original_cloud_ledger_exists': False, 'original_cloud_signing_key_exists': False,
               'controls': {'azure-voice-control.json': {'paused': True},
                   'cloudflare-gemma-quota-stop.json': {'until': '2099-01-01T00:00:00+00:00'},
                   'cloudflare-gemma-cooldown.json': {'until': '2098-01-01T00:00:00+00:00', 'reason': 'rate_limit'}},
               'databases': {role: file_identity(export / name) for role, name in DATABASES.items()}}
    (export / 'NATIVE-EXPORT.json').write_text(json.dumps(receipt), encoding='utf-8')
    return export, data, tmp_path / 'new-adapters', b'SYNTHETIC-KEY-' + b'x' * 32


def test_archives_exact_shared_images_missing_paths_and_existing_erasure_intents(archived):
    export, data, out, key = archived
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for root in (export, data) for path in root.rglob('*') if path.is_file()}
    result = native_adapters.prepare(export, data, out, signing_key=key)
    assert result['legacy_image_count'] == 1 and result['legacy_image_bindings'] == 2
    assert result['legacy_missing_bindings'] == 1 and result['native_erasure_intents_preserved'] == 2
    assert result['controls_imported'] == 3 and result['first_cloud_ledger_created']
    assert not result['cutover_ready'] and not result['cloud_AI_reviewed'] and not result['private_data_uploaded']
    with sqlite3.connect(out / 'cloud-photos.sqlite3') as db:
        assert db.execute('SELECT content FROM native_evidence_blobs').fetchone()[0] == (data / 'events/shared-blurred.jpg').read_bytes()
        assert db.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0] == 0
    with sqlite3.connect(out / 'cloud-deletion-ledger.sqlite3') as db:
        ledger = DeletionLedger(db, key)
        assert {item['target'] for item in ledger.records(ledger.checkpoint())} == {'expired-case', 'erased'}
    with sqlite3.connect(out / 'cloud-control.sqlite3') as db:
        assert json.loads(db.execute('SELECT payload FROM cloud_state WHERE name=?', ('azure-voice-control.json',)).fetchone()[0]) == {'paused': True}
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for root in (export, data) for path in root.rglob('*') if path.is_file()}
    assert all(key not in file.read_bytes() for file in out.iterdir() if file.is_file())


def test_changed_snapshot_and_existing_output_are_never_accepted(archived):
    export, data, out, key = archived
    out.mkdir()
    with pytest.raises(ValueError, match='new_private_adapter'):
        native_adapters.prepare(export, data, out, signing_key=key)
    with (export / DATABASES['usage']).open('ab') as handle:
        handle.write(b'changed')
    with pytest.raises(ValueError, match='export_changed'):
        native_adapters.prepare(export, data, out, signing_key=key)


def test_unbound_raw_photo_is_not_relabelled_as_cloud_reviewed(archived):
    export, data, out, key = archived
    with sqlite3.connect(export / DATABASES['events']) as db:
        db.execute('UPDATE events SET details_json=? WHERE id=?', ('{"source":"ep_patrol_local"}', 'a'))
    receipt = json.loads((export / 'NATIVE-EXPORT.json').read_text())
    receipt['databases']['events'] = file_identity(export / DATABASES['events'])
    (export / 'NATIVE-EXPORT.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='three_photo'):
        native_adapters.prepare(export, data, out, signing_key=key)
    assert not (out / 'NATIVE-ADAPTERS.json').exists()


def test_symlink_and_traversal_are_rejected_before_reading_outside_data(archived):
    export, data, out, key = archived
    with sqlite3.connect(export / DATABASES['events']) as db:
        db.execute('UPDATE events SET evidence=? WHERE id=?', ('events/../../outside-blurred.jpg', 'a'))
    receipt = json.loads((export / 'NATIVE-EXPORT.json').read_text())
    receipt['databases']['events'] = file_identity(export / DATABASES['events'])
    (export / 'NATIVE-EXPORT.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='unrecognised_native_evidence'):
        native_adapters.prepare(export, data, out, signing_key=key)
    assert not (out / 'NATIVE-ADAPTERS.json').exists()


def test_shared_legacy_image_is_erased_only_after_all_bound_events_expire(archived):
    from deploy.cloud.retention_restore import reconcile

    export, data, out, key = archived
    native_adapters.prepare(export, data, out, signing_key=key)
    with sqlite3.connect(out / 'cloud-photos.sqlite3') as db:
        with db:
            reconcile(db, 'photos', [{'kind': 'event', 'target': 'a', 'revision': 1, 'erased_ms': 1}])
        assert db.execute('SELECT COUNT(*) FROM native_evidence_blobs').fetchone()[0] == 1
        assert db.execute('SELECT event_id FROM native_evidence_bindings').fetchall() == [('b',)]
        with db:
            reconcile(db, 'photos', [{'kind': 'event', 'target': 'b', 'revision': 1, 'erased_ms': 2}])
        assert db.execute('SELECT COUNT(*) FROM native_evidence_blobs').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM cloud_erased_events').fetchone()[0] == 2
