"""Strict control ACK validation and bounded, content-free diagnostics."""
import time


class ControlReplyError(RuntimeError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__('not acknowledged: '+diagnostic['code'])


def request_ack(client, message, timeout):
    start = time.monotonic()
    before = {key: getattr(client, key, None) for key in ('_has_recv', '_unpack_failed')}
    diagnostic = {'code': 'not_confirmed', 'retcode': None,
                  'cmdset': message.cmdset, 'cmdid': message.cmdid}
    try:
        response = client.send_sync_msg(message, timeout=timeout)
        if response is None:
            diagnostic['code'] = 'reply_missing_or_unmatched'
        else:
            proto = response.get_proto()
            retcode = getattr(proto, '_retcode', None)
            if type(retcode) is not int:
                diagnostic['code'] = 'reply_malformed'
            else:
                diagnostic.update(retcode=retcode, code='confirmed' if retcode == 0 else 'robot_rejected')
    except Exception as error:  # noqa: BLE001 -- preserve classification without leaking SDK payloads
        diagnostic.update(code='sdk_exception', exception_type=type(error).__name__)
    diagnostic['elapsed_ms'] = round((time.monotonic()-start)*1000)
    for key, value in before.items():
        after = getattr(client, key, None)
        diagnostic[key.removeprefix('_')+'_delta'] = max(0, after-value) if type(after) is int and type(value) is int else None
    if diagnostic['code'] != 'confirmed':
        raise ControlReplyError(diagnostic)
    return diagnostic


def confirm_sdk_enable(robot):
    from robomaster import protocol
    proto = protocol.ProtoSetSdkMode()
    proto._enable = 1
    return request_ack(robot.client,
        protocol.Msg(robot.client.hostbyte, protocol.host2byte(9, 0), proto), timeout=3.0)
