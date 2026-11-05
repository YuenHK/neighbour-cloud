"""Append-only local motor transition evidence; no robot/network access."""
import json
import os
import uuid
from datetime import UTC, datetime


def sdk_counters(client):
    result = {}
    for name in ('_has_sent', '_has_recv', '_unpack_failed'):
        value = getattr(client, name, None)
        if type(value) is int:
            result[name.removeprefix('_')] = value
    running = getattr(client, '_running', None)
    if type(running) is bool:
        result['running'] = running
    pending = getattr(client, '_wait_ack_list', None)
    if type(pending) is dict:
        result['pending_ack_count'] = len(pending)
    return result


class MotorTrace:
    def __init__(self, root):
        stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S')
        self.path = root / '.runtime' / 'ep-motor-diagnostics' / f'{stamp}-{uuid.uuid4().hex}.jsonl'

    def append(self, evidence, *, sn, device_id, firmware=''):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The caller supplies only structured diagnostics, never raw replies,
        # exception messages, credentials, press ids or control-session tokens.
        allowed = {'stage', 'requested_mode', 'ack_timeout_ms', 'started_at_ms', 'outcome',
                   'sdk_before', 'sdk_after', 'elapsed_ms', 'reply_received', 'retcode',
                   'exception_type', 'engage_mode_acknowledged', 'diagnostic_persisted'}
        record = {'recorded_at_ms': int(datetime.now(UTC).timestamp()*1000),
                  'sn': sn, 'device_id': device_id, 'firmware': firmware,
                  **{key: value for key, value in evidence.items() if key in allowed}}
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(record, ensure_ascii=True, allow_nan=False)+'\n')
            output.flush()
            os.fsync(output.fileno())
