import json
from types import SimpleNamespace

from ep_runtime.motor_trace import MotorTrace, sdk_counters


def test_trace_appends_across_instances_without_overwriting_existing_evidence(tmp_path):
    first = MotorTrace(tmp_path)
    first.append({'stage': 'engage_mode', 'outcome': 'pending'}, sn='SYNTHETIC', device_id='ep-2')
    saved = first.path.read_bytes()
    second = MotorTrace(tmp_path)
    second.append({'stage': 'release_mode', 'outcome': 'acknowledged'}, sn='SYNTHETIC', device_id='ep-2')
    assert second.path != first.path
    assert first.path.read_bytes() == saved
    first.append({'stage': 'engage_mode', 'outcome': 'no_reply'}, sn='SYNTHETIC', device_id='ep-2')
    assert [json.loads(line)['outcome'] for line in first.path.read_text().splitlines()] == ['pending', 'no_reply']


def test_trace_whitelist_does_not_persist_control_tokens_or_raw_exception_messages(tmp_path):
    trace = MotorTrace(tmp_path)
    trace.append({'stage': 'engage_mode', 'outcome': 'exception', 'exception_type': 'RuntimeError',
                  'session_id': 'synthetic-private-session', 'press_id': 'synthetic-private-press',
                  'exception_message': 'synthetic-private-message', 'raw_reply': 'synthetic-private-packet'},
                 sn='SYNTHETIC', device_id='ep-2')
    content = trace.path.read_text()
    assert 'synthetic-private' not in content
    assert json.loads(content)['exception_type'] == 'RuntimeError'


def test_sdk_counter_snapshot_contains_counts_not_ack_identifiers_or_client_internals():
    client = SimpleNamespace(_running=True, _has_sent=3, _has_recv=9, _unpack_failed=1,
                             _wait_ack_list={'synthetic-private-ident': object()},
                             token='synthetic-private-token')
    assert sdk_counters(client) == {'has_sent': 3, 'has_recv': 9, 'unpack_failed': 1,
                                    'running': True, 'pending_ack_count': 1}
    assert 'synthetic-private' not in str(sdk_counters(client))
