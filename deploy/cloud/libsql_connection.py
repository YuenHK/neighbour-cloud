"""Experimental DB-API adapter, not yet selected by the production stores.

libSQL writes are acknowledged by the remote primary. Do not replace this with
periodic uploads of a temporary SQLite file: a sleeping host would lose writes.
The driver is installed in the research environment only until full migration,
photo persistence, retention and backup paths have passed acceptance.
"""
import sqlite3
import threading


class Row:
    def __init__(self, description, values):
        self._names = tuple(item[0] for item in description)
        self._values = tuple(values)
        self._lookup = {}
        for index, name in enumerate(self._names):
            self._lookup.setdefault(name.casefold(), index)

    def keys(self):
        return list(self._names)

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(self._values)

    def __getitem__(self, key):
        return self._values[self._lookup[key.casefold()]] if isinstance(key, str) else self._values[key]


class Connection:
    # Turso's remote primary rejects this connection-local SQLite PRAGMA.
    # Callers must observe actual rows instead of treating a fixed version as current.
    supports_data_version = False

    def __init__(self, connection, error_type):
        self._connection = connection
        self._error_type = error_type
        self._closed = False
        self._lock = threading.RLock()
        self.row_factory = None

    def _require_open(self):
        if self._closed:
            raise sqlite3.ProgrammingError('cloud database connection is closed')

    def _call(self, method, *args, **kwargs):
        with self._lock:
            self._require_open()
            try:
                return method(*args, **kwargs)
            except (self._error_type, ValueError) as error:
                # Do not return SQL, resident values, provider hosts or tokens.
                kind = sqlite3.IntegrityError if 'constraint' in str(error).casefold() else sqlite3.OperationalError
                raise kind('cloud_database_operation_failed') from None

    @property
    def in_transaction(self):
        return self._call(lambda: self._connection.in_transaction)

    @property
    def total_changes(self):
        return self._call(self._connection.execute, 'SELECT total_changes()').fetchone()[0]

    def execute(self, sql, parameters=()):
        return Cursor(self, self._call(self._connection.execute, sql, parameters))

    def executemany(self, sql, parameters):
        return Cursor(self, self._call(self._connection.executemany, sql, parameters))

    def executescript(self, sql):
        return Cursor(self, self._call(self._connection.executescript, sql))

    def commit(self):
        return self._call(self._connection.commit)

    def rollback(self):
        return self._call(self._connection.rollback)

    def close(self):
        with self._lock:
            if self._closed:
                return
            try:
                return self._call(self._connection.close)
            finally:
                # An uncertain close must never re-enter a disposed native handle.
                self._closed = True

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, kind, value, traceback):
        if kind is not None:
            self.rollback()
        else:
            try:
                self.commit()
            except sqlite3.Error:
                self.rollback()
                raise
        return False


class Cursor:
    def __init__(self, connection, cursor):
        self.connection = connection
        self._cursor = cursor

    @property
    def description(self):
        return self.connection._call(lambda: self._cursor.description)

    @property
    def lastrowid(self):
        return self.connection._call(lambda: self._cursor.lastrowid)

    @property
    def rowcount(self):
        return self.connection._call(lambda: self._cursor.rowcount)

    def _row(self, data):
        if data is None or self.connection.row_factory is None:
            return data
        if self.connection.row_factory is sqlite3.Row:
            return Row(self.description, data)
        raise sqlite3.NotSupportedError('unsupported_cloud_row_factory')

    def fetchone(self):
        return self._row(self.connection._call(self._cursor.fetchone))

    def fetchall(self):
        return [self._row(row) for row in self.connection._call(self._cursor.fetchall)]

    def fetchmany(self, size=128):
        if type(size) is not int or not 1 <= size <= 4096:
            raise sqlite3.ProgrammingError('invalid_cloud_fetch_size')
        return [self._row(row) for row in self.connection._call(self._cursor.fetchmany, size)]

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row

    def close(self):
        return self.connection._call(self._cursor.close)
