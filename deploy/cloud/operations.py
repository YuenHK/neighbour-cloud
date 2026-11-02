"""Small durable extension records. Explicit offline migration, never fallback storage.

The existing estate snapshot/retention pipeline includes this table. Secrets are
encrypted with an independent domain derived from the external ledger key.
"""
import base64
import hashlib
import hmac
import json
import os
import threading

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def migrate(db):
    if db.in_transaction:
        raise ValueError('migration_requires_idle_connection')
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS cloud_operations ('
                   'namespace TEXT NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL,'
                   'PRIMARY KEY(namespace,identity))')


class Operations:
    def __init__(self, db, key):
        self.db, self.lock = db, threading.RLock()
        self.cipher = AESGCM(hmac.digest(key, b'neighbour-operations-encryption-v1', 'sha256'))
        db.execute('SELECT namespace,identity,payload FROM cloud_operations LIMIT 0')

    def get(self, namespace, identity, default=None):
        with self.lock:
            row = self.db.execute('SELECT payload FROM cloud_operations WHERE namespace=? AND identity=?',
                                  (namespace, identity)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, namespace, identity, value):
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if len(data.encode()) > 2_000_000:
            raise ValueError('operation_too_large')
        with self.lock, self.db:
            self.db.execute('INSERT INTO cloud_operations VALUES(?,?,?) ON CONFLICT(namespace,identity) '
                            'DO UPDATE SET payload=excluded.payload', (namespace, identity, data))

    def items(self, namespace):
        with self.lock:
            rows = self.db.execute('SELECT identity,payload FROM cloud_operations WHERE namespace=? '
                                   'ORDER BY identity LIMIT 501', (namespace,)).fetchall()
        if len(rows) > 500:
            raise ValueError('operation_capacity_reached')
        return [(row[0], json.loads(row[1])) for row in rows]

    def delete(self, namespace, identity):
        with self.lock, self.db:
            self.db.execute('DELETE FROM cloud_operations WHERE namespace=? AND identity=?', (namespace, identity))

    def count(self, namespace):
        with self.lock:
            return self.db.execute('SELECT COUNT(*) FROM cloud_operations WHERE namespace=?', (namespace,)).fetchone()[0]

    def seal(self, namespace, identity, value):
        nonce = os.urandom(12)
        aad = f'{namespace}:{identity}'.encode()
        return base64.b64encode(nonce + self.cipher.encrypt(nonce, json.dumps(value).encode(), aad)).decode()

    def open(self, namespace, identity, value):
        raw = base64.b64decode(value, validate=True)
        return json.loads(self.cipher.decrypt(raw[:12], raw[12:], f'{namespace}:{identity}'.encode()))

    @staticmethod
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
