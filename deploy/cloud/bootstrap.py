"""Explicit, hardware-free component assembly for the cloud candidate.

This is not an ASGI entrypoint or a migration. It checks existing imported
schemas and flags before constructing stores, never opens edge_hub.app, and
never starts worker threads, model requests or hardware. Checks across DBs are
not atomic: verified cutover/one writer, authentication, durable backup and
HTTP/media integration are still separate release gates.
"""
import math
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
from types import SimpleNamespace

from deploy.cloud.database_profile import ROLE_FILES, DatabaseProfile
from deploy.cloud.deletion_ledger import DeletionLedger
from deploy.cloud.event_export import EventExportSnapshot
from deploy.cloud.photo_store import PhotoStore
from deploy.cloud.runtime_storage import RuntimeStorage
from deploy.cloud.state_store import NAMES, StateStore
from edge_hub.assistant_memory import MemoryCapabilities, MemoryStore
from edge_hub.cloud_allowance import CloudAllowance
from edge_hub.estate_services import EstateStore, ResidentServices
from edge_hub.events import EventStore
from edge_hub.governance import AccessJournal
from edge_hub.service_desk import ServiceDeskStore
from edge_hub.storage_context import use_storage

# Minimum current columns prevent constructors silently creating/upgrading an
# empty or old schema. These checks do not replace an authenticated import
# receipt, data fingerprints, external ledger freshness or one-writer proof.
REQUIRED = {
    'cases': {
        'service_cases': 'id submission_id fingerprint kind location message contact status revision created_at_ms updated_at_ms assignee note contact_preference intake_mode due_at_ms profile case_number team unit',
        'service_case_activity': 'id case_id status at_ms assignee note',
        'service_case_numbers': 'ordinal case_id',
        'patrol_case_links': 'event_id case_id desired_status sync_pending',
        'resident_session_cases': 'session_hash case_id topic last_turn',
        'resident_session_turns': 'seq session_hash turn_id case_id fingerprint',
        'resident_support_links': 'submission_id case_id'},
    'events': {'events': 'id type zone at_ms severity evidence details_json status',
               'event_stream_metadata': 'id stream_id', 'event_ingest_sequence': 'seq event_id',
               'event_completion': 'event_id completed_at_ms observed'},
    'estate': {'estate_knowledge': 'id title keywords answer enabled revision updated_ms',
               'estate_knowledge_history': 'id knowledge_id content at_ms',
               'resident_memories': 'id profile text created_ms active'},
    'memory': {'memories': 'id text revision updated_ms'},
    'journal': {'staff_access': 'id at_ms actor method route object_hash status'},
    'usage': {'usage': 'meter period amount'},
    'controls': {'cloud_state': 'name payload revision updated_ms'},
    'photos': {'cloud_photos': 'key event_id side digest content created_ms',
               'cloud_photo_tombstones': 'key event_id erased_ms',
               'cloud_photo_retention': 'event_id revision status completed_ms',
               'cloud_erased_events': 'event_id erased_ms'},
    'deletion_ledger': {'cloud_deletion_receipts': 'seq identity previous digest payload',
                        'cloud_deletion_head': 'id seq digest signature'}
}


class CloudStartupError(RuntimeError):
    pass


def verify_identity_rows(db, role):
    """Reject metadata that native first-run migrations would recreate."""
    if (role == 'cases' and db.execute(
            "SELECT 1 FROM service_cases c WHERE typeof(c.case_number)!='integer' OR c.case_number<1 "
            "OR (SELECT COUNT(*) FROM service_case_numbers n WHERE n.case_id=c.id "
            "AND typeof(n.ordinal)='integer' AND n.ordinal>0)!=1 LIMIT 1").fetchone()):
        raise ValueError('cloud_case_number_binding_missing')
    if role == 'events':
        rows = db.execute('SELECT id,stream_id FROM event_stream_metadata LIMIT 2').fetchall()
        if (len(rows) != 1 or rows[0][0] != 1 or not isinstance(rows[0][1], str)
                or not re.fullmatch('[a-f0-9]{32}', rows[0][1])):
            raise ValueError('cloud_event_stream_identity_missing')
        if db.execute("SELECT 1 FROM events e WHERE (SELECT COUNT(*) FROM event_ingest_sequence s "
                      "WHERE s.event_id=e.id AND typeof(s.seq)='integer' AND s.seq>0)!=1 LIMIT 1").fetchone():
            raise ValueError('cloud_event_sequence_missing')
        if db.execute("SELECT 1 FROM events e WHERE e.status IN ('resolved','false_positive') AND NOT EXISTS "
                      "(SELECT 1 FROM event_completion c WHERE c.event_id=e.id "
                      "AND typeof(c.completed_at_ms)='integer' AND c.completed_at_ms>=0 AND c.observed IN (0,1)) LIMIT 1").fetchone():
            raise ValueError('cloud_event_completion_missing')


class CloudServices:
    def __init__(self):
        self.closed = True
        self._stack = ExitStack()

    def _active(self):
        if self.closed:
            raise RuntimeError('cloud_services_closed')

    @contextmanager
    def scope(self):
        self._active()
        with use_storage(self.storage):
            yield self

    def describe(self):
        return {'components_open': not self.closed, 'site_hardware_created': False,
                'public_deployment_ready': False, 'native_app_selected': False}

    def close(self):
        if not self.closed:
            self.closed = True  # Also fences later lazy memory/journal opens.
            self._stack.close()

    def __enter__(self):
        self._active()
        return self

    def __exit__(self, kind, value, traceback):
        self.close()
        return False


