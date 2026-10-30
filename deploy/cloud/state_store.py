"""Dedicated durable operational flags; missing state never means unpaused."""
import json
import threading
import time
from datetime import UTC, datetime

NAMES = {'azure-voice-control.json', 'cloudflare-gemma-quota-stop.json',
         'cloudflare-gemma-cooldown.json'}


def validate(name, value):
    if name not in NAMES or not isinstance(value, dict):
        raise ValueError('invalid_cloud_control')
    if name == 'azure-voice-control.json':
        if set(value) != {'paused'} or type(value['paused']) is not bool:
            raise ValueError('invalid_cloud_control')
    else:
        fields = {'until', 'reason'} if name.endswith('cooldown.json') else {'until'}
        if set(value) != fields or not isinstance(value['until'], str):
            raise ValueError('invalid_cloud_control')
        until = datetime.fromisoformat(value['until'])
        if until.tzinfo is None or until.utcoffset() is None:
            raise ValueError('invalid_cloud_control')
        if 'reason' in value and value['reason'] not in ('network', 'rate_limit'):
            raise ValueError('invalid_cloud_control')
    return value


class StateStore:
    def __init__(self, connection, *, initialize=False):
        self.db = connection
        self.lock = threading.RLock()
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not tables and initialize is True:
            with self.db:
                self.db.execute('CREATE TABLE cloud_state(name TEXT PRIMARY KEY,payload TEXT NOT NULL,'
                                'revision INTEGER NOT NULL,updated_ms INTEGER NOT NULL)')
        elif tables != {'cloud_state'}:
            raise ValueError('cloud_control_store_requires_initialization_or_review')

    def seed(self, values):
        """Offline import only: never overwrite an existing flag or create defaults."""
        if not isinstance(values, dict) or not values:
            raise ValueError('explicit_cloud_controls_required')
        prepared = {name: json.dumps(validate(name, value), sort_keys=True) for name, value in values.items()}
        with self.lock:
            if self.db.in_transaction:
                raise ValueError('cloud_control_store_requires_dedicated_connection')
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                for name, payload in prepared.items():
                    if self.db.execute('SELECT 1 FROM cloud_state WHERE name=?', (name,)).fetchone():
                        raise ValueError('cloud_control_import_would_overwrite')
                    self.db.execute('INSERT INTO cloud_state VALUES(?,?,1,?)', (name, payload, int(time.time() * 1000)))

    def read(self, name):
        if name not in NAMES:
            raise ValueError('unsupported_cloud_control')
        with self.lock:
            row = self.db.execute('SELECT payload,revision FROM cloud_state WHERE name=?', (name,)).fetchone()
            if row is None:
                raise OSError('cloud_control_unavailable')
            try:
                if type(row[1]) is not int or row[1] < 1:
                    raise ValueError('invalid')
                return validate(name, json.loads(row[0]))
            except (ValueError, TypeError):
                raise OSError('cloud_control_unavailable') from None

    def write(self, name, value):
        value = validate(name, value)
        with self.lock:
            if self.db.in_transaction:
                raise ValueError('cloud_control_store_requires_dedicated_connection')
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                old = self.read(name)  # No upsert/default if the imported flag disappeared.
                if ('until' in value and datetime.fromisoformat(value['until']) < datetime.fromisoformat(old['until'])
                        and datetime.fromisoformat(old['until']) > datetime.now(UTC)):
                    raise ValueError('cloud_control_cannot_shorten_active_block')
                self.db.execute('UPDATE cloud_state SET payload=?,revision=revision+1,updated_ms=? WHERE name=?',
                                (json.dumps(value, sort_keys=True), int(time.time() * 1000), name))
