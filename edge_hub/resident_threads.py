"""Local, durable conversation-to-case links. No model calls or raw chat archive."""
import hashlib
import re

from edge_hub.resident_cases import NUMBER, number_value, routing_team, unit_reference

TOPIC_WORDS = {
    'water': r'漏水|積水|积水|水喉|滴水', 'litter': r'垃圾|清潔|清洁|污糟',
    'lift': r'升降機|電梯|电梯', 'repair': r'維修|维修|故障|壞咗|坏了',
    'noise': r'噪音|嘈|吵', 'incident': r'騷擾|骚扰|擅闖|擅闯',
    'danger': r'火警|火花|煙味|烟味|漏電|漏电|被困',
    'care': r'壓力|压力|焦慮|焦虑|孤單|孤独|失眠|情緒|情绪',
    'fees': r'管理費|管理费|欠費|欠费|分期', 'application': r'申請|申请|續期|续期',
}
REFERENCE = r'補充|补充|頭先|头先|啱啱|剛才|刚才|同一|嗰(?:件|個|單|度)|那(?:件|個|个|單|单)|更正|正確位置|承接'
NEW_ISSUE = r'另外|另一(?:件|個|个|單|单|處|处)|第二(?:件|個|个|單|单)|新(?:問題|问题|個案|个案)|仲有一件'
DETAIL = r'位置|(?:已經|漏咗|壞咗|停咗|持續).{0,5}(?:日|天|星期|月)|係.{0,8}(?:天花|廚房|廁所|走廊)|可以.{0,8}聯絡|電話'


def install(db):
    db.execute('CREATE TABLE IF NOT EXISTS resident_session_cases ('
               'session_hash TEXT NOT NULL,case_id TEXT NOT NULL,topic TEXT NOT NULL,last_turn INTEGER NOT NULL DEFAULT 0,'
               'PRIMARY KEY(session_hash,case_id))')
    db.execute('CREATE TABLE IF NOT EXISTS resident_session_turns ('
               'seq INTEGER PRIMARY KEY AUTOINCREMENT,session_hash TEXT NOT NULL,turn_id TEXT NOT NULL,case_id TEXT NOT NULL,fingerprint TEXT NOT NULL,'
               'UNIQUE(session_hash,turn_id))')
    db.execute('CREATE TABLE IF NOT EXISTS resident_support_links (submission_id TEXT PRIMARY KEY,case_id TEXT NOT NULL)')


def session_hash(session):
    return hashlib.sha256(('resident-issues:'+session).encode()).hexdigest()


def session_rows(store, session):
    """Adopt only the old deterministic identities of this exact session, once."""
    from edge_hub.resident_followup import TOPICS, identity
    key = session_hash(session)
    with store.lock, store.transaction():
        for topic in TOPICS:
            _, row = store.automatic_slot(identity(session, topic))
            if row and row['intake_mode'] == 'automatic':
                store.db.execute('INSERT OR IGNORE INTO resident_session_cases(session_hash,case_id,topic) VALUES (?,?,?)',
                                 (key, row['id'], topic))
        return store.db.execute('SELECT c.*,s.topic FROM resident_session_cases s JOIN service_cases c ON c.id=s.case_id '
                               "WHERE s.session_hash=? AND c.status!='resolved' ORDER BY s.last_turn DESC,c.created_at_ms DESC,c.rowid DESC",
                               (key,)).fetchall()


def different_place(old, text):
    """A newly supplied exact location is a refinement; a conflicting one is distinct."""
    old_unit, new_unit = unit_reference(old), unit_reference(text)
    if old_unit and new_unit:
        if old_unit.split('座')[0] != new_unit.split('座')[0]:
            return True
        if old_unit.endswith('室') and new_unit.endswith('室') and old_unit != new_unit:
            return True
    places = r'大堂|走廊|停車場|停车场|花園|花园|會所|会所|平台|廚房|廁所'
    a, b = re.search(places, old), re.search(places, text)
    return bool(a and b and a[0] != b[0])


def select_case(store, rows, text, need):
    if not rows:
        return None
    reference = bool(re.search(REFERENCE, text))
    # "另外補充" means another detail, not another incident.
    new_subject = re.sub(r'另外(?:再)?(?:補充|补充)', '', text)
    if re.search(NEW_ISSUE, new_subject):
        return None
    marked = re.search(rf'(?:個案|个案|編號|编号)[：:\s]*({NUMBER})', text) if reference else None
    if marked:
        matches = [row for row in rows if str(store.case_number(row)) == number_value(marked[1])
                   or str(row['case_number']) == number_value(marked[1])]
        return matches[0] if len(matches) == 1 else None
    if reference:
        # The topic named immediately in the reference wins over later new
        # symptoms (e.g. water dripping onto a sparking wire).
        lead = re.split('[，,。；;]', text, maxsplit=1)[0]
        named = [topic for topic, pattern in TOPIC_WORDS.items() if re.search(pattern, lead)]
        if named:
            matches = [row for row in rows if row['topic'] in named]
            if len(matches) == 1:
                return matches[0]
            if matches:
                return next((row for row in matches if not different_place(row['location']+' '+row['message'], text)), None)
        if not named and not different_place(rows[0]['location']+' '+rows[0]['message'], text):
            return rows[0]
    if need is None:
        return rows[0] if re.search(DETAIL, text) and not different_place(rows[0]['location']+' '+rows[0]['message'], text) else None
    if need['topic'] == 'assistance':
        return rows[0]  # A request for staff to call about an already open issue.
    if need['topic'] == 'repair' and re.search(DETAIL, text) and not different_place(rows[0]['location']+' '+rows[0]['message'], text):
        return rows[0]
    return next((row for row in rows if row['topic'] == need['topic'] and not different_place(row['location']+' '+row['message'], text)), None)


