"""Pinned SDK's real codec/ACK matcher with synthetic replies; no sockets."""
import struct
import sys
import threading
import unittest
from types import MethodType, SimpleNamespace

from ep_runtime import console_tests as helpers
from ep_runtime.bootstrap import load_sdk


class NativeAckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.addaudithook(helpers.deny_network)
        if not hasattr(helpers.ConsoleTests, 'sdk'):
            load_sdk(helpers.ROOT / '.runtime/ep-sdk/source/src')

    def client(self, *, retcode=0, mismatch=None, empty=False):
        from robomaster import client, protocol
        value = SimpleNamespace(_running=True, _wait_ack_mutex=threading.Lock(),
            _wait_ack_list={}, _event_list=[client.EventIdentify() for _ in range(4)],
            _has_sent=0, _has_recv=0, _unpack_failed=0)
        for name in ('_ack_register_identify', '_ack_unregister_identify', '_dispatch_to_send_sync', 'send_sync_msg'):
            setattr(value, name, MethodType(getattr(client.Client, name), value))
        value._make_ack_identify = client.Client._make_ack_identify
        packets = []

        def send(message):
            packets.append(bytes(message.pack()))
            value._has_sent += 1
            wire = bytearray(packets[-1][:11]) + (b'' if empty else bytes([retcode])) + bytes(2)
            wire[1] = len(wire)
            wire[2] = 4
            wire[3] = protocol.algo.crc8_calc(wire[:3])
            wire[4], wire[5] = message._receiver, message._sender
            struct.pack_into('<H', wire, 6, message._seq_id + (1 if mismatch == 'sequence' else 0))
            wire[8] = 0x80  # incoming ACK, no ACK-of-ACK requested
            if mismatch == 'command':
                wire[10] = 0x20
            struct.pack_into('<H', wire, len(wire)-2, protocol.algo.crc16_calc(wire[:-2]))
            response, rest = protocol.decode_msg(wire)
            assert response is not None and not rest
            value._has_recv += 1
            value._dispatch_to_send_sync(response)

        value.send_msg = send
        return value, packets

    def test_real_codec_and_ack_matcher_accept_both_mode_bytes_without_changing_timeout_or_ack_kind(self):
        from robomaster import protocol
        for mode in (0, 1):
            client, packets = self.client()
            proto = protocol.ProtoChassisSetWorkMode()
            proto._mode = mode
            message = protocol.Msg(201, 195, proto)
            response = client.send_sync_msg(message, timeout=.5)
            self.assertEqual(response.get_proto()._retcode, 0)
            self.assertEqual(packets[0][9:-2], bytes([0x3f, 0x19, mode]))
            self.assertEqual(message._need_ack, 2)
            self.assertEqual(client._unpack_failed, 0)

    def test_wrong_command_or_sequence_ack_never_acknowledges_engagement(self):
        from robomaster import protocol
        for mismatch in ('command', 'sequence'):
            client, packets = self.client(mismatch=mismatch)
            proto = protocol.ProtoChassisSetWorkMode()
            proto._mode = 1
            self.assertIsNone(client.send_sync_msg(protocol.Msg(201, 195, proto), timeout=.001))
            self.assertEqual(len(packets), 1)

    def test_negative_ack_keeps_its_real_retcode_for_diagnostics(self):
        from robomaster import protocol
        client, _ = self.client(retcode=7)
        response = client.send_sync_msg(protocol.Msg(201, 195, protocol.ProtoChassisSetWorkMode()), timeout=.5)
        self.assertEqual(response.get_proto()._retcode, 7)

    def test_control_enable_validates_real_ack_retcode_not_just_response_presence(self):
        from ep_runtime.control_ack import ControlReplyError, confirm_sdk_enable
        for retcode in (0, 7):
            client, packets = self.client(retcode=retcode)
            client.hostbyte = 201
            robot = SimpleNamespace(client=client)
            if retcode:
                with self.assertRaises(ControlReplyError) as raised:
                    confirm_sdk_enable(robot)
                self.assertEqual(raised.exception.diagnostic['code'], 'robot_rejected')
                self.assertEqual(raised.exception.diagnostic['retcode'], 7)
            else:
                self.assertEqual(confirm_sdk_enable(robot)['code'], 'confirmed')
            self.assertEqual(len(packets), 1)
            self.assertEqual(packets[0][9:12], bytes([0x3f, 0xd1, 1]))

    def test_missing_control_reply_is_not_accepted_or_retried(self):
        from robomaster import protocol

        from ep_runtime.control_ack import ControlReplyError, request_ack
        client, packets = self.client(mismatch='sequence')
        with self.assertRaises(ControlReplyError) as raised:
            request_ack(client, protocol.Msg(201, 195, protocol.ProtoSetWheelSpeed()), .001)
        self.assertEqual(raised.exception.diagnostic['code'], 'reply_missing_or_unmatched')
        self.assertEqual(len(packets), 1)

    def test_malformed_ack_returns_none_but_is_distinct_from_no_traffic_in_sdk_counters(self):
        from robomaster import protocol
        client, _ = self.client(empty=True)
        self.assertIsNone(client.send_sync_msg(protocol.Msg(201, 195, protocol.ProtoChassisSetWorkMode()), timeout=.5))
        self.assertEqual(client._has_recv, 1)
        self.assertEqual(client._unpack_failed, 1)


if __name__ == '__main__':
    unittest.main()
