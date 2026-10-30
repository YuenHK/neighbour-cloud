import hashlib
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
import test_cloud_database_profile

from deploy.cloud.database_profile import ROLE_FILES
from deploy.cloud.deletion_ledger import DeletionLedger
from deploy.cloud.photo_store import PhotoStore
from deploy.cloud.state_store import StateStore
from edge_hub.assistant_memory import MemoryStore
from edge_hub.cloud_allowance import CloudAllowance
from edge_hub.estate_services import EstateStore, KnowledgeEdit
from edge_hub.events import Event, EventStore
from edge_hub.governance import AccessJournal
from edge_hub.service_desk import ResidentCase, ServiceDeskStore

prepared = test_cloud_database_profile.prepared
KEY = b'public-synthetic-signing-key-only-32bytes'
FLAGS = {'azure-voice-control.json': {'paused': True},
         'cloudflare-gemma-quota-stop.json': {'until': '2000-01-01T00:00:00+00:00'},
         'cloudflare-gemma-cooldown.json': {'until': '2000-01-01T00:00:00+00:00', 'reason': 'network'}}


def path(profile, role):
    area, filename = ROLE_FILES[role]
    return (profile.runtime_root if area == 'runtime' else profile.settings_root) / filename


@pytest.fixture
def seeded(prepared):
    profile, runtime, settings, remote, calls = prepared
    cases = ServiceDeskStore(path(profile, 'cases'), connection_factory=profile.connect)
    try:
        first = cases.create(ResidentCase(submission_id='a' * 32, kind='water', message='公開合成案例', confirmed=True))
        assert first['case_number'] == 1
    finally:
        cases.close()
    events = EventStore(path(profile, 'events'), connection_factory=profile.connect)
    try:
        events.add(Event(id='synthetic-event', type='litter_detected', zone='PUBLIC', at_ms=1, severity='notice'))
    finally:
        events.close()
    estate = EstateStore(path(profile, 'estate'), connection_factory=profile.connect)
    try:
        estate.save_knowledge('b' * 32, KnowledgeEdit(title='公開開放時間', keywords=['泳池幾點'], answer='九點開放'))
    finally:
        estate.close()
    memories = MemoryStore(path(profile, 'memory'), connection_factory=profile.connect)
    with memories.connect() as db:
        db.execute('INSERT INTO memories VALUES(?,?,1,1)', ('MB842', 'PUBLIC-SYNTHETIC-MEMORY'))
    journal = AccessJournal(path(profile, 'journal'), connection_factory=profile.connect)
    identity = journal.begin('GET', '/api/v1/events')
    journal.finish(identity, 200)
    CloudAllowance(path(profile, 'usage'), connection_factory=profile.connect).reserve(
        {'azure_tts_characters': 123, 'cloudflare_gemma_neuron_reservations': 456})
    with closing(profile.connect(path(profile, 'controls'))) as db:
        StateStore(db, initialize=True).seed(FLAGS)
    with closing(profile.connect(path(profile, 'photos'))) as db:
        PhotoStore(db)
    with closing(profile.connect(path(profile, 'deletion_ledger'))) as db:
        ledger = DeletionLedger(db, KEY, initialize=True)
        ledger.append([{'kind': 'event', 'target': 'erased-synthetic', 'revision': 1, 'erased_ms': 1}])
    return profile, runtime, settings, remote, calls


def contents(profile):
    output = {}
    for role in ROLE_FILES:
        with closing(profile.connect(path(profile, role).as_uri() + '?mode=ro', uri=True)) as db:
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            value = [(table, [tuple(row) for row in db.execute('SELECT * FROM "' + table + '"')]) for table in tables]
            output[role] = hashlib.sha256(repr(value).encode()).hexdigest()
    return output


def test_explicit_bootstrap_preserves_imported_rows_quota_pause_and_signed_ledger(seeded):
    from deploy.cloud.bootstrap import open_services
    from edge_hub import azure_voice

    profile, runtime, settings, _, _ = seeded
    before = contents(profile)
    services = open_services(profile, signing_key_loader=lambda: KEY)
    try:
        assert services.cases.list()['items'][0]['case_number'] == 1
        assert services.events.get_event('synthetic-event').zone == 'PUBLIC'
        assert services.memory.items()[0]['id'] == 'MB842'
        assert services.estate.knowledge()[0]['answer'] == '九點開放'
        assert services.journal.recent()[0]['status'] == 200
        assert services.ledger.checkpoint()['seq'] == 1
        with services.scope():
            status = azure_voice.status()
            assert status['used'] == 123 and status['paused'] and status['blocked']
        assert services.describe()['site_hardware_created'] is False
        assert services.describe()['public_deployment_ready'] is False
    finally:
        services.close()
    assert before == contents(profile)
    assert list(runtime.iterdir()) == [] and list(settings.iterdir()) == []