def record_crisis(store, request, session):
    """An explicit escalation of an existing care case stays in that case."""
    from edge_hub.resident_crisis import PREFIX
    with store.lock, store.transaction():
        linked = store.db.execute('SELECT c.* FROM resident_support_links l JOIN service_cases c ON c.id=l.case_id '
                                  'WHERE l.submission_id=?', (request.submission_id,)).fetchone()
        if linked:
            return receipt(store, linked)
        rows = session_rows(store, session)
        selected = next((row for row in rows if row['kind'] == 'human_support'), None)
        if selected:
            result = store.record_automatic(request.model_copy(update={'submission_id': selected['submission_id']}),
                                            quote=request.message)
            message = selected['message']
            if not message.startswith(PREFIX):
                store.db.execute('UPDATE service_cases SET message=?,due_at_ms=?,revision=revision+1 WHERE id=?',
                                 (PREFIX+store.db.execute('SELECT message FROM service_cases WHERE id=?', (selected['id'],)).fetchone()[0],
                                  min(selected['due_at_ms'], selected['created_at_ms']+5*60_000), selected['id']))
        else:
            result = store.create(request)
        store.db.execute('INSERT INTO resident_support_links(submission_id,case_id) VALUES (?,?)',
                         (request.submission_id, result['id']))
        store.db.execute("INSERT OR IGNORE INTO resident_session_cases(session_hash,case_id,topic) VALUES (?,?,'care')",
                         (session_hash(session), result['id']))
        return result


def replay(store, session, turn, *, quote=None):
    with store.lock:
        if quote is not None:
            fingerprint = store.db.execute('SELECT fingerprint FROM resident_session_turns WHERE session_hash=? AND turn_id=?',
                                          (session_hash(session), turn)).fetchone()
            if fingerprint and fingerprint[0] != hashlib.sha256(quote.encode()).hexdigest():
                from fastapi import HTTPException
                raise HTTPException(409, '這次傳送已用於其他內容，未有建立新個案。')
        return store.db.execute('SELECT c.* FROM resident_session_turns t JOIN service_cases c ON c.id=t.case_id '
                                'WHERE t.session_hash=? AND t.turn_id=?', (session_hash(session), turn)).fetchone()


def receipt(store, row, *, replayed=True):
    return {'id': row['id'], 'case_number': store.case_number(row), 'kind': row['kind'], 'team': row['team'],
            'status': row['status'], 'replayed': replayed, 'contact_available': bool(row['contact'] or row['unit'].endswith('室'))}


def record(store, request, *, session, turn, topic, selected, quote, outreach_requested):
    """Bind the turn atomically with the case write; retries keep even completed cases."""
    key = session_hash(session)
    with store.lock, store.transaction():
        existing = replay(store, session, turn, quote=quote)
        if existing:
            return receipt(store, existing)
        if selected:
            request = request.model_copy(update={'submission_id': selected['submission_id']})
        result = store.record_automatic(request, quote=quote, outreach_requested=outreach_requested)
        row = store.db.execute('SELECT * FROM service_cases WHERE id=?', (result['id'],)).fetchone()
        if request.kind == 'hazard' and row['kind'] != 'hazard':
            # Related danger escalates the original report; never downgrade or
            # reset the staff's assignment, notes or acknowledged status.
            due = min(row['due_at_ms'], row['created_at_ms']+15*60_000)
            store.db.execute('UPDATE service_cases SET kind=?,team=?,due_at_ms=?,revision=revision+1 WHERE id=?',
                             ('hazard', routing_team('hazard', quote), due, row['id']))
        seq = store.db.execute('INSERT INTO resident_session_turns(session_hash,turn_id,case_id,fingerprint) VALUES (?,?,?,?)',
                               (key, turn, row['id'], hashlib.sha256(quote.encode()).hexdigest())).lastrowid
        store.db.execute('INSERT INTO resident_session_cases(session_hash,case_id,topic,last_turn) VALUES (?,?,?,?) '
                         'ON CONFLICT(session_hash,case_id) DO UPDATE SET last_turn=excluded.last_turn',
                         (key, row['id'], selected['topic'] if selected else topic, seq))
        return receipt(store, store.db.execute('SELECT * FROM service_cases WHERE id=?', (row['id'],)).fetchone(),
                       replayed=result['replayed'])
