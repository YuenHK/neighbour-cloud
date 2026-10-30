import importlib.util
import io
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from deploy.cloud.deletion_ledger import DeletionLedger

ROOT = Path(__file__).resolve().parents[1] / 'deploy/cloud'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


photos = load('photo_store')


@pytest.fixture(params=['sqlite', 'libsql'])
def db(request):
    if request.param == 'libsql':
        driver = pytest.importorskip('libsql')
        adapter = load('libsql_connection')
        connection = adapter.Connection(driver.connect(':memory:'), driver.Error)
    else:
        connection = sqlite3.connect(':memory:')
    yield connection
    connection.close()


@pytest.fixture
def ledger():
    connection = sqlite3.connect(':memory:')
    journal = DeletionLedger(connection, b'k' * 32, initialize=True)
    yield journal
    connection.close()


def image(color='green'):
    output = io.BytesIO()
    Image.new('RGB', (16, 16), color).save(output, format='JPEG')
    return output.getvalue()


def put(store, *, side='event', key='events/synthetic/main.jpg', data=None, reviewed=True):
    return store.put('synthetic', side, key, image() if data is None else data, reviewed=reviewed, now_ms=1)


def test_three_bound_photos_are_immutable_and_identical_retries_are_free(db):
    store = photos.PhotoStore(db)
    for side in ('event', 'left', 'right'):
        key = f'events/synthetic/{side}.jpg'
        assert not put(store, side=side, key=key)['replayed']
        assert put(store, side=side, key=key)['replayed']
        assert store.get(key) == image()
        with pytest.raises(ValueError, match='immutable'):
            put(store, side=side, key=key, data=image('red'))
    assert db.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0] == 3


@pytest.mark.parametrize('key', ['../private.jpg', '/events/private.jpg', 'events/../private.jpg',
                                 'events/x.svg', 'events/x.jpg?token=1'])
def test_unbound_paths_and_unreviewed_input_cannot_enter_store(db, key):
    store = photos.PhotoStore(db)
    with pytest.raises(ValueError):
        put(store, key=key)
    with pytest.raises(ValueError):
        put(store, reviewed=False)
    assert db.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0] == 0


def test_restart_independent_storage_and_content_integrity(db):
    store = photos.PhotoStore(db)
    put(store)
    assert photos.PhotoStore(db).get('events/synthetic/main.jpg') == image()
    with db:
        db.execute('UPDATE cloud_photos SET content=?', (image('red'),))
    with pytest.raises(ValueError, match='integrity_failed'):
        store.get('events/synthetic/main.jpg')


def test_budget_is_atomic_and_does_not_replace_older_evidence(db):
    store = photos.PhotoStore(db, max_bytes=len(image()))
    put(store)
    with pytest.raises(ValueError, match='budget_reached'):
        put(store, side='left', key='events/synthetic/left.jpg')
    assert db.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0] == 1
    assert store.get('events/synthetic/main.jpg') == image()


def test_90_days_are_counted_from_staff_completion_not_photo_creation(db, ledger):
    store = photos.PhotoStore(db)
    put(store)
    assert store.expire(now_ms=200 * photos.DAY)['erased_photos'] == 0
    store.event_state('synthetic', 'resolved', 2, completed_ms=100 * photos.DAY)
    assert store.expire(now_ms=189 * photos.DAY)['erased_photos'] == 0
    assert store.expire(now_ms=190 * photos.DAY, deletion_ledger=ledger)['erased_photos'] == 1
    with pytest.raises(KeyError):
        store.get('events/synthetic/main.jpg')
    with pytest.raises(ValueError, match='was_erased'):
        put(store)


def test_reopen_and_stale_staff_updates_cannot_delete_active_evidence(db):
    store = photos.PhotoStore(db)
    put(store)
    store.event_state('synthetic', 'resolved', 2, completed_ms=10 * photos.DAY)
    store.event_state('synthetic', 'confirmed', 3)
    with pytest.raises(ValueError, match='stale'):
        store.event_state('synthetic', 'resolved', 2, completed_ms=10 * photos.DAY)
    assert store.expire(now_ms=200 * photos.DAY)['erased_photos'] == 0