def test_bootstrap_connects_csv_provider_and_cleans_all_owned_handles(seeded):
    from deploy.cloud.bootstrap import open_services
    from edge_hub.csv_export import PreparedEventExport

    profile, _, _, _, _ = seeded
    with open_services(profile, signing_key_loader=lambda: KEY) as services:
        export = PreparedEventExport(services.events)
        try:
            assert 'synthetic-event' in ''.join(export)
        finally:
            export.close()
        snapshot = services.events._connection
        memory, journal = services.memory, services.journal
    services.close()
    with pytest.raises(sqlite3.Error):
        snapshot.execute('SELECT 1')
    with pytest.raises(RuntimeError, match='closed'):
        memory.items()
    with pytest.raises(RuntimeError, match='closed'):
        journal.recent()
    with pytest.raises(RuntimeError, match='closed'), services.scope():
        pytest.fail('closed services cannot enter a scope')


def test_failed_constructor_after_open_closes_every_returned_connection(seeded, monkeypatch):
    from deploy.cloud import bootstrap
    from edge_hub.storage_context import current_storage

    profile, _, _, _, _ = seeded
    original, readers = profile.connect, []

    def connect(*a, **kw):
        result = original(*a, **kw)
        readers.append(result)
        return result

    class BrokenEstate:
        def __init__(self, path, *, connection_factory):
            db = connection_factory(path, check_same_thread=False)
            db.execute('SELECT 1')
            raise OSError('PRIVATE-FAILURE-AFTER-OPEN')

    monkeypatch.setattr(profile, 'connect', connect)
    monkeypatch.setattr(bootstrap, 'EstateStore', BrokenEstate)
    try:
        with pytest.raises(bootstrap.CloudStartupError) as error:
            bootstrap.open_services(profile, signing_key_loader=lambda: KEY)
        assert 'PRIVATE' not in str(error.value) and current_storage() is None
        for reader in readers:
            with pytest.raises(sqlite3.Error):
                reader.execute('SELECT 1')
    finally:
        for reader in readers:
            reader.close()


@pytest.mark.parametrize('role', list(ROLE_FILES))
def test_missing_imported_role_rejects_readonly_before_signing_key_or_constructor(seeded, role, monkeypatch):
    from deploy.cloud.bootstrap import REQUIRED, CloudStartupError, open_services

    profile, _, _, _, _ = seeded
    table = next(iter(REQUIRED[role]))
    with closing(profile.connect(path(profile, role))) as db, db:
        db.execute(f'DROP TABLE "{table}"')
    original, calls, keys = profile.connect, [], []

    def connect(*a, **kw):
        calls.append((a, kw))
        return original(*a, **kw)
    monkeypatch.setattr(profile, 'connect', connect)
    with pytest.raises(CloudStartupError):
        open_services(profile, signing_key_loader=lambda: keys.append('requested'))
    assert keys == [] and calls and all(options['uri'] for _, options in calls)
    with closing(original(path(profile, role).as_uri() + '?mode=ro', uri=True)) as db:
        assert db.execute('SELECT name FROM sqlite_master WHERE name=?', (table,)).fetchone() is None


@pytest.mark.parametrize('role,table,column', [('memory', 'memories', 'revision'),
                                             ('estate', 'resident_memories', 'active')])
def test_old_columns_are_not_silently_upgraded_by_runtime(seeded, role, table, column):
    from deploy.cloud.bootstrap import CloudStartupError, open_services

    profile, _, _, _, _ = seeded
    with closing(profile.connect(path(profile, role))) as db, db:
        db.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{column}" TO old_column')
    before = contents(profile)
    with pytest.raises(CloudStartupError):
        open_services(profile, signing_key_loader=lambda: KEY)
    assert contents(profile) == before
    with closing(profile.connect(path(profile, role).as_uri() + '?mode=ro', uri=True)) as db:
        assert column not in {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}


