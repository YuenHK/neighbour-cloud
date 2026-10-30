"""Read counters without creating/resetting them. None means unavailable."""
import re
import sqlite3
from contextlib import closing

from edge_hub.storage_context import current_storage


def usage_snapshot(database, periods):
    periods = tuple(periods)
    if not 1 <= len(periods) <= 2 or any(not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}(?:-\d{2})?', value) for value in periods):
        raise ValueError('bounded_usage_periods_required')
    storage = current_storage()
    if storage is None and not database.is_file():
        return {}
    connect = storage.connect if storage is not None else sqlite3.connect
    try:
        with closing(connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            rows = db.execute('SELECT meter,period,amount FROM usage WHERE period IN (' +
                              ','.join('?' for _ in periods) + ') LIMIT 129', periods).fetchall()
        if len(rows) > 128:
            return None
        result = {}
        for meter, period, amount in rows:
            if (not isinstance(meter, str) or not isinstance(period, str) or period not in periods
                    or type(amount) is not int or not 0 <= amount < 2**63 or (meter, period) in result):
                return None
            result[meter, period] = amount
        return result
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        return None