def test_joined_outer_transaction_rolls_back_photo_and_retention_together(db):
    store = photos.PhotoStore(db)
    with pytest.raises(ValueError, match='synthetic_failure'), db:
        db.execute('BEGIN IMMEDIATE')
        put(store)
        store.event_state('synthetic', 'resolved', 2, completed_ms=1)
        raise ValueError('synthetic_failure')
    assert db.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM cloud_photo_retention').fetchone()[0] == 0


def test_staff_note_revision_cannot_extend_existing_completion_deadline(db, ledger):
    store = photos.PhotoStore(db)
    put(store)
    store.event_state('synthetic', 'resolved', 2, completed_ms=10 * photos.DAY)
    with pytest.raises(ValueError, match='completion_clock'):
        store.event_state('synthetic', 'resolved', 3, completed_ms=20 * photos.DAY)
    assert store.expire(now_ms=100 * photos.DAY, deletion_ledger=ledger)['erased_photos'] == 1


def test_expired_event_cannot_be_reopened_to_restore_old_or_new_photo_key(db, ledger):
    store = photos.PhotoStore(db)
    put(store)
    store.event_state('synthetic', 'resolved', 2, completed_ms=photos.DAY)
    store.expire(now_ms=91 * photos.DAY, deletion_ledger=ledger)
    with pytest.raises(ValueError, match='event_was_erased'):
        store.event_state('synthetic', 'confirmed', 3)
    with pytest.raises(ValueError):
        put(store, side='left', key='events/synthetic/left.jpg')


def test_existing_png_evidence_keeps_original_bytes_and_digest(db):
    store = photos.PhotoStore(db)
    output = io.BytesIO()
    Image.new('RGB', (16, 16), 'green').save(output, format='PNG')
    data = output.getvalue()
    key = 'events/legacy-blurred.png'
    put(store, key=key, data=data)
    assert store.get(key) == data
    with pytest.raises(ValueError, match='invalid_cloud_photo'):
        put(store, side='left', key='events/wrong.jpg', data=data)


def test_actual_patrol_event_states_are_supported_without_case_status_aliases(db):
    store = photos.PhotoStore(db)
    store.event_state('synthetic', 'pending', 1)
    put(store)
    store.event_state('synthetic', 'confirmed', 2)
    assert store.expire(now_ms=200 * photos.DAY)['erased_photos'] == 0
    with pytest.raises(ValueError, match='invalid_cloud_photo_event_state'):
        store.event_state('synthetic', 'acknowledged', 3)


def test_expiry_cannot_run_without_an_independent_durable_intent(db):
    store = photos.PhotoStore(db)
    put(store)
    store.event_state('synthetic', 'resolved', 2, completed_ms=photos.DAY)
    with pytest.raises(ValueError, match='independent_cloud_deletion_ledger_required'):
        store.expire(now_ms=91 * photos.DAY)
    assert store.get('events/synthetic/main.jpg') == image()
    assert db.execute('SELECT COUNT(*) FROM cloud_erased_events').fetchone()[0] == 0


def test_uncertain_ledger_ack_blocks_deletion_and_retry_is_idempotent(db, ledger, monkeypatch):
    store = photos.PhotoStore(db)
    put(store)
    store.event_state('synthetic', 'resolved', 2, completed_ms=photos.DAY)
    append = ledger.append
    def uncertain(records):
        append(records)
        raise sqlite3.OperationalError('synthetic_ack_lost')
    monkeypatch.setattr(ledger, 'append', uncertain)
    with pytest.raises(sqlite3.OperationalError, match='synthetic_ack_lost'):
        store.expire(now_ms=91 * photos.DAY, deletion_ledger=ledger)
    assert store.get('events/synthetic/main.jpg') == image()
    assert ledger.checkpoint()['seq'] == 1
    monkeypatch.setattr(ledger, 'append', append)
    assert store.expire(now_ms=92 * photos.DAY, deletion_ledger=ledger)['erased_photos'] == 1
    assert ledger.checkpoint()['seq'] == 1


def test_photo_storage_cannot_be_put_in_the_ledger_database(ledger):
    with pytest.raises(ValueError, match='separate_deletion_ledger'):
        photos.PhotoStore(ledger.db)
    assert ledger.checkpoint()['seq'] == 0
