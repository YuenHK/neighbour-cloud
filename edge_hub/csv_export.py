"""Spreadsheet-oriented CSV export; never changes stored event values.

Quotes every field, neutralizes formula/control prefixes on initial import.
No CSV escaping can guarantee every spreadsheet's save/reopen behaviour.
"""
import csv
import io
import re
import sqlite3

from edge_hub.events import EventExportBusy


class ExportPreparationError(RuntimeError):
    pass


class PreparedEventExport:
    """Own a primed export so snapshot preparation happens before HTTP headers."""

    def __init__(self, store):
        self._rows = export_event_rows(store)
        try:
            self._header = next(self._rows)
        except (OSError, sqlite3.Error, EventExportBusy):
            self._rows.close()
            raise ExportPreparationError('event export temporarily unavailable') from None

    def __iter__(self):
        return self

    def __next__(self):
        if self._header is not None:
            header, self._header = self._header, None
            return header
        return next(self._rows)

    def close(self):
        self._header = None
        self._rows.close()


def safe_csv_cell(value):
    text = '' if value is None else str(value)
    stripped = re.sub(r'^[\s\ufeff]+', '', text)
    if text.startswith(('\t', '\r', '\n')) or stripped.startswith(('=', '+', '-', '@', '＝', '＋', '－', '＠')):
        return "'" + text
    return text


def export_event_rows(store):
    def row(values):
        buffer = io.StringIO(newline='')
        csv.writer(buffer, quoting=csv.QUOTE_ALL).writerow([safe_csv_cell(value) for value in values])
        return buffer.getvalue()

    with store.export_snapshot() as snapshot:
        cursor = snapshot.execute('SELECT e.* FROM events e JOIN event_ingest_sequence s '
                                  'ON s.event_id=e.id ORDER BY s.seq ASC')
        try:
            yield row(['id', 'type', 'zone', 'at_ms', 'severity', 'status', 'evidence'])
            while rows := cursor.fetchmany(500):
                for stored in rows:
                    event = store._from_row(stored)
                    yield row([event.id, event.type, event.zone, event.at_ms, event.severity,
                               event.status, event.evidence])
        finally:
            cursor.close()
