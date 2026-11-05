"""Run with the dedicated EP Python. Synthetic data; no robot or real WLAN key."""
import base64
import ipaddress
import socket
import struct
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from edge_hub.robot_control import ControlError, RobotCommand, RobotController
from ep_runtime.bootstrap import load_sdk
from ep_runtime.console_session import EpSession, Utf8Wifi, local_ep_ip
from ep_runtime.console_session import LiveTransport
from ep_runtime.handshake import HandshakeError, attach_handshake

ROOT = Path(__file__).resolve().parents[1]


def deny_network(event, args):
    if event.startswith('socket.') and event != 'socket.gethostname':
        raise RuntimeError('offline EP tests forbid all sockets')


class ConsoleTests(unittest.TestCase):
    def test_connection_never_claims_sdk_ready_after_enable_rejection(self):
        robot = self.fake_robot()
        robot.initialize.side_effect = lambda **kw: robot._enable_sdk(1)
        robot.client.send_sync_msg.return_value = SimpleNamespace(get_proto=lambda: SimpleNamespace(_retcode=7))
        self.session.sdk = self.sdk
        with patch.object(self.sdk, 'Robot', return_value=robot), \
                patch('ifaddr.get_adapters', return_value=[]), \
                patch('ep_runtime.console_session.local_ep_ip', return_value='192.168.1.10'):
            with self.assertRaises(ControlError):
                self.session.connect('192.168.1.2', True)
        self.assertIsNone(self.session.robot)
        self.assertEqual(self.session.sdk_confirmation['code'], 'robot_rejected')
        self.assertEqual(self.session.last_connection_error['stage'], 'enable_sdk')
        robot.client._conn._sock.sendto.assert_not_called()
        robot.gimbal.recenter.assert_not_called()

    def test_manual_stop_check_never_clears_fault_or_prepares_motion(self):
        robot = self.fake_robot()
        self.session.robot, self.session.sn = robot, 'SYNTHETIC-EP'
        database = Path(self.temp.name)/'check.sqlite3'
        control = RobotController(database, transport=LiveTransport(robot, model='EP', on_site_motion_authorized=True))
        self.session.control = control
        with control.db:
            control.db.execute('UPDATE control_safety SET requires_reset=1,fault=1 WHERE id=1')
        control.state, control.stop_latched = 'fault', True
        try:
            result = self.session.handle('check-stop', {'confirmed_stationary': True})
            self.assertEqual(result['stop_confirmation']['code'], 'confirmed')
            self.assertEqual(result['control']['state'], 'fault')
            self.assertEqual(tuple(control.db.execute('SELECT requires_reset,fault FROM control_safety').fetchone()), (1, 1))
            self.assertIsNone(control.lease)
            robot.set_robot_mode.assert_not_called()
            robot.gimbal.recenter.assert_not_called()
            robot.client._conn._sock.sendto.assert_not_called()
            self.assert_wheel_stop(robot)
        finally:
            self.session.disconnect()

    def test_trajectory_led_uses_only_led_packets_never_firing_packets(self):
        from robomaster.blaster import Blaster, LED_OFF, LED_ON
        device = object.__new__(Blaster)
        packets = []
        device._send_sync_proto = lambda proto: packets.append(proto) or True
        self.assertTrue(device.set_led(brightness=255, effect=LED_ON))
        self.assertTrue(device.set_led(brightness=0, effect=LED_OFF))
        self.assertEqual([(p._cmdset, p._cmdid) for p in packets], [(0x3f, 0x55)]*2)
        self.assertEqual(packets[0].pack_req()[0] & 15, 1)
        self.assertEqual(packets[1].pack_req()[0] & 15, 0)

    def short_session(self, release_check=False):
        from ep_runtime.short_press_session import ShortPressEpSession
        from ep_runtime.short_press_session import ReleaseCheckEpSession
        robot = self.fake_robot()
        now = [0.0]
        session_type = ReleaseCheckEpSession if release_check else ShortPressEpSession
        session = session_type(Path(self.temp.name), lambda: self.sdk)
        transport = LiveTransport(robot, model='EP', on_site_motion_authorized=True)
        session.robot, session.drive_mode = robot, 'chassis_lead'
        session.prepared_idle, session.gimbal_mode_applied = True, True
        session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        session.control = RobotController(transport=transport, clock=lambda: now[0], wall_clock=lambda: 1.0)
        payload = {'session_id': session.short_session, 'press_id': 'b' * 32,
                   'issued_at_ms': 1000, 'confirmed_clear_path': True}
        return session, robot, now, payload

    def fake_robot(self):
        robot = Mock()
        robot.initialize.return_value = True
        robot.get_version.return_value = 'synthetic-version'
        robot.get_sn.return_value = 'SYNTHETIC-EP'
        robot.set_robot_mode.return_value = True
        robot.get_robot_mode.return_value = 'chassis_lead'
        robot.gimbal.recenter.return_value.wait_for_completed.return_value = True
        robot.gimbal.recenter.return_value.has_succeeded = True
        robot.gimbal.drive_speed.return_value = True
        robot.ip = '192.168.1.2'
        robot.client.hostbyte = 201
        robot.chassis._host = 195
        sock = Mock()
        sock.sendto.side_effect = lambda packet, address: len(packet)
        robot.client._conn = SimpleNamespace(_proto_type='udp', _sock=sock,
                                            _target_addr=('192.168.1.2', 20020))
        robot.client.send_sync_msg.return_value = SimpleNamespace(
            get_proto=lambda: SimpleNamespace(_retcode=0))
        robot.chassis.sub_status.side_effect = lambda **kw: kw['callback']((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return robot

    def assert_wheel_stop(self, robot):
        message = robot.client.send_sync_msg.call_args.args[0]
        packet = message.pack()
        self.assertEqual(packet[9:11], bytes([0x3f, 0x20]))
        self.assertEqual(struct.unpack_from('<hhhh', packet, 11), (0, 0, 0, 0))
        self.assertEqual((packet[8] >> 5) & 3, 2)
        self.assertEqual(robot.client.send_sync_msg.call_args.kwargs, {'timeout': .5})
    @classmethod
    def setUpClass(cls):
        sys.addaudithook(deny_network)
        cls.sdk, _ = load_sdk(ROOT / '.runtime/ep-sdk/source/src')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = EpSession(Path(self.temp.name), lambda: self.sdk)
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    def tearDown(self):
        self.session.stopping.set()
        self.session.disconnect()
        self.temp.cleanup()

    def test_status_does_not_load_sdk_or_connect(self):
        self.session.sdk_loader = Mock(side_effect=AssertionError('no import'))
        self.assertEqual(self.session.handle('status', {})['connection'], 'not_connected')

    def test_short_press_is_minimum_speed_and_host_deadline_stops_without_client_release(self):
        session, robot, now, payload = self.short_session()
        session.speed_level = session.control.transport.speed_level = 4
        try:
            with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                state = session.handle('short-press-start', payload)
                self.assertTrue(state['control']['lease_active'])
                packet = robot.client._conn._sock.sendto.call_args.args[0]
                self.assertAlmostEqual(struct.unpack_from('<fff', packet, 11)[0], .15)
                self.assertEqual(struct.unpack_from('<fff', packet, 11)[1:], (0, 0))
                self.assertEqual(session.control.motion_deadline, .2)
                now[0] = .199
                session.control.tick()
                robot.client.send_sync_msg.assert_not_called()
                now[0] = .201
                session.control.tick()
                self.assert_wheel_stop(robot)
                self.assertIsNone(session.control.lease)
                self.assertEqual(session.control.direction, 'stop')
                count = robot.client.send_sync_msg.call_count
                session.handle('short-press-release', payload)
                self.assertEqual(robot.client.send_sync_msg.call_count, count)
                with self.assertRaises(ControlError):
                    session.handle('short-press-start', {**payload, 'press_id': 'd' * 32})
                self.assertEqual(robot.client._conn._sock.sendto.call_count, 1)
        finally:
            session.stopping.set()
            session.disconnect()

    def test_short_release_before_start_fences_late_move_and_old_session_is_rejected(self):
        session, robot, _, payload = self.short_session()
        try:
            with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                with self.assertRaises(ControlError):
                    session.handle('short-press-release', {**payload, 'session_id': 'c' * 32})
                session.handle('short-press-release', payload)
                session.handle('short-press-start', payload)
                robot.client._conn._sock.sendto.assert_not_called()
                robot.client.send_sync_msg.assert_not_called()
                self.assertIsNone(session.control.lease)
                self.assertTrue(session.short_used)
        finally:
            session.stopping.set()
            session.disconnect()

    def test_short_press_expired_future_unconfirmed_and_generic_control_never_move(self):
        session, robot, _, payload = self.short_session()
        try:
            with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                for invalid in [{**payload, 'issued_at_ms': 799}, {**payload, 'issued_at_ms': 1100},
                                {**payload, 'confirmed_clear_path': False}]:
                    with self.assertRaises(ControlError):
                        session.handle('short-press-start', invalid)
                for operation in ['lease', 'command', 'speed', 'gimbal-follow', 'video-start']:
                    with self.assertRaises(ControlError):
                        session.handle(operation, {})
            robot.client._conn._sock.sendto.assert_not_called()
            robot.client.send_sync_msg.assert_not_called()
            self.assertIsNone(session.control.lease)
        finally:
            session.stopping.set()
            session.disconnect()

    def test_short_press_unprepared_or_stale_chassis_never_sends_motion(self):
        session, robot, _, payload = self.short_session()
        try:
            with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                session.prepared_idle = False
                with self.assertRaises(ControlError):
                    session.handle('short-press-start', payload)
                session.prepared_idle = True
                session.chassis_status_at -= 1
                with self.assertRaises(ControlError):
                    session.handle('short-press-start', payload)
            robot.client._conn._sock.sendto.assert_not_called()
            robot.client.send_sync_msg.assert_not_called()
        finally:
            session.stopping.set()
            session.disconnect()

    def test_short_release_requires_wheel_stop_reply_and_latches_fault_if_lost(self):
        session, robot, _, payload = self.short_session()
        try:
            with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                session.handle('short-press-start', payload)
                robot.client.send_sync_msg.return_value = None
                state = session.handle('short-press-release', payload)
                self.assertEqual(state['control']['state'], 'fault')
                self.assertTrue(state['control']['software_stop_latched'])
                self.assertFalse(state['movement_enabled'])
                self.assertIsNone(session.control.lease)
                with self.assertRaises(ControlError):
                    session.handle('short-press-start', {**payload, 'press_id': 'd' * 32})
            self.assertEqual(robot.client._conn._sock.sendto.call_count, 1)
        finally:
            session.stopping.set()
            session.disconnect()

    def test_short_press_pickup_guard_cancels_active_motion_and_keeps_stop_latched(self):
        session, robot, _, payload = self.short_session()
        try:
            with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                session.handle('short-press-start', payload)
                session.receive_chassis_status((0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0))
                session.guard_chassis()
                self.assert_wheel_stop(robot)
                self.assertTrue(session.control.stop_latched)
                self.assertIsNone(session.control.lease)
                self.assertFalse(session.status()['movement_enabled'])
                self.assertEqual(robot.client._conn._sock.sendto.call_count, 1)
        finally:
            session.stopping.set()
            session.disconnect()

    def test_release_check_stops_at_early_release_and_records_human_source(self):
        session, robot, now, payload = self.short_session(release_check=True)
        try:
            with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                state = session.handle('short-press-start', payload)
                self.assertEqual(state['acceptance_stage'], 5)
                self.assertEqual(session.control.motion_deadline, .5)
                now[0] = .1
                result = session.handle('short-press-release', {**payload, 'source': 'release'})
                self.assertEqual(result['control']['reason'], 'operator_release')
                self.assertEqual(result['short_press_stop_origin'], 'release')
                self.assertFalse(result['control']['lease_active'])
                self.assert_wheel_stop(robot)
                self.assertEqual(robot.client._conn._sock.sendto.call_count, 1)
        finally:
            session.stopping.set()
            session.disconnect()

    def test_release_check_limit_and_blur_cannot_be_mislabelled_as_human_release(self):
        for source in ['host_limit', 'limit', 'blur']:
            session, robot, now, payload = self.short_session(release_check=True)
            try:
                with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                    session.handle('short-press-start', payload)
                    now[0] = .501 if source == 'host_limit' else .1
                    if source == 'host_limit':
                        session.control.tick()
                    result = session.handle('short-press-release', {
                        **payload, 'source': 'release' if source == 'host_limit' else source})
                    self.assertEqual(result['short_press_stop_origin'], source)
                    self.assertFalse(result['control']['lease_active'])
                    self.assert_wheel_stop(robot)
            finally:
                session.stopping.set()
                session.disconnect()

    def test_stage_two_worker_rejects_all_control_and_media_before_sdk_load(self):
        from ep_runtime.readonly_session import ReadOnlyEpSession
        loader = Mock(side_effect=AssertionError('must not load SDK'))
        session = ReadOnlyEpSession(Path(self.temp.name), loader)
        try:
            self.assertFalse(session.realtime_controls_enabled)
            self.assertFalse(session.handle('status', {})['movement_enabled'])
            for operation in ['prepare-control', 'lease', 'command', 'stop', 'reset-stop',
                              'speed', 'gimbal-follow', 'gimbal-start', 'gimbal-target',
                              'gimbal-stop', 'video-start', 'video-frame', 'video-stop',
                              'video-heartbeat', 'qr', 'health', 'heartbeat']:
                with self.assertRaises(ControlError):
                    session.handle(operation, {})
            loader.assert_not_called()
            self.assertIsNone(session.control)
        finally:
            session.stopping.set()
            session.disconnect()

    def test_stage_two_connect_and_poll_have_no_speed_gimbal_camera_or_lease(self):
        from ep_runtime.readonly_session import ReadOnlyEpSession
        robot = self.fake_robot()
        session = ReadOnlyEpSession(Path(self.temp.name), lambda: SimpleNamespace(Robot=lambda: robot))
        try:
            with patch('ep_runtime.console_session.local_ep_ip', return_value='192.168.1.3'):
                result = session.handle('connect', {
                    'ip': '192.168.1.2', 'confirmed': True, 'expected_sn': 'SYNTHETIC-EP'})
            self.assertEqual(result['connection'], 'connected')
            for _ in range(100):
                session.handle('status', {})
                session.hold_idle()
            self.assertIsNone(session.control)
            robot.client._conn._sock.sendto.assert_not_called()
            robot.client.send_sync_msg.assert_not_called()
            robot.chassis.drive_speed.assert_not_called()
            robot.chassis.drive_wheels.assert_not_called()
            robot.gimbal.recenter.assert_not_called()
            robot.gimbal.drive_speed.assert_not_called()
            robot.camera.start_video_stream.assert_not_called()
            self.assertFalse(list((Path(self.temp.name) / '.runtime').glob('ep-control*.sqlite3')))
        finally:
            session.stopping.set()
            session.handle('disconnect', {})

    def test_stage_three_manual_prepare_then_idle_never_has_a_lease_or_body_speed(self):
        from ep_runtime.readonly_session import PreparedIdleEpSession
        robot = self.fake_robot()
        session = PreparedIdleEpSession(Path(self.temp.name), lambda: SimpleNamespace(Robot=lambda: robot))
        try:
            with patch('ep_runtime.console_session.local_ep_ip', return_value='192.168.1.3'):
                session.handle('connect', {'ip': '192.168.1.2', 'confirmed': True})
            robot.gimbal.recenter.assert_not_called()
            robot.client.send_sync_msg.assert_not_called()
            state = session.handle('prepare-control', {})
            self.assertTrue(state['prepared_idle'])
            self.assertFalse(state['control']['lease_active'])
            self.assertFalse(state['movement_enabled'])
            self.assertEqual([call.kwargs for call in robot.set_robot_mode.call_args_list],
                             [{'mode': 'free'}, {'mode': 'chassis_lead'}])
            robot.gimbal.recenter.assert_called_once_with(pitch_speed=30, yaw_speed=60)
            self.assert_wheel_stop(robot)
            count = robot.client.send_sync_msg.call_count
            for _ in range(200):
                session.handle('status', {})
                session.hold_idle()
            self.assertEqual(robot.client.send_sync_msg.call_count, count)
            for operation in ['lease', 'command', 'speed', 'stop', 'reset-stop',
                              'gimbal-follow', 'gimbal-start', 'video-start']:
                with self.assertRaises(ControlError):
                    session.handle(operation, {})
            with self.assertRaises(ControlError):
                session.handle('prepare-control', {})
            self.assertIsNone(session.control.lease)
            robot.client._conn._sock.sendto.assert_not_called()
            robot.camera.start_video_stream.assert_not_called()
        finally:
            session.stopping.set()
            session.handle('disconnect', {})

    def test_stage_three_preserves_selected_secondary_stop_before_any_mode_or_recenter(self):
        from ep_runtime.readonly_session import PreparedIdleEpSession
        database = Path(self.temp.name) / '.runtime/ep-control-ep-2.sqlite3'
        saved = RobotController(database)
        saved.software_stop()
        saved.close()
        robot = self.fake_robot()
        session = PreparedIdleEpSession(Path(self.temp.name), lambda: None)
        session.device_id = 'ep-2'
        session.robot = robot
        session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        try:
            with self.assertRaises(ControlError):
                session.handle('prepare-control', {})
            self.assertTrue(session.control.stop_latched)
            self.assertFalse(session.status()['prepared_idle'])
            robot.set_robot_mode.assert_not_called()
            robot.gimbal.recenter.assert_not_called()
            robot.client.send_sync_msg.assert_not_called()
            robot.client._conn._sock.sendto.assert_not_called()
        finally:
            session.stopping.set()
            session.disconnect()

    def test_stage_three_failed_recenter_is_not_retried_and_has_no_lease(self):
        from ep_runtime.readonly_session import PreparedIdleEpSession
        robot = self.fake_robot()
        robot.gimbal.recenter.return_value.wait_for_completed.return_value = False
        session = PreparedIdleEpSession(Path(self.temp.name), lambda: None)
        session.robot = robot
        session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        try:
            for _ in range(2):
                with self.assertRaises(ControlError):
                    session.handle('prepare-control', {})
            robot.gimbal.recenter.assert_called_once()
            self.assertIsNone(session.control)
            self.assertFalse(session.status()['prepared_idle'])
            robot.client._conn._sock.sendto.assert_not_called()
        finally:
            session.stopping.set()
            session.disconnect()

    def test_stage_three_explicit_ordinary_stop_reset_is_data_only_and_never_prepares(self):
        from ep_runtime.readonly_session import PreparedIdleEpSession
        database = Path(self.temp.name) / '.runtime/ep-control-ep-2.sqlite3'
        saved = RobotController(database)
        saved.software_stop()
        saved.close()
        robot = self.fake_robot()
        session = PreparedIdleEpSession(Path(self.temp.name), lambda: None)
        session.device_id, session.robot = 'ep-2', robot
        session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        try:
            self.assertTrue(session.status()['control']['software_stop_latched'])
            self.assertIsNone(session.control)
            with self.assertRaises(ControlError):
                session.handle('reset-stop', {})
            result = session.handle('reset-stop', {'confirmed_stationary': True})
            self.assertFalse(result['control']['software_stop_latched'])
            self.assertFalse(result['control']['lease_active'])
            self.assertFalse(result['prepared_idle'])
            self.assertFalse(result['prepare_attempted'])
            robot.client.send_sync_msg.assert_not_called()
            robot.client._conn._sock.sendto.assert_not_called()
            robot.gimbal.recenter.assert_not_called()
            robot.set_robot_mode.assert_not_called()
            with self.assertRaises(ControlError):
                session.handle('lease', {})
        finally:
            session.stopping.set()
            session.disconnect()

    def test_stage_three_fault_reset_is_denied_without_controller_or_command(self):
        import sqlite3
        from ep_runtime.readonly_session import PreparedIdleEpSession
        database = Path(self.temp.name) / '.runtime/ep-control.sqlite3'
        saved = RobotController(database)
        saved.close()
        with closing(sqlite3.connect(database)) as db:
            db.execute('UPDATE control_safety SET requires_reset=1,fault=1 WHERE id=1')
            db.commit()
        robot = self.fake_robot()
        session = PreparedIdleEpSession(Path(self.temp.name), lambda: None)
        session.robot = robot
        session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        try:
            self.assertEqual(session.status()['control']['state'], 'fault')
            with self.assertRaises(ControlError):
                session.handle('reset-stop', {'confirmed_stationary': True})
            self.assertIsNone(session.control)
            robot.client.send_sync_msg.assert_not_called()
            robot.client._conn._sock.sendto.assert_not_called()
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT requires_reset,fault FROM control_safety').fetchone(), (1, 1))
        finally:
            session.stopping.set()
            session.disconnect()

    def test_health_uses_fresh_telemetry_and_lost_identity_probe_marks_offline(self):
        robot = self.fake_robot()
        self.session.robot = robot
        self.session.sn = 'SYNTHETIC-EP'
        self.session.receive_battery(80)
        self.assertEqual(self.session.handle('health', {})['connection'], 'connected')
        robot.client.send_sync_msg.assert_not_called()
        self.session.battery_at = 0
        robot.client.send_sync_msg.return_value = None
        self.assertEqual(self.session.handle('health', {})['connection'], 'not_connected')
        self.assertEqual(robot.client.send_sync_msg.call_args.kwargs['timeout'], .5)
        robot.client._conn._sock.sendto.assert_not_called()
        robot.camera.start_video_stream.assert_not_called()

    def test_pairing_only_rejects_control_before_loading_sdk(self):
        from ep_runtime.pairing_session import PairingOnlyEpSession
        loader = Mock(side_effect=AssertionError('no SDK import for forbidden operation'))
        session = PairingOnlyEpSession(Path(self.temp.name), loader)
        try:
            session.handle('status', {})
            session.handle('qr-status', {})
            for operation in ['connect', 'prepare-control', 'lease', 'command', 'stop',
                              'reset-stop', 'health', 'gimbal-follow', 'gimbal-start',
                              'gimbal-target', 'speed', 'video-start', 'video-frame']:
                with self.assertRaises(ControlError):
                    session.handle(operation, {})
            loader.assert_not_called()
            self.assertIsNone(session.robot)
            self.assertIsNone(session.control)
        finally:
            session.stopping.set()
            session.handle('disconnect', {})

    def test_pairing_only_qr_and_received_reply_never_construct_or_connect_robot(self):
        import queue
        import time
        from robomaster import algo, conn
        from ep_runtime.pairing_session import PairingOnlyEpSession
        robot_factory = Mock(side_effect=AssertionError('pairing must never create Robot'))
        session = PairingOnlyEpSession(Path(self.temp.name), lambda: SimpleNamespace(Robot=robot_factory))
        helper = conn.ConnectionHelper()
        helper._appid = '12345'
        incoming, replied = queue.Queue(), threading.Event()
        plain = struct.pack('>HI4B6B', 0x5a5b, 1, 192, 168, 99, 42, 0, 1, 2, 3, 4, 5)
        incoming.put((algo.simple_encrypt(plain + b'12345\0\0'), ('192.168.99.42', 45678)))
        class Listener:
            closed = False
            def bind(self, address):
                self.address = address
            def settimeout(self, timeout):
                pass
            def recvfrom(self, size):
                if self.closed:
                    raise OSError()
                try:
                    return incoming.get(timeout=.01)
                except queue.Empty:
                    raise TimeoutError() from None
            def sendto(self, data, address):
                self.reply = (data, address)
                replied.set()
            def close(self):
                self.closed = True
        listener = Listener()
        try:
            with patch('ep_runtime.console_session.socket.socket', return_value=listener), patch(
                    'robomaster.conn.ConnectionHelper', return_value=helper):
                qr = session.handle('qr', {'ssid': 'Synthetic-Current', 'password': 'synthetic-only-123'})
            self.assertTrue(replied.wait(1))
            deadline = time.monotonic() + 1
            while not session.candidates and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(listener.address, ('0.0.0.0', 45678))
            self.assertEqual(listener.reply, (b'12345', ('192.168.99.42', 45678)))
            self.assertIn(b'<svg', base64.b64decode(qr['svg_base64']))
            self.assertNotIn('synthetic-only-123', str(qr))
            state = session.handle('status', {})
            self.assertFalse(state['identity_verified'])
            self.assertFalse(state['movement_enabled'])
            self.assertEqual(state['connection'], 'not_connected')
            self.assertEqual(state['candidates'][0]['ip'], '192.168.99.42')
            robot_factory.assert_not_called()
            self.assertIsNone(session.robot)
            self.assertIsNone(session.control)
            self.assertFalse(session.realtime_controls_enabled)
            self.assertFalse(list(Path(self.temp.name).glob('**/*')))
        finally:
            session.stopping.set()
            session.handle('disconnect', {})
        self.assertTrue(listener.closed)
        self.assertIsNone(session.handle('qr-status', {})['svg_base64'])

    def test_battery_requires_real_valid_fresh_callback_and_expires(self):
        import time
        self.assertIsNone(self.session.status()['battery_percent'])
        for value in (-1, 101, True, '80', None):
            self.session.receive_battery(value)
            self.assertIsNone(self.session.status()['battery_percent'])
        self.session.receive_battery(73)
        self.assertEqual(self.session.status()['battery_percent'], 73)
        self.session.battery_at = time.monotonic() - 6
        self.assertIsNone(self.session.status()['battery_percent'])

    def test_stale_frame_is_never_returned_or_replayed_and_stop_clears_buffer(self):
        import time
        self.session.video_enabled = True
        self.session.video_frame = 'synthetic-image'
        self.session.video_at = time.monotonic()
        self.assertEqual(self.session.frame_snapshot()['jpeg_base64'], 'synthetic-image')
        self.session.video_at = time.monotonic() - 2
        self.assertIsNone(self.session.frame_snapshot()['jpeg_base64'])
        self.session.stop_video()
        self.assertIsNone(self.session.video_frame)
        self.assertFalse(self.session.video_enabled)

    def test_camera_is_explicit_and_decode_is_local_without_any_motor_command(self):
        import time
        import numpy as np
        robot = self.fake_robot()
        robot.camera.start_video_stream.return_value = True
        robot.camera.read_cv2_image.return_value = np.zeros((360, 640, 3), dtype=np.uint8)
        self.session.robot = robot
        self.assertFalse(self.session.status()['video_enabled'])
        self.session.handle('video-start', {})
        deadline = time.monotonic() + 2
        while self.session.video_frame is None and time.monotonic() < deadline:
            time.sleep(.01)
        encoded = self.session.frame_snapshot()['jpeg_base64']
        self.assertTrue(base64.b64decode(encoded).startswith(b'\xff\xd8'))
        robot.camera.start_video_stream.assert_called_once_with(display=False, resolution='360p')
        robot.client._conn._sock.sendto.assert_not_called()
        self.session.handle('video-stop', {})
        self.assertFalse(self.session.status()['video_enabled'])

    def test_sdk_qr_payload_round_trips_ascii_and_unicode_in_memory(self):
        from robomaster import algo, conn
        import cv2
        import numpy as np
        import qrcode
        for ssid in ('Synthetic-EP', '公開測試WiFi'):
            helper = conn.ConnectionHelper()
            # Keep this decoder fixture reproducible; production pairing keeps
            # its random app id. Some random QR patterns defeat OpenCV decoding.
            helper._appid = '12345'
            words = helper.build_qrcode_string(Utf8Wifi(ssid), Utf8Wifi('test-only-123'))
            packet = algo.simple_encrypt(base64.b64decode(words))
            self.assertEqual(packet[0] & 63, len(ssid.encode('utf-8')))
            self.assertEqual(packet[12:12 + len(ssid.encode('utf-8'))].decode('utf-8'), ssid)
            qr = qrcode.QRCode(box_size=8, border=4)
            qr.add_data(words)
            qr.make(fit=True)
            image = (1 - np.array(qr.get_matrix(), dtype=np.uint8)) * 255
            image = np.repeat(np.repeat(image, 8, axis=0), 8, axis=1)
            decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
            self.assertEqual(decoded, words)

    def test_qr_starts_only_explicit_pair_listener_then_cancel_closes_it(self):
        class Listener:
            def __init__(self):
                self.closed = False
                self.wait = threading.Event()
            def bind(self, address):
                self.address = address
            def settimeout(self, value):
                pass
            def recvfrom(self, limit):
                self.wait.wait(.01)
                if self.closed:
                    raise OSError()
                raise socket.timeout()
            def close(self):
                self.closed = True
                self.wait.set()
        listener = Listener()
        with patch('ep_runtime.console_session.socket.socket', return_value=listener):
            result = self.session.handle('qr', {'ssid': 'Synthetic-EP', 'password': 'test-only-123'})
        self.assertEqual(listener.address, ('0.0.0.0', 45678))
        self.assertIn(b'<svg', base64.b64decode(result['svg_base64']))
        self.assertNotIn('test-only-123', str(result))
        self.assertIsNone(self.session.robot)
        self.session.cancel_pairing()
        self.assertTrue(listener.closed)

    def test_two_pairing_peers_are_acked_and_old_code_is_counted_without_exposing_credentials(self):
        import queue
        import time
        from robomaster import algo, conn
        helper = conn.ConnectionHelper()
        helper._appid = '12345'
        incoming = queue.Queue()
        def packet(appid, ip):
            plain = struct.pack('>HI4B6B', 0x5a5b, 1, 192, 168, 1, ip, 0, 1, 2, 3, 4, ip)
            return algo.simple_encrypt(plain + appid.encode().ljust(7, b'\0'))
        incoming.put((packet('12345', 2), ('192.168.1.2', 45678)))
        incoming.put((packet('12345', 3), ('192.168.1.3', 45678)))
        incoming.put((packet('99999', 4), ('192.168.1.4', 45678)))
        class Listener:
            closed = False
            replies = []
            def bind(self, address):
                pass
            def settimeout(self, timeout):
                pass
            def recvfrom(self, size):
                if self.closed:
                    raise OSError()
                try:
                    return incoming.get(timeout=.01)
                except queue.Empty:
                    raise TimeoutError() from None
            def sendto(self, data, address):
                self.replies.append(address)
            def close(self):
                self.closed = True
        listener = Listener()
        with patch('ep_runtime.console_session.socket.socket', return_value=listener), patch('robomaster.conn.ConnectionHelper', return_value=helper):
            self.session.qr('Synthetic-EP', 'test-only-123')
        deadline = time.monotonic() + 1
        while self.session.pair_diagnostics['received'] < 3 and time.monotonic() < deadline:
            time.sleep(.01)
        state = self.session.status()
        self.assertEqual(state['pairing_diagnostics']['accepted'], 2)
        self.assertEqual(state['pairing_diagnostics']['wrong_code'], 1)
        self.assertEqual(len(state['candidates']), 2)
        self.assertEqual(len(listener.replies), 2)
        self.assertNotIn('test-only-123', str(state))
        self.assertNotIn('12345', str(state))

    def test_connect_requires_confirmation_and_valid_private_ip_before_sdk(self):
        self.session.sdk_loader = Mock(side_effect=AssertionError('must not initialize'))
        with self.assertRaises(ControlError):
            self.session.connect('192.168.1.2', False)
        for ip in ('127.0.0.1', '8.8.8.8', '0.0.0.0', '224.0.0.1', '169.254.1.2', 'bad-ip'):
            with self.assertRaises(ControlError):
                self.session.connect(ip, True)

    def test_explicit_target_zero_speed_start_and_replay_stops_fake_robot(self):
        robot = self.fake_robot()
        self.session.sdk_loader = lambda: SimpleNamespace(Robot=lambda: robot)
        with patch('ep_runtime.console_session.local_ep_ip', return_value='192.168.1.3'):
            status = self.session.connect('192.168.1.2', True)
        self.assertEqual(status['connection'], 'connected')
        robot.initialize.assert_called_once_with(conn_type='sta', proto_type='udp')
        robot.chassis.drive_speed.assert_not_called()
        robot.client._conn._sock.sendto.assert_not_called()
        self.assertIsNone(self.session.control)
        robot.set_robot_mode.assert_not_called()
        robot.gimbal.recenter.assert_not_called()
        with self.assertRaises(ControlError):
            self.session.connect('192.168.1.2', True)
        self.session.handle('prepare-control', {})
        self.assertEqual([call.kwargs for call in robot.set_robot_mode.call_args_list], [{'mode': 'free'}, {'mode': 'chassis_lead'}])
        robot.gimbal.recenter.assert_called_once_with(pitch_speed=30, yaw_speed=60)
        robot.get_robot_mode.assert_called_once_with()
        self.assertEqual(self.session.status()['drive_mode'], 'chassis_lead')
        self.assert_wheel_stop(robot)
        lease = self.session.handle('lease', {})
        import time
        command = RobotCommand(lease_token=lease['lease_token'], seq=0,
                              issued_at_ms=int(time.time()*1000), ttl_ms=300, direction='forward')
        self.session.handle('command', command.model_dump())
        self.assertAlmostEqual(struct.unpack_from('<fff', robot.client._conn._sock.sendto.call_args.args[0], 11)[0], .15)
        with self.assertRaises(ControlError):
            self.session.handle('command', command.model_dump())
        self.assertEqual(self.session.control.direction, 'stop')
        self.assertFalse(self.session.control.lease)

    def test_selects_only_matching_local_interface(self):
        adapter = lambda ip, prefix: SimpleNamespace(ips=[SimpleNamespace(ip=ip, network_prefix=prefix)])
        target = ipaddress.IPv4Address('192.168.1.2')
        self.assertEqual(local_ep_ip(target, [adapter('10.0.0.2', 24), adapter('192.168.1.3', 24)]), '192.168.1.3')
        with self.assertRaises(ControlError):
            local_ep_ip(target, [adapter('10.0.0.2', 24)])

    def test_remembered_identity_mismatch_never_prepares_or_moves_robot(self):
        robot = self.fake_robot()
        self.session.sdk_loader = lambda: SimpleNamespace(Robot=lambda: robot)
        with patch('ep_runtime.console_session.local_ep_ip', return_value='192.168.1.3'):
            with self.assertRaisesRegex(ControlError, '機體位址已變更'):
                self.session.connect('192.168.1.2', True, expected_sn='OTHER-SYNTHETIC-EP')
        self.assertIsNone(self.session.robot)
        self.assertIsNone(self.session.control)
        robot.client._conn._sock.sendto.assert_not_called()
        robot.close.assert_called_once()

    def test_unconfirmed_chassis_follow_mode_refuses_controller_and_lease(self):
        robot = self.fake_robot()
        self.session.robot = robot
        robot.get_robot_mode.return_value = 'free'
        with self.assertRaisesRegex(ControlError, '鏡頭跟隨底盤'):
            self.session.prepare_control()
        self.assertIsNone(self.session.control)
        self.assertIsNone(self.session.drive_mode)
        for call in robot.client._conn._sock.sendto.call_args_list:
            self.assertEqual(struct.unpack_from('<fff', call.args[0], 11), (0, 0, 0))

    def test_completed_but_failed_gimbal_center_cannot_enable_movement(self):
        robot = self.fake_robot()
        self.session.robot = robot
        robot.gimbal.recenter.return_value.has_succeeded = False
        with self.assertRaises(ControlError):
            self.session.prepare_control()
        self.assertIsNone(self.session.control)
        self.assertEqual([call.kwargs for call in robot.set_robot_mode.call_args_list], [{'mode': 'free'}])
        robot.get_robot_mode.assert_not_called()
        robot.chassis.drive_speed.assert_not_called()

    def test_idle_never_renews_body_velocity_or_sends_unsolicited_wheel_commands(self):
        robot = self.fake_robot()
        self.session.robot = robot
        for _ in range(200):
            self.session.hold_idle()
        robot.client._conn._sock.sendto.assert_not_called()
        robot.client.send_sync_msg.assert_not_called()
        self.session.control = SimpleNamespace(lease='synthetic-only', direction='forward', tick=lambda: None)
        self.session.hold_idle()
        robot.client._conn._sock.sendto.assert_not_called()
        robot.client.send_sync_msg.assert_not_called()
        self.session.control = None

    def test_two_minutes_after_release_or_timeout_send_no_further_motor_commands(self):
        # Fake clocks and socket only: this checks dispatch, not physical coasting.
        for source in ('release', 'host_limit'):
            with self.subTest(source=source):
                session, robot, now, payload = self.short_session(release_check=True)
                session.realtime_controls_enabled = False
                try:
                    with patch('ep_runtime.short_press_session.time.time', return_value=1.0):
                        session.handle('short-press-start', payload)
                        now[0] = .1 if source == 'release' else .501
                        if source == 'release':
                            session.handle('short-press-release', {**payload, 'source': 'release'})
                        else:
                            session.control.tick()
                    self.assert_wheel_stop(robot)
                    self.assertEqual(robot.client.send_sync_msg.call_count, 1)
                    for step in range(601):
                        now[0] = 1 + step * .2
                        session.control.tick()
                        session.hold_idle()
                        session.guard_chassis()
                        state = session.status()
                        self.assertFalse(state['control']['lease_active'])
                        self.assertEqual(state['control']['direction'], 'stop')
                    self.assertEqual(robot.client._conn._sock.sendto.call_count, 1)
                    self.assertEqual(robot.client.send_sync_msg.call_count, 1)
                    robot.chassis.drive_speed.assert_not_called()
                    robot.chassis.drive_wheels.assert_not_called()
                    robot.chassis._set_mode.assert_not_called()
                    robot.set_robot_mode.assert_not_called()
                finally:
                    session.stopping.set()
                    session.disconnect()

    def test_pinned_private_chassis_mode_method_ignores_requested_mode(self):
        # Characterize the fixed SDK before considering motor release. Do not
        # call this private method on hardware or infer its byte semantics here.
        from robomaster import chassis
        robot = self.fake_robot()
        native = chassis.Chassis(robot)
        native._send_sync_proto = Mock(return_value=True)
        for requested in (0, 1):
            self.assertTrue(native._set_mode(requested))
            proto = native._send_sync_proto.call_args.args[0]
            self.assertEqual((proto._cmdset, proto._cmdid), (0x3f, 0x19))
            self.assertEqual(proto.pack_req(), b'\x00')

    def test_stop_before_first_drive_never_centers_gimbal_and_latches_control(self):
        robot = self.fake_robot()
        self.session.robot = robot
        state = self.session.handle('stop', {})
        self.assertTrue(state['software_stop_latched'])
        self.assertEqual(state['direction'], 'stop')
        robot.gimbal.recenter.assert_not_called()
        robot.set_robot_mode.assert_not_called()
        for call in robot.client._conn._sock.sendto.call_args_list:
            self.assertEqual(struct.unpack_from('<fff', call.args[0], 11), (0, 0, 0))

    def test_wheel_stop_requires_reply_and_never_falls_back_to_body_speed(self):
        robot = self.fake_robot()
        self.session.robot = robot
        transport = LiveTransport(robot, model='EP', on_site_motion_authorized=True)
        for reply in [None, SimpleNamespace(get_proto=lambda: SimpleNamespace(_retcode=1))]:
            robot.client.send_sync_msg.return_value = reply
            with self.assertRaisesRegex(RuntimeError, 'not acknowledged'):
                transport.stop()
        robot.client._conn._sock.sendto.assert_not_called()
        robot.gimbal.recenter.assert_not_called()

    def test_pickup_revokes_active_motion_and_requires_explicit_reset(self):
        robot = self.fake_robot()
        self.session.robot = robot
        self.session.prepare_control()
        self.session.handle('lease', {})
        self.session.receive_chassis_status((0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        self.session.guard_chassis()
        self.assertTrue(self.session.control.stop_latched)
        self.assertIsNone(self.session.control.lease)
        self.assert_wheel_stop(robot)
        robot.client._conn._sock.sendto.assert_not_called()
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with self.assertRaises(ControlError):
            self.session.handle('lease', {})

    def test_stale_missing_invalid_or_rollover_status_cannot_prepare_or_move(self):
        robot = self.fake_robot()
        self.session.robot = robot
        for values in [None, (0,), (1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0),
                       (1, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0)]:
            self.session.receive_chassis_status(values)
            with self.assertRaises(ControlError):
                self.session.prepare_control()
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        self.session.chassis_status_at -= .6
        with self.assertRaises(ControlError):
            self.session.prepare_control()
        robot.gimbal.recenter.assert_not_called()
        robot.client.send_sync_msg.assert_not_called()
        robot.client._conn._sock.sendto.assert_not_called()

    def test_stop_reply_loss_latches_fault_and_cannot_be_reset_as_stationary(self):
        robot = self.fake_robot()
        self.session.robot = robot
        self.session.prepare_control()
        self.session.handle('lease', {})
        robot.client.send_sync_msg.return_value = None
        self.session.receive_chassis_status((0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        self.session.guard_chassis()
        self.assertEqual(self.session.control.state, 'fault')
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with self.assertRaises(ControlError):
            self.session.handle('reset-stop', {'confirmed_stationary': True})
        robot.client._conn._sock.sendto.assert_not_called()

    def test_persisted_stop_is_restored_before_any_gimbal_center_or_mode_change(self):
        robot = self.fake_robot()
        self.session.robot = robot
        self.session.handle('stop', {})
        self.session.control.close()
        self.session.control = None
        with self.assertRaises(ControlError):
            self.session.prepare_control()
        self.assertTrue(self.session.control.stop_latched)
        robot.gimbal.recenter.assert_not_called()
        robot.set_robot_mode.assert_not_called()
        self.session.handle('reset-stop', {'confirmed_stationary': True})
        self.session.prepare_control()
        robot.gimbal.recenter.assert_called_once()

    def test_speed_range_scales_only_manual_commands_and_cannot_change_during_lease(self):
        import time
        robot = self.fake_robot()
        self.session.robot = robot
        self.session.set_speed(4)
        self.session.prepare_control()
        lease = self.session.handle('lease', {})
        self.session.handle('command', {'lease_token': lease['lease_token'], 'seq': 0,
            'issued_at_ms': int(time.time()*1000), 'ttl_ms': 300, 'direction': 'forward'})
        self.assertAlmostEqual(struct.unpack_from('<fff', robot.client._conn._sock.sendto.call_args.args[0], 11)[0], .6)
        with self.assertRaises(ControlError):
            self.session.set_speed(1)
        self.session.control.software_stop()

    def test_cursor_controls_only_gimbal_with_expiry_and_generation_fencing(self):
        import time
        robot = self.fake_robot()
        robot.get_robot_mode.return_value = 'free'
        self.session.robot = robot
        self.session.configure_follow(False)
        robot.gimbal.recenter.assert_not_called()
        self.session.receive_gimbal_angles((0, 0, 0, 0))
        session = self.session.start_gimbal()
        payload = {'generation': session['generation'], 'seq': 0, 'issued_at_ms': int(time.time()*1000), 'pitch': 25, 'yaw': 60}
        self.session.target_gimbal(payload)
        self.session.update_gimbal()
        robot.gimbal.drive_speed.assert_called_with(pitch_speed=30, yaw_speed=60)
        self.session.gimbal_until = time.monotonic() - 1
        self.session.update_gimbal()
        robot.gimbal.drive_speed.assert_called_with(pitch_speed=0, yaw_speed=0)
        with self.assertRaises(ControlError):
            self.session.target_gimbal(payload)
        self.assertIsNone(self.session.control)
        for call in robot.client._conn._sock.sendto.call_args_list:
            self.assertEqual(struct.unpack_from('<fff', call.args[0], 11), (0, 0, 0))

    def test_reenabling_follow_always_recenters_before_restoring_chassis_follow(self):
        robot = self.fake_robot()
        self.session.robot = robot
        order = []
        centered = robot.gimbal.recenter.return_value
        def set_mode(*, mode):
            order.append(mode)
            robot.get_robot_mode.return_value = mode
            return True
        def recenter(**kwargs):
            order.append('recenter')
            self.assertEqual(kwargs, {'pitch_speed': 30, 'yaw_speed': 60})
            return centered
        robot.set_robot_mode.side_effect = set_mode
        robot.gimbal.recenter.side_effect = recenter
        self.session.configure_follow(True)
        self.session.configure_follow(False)
        self.session.receive_gimbal_angles((10, 45, 10, 45))
        self.session.configure_follow(True)
        self.assertEqual(order, ['free', 'recenter', 'chassis_lead', 'free', 'free', 'recenter', 'chassis_lead'])
        self.assertEqual(robot.gimbal.recenter.call_count, 2)
        self.assertTrue(self.session.status()['follow_enabled'])
        self.assertEqual(self.session.status()['drive_mode'], 'chassis_lead')
        self.assertIsNone(self.session.control)
        for call in robot.client._conn._sock.sendto.call_args_list:
            self.assertEqual(struct.unpack_from('<fff', call.args[0], 11), (0, 0, 0))

    def test_read_only_connection_does_not_depend_on_chassis_command_acceptance(self):
        robot = self.fake_robot()
        robot.client.send_sync_msg.side_effect = OSError('synthetic stop reply failure')
        self.session.sdk_loader = lambda: SimpleNamespace(Robot=lambda: robot)
        with patch('ep_runtime.console_session.local_ep_ip', return_value='192.168.1.3'):
            self.assertEqual(self.session.connect('192.168.1.2', True)['connection'], 'connected')
        robot.chassis.drive_speed.assert_not_called()
        with self.assertRaises(ControlError):
            self.session.prepare_control()
        self.assertEqual(self.session.status()['connection'], 'connected')
        self.assertIsNone(self.session.control)

    def test_push_protocol_has_no_ack_and_adapter_only_confirms_local_dispatch(self):
        from robomaster import chassis, client
        from types import MethodType
        robot = self.fake_robot()
        robot.client._running = True
        robot.client.send_sync_msg = MethodType(client.Client.send_sync_msg, robot.client)
        native_chassis = chassis.Chassis(robot)
        # Actual fixed SDK returns False on a successfully queued PUSH message.
        self.assertFalse(native_chassis.drive_speed(x=0, y=0, z=0))
        robot.client.send_msg.assert_called_once()
        self.assertEqual(robot.client.send_msg.call_args.args[0]._need_ack, 0)
        transport = LiveTransport(robot, model='EP', on_site_motion_authorized=True)
        transport.drive('left', 300)
        packet, target = robot.client._conn._sock.sendto.call_args.args
        self.assertEqual(target, ('192.168.1.2', 20020))
        self.assertEqual((packet[8] >> 5) & 3, 0)
        self.assertEqual(packet[9:11], bytes([0x3f, 0x21]))
        self.assertAlmostEqual(struct.unpack_from('<fff', packet, 11)[1], -.15)
        robot.client.send_sync_msg = Mock(return_value=SimpleNamespace(
            get_proto=lambda: SimpleNamespace(_retcode=0)))
        transport.stop()
        self.assert_wheel_stop(robot)

    def test_expired_command_sends_zero_through_live_adapter_without_real_network(self):
        robot = self.fake_robot()
        now = [0.0]
        transport = LiveTransport(robot, model='EP', on_site_motion_authorized=True)
        controller = RobotController(transport=transport, clock=lambda: now[0], wall_clock=lambda: 1.0)
        try:
            lease = controller.acquire()
            controller.command(RobotCommand(lease_token=lease['lease_token'], seq=0,
                issued_at_ms=1000, ttl_ms=300, direction='forward'))
            self.assertAlmostEqual(struct.unpack_from('<fff', robot.client._conn._sock.sendto.call_args.args[0], 11)[0], .15)
            now[0] = .301
            controller.tick()
            self.assert_wheel_stop(robot)
            self.assertFalse(controller.status()['lease_active'])
            self.assertEqual(controller.status()['direction'], 'stop')
        finally:
            controller.close()

    def test_original_sdk_drops_state_zero_acceptance_but_adapter_accepts_it(self):
        from robomaster import conn, protocol
        message = protocol.Msg(9, 0, protocol.ProtoSetSdkConnection())
        result = SimpleNamespace(_retcode=0, _state=0)
        response = Mock(is_ack=True, cmdset=message.cmdset, cmdid=message.cmdid,
                        _seq_id=message._seq_id)
        response.unpack_protocol.return_value = True
        response.get_proto.return_value = result
        sock = Mock()
        # Winsock raises WSAEINVAL for getsockname() on an unbound UDP socket.
        sock.getsockname.side_effect = OSError(10022, 'unbound socket')
        sock.recvfrom.return_value = (b'synthetic-ack', ('192.168.1.2', 30030))
        connection = SimpleNamespace(_sock=sock)
        stages = []
        with patch('robomaster.protocol.decode_msg', return_value=(response, b'')):
            self.assertIsNone(conn.SdkConnection.switch_remote_route(connection, message, ('192.168.1.2', 30030)))
            robot = SimpleNamespace(_sdk_conn=connection)
            attach_handshake(robot, '192.168.1.2', '192.168.1.3', stages.append)
            self.assertEqual(connection.switch_remote_route(message, ('192.168.1.2', 30030)), (True, '192.168.1.3'))
        self.assertEqual(message.get_proto().pack_req()[4:8], bytes([192, 168, 1, 3]))
        self.assertEqual(stages, ['network_handshake', 'network_ready'])
        sock.bind.assert_called_once_with(('192.168.1.3', 0))

    def test_handshake_busy_and_timeout_are_distinguished_without_exposing_packets(self):
        from robomaster import protocol
        message = protocol.Msg(9, 0, protocol.ProtoSetSdkConnection())
        response = Mock(is_ack=True, cmdset=message.cmdset, cmdid=message.cmdid, _seq_id=message._seq_id)
        response.unpack_protocol.return_value = True
        response.get_proto.return_value = SimpleNamespace(_retcode=0, _state=1)
        sock = Mock()
        sock.getsockname.return_value = ('192.168.1.3', 12345)
        sock.recvfrom.return_value = (b'private-synthetic-packet', ('192.168.1.2', 30030))
        connection = SimpleNamespace(_sock=sock)
        attach_handshake(SimpleNamespace(_sdk_conn=connection), '192.168.1.2', '192.168.1.3', lambda stage: None)
        with patch('robomaster.protocol.decode_msg', return_value=(response, b'')):
            with self.assertRaisesRegex(HandshakeError, '^robot_busy$'):
                connection.switch_remote_route(message, ('192.168.1.2', 30030))
        sock.recvfrom.side_effect = socket.timeout()
        with self.assertRaisesRegex(HandshakeError, '^handshake_timeout$'):
            connection.switch_remote_route(message, ('192.168.1.2', 30030))
        self.assertEqual(connection._console_error, 'handshake_timeout')

    def test_same_qr_is_available_after_time_and_page_reload_until_cleared(self):
        self.session.qr_image = 'synthetic-image-only'
        self.session.qr_ssid = 'Synthetic-EP'
        snapshot = self.session.handle('qr-status', {})
        self.assertIsNone(snapshot['expires_in_seconds'])
        self.assertEqual(snapshot['svg_base64'], 'synthetic-image-only')
        self.assertEqual(self.session.handle('status', {})['qr_expires_in_seconds'], 0)
        self.session.cancel_pairing()
        self.assertIsNone(self.session.handle('qr-status', {})['svg_base64'])


if __name__ == '__main__':
    unittest.main()
