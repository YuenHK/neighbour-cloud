import copy
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from deploy.cloud.database_profile import ROLE_FILES, DatabaseProfile
from edge_hub.assistant_memory import MemoryStore
from edge_hub.cloud_allowance import AllowanceExceeded, CloudAllowance
from edge_hub.estate_services import EstateStore, KnowledgeEdit
from edge_hub.events import Event, EventStore
from edge_hub.governance import AccessJournal
from edge_hub.service_desk import ResidentCase, ServiceDeskStore


def manifest():
    return {'format': 'neighbour-cloud-storage-v1', 'provider': 'turso-libsql', 'plan': 'Free',
            'ui_verified': True, 'mode': 'remote-primary',
            'databases': {role: {'url': 'libsql://synthetic-' + role.replace('_', '-') + '.turso.io',
                                 'credential': 'turso-data-token'} for role in ROLE_FILES}}


@pytest.fixture(params=['sqlite', 'libsql'])
def prepared(tmp_path, request):
    root = tmp_path / 'cloud'
    runtime, settings, remote = (root / name for name in ('runtime', 'settings with %20', 'remote'))
    for directory in (runtime, settings, remote):
        directory.mkdir(parents=True)
    native = sqlite3
    if request.param == 'libsql':
        native = pytest.importorskip('libsql')
    calls = []
    urls = {entry['url']: role for role, entry in manifest()['databases'].items()}

    def connect(url, **kwargs):
        calls.append(url)
        assert kwargs['auth_token'] == 'synthetic-test-turso-token'
        path = remote / (urls[url] + '.sqlite3')
        if request.param == 'libsql':
            return native.connect(str(path), timeout=kwargs['timeout'], _check_same_thread=kwargs['_check_same_thread'])
        return sqlite3.connect(path, timeout=kwargs['timeout'], check_same_thread=kwargs['_check_same_thread'])
    driver = SimpleNamespace(Error=native.Error, connect=connect)
    profile = DatabaseProfile(manifest(), runtime_root=runtime, settings_root=settings,
                              secret_loader=lambda: b'synthetic-test-turso-token', driver_loader=lambda: driver)
    return profile, runtime, settings, remote, calls


def test_real_stores_with_explicit_factory_reopen_and_never_create_local_db(prepared):
    profile, runtime, settings, _, calls = prepared
    cases = ServiceDeskStore(runtime / 'service-desk.sqlite3', connection_factory=profile.connect)
    try:
        first = cases.create(ResidentCase(submission_id='a' * 32, kind='water', message='PUBLIC-CASE', confirmed=True))
        assert first['case_number'] == 1
    finally:
        cases.close()
    cases = ServiceDeskStore(runtime / 'service-desk.sqlite3', connection_factory=profile.connect)
    try:
        assert cases.list()['items'][0]['message'] == 'PUBLIC-CASE'
        assert cases.create(ResidentCase(submission_id='b' * 32, kind='litter', message='PUBLIC-NEXT', confirmed=True))['case_number'] == 2
    finally:
        cases.close()
    memory = MemoryStore(runtime / 'assistant-memory.sqlite3', connection_factory=profile.connect)
    memory.remember('PUBLIC-EXPLICIT-MEMORY')
    assert MemoryStore(runtime / 'assistant-memory.sqlite3', connection_factory=profile.connect).items()[0]['text'] == 'PUBLIC-EXPLICIT-MEMORY'
    facts = EstateStore(runtime / 'estate-information.sqlite3', connection_factory=profile.connect)
    try:
        facts.save_knowledge('a' * 32, KnowledgeEdit(title='泳池', keywords=['泳池幾點'], answer='九點開放'))
        facts.prepare_index()
        assert facts.knowledge()[0]['revision'] == 1
    finally:
        facts.close()
    assert list(runtime.iterdir()) == [] and list(settings.iterdir()) == []
    assert len(calls) >= 4


def test_event_stream_identity_staff_journal_and_state_survive_reopen(prepared):
    profile, runtime, _, _, _ = prepared
    path = runtime / 'events.sqlite3'
    events = EventStore(path, connection_factory=profile.connect)
    events.add(Event(id='synthetic', type='litter_detected', zone='PUBLIC-ZONE', at_ms=1, severity='notice'))
    events.update_status('synthetic', 'confirmed')
    stream = events._connection.execute('SELECT stream_id FROM event_stream_metadata').fetchone()[0]
    events.close()
    events = EventStore(path, connection_factory=profile.connect)
    try:
        assert events.get_event('synthetic').status == 'confirmed'
        assert events._connection.execute('SELECT stream_id FROM event_stream_metadata').fetchone()[0] == stream
    finally:
        events.close()
    journal = AccessJournal(runtime / 'staff-access.sqlite3', connection_factory=profile.connect)
    request_id = journal.begin('PATCH', '/api/v1/events/' + 'a' * 32)
    journal.finish(request_id, 200)
    assert AccessJournal(runtime / 'staff-access.sqlite3', connection_factory=profile.connect).recent()[0]['status'] == 200
    assert not any(runtime.iterdir())


