"""Independent deletion-intent ledger for the cloud candidate (not deployed).

Keep this database and signing key outside restorable application snapshots.
Each recovery must verify against a checkpoint read from this live ledger.
A signed old checkpoint alone does not prove freshness; loss/rollback of this
independent ledger requires operator review, never an automatic empty reset.
"""
import hashlib
import hmac
import json
import re
import threading

ZERO = '0' * 64
TABLES = {'cloud_deletion_receipts', 'cloud_deletion_head'}
MAX_RECORDS = 100_000


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def validate(record):
    if (not isinstance(record, dict) or set(record) != {'kind', 'target', 'revision', 'erased_ms'}
            or record['kind'] not in ('case', 'event')
            or not isinstance(record['target'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', record['target'])
            or type(record['revision']) is not int or not 1 <= record['revision'] < 2**63
            or type(record['erased_ms']) is not int or not 0 <= record['erased_ms'] < 2**63):
        raise ValueError('invalid_deletion_intent')
    return record


def identity(record):
    return hashlib.sha256(canonical({key: record[key] for key in ('kind', 'target', 'revision')}).encode()).hexdigest()


def digest(previous, payload):
    return hashlib.sha256(('neighbour-deletion-v1:' + previous + ':' + payload).encode()).hexdigest()


class DeletionLedger:
    def __init__(self, connection, signing_key, *, initialize=False):
        if not isinstance(signing_key, bytes) or not 32 <= len(signing_key) <= 128 or connection.in_transaction:
            raise ValueError('independent_deletion_ledger_configuration_required')
        self.db, self._key = connection, signing_key
        self.lock = threading.RLock()
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables != TABLES:
            if tables or initialize is not True:
                raise ValueError('independent_deletion_ledger_missing_or_unrecognised')
            with self.db:
                self.db.execute('CREATE TABLE cloud_deletion_receipts('
                                'seq INTEGER PRIMARY KEY,identity TEXT NOT NULL UNIQUE,previous TEXT NOT NULL,'
                                'digest TEXT NOT NULL,payload TEXT NOT NULL)')
                self.db.execute('CREATE TABLE cloud_deletion_head('
                                'id INTEGER PRIMARY KEY CHECK(id=1),seq INTEGER NOT NULL,'
                                'digest TEXT NOT NULL,signature TEXT NOT NULL)')
                self.db.execute('INSERT INTO cloud_deletion_head VALUES(1,0,?,?)', (ZERO, self._sign(0, ZERO)))
        self.checkpoint()

    def _sign(self, seq, value):
        return hmac.new(self._key, f'neighbour-deletion-head-v1:{seq}:{value}'.encode(), hashlib.sha256).hexdigest()

    def _head(self):
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables != TABLES:
            raise ValueError('independent_deletion_ledger_schema_changed')
        rows = self.db.execute('SELECT seq,digest,signature FROM cloud_deletion_head WHERE id=1').fetchall()
        if len(rows) != 1:
            raise ValueError('deletion_ledger_head_invalid')
        seq, value, signature = tuple(rows[0])
        if (type(seq) is not int or not 0 <= seq <= MAX_RECORDS
                or not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                or not isinstance(signature, str) or not re.fullmatch('[a-f0-9]{64}', signature)
                or not hmac.compare_digest(signature, self._sign(seq, value))):
            raise ValueError('deletion_ledger_head_invalid')
        return {'seq': seq, 'digest': value, 'signature': signature}

    def _verified(self, expected=None):
        head = self._head()
        if expected is not None and head != expected:
            raise ValueError('deletion_ledger_checkpoint_changed')
        seq, previous, records = 0, ZERO, []
        while seq < head['seq']:
            rows = self.db.execute('SELECT seq,identity,previous,digest,payload FROM cloud_deletion_receipts '
                                   'WHERE seq>? ORDER BY seq LIMIT 256', (seq,)).fetchall()
            if not rows:
                raise ValueError('deletion_ledger_chain_invalid')
            for row in rows:
                number, item_id, prior, value, payload = tuple(row)
                if (number != seq + 1 or prior != previous or not isinstance(payload, str)
                        or len(payload) > 512 or digest(previous, payload) != value):
                    raise ValueError('deletion_ledger_chain_invalid')
                try:
                    record = validate(json.loads(payload))
                except (ValueError, TypeError):
                    raise ValueError('deletion_ledger_chain_invalid') from None
                if canonical(record) != payload or identity(record) != item_id:
                    raise ValueError('deletion_ledger_chain_invalid')
                records.append(record)
                previous, seq = value, number
        if (seq != head['seq'] or previous != head['digest']
                or self.db.execute('SELECT COUNT(*) FROM cloud_deletion_receipts').fetchone()[0] != seq):
            raise ValueError('deletion_ledger_chain_invalid')
        return head, records

    def _read(self, expected=None):
        with self.lock:
            if self.db.in_transaction:
                raise ValueError('deletion_ledger_requires_dedicated_connection')
            with self.db:
                self.db.execute('BEGIN')
                return self._verified(expected)

    def checkpoint(self):
        return self._read()[0]

    def records(self, expected_checkpoint):
        if not isinstance(expected_checkpoint, dict) or set(expected_checkpoint) != {'seq', 'digest', 'signature'}:
            raise ValueError('live_deletion_checkpoint_required')
        return self._read(expected_checkpoint)[1]

    def append(self, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 1000:
            raise ValueError('bounded_deletion_intent_batch_required')
        batch = [dict(validate(record)) for record in records]
        with self.lock:
            if self.db.in_transaction:
                raise ValueError('deletion_ledger_requires_dedicated_connection')
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                head, _ = self._verified()
                for record in batch:
                    item_id = identity(record)
                    old = self.db.execute('SELECT payload FROM cloud_deletion_receipts WHERE identity=?', (item_id,)).fetchone()
                    if old:
                        # A delayed retry keeps the first durable intent time.
                        prior = validate(json.loads(old[0]))
                        if any(prior[key] != record[key] for key in ('kind', 'target', 'revision')):
                            raise ValueError('deletion_ledger_identity_conflict')
                        continue
                    if head['seq'] >= MAX_RECORDS:
                        raise ValueError('deletion_ledger_capacity_requires_review')
                    payload = canonical(record)
                    value, seq = digest(head['digest'], payload), head['seq'] + 1
                    self.db.execute('INSERT INTO cloud_deletion_receipts VALUES(?,?,?,?,?)',
                                    (seq, item_id, head['digest'], value, payload))
                    head = {'seq': seq, 'digest': value, 'signature': self._sign(seq, value)}
                self.db.execute('UPDATE cloud_deletion_head SET seq=?,digest=?,signature=? WHERE id=1',
                                (head['seq'], head['digest'], head['signature']))
            # Only a successfully committed intent may precede data deletion.
            return head