@pytest.mark.parametrize('name', list(FLAGS))
def test_missing_control_never_creates_default_and_no_ledger_key_read(seeded, name):
    from deploy.cloud.bootstrap import CloudStartupError, open_services

    profile, _, _, _, _ = seeded
    with closing(profile.connect(path(profile, 'controls'))) as db, db:
        db.execute('DELETE FROM cloud_state WHERE name=?', (name,))
    before, keys = contents(profile), []
    with pytest.raises(CloudStartupError):
        open_services(profile, signing_key_loader=lambda: keys.append('requested'))
    assert keys == [] and contents(profile) == before


def test_corrupt_signed_ledger_blocks_and_preserves_all_data(seeded):
    from deploy.cloud.bootstrap import CloudStartupError, open_services

    profile, _, _, _, _ = seeded
    before = contents(profile)
    with pytest.raises(CloudStartupError):
        open_services(profile, signing_key_loader=lambda: b'wrong-public-synthetic-key-32bytes')
    assert contents(profile) == before


def test_unexpected_schema_and_elapsed_startup_budget_do_not_create_or_heal(seeded):
    from deploy.cloud.bootstrap import CloudStartupError, open_services

    profile, _, _, _, _ = seeded
    before = contents(profile)
    ticks = iter([0, 30])
    with pytest.raises(CloudStartupError):
        open_services(profile, signing_key_loader=lambda: KEY, clock=lambda: next(ticks))
    assert contents(profile) == before
    with closing(profile.connect(path(profile, 'events'))) as db, db:
        db.execute('CREATE VIEW unreviewed AS SELECT 1')
    with pytest.raises(CloudStartupError):
        open_services(profile, signing_key_loader=lambda: KEY)
    with closing(profile.connect(path(profile, 'events').as_uri() + '?mode=ro', uri=True)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchone()[0] == 'unreviewed'


def test_reopen_uses_existing_short_numbers_and_quota_and_resets_scope(seeded):
    from deploy.cloud.bootstrap import open_services
    from edge_hub.storage_context import current_storage

    profile, _, _, _, _ = seeded
    with open_services(profile, signing_key_loader=lambda: KEY) as first:
        with first.scope():
            CloudAllowance(path(profile, 'usage')).reserve({'azure_tts_characters': 1})
        receipt = first.cases.create(ResidentCase(submission_id='c' * 32, kind='water', message='另一公開合成案例', confirmed=True))
        assert receipt['case_number'] == 2
    with open_services(profile, signing_key_loader=lambda: KEY) as second:
        assert second.cases.progress('2')
        assert second.memory.items()[0]['id'] == 'MB842'
        with second.scope():
            from edge_hub.azure_voice import status
            assert status()['used'] == 124 and status()['paused']
    assert current_storage() is None


def test_import_is_hardware_free_and_opens_no_database_or_network_in_fresh_process():
    script = """
import sys
def audit(event, args):
    if event in ('sqlite3.connect', 'socket.connect'):
        raise AssertionError('bootstrap import must not open DB or network')
sys.addaudithook(audit)
import deploy.cloud.bootstrap
for name in ('edge_hub.app','edge_hub.ep_fleet','edge_hub.robot_control',
             'edge_hub.vision_runtime','local_audio_gateway.app','ep_runtime.dji'):
    assert name not in sys.modules, name
assert not any(name.startswith(('ep_runtime.', 'robomaster', 'edge_hub.ep_')) for name in sys.modules)
print('hardware_free_no_network_no_database')
"""
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'hardware_free_no_network_no_database'


@pytest.mark.parametrize('fault', ['case_number_binding', 'stream_identity', 'event_sequence', 'completion_time'])
def test_missing_imported_identity_and_completion_metadata_never_auto_heal(seeded, fault):
    from deploy.cloud.bootstrap import CloudStartupError, open_services

    profile, _, _, _, _ = seeded
    role = 'cases' if fault == 'case_number_binding' else 'events'
    if fault == 'completion_time':
        events = EventStore(path(profile, role), connection_factory=profile.connect)
        events.update_status('synthetic-event', 'resolved')
        events.close()
    table = {'case_number_binding': 'service_case_numbers', 'stream_identity': 'event_stream_metadata',
             'event_sequence': 'event_ingest_sequence', 'completion_time': 'event_completion'}[fault]
    with closing(profile.connect(path(profile, role))) as db, db:
        db.execute(f'DELETE FROM "{table}"')
    before = contents(profile)
    with pytest.raises(CloudStartupError):
        services = open_services(profile, signing_key_loader=lambda: KEY)
        services.close()
    assert contents(profile) == before
