"""Durable patrol -> numbered staff case -> event status mirror. No robot calls."""
import hashlib
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from edge_hub.service_desk import ResidentCase, ReviewCase, local_resident_request


class PatrolFollowup:
    def __init__(self, events, cases, data_root=None):
        self.events, self.cases = events, cases
        self.data_root = Path(data_root) if data_root is not None else None
        cases.patrol_sync = self.flush_case

    def ensure(self, event):
        if (event.details.get('source') != 'ep_patrol_local' or event.details.get('is_test') is True
                or not re.fullmatch('[a-f0-9]{32}', event.id)):
            raise ValueError('not an eligible patrol event')
        if event.status in ('resolved', 'false_positive'):
            # Never recreate a completed/expired historical report as a new case.
            with self.cases.lock:
                return self._link(event.id)
        kind = {'litter_detected':'litter', 'leak_detected':'water', 'smoke_fire_candidate':'hazard',
                'electrical_visual_candidate':'hazard', 'access_candidate':'general'}.get(event.type)
        if kind is None:
            raise ValueError('invalid patrol type')
        with self.cases.lock:
            existing = self._link(event.id)
            if existing:
                return existing
            if self.data_root is not None:
                photos = event.details.get('photos', [])
                if len(photos) != 3 or {photo.get('side') for photo in photos} != {'event','left','right'}:
                    raise ValueError('complete photo bundle required')
                for photo in photos:
                    path = (self.data_root/photo['path']).resolve()
                    if (not path.is_relative_to((self.data_root/'events/ep-patrol').resolve())
                            or not path.is_file() or path.stat().st_size > 350000
                            or hashlib.sha256(path.read_bytes()).hexdigest() != photo['sha256']):
                        raise ValueError('photo bundle unavailable')
            request = ResidentCase(submission_id=hashlib.sha256(('patrol-case:'+event.id).encode()).hexdigest()[:32],
                kind=kind, location=event.zone[:120],
                message=(f'【巡查候選・待核實】{event.details.get("caption", "請查看現場相片核實。")}\n'
                         f'機體 SN：{event.details.get("robot_sn", "未提供")}。已附事件及左右環境相片；尚未代表已確認危險。')[:2000],
                confirmed=True)
            receipt = self.cases.create(request)
            desired = {'new':'pending', 'acknowledged':'confirmed', 'resolved':'resolved'}[receipt['status']]
            if not receipt['replayed'] and event.status == 'confirmed':
                self.cases.review(receipt['id'], ReviewCase(expected_revision=1,status='acknowledged'))
                desired = 'confirmed'
            with self.cases.db:
                self.cases.db.execute('INSERT OR IGNORE INTO patrol_case_links(event_id,case_id,desired_status) VALUES (?,?,?)',
                                      (event.id, receipt['id'], desired))
            self.flush_case(receipt['id'])
            return self._link(event.id)

    def _link(self, event_id):
        row = self.cases.db.execute('SELECT l.*,c.case_number,c.revision,c.status,c.note,c.team FROM patrol_case_links l '
                                    'JOIN service_cases c ON c.id=l.case_id WHERE l.event_id=?', (event_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['case_number'] = self.cases.case_number({'id': row['case_id'], 'case_number': row['case_number']})
        return result

    def snapshot(self, event_ids=None):
        with self.cases.lock:
            where = ' WHERE l.event_id IN ('+','.join('?' for _ in event_ids)+')' if event_ids else ''
            ids = self.cases.db.execute('SELECT l.event_id FROM patrol_case_links l JOIN service_cases c ON c.id=l.case_id '
                                       +where+" ORDER BY CASE c.status WHEN 'resolved' THEN 1 ELSE 0 END,c.created_at_ms DESC LIMIT 100",
                                       event_ids or []).fetchall()
            result = [self._link(row[0]) for row in ids]
            for row in result:
                if len(row['note']) > 160:
                    row['note'] = row['note'][:160]+'…'
            return result

    def flush_case(self, case_id):
        # Holding the case lock prevents a late older mirror from overwriting a newer review.
        with self.cases.lock:
            link = self.cases.db.execute('SELECT * FROM patrol_case_links WHERE case_id=? AND sync_pending=1', (case_id,)).fetchone()
            if not link:
                return
            try:
                event = self.events.get_event(link['event_id'])
                if event is None or event.details.get('source') != 'ep_patrol_local':
                    return
                if event.status != link['desired_status']:
                    self.events.update_status(link['event_id'], link['desired_status'])
                with self.cases.db:
                    self.cases.db.execute('UPDATE patrol_case_links SET sync_pending=0 WHERE case_id=?', (case_id,))
            except Exception:  # noqa: BLE001 -- durable outbox remains for local retry, never robot/cloud work
                return

    def flush_pending(self):
        try:
            with self.cases.lock:
                pending = self.cases.db.execute('SELECT case_id FROM patrol_case_links WHERE sync_pending=1 LIMIT 100').fetchall()
        except sqlite3.Error:
            return
        for row in pending:
            self.flush_case(row[0])

    def review_event(self, event, status, revision):
        if status == 'pending':
            raise HTTPException(409, '已連結跟進個案，請在工作台核對進度，不能直接重設。')
        if revision is None:
            raise HTTPException(409, '請先重新整理現場回報，核對跟進個案。')
        link = self.ensure(event)
        if not link:
            raise HTTPException(409, '請先重新整理現場回報，核對跟進個案。')
        result = self.cases.review(link['case_id'], ReviewCase(expected_revision=revision,
            status='acknowledged' if status == 'confirmed' else 'resolved'), event_status=status)
        if result.get('patrol_sync_pending'):
            raise HTTPException(503, '個案進度已保存，現場回報同步中；請重新整理核對，勿重複提交。')
        return self.events.get_event(event.id)


def followup_router(manager, authorize):
    router = APIRouter()
    def check(request, key):
        authorize(key)
        if not local_resident_request(request):
            raise HTTPException(403)

    @router.get('/api/v1/patrol/followups')
    def snapshot(request: Request, ids: str = Query(default='', max_length=3300, pattern='^[a-f0-9,]*$'), x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        selected = ids.split(',') if ids else None
        if selected and (len(selected) > 100 or any(not re.fullmatch('[a-f0-9]{32}', value) for value in selected)):
            raise HTTPException(422)
        return JSONResponse({'items':manager.snapshot(selected)}, headers={'Cache-Control':'no-store'})

    @router.post('/api/v1/patrol/events/{event_id}/followup')
    def ensure(event_id: str, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        event = manager.events.get_event(event_id)
        if not event or event.details.get('source') != 'ep_patrol_local' or event.details.get('is_test') is True:
            raise HTTPException(404)
        try:
            result = manager.ensure(event)
        except ValueError:
            raise HTTPException(409, '事件三張相片未能核對，未建立跟進個案。') from None
        except sqlite3.Error:
            raise HTTPException(503, '跟進個案尚未確認，請稍後核對；事件仍保留。') from None
        if result is None:
            raise HTTPException(410, '已結束的回報不會重新建立個案。')
        return JSONResponse(result, headers={'Cache-Control':'no-store'})
    return router
