import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'deploy/cloud'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger_module = load('deletion_ledger')


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


def intent(target='synthetic-case', *, kind='case', revision=2, stamp=100):
    return {'kind': kind, 'target': target, 'revision': revision, 'erased_ms': stamp}


def test_missing_ledger_is_not_automatically_reset_to_empty(db):
    with pytest.raises(ValueError, match='missing_or_unrecognised'):
        ledger_module.DeletionLedger(db, b'k' * 32)
    assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0


def test_signed_checkpoint_retry_keeps_original_intent_and_never_private_content(db):
    ledger = ledger_module.DeletionLedger(db, b'k' * 32, initialize=True)
    assert ledger.checkpoint()['seq'] == 0
    first = ledger.append([intent()])
    assert first['seq'] == 1
    assert ledger.append([intent(stamp=999)]) == first
    assert ledger.records(first) == [intent()]
    assert db.execute('SELECT COUNT(*) FROM cloud_deletion_receipts').fetchone()[0] == 1


def test_corrupt_payload_and_wrong_signing_key_fail_closed(db):
    ledger = ledger_module.DeletionLedger(db, b'k' * 32, initialize=True)
    checkpoint = ledger.append([intent()])
    with pytest.raises(ValueError, match='head_invalid'):
        ledger_module.DeletionLedger(db, b'z' * 32)
    with db:
        db.execute('UPDATE cloud_deletion_receipts SET payload=? WHERE seq=1', ('PRIVATE-TAMPER-MARKER',))
    with pytest.raises(ValueError) as caught:
        ledger.records(checkpoint)
    assert 'PRIVATE-TAMPER-MARKER' not in str(caught.value)


def test_old_signed_checkpoint_does_not_meet_current_recovery_checkpoint(db):
    ledger = ledger_module.DeletionLedger(db, b'k' * 32, initialize=True)
    old = ledger.append([intent()])
    current = ledger.append([intent('next-case')])
    with pytest.raises(ValueError, match='checkpoint_changed'):
        ledger.records(old)
    with db:
        db.execute('DELETE FROM cloud_deletion_receipts WHERE seq=2')
        db.execute('UPDATE cloud_deletion_head SET seq=?,digest=?,signature=? WHERE id=1',
                   (old['seq'], old['digest'], old['signature']))
    with pytest.raises(ValueError, match='checkpoint_changed'):
        ledger.records(current)


def test_invalid_batch_cannot_append_a_partial_intent(db):
    ledger = ledger_module.DeletionLedger(db, b'k' * 32, initialize=True)
    with pytest.raises(ValueError):
        ledger.append([intent(), {'kind': 'case', 'target': '../private'}])
    assert ledger.checkpoint()['seq'] == 0


def test_transport_failure_rolls_back_entire_intent_batch(db):
    ledger = ledger_module.DeletionLedger(db, b'k' * 32, initialize=True)

    class Failing:
        def __init__(self):
            self.count = 0
        def __getattr__(self, name):
            return getattr(db, name)
        def __enter__(self):
            db.__enter__()
            return self
        def __exit__(self, *args):
            return db.__exit__(*args)
        def execute(self, sql, args=()):
            if sql.startswith('INSERT INTO cloud_deletion_receipts'):
                self.count += 1
                if self.count == 2:
                    raise sqlite3.OperationalError('synthetic_transport_failure')
            return db.execute(sql, args)

    ledger.db = Failing()
    with pytest.raises(sqlite3.OperationalError, match='synthetic_transport_failure'):
        ledger.append([intent(), intent('next-case')])
    assert ledger.checkpoint()['seq'] == 0


def test_application_data_cannot_be_mistaken_for_independent_ledger(db):
    db.execute('CREATE TABLE resident_data(id TEXT)')
    db.commit()
    with pytest.raises(ValueError, match='missing_or_unrecognised'):
        ledger_module.DeletionLedger(db, b'k' * 32, initialize=True)