def test_quota_counter_uses_same_remote_primary_after_restart_and_readonly_uri(prepared):
    profile, _, settings, _, _ = prepared
    now = datetime(2026, 10, 29, tzinfo=UTC)
    path = settings / 'cloud-usage.sqlite3'
    CloudAllowance(path, connection_factory=profile.connect).reserve(
        {'cloudflare_gemma_neuron_reservations': 8000, 'azure_tts_characters': 400000}, now=now)
    with pytest.raises(AllowanceExceeded):
        CloudAllowance(path, connection_factory=profile.connect).reserve({'cloudflare_gemma_neuron_reservations': 1}, now=now)
    tomorrow = datetime(2026, 10, 30, tzinfo=UTC)
    CloudAllowance(path, connection_factory=profile.connect).reserve({'cloudflare_gemma_neuron_reservations': 1}, now=tomorrow)
    with pytest.raises(AllowanceExceeded):
        CloudAllowance(path, connection_factory=profile.connect).reserve({'azure_tts_characters': 1}, now=tomorrow)
    connection = profile.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        assert connection.execute('SELECT amount FROM usage WHERE meter=? AND period=?',
                                  ('azure_tts_characters', '2026-10')).fetchone()[0] == 400000
        with pytest.raises(sqlite3.OperationalError):
            connection.execute('UPDATE usage SET amount=0')
    finally:
        connection.close()
    assert not path.exists()


def test_unbound_local_data_and_unsafe_uris_do_not_load_secret_or_driver(prepared, tmp_path):
    profile, runtime, _, _, calls = prepared
    cases = runtime / 'service-desk.sqlite3'
    cases.write_bytes(b'PRESERVE-EXISTING-DATA')
    for value, options in ((cases, {}), (tmp_path / 'service-desk.sqlite3', {}),
                           (runtime / 'ep-control-ep-2.sqlite3', {}),
                           ('service-desk.sqlite3', {}), (':memory:', {}),
                           (cases.as_uri() + '?mode=ro&cache=shared', {'uri': True})):
        with pytest.raises(ValueError):
            profile.connect(value, **options)
    assert calls == [] and cases.read_bytes() == b'PRESERVE-EXISTING-DATA'


@pytest.mark.parametrize('url', ['https://example.turso.io', 'libsql://127.0.0.1',
                                'libsql://user:SECRET@example.turso.io', 'libsql://example.turso.io:443',
                                'libsql://example.turso.io/path', 'libsql://example.turso.io/?token=SECRET',
                                'libsql://example.turso.io.evil.invalid'])
def test_endpoint_validation_refuses_credential_leak_or_unapproved_host(tmp_path, url):
    runtime, settings = tmp_path / 'runtime', tmp_path / 'settings'
    runtime.mkdir()
    settings.mkdir()
    data = manifest()
    data['databases']['cases']['url'] = url
    with pytest.raises(ValueError) as caught:
        DatabaseProfile(data, runtime_root=runtime, settings_root=settings)
    assert 'SECRET' not in str(caught.value)


def test_complete_free_profile_and_distinct_ledger_endpoint_are_mandatory(tmp_path):
    runtime, settings = tmp_path / 'runtime', tmp_path / 'settings'
    runtime.mkdir()
    settings.mkdir()
    for mutate in (lambda data: data.update(plan='Paid'), lambda data: data.update(mode='embedded-replica'),
                   lambda data: data['databases'].pop('usage'),
                   lambda data: data['databases'].update(deletion_ledger=copy.deepcopy(data['databases']['photos']))):
        data = manifest()
        mutate(data)
        with pytest.raises(ValueError):
            DatabaseProfile(data, runtime_root=runtime, settings_root=settings)


def test_json_duplicate_keys_are_not_silently_accepted(tmp_path):
    profile = tmp_path / 'bad.json'
    profile.write_text('{"plan":"Free","plan":"Paid"}')
    with pytest.raises(ValueError, match='invalid_cloud_profile_file'):
        DatabaseProfile.from_file(profile, runtime_root=tmp_path, settings_root=tmp_path)


def test_driver_or_secret_error_never_exposes_credential_or_falls_back(prepared, monkeypatch):
    profile, runtime, _, _, calls = prepared
    def fail():
        raise RuntimeError('PRIVATE-TEST-CREDENTIAL')
    monkeypatch.setattr(profile, '_secret_loader', fail)
    with pytest.raises(ValueError) as caught:
        profile.connect(runtime / 'service-desk.sqlite3')
    assert str(caught.value) == 'cloud_database_credential_unavailable'
    assert calls == [] and not (runtime / 'service-desk.sqlite3').exists()


def test_readonly_initialization_failure_closes_driver_and_masks_provider_error(prepared, monkeypatch):
    profile, _, settings, _, _ = prepared
    closed = []
    class FailedSession:
        def execute(self, *args):
            raise sqlite3.OperationalError('PRIVATE-TEST-PROVIDER-ERROR')
        def close(self):
            closed.append(True)
    driver = SimpleNamespace(Error=sqlite3.Error, connect=lambda *args, **kwargs: FailedSession())
    monkeypatch.setattr(profile, '_driver_loader', lambda: driver)
    with pytest.raises(ValueError) as caught:
        profile.connect((settings / 'cloud-usage.sqlite3').as_uri() + '?mode=ro', uri=True)
    assert str(caught.value) == 'cloud_database_connection_unavailable'
    assert closed == [True]


def test_manifest_mutation_after_validation_cannot_retarget_connections(prepared):
    original, runtime, _, _, calls = prepared
    data = manifest()
    profile = DatabaseProfile(data, runtime_root=runtime, settings_root=runtime.parent / 'settings with %20',
                              secret_loader=original._secret_loader, driver_loader=original._driver_loader)
    data['databases']['cases']['url'] = 'libsql://other-account.turso.io'
    connection = profile.connect(runtime / 'service-desk.sqlite3')
    connection.close()
    assert calls == ['libsql://synthetic-cases.turso.io']


def test_memory_initialization_failure_closes_injected_connection(tmp_path):
    closed = []
    class Broken:
        def execute(self, *args):
            raise sqlite3.OperationalError('synthetic_unavailable')
        def close(self):
            closed.append(True)
    store = MemoryStore(tmp_path / 'memory.sqlite3', connection_factory=lambda *a, **k: Broken())
    with pytest.raises(sqlite3.OperationalError):
        store.items()
    assert closed == [True]
