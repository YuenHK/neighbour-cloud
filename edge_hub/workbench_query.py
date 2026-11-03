"""Bounded, parameterized workbench searches. Dates are Hong Kong calendar days."""
import re
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, Query

HK = timezone(timedelta(hours=8))


def parameters(q: str = Query(default='', max_length=120), state: str = Query(default='all', max_length=20),
               sort: str = Query(default='created_desc', max_length=30),
               date_field: str = Query(default='created', max_length=20),
               date_from: str = Query(default='', max_length=10), date_to: str = Query(default='', max_length=10),
               live_only: bool = Query(default=False)):
    return {'q': q, 'state': state, 'sort': sort, 'date_field': date_field, 'date_from': date_from,
            'date_to': date_to, 'live_only': live_only}


def validate(kind, *, q='', state='all', sort='created_desc', date_field='created', date_from='', date_to='', live_only=False):
    states = {'all', 'open', 'new', 'acknowledged', 'resolved'} if kind == 'cases' else {
        'all', 'open', 'pending', 'confirmed', 'false_positive', 'resolved'}
    sorts = {'created_desc', 'created_asc', 'updated_desc', 'due_asc', 'priority'} if kind == 'cases' else {
        'created_desc', 'created_asc', 'completed_desc', 'priority'}
    fields = {'created', 'updated', 'due'} if kind == 'cases' else {'created', 'completed'}
    if (not isinstance(q, str) or len(q) > 120 or state not in states or sort not in sorts
            or date_field not in fields or type(live_only) is not bool):
        raise HTTPException(422, '檢索條件不正確。')

    def day(value):
        if value == '':
            return None
        try:
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError
            parsed = date.fromisoformat(value)
            if not 1970 <= parsed.year <= 2200:
                raise ValueError
            return parsed
        except (ValueError, TypeError):
            raise HTTPException(422, '請輸入有效日期。') from None

    first, last = day(date_from), day(date_to)
    if first and last and first > last:
        raise HTTPException(422, '開始日期不可遲於結束日期。')
    def stamp(value):
        return int(datetime.combine(value, time.min, HK).timestamp() * 1000)
    return {'q': q.strip(), 'state': state, 'sort': sort, 'date_field': date_field,
            'from_ms': stamp(first) if first else None,
            'to_ms': stamp(last + timedelta(days=1)) if last else None, 'live_only': live_only}


def date_clauses(column, values):
    clauses, args = [], []
    if values['from_ms'] is not None:
        clauses.append(column + '>=?')
        args.append(values['from_ms'])
    if values['to_ms'] is not None:
        clauses.append(column + '<?')
        args.append(values['to_ms'])
    return clauses, args
