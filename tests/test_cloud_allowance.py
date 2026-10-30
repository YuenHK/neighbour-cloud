from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from edge_hub.cloud_allowance import AllowanceExceeded, CloudAllowance


NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def test_persists_across_restart(tmp_path):
    path = tmp_path / 'usage.sqlite3'
    CloudAllowance(path).reserve({'azure_stt_seconds': 14400}, now=NOW)
    with pytest.raises(AllowanceExceeded):
        CloudAllowance(path).reserve({'azure_stt_seconds': 1}, now=NOW)


def test_atomic_reservation_and_round_up(tmp_path):
    meter = CloudAllowance(tmp_path / 'usage.sqlite3')
    meter.reserve({'groq_requests': 100}, now=NOW)
    with pytest.raises(AllowanceExceeded):
        meter.reserve({'azure_stt_seconds': 10, 'groq_requests': 1}, now=NOW)
    meter.reserve({'azure_stt_seconds': 14399.1}, now=NOW)
    with pytest.raises(AllowanceExceeded):
        meter.reserve({'azure_stt_seconds': 0.1}, now=NOW)


def test_new_day_does_not_reset_month(tmp_path):
    meter = CloudAllowance(tmp_path / 'usage.sqlite3')
    meter.reserve({'groq_requests': 100, 'azure_stt_seconds': 14400}, now=NOW)
    tomorrow = datetime(2026, 9, 19, tzinfo=timezone.utc)
    meter.reserve({'groq_requests': 1}, now=tomorrow)
    with pytest.raises(AllowanceExceeded):
        meter.reserve({'azure_stt_seconds': 1}, now=tomorrow)
    meter.reserve({'azure_stt_seconds': 1}, now=datetime(2026, 10, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize('amount', [0, -1, float('nan'), float('inf')])
def test_invalid_amount_rejected(tmp_path, amount):
    meter = CloudAllowance(tmp_path / 'usage.sqlite3')
    with pytest.raises(ValueError):
        meter.reserve({'groq_requests': amount}, now=NOW)


def test_unknown_meter_rejected(tmp_path):
    with pytest.raises(ValueError):
        CloudAllowance(tmp_path / 'usage.sqlite3').reserve({'unknown': 1}, now=NOW)


def test_parallel_requests_do_not_exceed_limit(tmp_path):
    meter = CloudAllowance(tmp_path / 'usage.sqlite3')

    def attempt(_):
        try:
            meter.reserve({'groq_requests': 10}, now=NOW)
            return 1
        except AllowanceExceeded:
            return 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 10
