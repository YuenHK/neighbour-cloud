import sqlite3

from edge_hub.quota_overview import counter, overview


def test_percentage_is_remaining_and_unknown_is_not_zero():
    assert counter(13, 1000)['percent'] == 98.7
    for used, limit in ((None,100), (True,100), (0,0), (-1,100), (0,True)):
        assert counter(used,limit)['percent'] is None
    assert counter(110,100)['percent'] == 0


def test_official_snapshot_and_local_limits_are_distinct_and_include_both_budgets(tmp_path):
    from datetime import UTC, datetime
    path = tmp_path/'usage.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE usage(meter TEXT,period TEXT,amount INTEGER)')
        period = datetime.now(UTC).strftime('%Y-%m-%d')
        db.executemany('INSERT INTO usage VALUES (?,?,?)', [('gemini_chat_requests',period,20),('gemini_chat_characters',period,190000)])
    result = overview({'status':'stale','updated_at_ms':1000,'data':{'used':13,'limit':1000,'key_used':90,'key_limit':100}}, voice_configured=True, database=path)
    rows = {row['id']:row for row in result['rows']}
    assert rows['tavily']['provider']['percent'] == 98.7
    assert rows['tavily']['provider']['status'] == 'stale'
    assert rows['tavily-key']['provider']['percent'] == 10
    assert rows['google-chat']['provider']['percent'] is None
    assert rows['google-chat']['guard']['percent'] == 5
    assert len(rows['google-chat']['guard']['counters']) == 2
    assert 'local' not in rows and 'siliconflow-balance' not in rows


def test_broken_local_database_cannot_be_displayed_as_unused_quota(tmp_path):
    path = tmp_path/'broken.sqlite3'
    path.write_bytes(b'not a database')
    result = overview({'status':'unavailable','data':None},voice_configured=False,database=path)
    rows = {row['id']:row for row in result['rows']}
    assert rows['tavily']['provider']['percent'] is None
    assert rows['google-chat']['guard']['percent'] is None
    assert rows['google-chat']['guard']['status'] == 'unavailable'
    assert rows['google-voice']['provider']['status'] == 'not_configured'


def test_active_inventory_reads_monthly_voice_separately_and_reports_exact_local_reset(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from edge_hub import azure_voice, cloudflare_gemma
    monkeypatch.setattr(cloudflare_gemma, 'selected', lambda: True)
    monkeypatch.setattr(azure_voice, 'configured', lambda: True)
    path = tmp_path/'usage.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE usage(meter TEXT,period TEXT,amount INTEGER)')
        db.executemany('INSERT INTO usage VALUES (?,?,?)', [
            ('cloudflare_gemma_neuron_reservations', '2026-12-31', 534),
            ('azure_tts_characters', '2026-12', 785),
            ('azure_tts_characters', '2026-12-31', 99999)])
    result = overview({'status':'ok','data':{'used':35,'limit':1000}}, voice_configured=True,
        database=path, now=datetime(2026,12,31,23,tzinfo=UTC))
    rows = {row['id']: row for row in result['active_rows']}
    assert set(rows) == {'tavily', 'cloudflare-gemma', 'azure-voice'}
    voice = rows['azure-voice']
    assert voice['guard']['counters'][0]['remaining'] == 399215
    assert voice['guard']['interval'] == 'month'
    assert voice['guard']['reset_at'] == '2027-01-01T00:00:00Z'
    assert '2027-01-01 08:00' in voice['guard']['period']
    assert voice['provider']['percent'] is None and '500,000' in voice['provider']['allocation']
    assert '時刻' in rows['tavily']['reset_label'] and '2027-01-01' in rows['tavily']['reset_label']
    assert 'google-chat' in {row['id'] for row in result['other_rows']}