def open_services(profile, *, signing_key_loader, scratch_root=None, timeout=20, clock=None,
                  validation_workers=1):
    """Assemble existing components only after checks; requires a fenced cutover."""
    if (not isinstance(profile, DatabaseProfile) or not callable(signing_key_loader)
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60
            or (clock is not None and not callable(clock))
            or type(validation_workers) is not int or not 1 <= validation_workers <= 4):
        raise ValueError('explicit_cloud_startup_configuration_required')
    stamp = clock or time.monotonic
    deadline = stamp() + timeout
    owner = CloudServices()
    owner.closed = False
    preparing = True

    def check():
        if stamp() >= deadline:
            raise TimeoutError('cloud_startup_budget_exceeded')

    def connect(*args, **kwargs):
        owner._active()
        db = profile.connect(*args, **kwargs)
        if preparing:
            # A constructor may raise after opening a handle but before
            # returning an object whose close() could be registered.
            stack.callback(db.close)
        return db

    paths = {role: (profile.runtime_root if area == 'runtime' else profile.settings_root) / filename
             for role, (area, filename) in ROLE_FILES.items()}

    def verify_role(item):
        role, path = item
        # Each independent reader is closed by its own worker, even if a
        # different role fails. No constructor, migration or writer runs.
        with closing(profile.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            check()
            # SQLite's table-valued PRAGMAs let the remote primary return the
            # same schema, column, integrity and FK checks in one round trip.
            # Keep the result categories separate; empty/malformed integrity
            # evidence is never success.
            rows = db.execute("SELECT 'schema',type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                "UNION ALL SELECT 'column',m.name,p.name FROM sqlite_master m "
                "JOIN pragma_table_info(m.name) p WHERE m.type='table' AND m.name NOT LIKE 'sqlite_%' "
                "UNION ALL SELECT 'quick',quick_check,NULL FROM pragma_quick_check "
                "UNION ALL SELECT 'foreign',\"table\",parent FROM pragma_foreign_key_check").fetchall()
            if any(row[0] not in ('schema', 'column', 'quick', 'foreign') for row in rows):
                raise ValueError('cloud_imported_metadata_invalid')
            schema = [(row[1], row[2]) for row in rows if row[0] == 'schema']
            if any(row[0] not in ('table', 'index') for row in schema):
                raise ValueError('cloud_schema_requires_review')
            tables = {row[1] for row in schema if row[0] == 'table'}
            if not set(REQUIRED[role]).issubset(tables):
                raise ValueError('cloud_imported_schema_missing')
            actual = {}
            for category, table, column in rows:
                if category == 'column':
                    actual.setdefault(table, set()).add(column)
            for table, columns in REQUIRED[role].items():
                if not set(columns.split()).issubset(actual.get(table, set())):
                    raise ValueError('cloud_imported_columns_missing')
            if ([row[1] for row in rows if row[0] == 'quick'] != ['ok']
                    or any(row[0] == 'foreign' for row in rows)):
                raise ValueError('cloud_imported_integrity_failed')
            verify_identity_rows(db, role)
            check()

    try:
        with ExitStack() as stack:
            # All checks finish before constructors. A bounded optional pool
            # overlaps independent network reads, never writes or migrations.
            if validation_workers == 1:
                for item in paths.items():
                    check()
                    verify_role(item)
            else:
                with ThreadPoolExecutor(max_workers=validation_workers, thread_name_prefix='cloud-preflight') as pool:
                    for _ in pool.map(verify_role, paths.items()):
                        check()

            def owned(role):
                check()
                db = connect(paths[role], check_same_thread=False)
                stack.callback(db.close)
                return db

            controls = StateStore(owned('controls'))  # No initialize flag/defaults.
            for name in sorted(NAMES):
                controls.read(name)
            ledger = DeletionLedger(owned('deletion_ledger'), signing_key_loader())
            photos = PhotoStore(owned('photos'), initialize=False)
            storage = RuntimeStorage(SimpleNamespace(settings_root=profile.settings_root, connect=connect), controls)
            with use_storage(storage):
                CloudAllowance(paths['usage'])  # Runtime mode forbids empty-table creation.
                check()
                cases = ServiceDeskStore(paths['cases'], connection_factory=connect, initialize=False)
                stack.callback(cases.close)
                check()
                estate = EstateStore(paths['estate'], connection_factory=connect, initialize=False)
                stack.callback(estate.close)
                check()
                exports = EventExportSnapshot(paths['events'], connection_factory=connect, scratch_root=scratch_root)
                events = EventStore(paths['events'], connection_factory=connect, export_snapshot_factory=exports,
                                    initialize=False)
                stack.callback(events.close)
                memory = MemoryStore(paths['memory'], connection_factory=connect, initialize=False)
                memory.items()  # Exercise the lazy path under the same factory.
                journal = AccessJournal(paths['journal'], connection_factory=connect, initialize=False)
                journal.recent(1)
                check()
            owner.cases, owner.estate, owner.events = cases, estate, events
            owner.memory, owner.journal = memory, journal
            owner.ledger, owner.photos, owner.storage = ledger, photos, storage
            owner.residents = ResidentServices(estate, cases)
            owner.memory_capabilities = MemoryCapabilities()
            preparing = False  # Later lazy operations own/close their connections.
            owner._stack = stack.pop_all()
        return owner
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, sqlite3.Error):
        owner.closed = True
        raise CloudStartupError('cloud_startup_requires_verified_import_and_state') from None
    except BaseException:
        owner.closed = True
        raise
