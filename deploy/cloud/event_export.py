"""Explicit cloud CSV snapshot provider; no remote transaction during download.

Temporary SQLite is only an immutable export copy, never the live data store or
a claimed durable backup. No source writes, retry or local-data fallback.
"""
import math
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from pathlib import Path

from deploy.cloud.sql_snapshot import snapshot


class EventExportSnapshot:
    def __init__(self, database, *, connection_factory, scratch_root=None, timeout=5,
                 max_bytes=128 * 1024 * 1024, clock=None):
        database = Path(database)
        if not database.is_absolute() or not callable(connection_factory):
            raise ValueError('explicit_event_export_source_required')
        if (type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 5
                or type(max_bytes) is not int or not 0 < max_bytes <= 128 * 1024 * 1024):
            raise ValueError('bounded_event_export_required')
        if scratch_root is not None:
            scratch_root = Path(scratch_root)
            if (not scratch_root.is_absolute() or not scratch_root.is_dir()
                    or scratch_root.is_symlink() or any(p.is_symlink() for p in scratch_root.parents)):
                raise ValueError('existing_event_export_scratch_required')
        if clock is not None and not callable(clock):
            raise ValueError('event_export_clock_required')
        self.database, self.connect, self.scratch_root = database, connection_factory, scratch_root
        self.timeout, self.max_bytes, self.clock = timeout, max_bytes, clock or time.monotonic

    @contextmanager
    def __call__(self):
        deadline = self.clock() + self.timeout

        def remaining():
            value = deadline - self.clock()
            if value <= 0:
                raise TimeoutError('event export snapshot budget exceeded')
            return value

        try:
            with tempfile.TemporaryDirectory(prefix='neighbour-cloud-event-export-', dir=self.scratch_root) as directory:
                output = Path(directory) / 'snapshot.sqlite3'
                with closing(self.connect(self.database.as_uri() + '?mode=ro', uri=True,
                                          timeout=min(2, remaining()))) as source:
                    snapshot(source, output, timeout=remaining(), max_bytes=self.max_bytes, clock=self.clock)
                remaining()
                # The remote reader and its transaction are already closed.
                with closing(sqlite3.connect(output.as_uri() + '?mode=ro', uri=True,
                                             check_same_thread=False)) as copied:
                    copied.row_factory = sqlite3.Row
                    copied.execute('PRAGMA trusted_schema=OFF')
                    remaining()
                    yield copied
        except (OSError, ValueError, sqlite3.Error):
            raise sqlite3.OperationalError('cloud event export temporarily unavailable') from None
