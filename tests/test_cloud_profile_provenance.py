import copy
import sqlite3
from types import SimpleNamespace

import pytest
import test_cloud_database_profile

from deploy.cloud.database_profile import DatabaseProfile

prepared = test_cloud_database_profile.prepared


def api_manifest():
    value = test_cloud_database_profile.manifest()
    value.pop('ui_verified')
    value['format'] = 'neighbour-cloud-storage-v2'
    value['plan_verification'] = {'source': 'turso-platform-api', 'organization': 'public-test',
        'plan_id': 'starter', 'monthly_price': '0', 'overages': False,
        'checked_utc': '2026-10-30T05:00:00+00:00', 'receipt_sha256': 'a' * 64}
    for entry in value['databases'].values():
        entry['read_credential'] = 'turso-read-token'
    return value


def test_api_provenance_does_not_require_or_claim_ui_inspection(prepared):
    _, runtime, settings, _, calls = prepared
    profile = DatabaseProfile(api_manifest(), runtime_root=runtime, settings_root=settings)
    assert profile.runtime_root == runtime.resolve() and calls == []


@pytest.mark.parametrize(('key', 'value'), [('source', 'unverified'), ('organization', '../other'),
    ('plan_id', 'trial'), ('monthly_price', '5.99'), ('overages', True),
    ('receipt_sha256', 'bad'), ('checked_utc', '2026-10-30T05:00:00'), ('checked_utc', 'invalid')])
def test_api_provenance_rejects_paid_trial_overage_or_missing_evidence(prepared, key, value):
    _, runtime, settings, _, calls = prepared
    info = api_manifest()
    info['plan_verification'][key] = value
    with pytest.raises(ValueError, match='explicit_complete_free_cloud_database_profile_required'):
        DatabaseProfile(info, runtime_root=runtime, settings_root=settings)
    assert calls == []


def test_v1_ui_marker_and_v2_api_provenance_cannot_be_mixed(prepared):
    _, runtime, settings, _, _ = prepared
    info = api_manifest()
    info['ui_verified'] = True
    with pytest.raises(ValueError):
        DatabaseProfile(info, runtime_root=runtime, settings_root=settings)
    info = copy.deepcopy(info)
    info.pop('ui_verified')
    info['plan_verification']['api_key'] = 'public-invalid-field'
    with pytest.raises(ValueError):
        DatabaseProfile(info, runtime_root=runtime, settings_root=settings)


def test_v2_remote_read_only_uses_dedicated_provider_token_and_no_query_only_pragma(prepared):
    _, runtime, settings, _, _ = prepared
    calls, loaded = [], []

    class Remote:
        def execute(self, sql, parameters=()):
            calls.append(sql)
            if sql.startswith('PRAGMA'):
                raise ValueError('SQL not allowed statement')
            if sql.startswith('UPDATE'):
                raise sqlite3.OperationalError('provider denies writes using read-only token')
            return sqlite3.connect(':memory:').execute(sql, parameters)

        def close(self):
            pass

    def connect(url, **options):
        assert options['auth_token'] == 'public-synthetic-read-only-token'
        return Remote()

    profile = DatabaseProfile(api_manifest(), runtime_root=runtime, settings_root=settings,
        secret_loader=lambda: loaded.append('writer'),
        read_secret_loader=lambda: b'public-synthetic-read-only-token',
        driver_loader=lambda: SimpleNamespace(Error=sqlite3.Error, connect=connect))
    db = profile.connect((runtime / 'service-desk.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        assert db.execute('SELECT 1').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute('UPDATE public_table SET value=0')
    finally:
        db.close()
    assert loaded == [] and not any(sql.startswith('PRAGMA') for sql in calls)


def test_v2_missing_read_credential_never_uses_writer_or_opens_driver(prepared):
    _, runtime, settings, _, calls = prepared
    loaded = []

    def missing():
        raise RuntimeError('public-synthetic-unavailable')

    profile = DatabaseProfile(api_manifest(), runtime_root=runtime, settings_root=settings,
        secret_loader=lambda: loaded.append('writer'), read_secret_loader=missing,
        driver_loader=lambda: calls.append('driver'))
    with pytest.raises(ValueError, match='cloud_database_credential_unavailable'):
        profile.connect((runtime / 'service-desk.sqlite3').as_uri() + '?mode=ro', uri=True)
    assert loaded == [] and calls == []


@pytest.mark.parametrize('binding', [None, 'turso-data-token', 'unapproved-secret'])
def test_v2_requires_explicit_read_only_reference(prepared, binding):
    _, runtime, settings, _, calls = prepared
    info = api_manifest()
    if binding is None:
        info['databases']['cases'].pop('read_credential')
    else:
        info['databases']['cases']['read_credential'] = binding
    with pytest.raises(ValueError, match='invalid_cloud_database_binding'):
        DatabaseProfile(info, runtime_root=runtime, settings_root=settings)
    assert calls == []
