"""Conservative local reservations, not a replacement for provider billing limits.

Only counters are persisted; never audio, transcripts, prompts or credentials.
Reserve before dispatch. Failed requests remain reserved to avoid undercounting
when a provider processed a request but its response was lost.
"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

# Headroom below advertised F0 allowances. Groq limits vary by model/account.
LIMITS = {
    "model_gallery_search_credits": ("month", 30),
    "patrol_cloud_checks": ("day", 20),
    "patrol_cloud_neuron_reservations": ("day", 2000),
    "cloudflare_gemma_neuron_reservations": ("day", 8000),
    "gemini_chat_requests": ("day", 100),
    "gemini_chat_characters": ("day", 200000),
    "gemini_tts_requests": ("day", 40),
    "gemini_tts_characters": ("day", 5000),
    "siliconflow_stt_seconds": ("day", 1200),
    "siliconflow_chat_requests": ("day", 200),
    "siliconflow_input_characters": ("day", 100000),
    "azure_stt_seconds": ("month", 14400),
    "azure_tts_characters": ("month", 400000),
    "groq_requests": ("day", 100),
    "groq_token_reservations": ("day", 80000),
}


class AllowanceExceeded(ValueError):
    pass


class CloudAllowance:
    def __init__(self, database: Path, *, connection_factory=None):
        self.database = database
        from edge_hub.storage_context import current_storage
        storage = current_storage()
        if connection_factory is None and storage is not None:
            connection_factory = storage.connect
        self._connection_factory = connection_factory
        if storage is None:
            database.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            if storage is not None:
                # Runtime cloud access is not a migration or an initialization.
                # A missing imported ledger must not silently become zero usage.
                connection.execute('SELECT meter,period,amount FROM usage LIMIT 0')
                return
            connection.execute(
                'CREATE TABLE IF NOT EXISTS usage ('
                'meter TEXT NOT NULL, period TEXT NOT NULL, amount INTEGER NOT NULL, '
                'PRIMARY KEY (meter, period))'
            )

    def _connect(self):
        connect = sqlite3.connect if self._connection_factory is None else self._connection_factory
        return connect(self.database, timeout=10)

    def reserve(self, amounts: dict[str, float], *, now: datetime | None = None) -> None:
        """Atomically reserve all counters or none. Invalid input fails closed."""
        stamp = now or datetime.now(UTC)
        if stamp.tzinfo is None:
            raise ValueError('A timezone-aware timestamp is required')
        stamp = stamp.astimezone(UTC)
        reservations = []
        for meter, amount in amounts.items():
            if meter not in LIMITS or not math.isfinite(amount) or amount <= 0:
                raise ValueError('Invalid allowance reservation')
            interval, maximum = LIMITS[meter]
            period = stamp.strftime('%Y-%m' if interval == 'month' else '%Y-%m-%d')
            reservations.append((meter, period, math.ceil(amount), maximum))
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            for meter, period, amount, maximum in reservations:
                row = connection.execute(
                    'SELECT amount FROM usage WHERE meter=? AND period=?', (meter, period)
                ).fetchone()
                used = row[0] if row else 0
                if type(used) is not int or not 0 <= used < 2**63:
                    raise ValueError('Invalid persisted allowance')
                if used + amount > maximum:
                    raise AllowanceExceeded(f'Local allowance reached: {meter}')
                connection.execute(
                    'INSERT INTO usage VALUES (?, ?, ?) ON CONFLICT(meter, period) '
                    'DO UPDATE SET amount=excluded.amount',
                    (meter, period, used + amount),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
