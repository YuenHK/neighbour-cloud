"""Local staff access journal and conservative 90-day retention planning.

The journal never stores request bodies, query strings, keys or case contents.
Preview never deletes; hardware control and emergency stop never depend on it.
"""
import hashlib
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse


def private_staff_path(path, method):
    if path.startswith(('/api/v1/patrol/events/', '/api/v1/service-desk/resident-memories',
                        '/api/v1/service-desk/knowledge', '/api/v1/assistant/memories')):
        return True
    if path.startswith('/api/v1/service-desk/requests'):
        return method != 'POST'
    return path == '/api/v1/events' or path.startswith('/api/v1/events/')


class AccessJournal:
    def __init__(self, database, *, connection_factory=None):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection_factory = connection_factory
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS staff_access ('
                'id INTEGER PRIMARY KEY,at_ms INTEGER NOT NULL,actor TEXT NOT NULL,'
                'method TEXT NOT NULL,route TEXT NOT NULL,object_hash TEXT NOT NULL,status INTEGER)')

    def connect(self):
        connect = sqlite3.connect if self._connection_factory is None else self._connection_factory
        return connect(self.path, timeout=2)

    def begin(self, method, path, actor='operator'):
        route = re.sub(r'/[a-f0-9]{32}(?=/|$)', '/{id}', path)
        # Hash object-specific path; never the supplied authentication key.
        digest = hashlib.sha256(path.encode()).hexdigest() if route != path else ''
        with closing(self.connect()) as db, db:
            return db.execute('INSERT INTO staff_access(at_ms,actor,method,route,object_hash) VALUES(?,?,?,?,?)',
                              (int(time.time()*1000), actor, method[:8], route[:180], digest)).lastrowid

    def finish(self, identity, status):
        with closing(self.connect()) as db, db:
            db.execute('UPDATE staff_access SET status=? WHERE id=?', (status, identity))

    def recent(self, limit=50):
        with closing(self.connect()) as db, db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM staff_access ORDER BY id DESC LIMIT ?', (limit,))]


def retention_preview(cases, events, *, now_ms=None):
    now = int(time.time()*1000) if now_ms is None else now_ms
    cutoff = now - 90*86400000
    with cases.lock:
        due = cases.db.execute("SELECT COUNT(*) FROM service_cases WHERE status='resolved' AND updated_at_ms<=?", (cutoff,)).fetchone()[0]
    with events._lock:
        observed_date = events._connection.execute('SELECT COUNT(*) FROM event_completion WHERE observed=1').fetchone()[0]
    return {'retention_days': 90, 'clock': 'completion_time', 'due_completed_cases': due,
            'event_completion_date_first_observed': observed_date, 'automatic_deletion_enabled': False,
            'backup_cleanup_verified': False, 'excluded': ['long_term_memories', 'MB842', 'robot_safety_and_audit'],
            'notice': '完成後90日清除個案私人欄位及相片，保留編號存根。舊回報沒有完成日期，保守由首次確認已完成時計90日；不以拍攝日代替。範圍包括本機服務庫及.runtime內可辨認的SQLite備份，不包括外部搬機包、ZIP或手動匯出。'}


class GovernanceMaintenance:
    def __init__(self, cases, events, runtime_root, data_root, journal, backups=None):
        self.cases, self.events = cases, events
        self.runtime, self.data, self.journal = runtime_root, data_root, journal
        self.stop = threading.Event()
        self.backups = backups
        self.thread = None
        self.state = {'last_run_ms': None, 'last_success': None, 'last_error': None}

    def run_once(self):
        from edge_hub.case_retention import expire_cases, expire_event_photos
        record = None
        try:
            record = self.journal.begin('RETENTION', '/maintenance/90-day', 'automatic_policy')
            counts = expire_cases(self.cases, self.runtime)
            photos = expire_event_photos(self.events, self.data, runtime_root=self.runtime)
            self.state = {'last_run_ms': int(time.time()*1000), 'last_success': True, 'last_error': None,
                          **counts, **photos}
            self.journal.finish(record, 200)
            if self.backups:
                self.backups.tick()
        except (OSError, ValueError, sqlite3.Error) as error:
            self.state = {'last_run_ms': int(time.time()*1000), 'last_success': False, 'last_error': type(error).__name__}
            if record is not None:
                try:
                    self.journal.finish(record, 503)
                except sqlite3.Error:
                    pass  # Keep the original unfinished intent, not a false success.

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        def run():
            while not self.stop.is_set():
                self.run_once()
                self.stop.wait(3600)
        self.thread = threading.Thread(target=run, name='local-privacy-retention', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=3)


def governance_router(journal, cases, events, authorize, maintenance=None):
    router = APIRouter(prefix='/api/v1/governance')

    @router.get('/audit')
    def audit(x_operator_key: str | None = Header(default=None), limit: int = Query(default=50, ge=1, le=100)):
        authorize(x_operator_key)
        return JSONResponse({'items': journal.recent(limit)}, headers={'Cache-Control': 'no-store'})

    @router.get('/retention')
    def retention(x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        result = retention_preview(cases, events)
        if maintenance:
            result.update(automatic_deletion_enabled=bool(maintenance.thread and maintenance.thread.is_alive()),
                          maintenance=maintenance.state)
            if maintenance.backups:
                result['backups'] = dict(maintenance.backups.state)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    return router
