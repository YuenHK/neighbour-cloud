"""Offline stage-six protocol tests; all real sockets are forbidden."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from edge_hub.robot_control import ControlError, RobotController
from ep_runtime import console_tests as helpers
from ep_runtime.body_snapshot import BodySnapshot
from ep_runtime.bootstrap import load_sdk
from ep_runtime.esc_snapshot import EscSnapshot, subscribe_snapshot_esc
from ep_runtime.idle_motor_session import IdleMotorEpSession, IdleMotorTransport


class IdleMotorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.addaudithook(helpers.deny_network)
        if hasattr(helpers.ConsoleTests, 'sdk'):
            cls.sdk = helpers.ConsoleTests.sdk
        else:
            cls.sdk, _ = load_sdk(helpers.ROOT / '.runtime/ep-sdk/source/src')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.robot = helpers.ConsoleTests.fake_robot(self)
        self.robot.dds.add_subject_info.return_value = True
        self.session = IdleMotorEpSession(Path(self.temp.name), lambda: self.sdk)
        self.session.realtime_controls_enabled = False
        self.session.robot = self.robot
        self.session.drive_mode = 'chassis_lead'
        self.session.prepared_idle = self.session.gimbal_mode_applied = True
        self.clock = [100.]
        self.monotonic = patch('ep_runtime.idle_motor_session.time.monotonic', side_effect=lambda: self.clock[0])
        self.monotonic.start()
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        self.session.control = RobotController(transport=IdleMotorTransport(self.session),
            clock=lambda: self.clock[0] - 100, wall_clock=lambda: 1.)
        self.session.motor_state = 'holding_zero'
        self.session.record_stop()
        self.payload = {'session_id': self.session.short_session, 'press_id': 'b' * 32,
                        'issued_at_ms': 1000, 'confirmed_clear_path': True}
        self.seq = 0

    def tearDown(self):
        self.session.stopping.set()
        self.session.disconnect()
        self.monotonic.stop()
        self.temp.cleanup()

    def deliver(self, values):
        for topic, values_body in [('position', (0., 0., 0.)), ('attitude', (0., 0., 0.)),
                                   ('velocity', (0.,) * 6)]:
            self.session.receive_body(BodySnapshot(topic, values_body, self.clock[0], self.seq + 1))
        self.session.receive_esc(EscSnapshot(values, self.clock[0]))

    def zero_samples(self):
        self.session.record_stop()  # synthetic new acknowledged-stop window
        # Samples strictly advance, span 2.2s and refresh independent ground flags.
        for _ in range(23):
            self.clock[0] += .1
            self.seq += 1
            self.deliver(([0] * 4, [0] * 4, [self.seq] * 4, [0] * 4))
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    def release(self, **extra):
        result = self.session.handle('motor-release', {'session_id': self.session.short_session,
            'stop_id': self.session.motor_stop_id, 'confirmed_stationary': True, **extra})
        # Fake post-ACK telemetry only; no extra hardware commands.
        for _ in range(24):
            self.clock[0] += .1
            self.seq += 1
            self.deliver(([0]*4, [0]*4, [self.seq]*4, [0]*4))
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return result

    def activate(self):
        with patch('ep_runtime.short_press_session.time.time', return_value=1.):
            return self.session.handle('motor-activate', self.payload)

    def packets(self):
        return [call.args[0].pack()[9:-2] for call in self.robot.client.send_sync_msg.call_args_list]

    def test_body_subscription_uses_native_topics_without_mutating_sdk_classes(self):
        from robomaster.chassis import PositionSubject

        from ep_runtime.body_snapshot import subscribe_body_snapshots
        original = PositionSubject.data_info
        self.assertTrue(subscribe_body_snapshots(self.robot, lambda frame: None))
        subjects = [call.args[0] for call in self.robot.dds.add_subject_info.call_args_list]
        self.assertEqual([subject.freq for subject in subjects], [10, 10, 10])
        self.assertEqual([subject.data_info().topic for subject in subjects],
                         ['position', 'attitude', 'velocity'])
        self.assertEqual(subjects[0]._cs, 1)
        self.assertIs(PositionSubject.data_info, original)
        self.robot.client.send_sync_msg.assert_not_called()

    def test_fresh_esc_alone_cannot_release_without_body_topics(self):
        for index in range(25):
            self.clock[0] += .1
            self.session.receive_esc(EscSnapshot(((0,)*4, (0,)*4, (index+1,)*4, (0,)*4), self.clock[0]))
        self.assertFalse(self.session.wheels_at_rest())
        with self.assertRaises(ControlError):
            self.release()
        self.robot.client.send_sync_msg.assert_not_called()

    def test_motor_count_anchor_is_diagnostic_not_a_body_motion_latch(self):
        self.zero_samples()
        for index in range(90):
            self.clock[0] += .1
            self.seq += 1
            self.deliver(([0]*4, [index // 3, 0, 0, 0], [self.seq]*4, [0]*4))
            self.session.wheels_at_rest()
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        state = self.session.status()
        self.assertEqual(state['esc_diagnostics']['encoder_comparator']['reason'], 'encoder_drift_since_rest')
        self.assertIsNotNone(state['esc_diagnostics']['encoder_comparator']['first_block'])
        self.assertIsNone(state['esc_diagnostics']['first_block_evidence'])
        self.assertTrue(state['wheel_rest_confirmed'])
        self.assertFalse(state['movement_enabled'])
        self.robot.client.send_sync_msg.assert_not_called()
        with self.assertRaises(ControlError):
            self.release(confirmed_stationary=False)

    def test_only_actual_release_ack_starts_observation_and_new_epoch(self):
        self.zero_samples()
        state = self.session.status()
        self.assertIsNone(state['motor_release_receipt'])
        self.assertEqual(state['released_observation_seconds'], 0)
        state = self.session.handle('motor-release', {'session_id': self.session.short_session,
            'stop_id': self.session.motor_stop_id, 'confirmed_stationary': True})
        self.assertIsNotNone(state['motor_release_receipt'])
        self.assertFalse(state['wheel_rest_confirmed'])
        self.assertFalse(state['movement_enabled'])
        self.clock[0] += 120
        state = self.session.status()
        self.assertEqual(state['released_observation_seconds'], 120)
        self.assertFalse(state['motor_release_receipt']['physical_effect_verified'])
        self.assertFalse(state['movement_enabled'])  # elapsed alone never passes stale telemetry

    def test_release_failure_never_creates_observation_receipt(self):
        self.zero_samples()
        self.robot.client.send_sync_msg.return_value = None
        with self.assertRaises(ControlError):
            self.release()
        self.assertIsNone(self.session.status()['motor_release_receipt'])
        self.assertEqual(self.session.status()['released_observation_seconds'], 0)

    def test_explicit_rest_confirmation_and_fresh_samples_required(self):
        with self.assertRaises(ControlError):
            self.release()
        self.zero_samples()
        with self.assertRaises(ControlError):
            self.release(confirmed_stationary=False)
        with self.assertRaises(ControlError):
            self.release(stop_id='c' * 32)
        self.robot.client.send_sync_msg.assert_not_called()
        self.assertEqual(self.release()['motor_state'], 'released_reply')
        self.assertEqual(self.packets(), [b'\x3f\x19\x00'])
        self.robot.chassis._set_mode.assert_not_called()
        self.robot.client._conn._sock.sendto.assert_not_called()
        self.session.disconnect()
        self.assertEqual(self.packets(), [b'\x3f\x19\x00'])

    def test_release_enable_separate_start_stop_and_new_confirmation_release(self):
        self.zero_samples()
        old_stop = self.session.motor_stop_id
        self.release()
        self.activate()
        self.assertEqual(self.packets()[:2], [b'\x3f\x19\x00', b'\x3f\x19\x01'])
        self.assertEqual(self.packets()[2], b'\x3f\x20' + bytes(8))
        self.robot.client._conn._sock.sendto.assert_not_called()
        with patch('ep_runtime.short_press_session.time.time', return_value=1.):
            self.session.handle('short-press-start', self.payload)
            state = self.session.handle('short-press-release', {**self.payload, 'source': 'release'})
        self.assertEqual(state['control']['direction'], 'stop')
        self.assertNotEqual(self.session.motor_stop_id, old_stop)
        self.assertEqual(self.robot.client._conn._sock.sendto.call_count, 1)
        with self.assertRaises(ControlError):
            self.release()
        self.zero_samples()
        self.release()
        before = len(self.packets())
        self.clock[0] += 120
        for _ in range(600):
            self.session.control.tick()
            self.session.hold_idle()
            self.session.guard_chassis()
        self.assertEqual(len(self.packets()), before)
        self.assertEqual(self.packets()[-1], b'\x3f\x19\x00')
        with self.assertRaises(ControlError):
            self.activate()

    def test_nonzero_replayed_or_stale_telemetry_cannot_release(self):
        self.zero_samples()
        self.deliver(([7, 0, 0, 0], [0] * 4, [self.seq + 1] * 4, [0] * 4))
        with self.assertRaises(ControlError):
            self.release()
        self.zero_samples()
        self.deliver(([0] * 4, [1, 0, 0, 0], [self.seq] * 4, [0] * 4))
        with self.assertRaises(ControlError):
            self.release()
        self.zero_samples()
        self.clock[0] += .251
        with self.assertRaises(ControlError):
            self.release()
        self.robot.client.send_sync_msg.assert_not_called()

    def test_early_release_fences_activation_without_engaging_or_moving(self):
        self.zero_samples()
        self.release()
        self.session.handle('short-press-release', self.payload)
        with self.assertRaises(ControlError):
            self.activate()
        self.assertEqual(self.packets(), [b'\x3f\x19\x00'])
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_release_after_activation_fences_late_start(self):
        self.zero_samples()
        self.release()
        self.activate()
        self.session.handle('short-press-release', self.payload)
        with patch('ep_runtime.short_press_session.time.time', return_value=1.):
            self.session.handle('short-press-start', self.payload)
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_late_enable_reply_cannot_extend_original_press_deadline(self):
        self.zero_samples()
        self.release()
        self.activate()
        with patch('ep_runtime.short_press_session.time.time', return_value=1.501), self.assertRaises(ControlError):
            self.session.handle('short-press-start', self.payload)
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_mode_ack_loss_faults_without_moving_and_cannot_reset(self):
        self.zero_samples()
        self.release()
        self.robot.client.send_sync_msg.return_value = None
        with self.assertRaises(ControlError):
            self.activate()
        self.assertEqual(self.session.control.state, 'fault')
        self.assertTrue(self.session.control.stop_latched)
        evidence = self.session.status()['motor_mode_diagnostics'][-1]
        self.assertEqual(evidence['stage'], 'engage_mode')
        self.assertEqual(evidence['outcome'], 'no_reply')
        self.assertEqual(evidence['ack_timeout_ms'], 500)
        with self.assertRaises(ControlError):
            self.session.control.reset_software_stop()
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_bad_subscription_or_stop_ack_does_not_allow_release(self):
        self.session.control.close()
        self.session.control = None
        self.session.prepared_idle = self.session.gimbal_mode_applied = False
        self.robot.dds.add_subject_info.return_value = False
        with self.assertRaises(ControlError):
            self.session.handle('prepare-control', {})
        self.assertEqual(self.session.control.state, 'fault')
        self.assertFalse(self.session.status()['movement_enabled'])

    def test_release_ack_loss_never_claims_released_and_latches_fault(self):
        self.zero_samples()
        self.robot.client.send_sync_msg.return_value = None
        with self.assertRaises(ControlError):
            self.release()
        self.assertEqual(self.session.motor_state, 'unknown')
        self.assertEqual(self.session.control.state, 'fault')
        self.assertTrue(self.session.control.stop_latched)
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_enable_success_but_zero_stop_ack_loss_still_refuses_motion(self):
        self.zero_samples()
        self.release()
        success = self.robot.client.send_sync_msg.return_value
        self.robot.client.send_sync_msg.side_effect = [success, None, success]
        with self.assertRaises(ControlError):
            self.activate()
        self.assertEqual(self.session.motor_state, 'unknown')
        self.assertEqual(self.session.control.state, 'fault')
        evidence = self.session.status()['motor_mode_diagnostics'][-1]
        self.assertEqual(evidence['stage'], 'zero_stop_after_engage')
        self.assertTrue(evidence['engage_mode_acknowledged'])
        with self.assertRaises(ControlError):
            self.session.handle('short-press-start', self.payload)
        self.robot.client._conn._sock.sendto.assert_not_called()
        self.robot.client.send_sync_msg.side_effect = None

    def test_mode_negative_ack_is_not_timeout_and_never_retried_or_accepted(self):
        self.zero_samples()
        self.robot.client.send_sync_msg.return_value = SimpleNamespace(
            get_proto=lambda: SimpleNamespace(_retcode=7))
        with self.assertRaises(ControlError):
            self.release()
        evidence = self.session.status()['motor_mode_diagnostics'][-1]
        self.assertEqual(evidence['outcome'], 'reply_not_successful')
        self.assertEqual(evidence['retcode'], 7)
        self.assertEqual(evidence['stage'], 'release_mode')
        self.assertEqual(self.session.control.state, 'fault')
        self.assertEqual(len(self.session.motor_mode_diagnostics), 1)
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_mode_exception_reports_only_type_without_leaking_exception_message(self):
        self.zero_samples()
        self.robot.client.send_sync_msg.side_effect = RuntimeError('synthetic-private-message')
        with self.assertRaises(ControlError):
            self.release()
        evidence = self.session.status()['motor_mode_diagnostics'][-1]
        self.assertEqual(evidence['outcome'], 'exception')
        self.assertEqual(evidence['exception_type'], 'RuntimeError')
        self.assertNotIn('synthetic-private-message', str(evidence))
        self.robot.client.send_sync_msg.side_effect = None

    def test_mode_and_following_zero_ack_are_journalled_separately_without_control_credentials(self):
        self.zero_samples()
        self.assertEqual(self.session.status()['motor_transition_version'], 'durable-ack-v1')
        self.release()
        self.activate()
        rows = [json.loads(line) for line in self.session.motor_trace.path.read_text().splitlines()]
        completed = [(row['stage'], row['outcome']) for row in rows if row['outcome'] != 'pending']
        self.assertEqual(completed, [('release_mode', 'acknowledged'), ('engage_mode', 'acknowledged'),
                                    ('zero_stop_after_engage', 'acknowledged')])
        text = self.session.motor_trace.path.read_text()
        for secret in (self.session.short_session, self.payload['press_id'], 'issued_at_ms', 'confirmed_clear_path'):
            self.assertNotIn(secret, text)
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_unwritable_intent_journal_sends_no_mode_packet_and_does_not_clear_any_fault(self):
        self.zero_samples()
        with patch.object(self.session.motor_trace, 'append', side_effect=OSError), self.assertRaises(ControlError):
            self.release()
        self.robot.client.send_sync_msg.assert_not_called()
        self.assertEqual(self.session.motor_state, 'holding_zero')
        self.assertFalse(self.session.motor_mode_diagnostics[-1]['diagnostic_persisted'])

    def test_lost_post_ack_record_faults_without_movement_or_ack_retry(self):
        self.zero_samples()
        with patch.object(self.session.motor_trace, 'append', side_effect=[None, OSError]), self.assertRaises(ControlError):
            self.release()
        self.assertEqual(self.session.control.state, 'fault')
        self.assertEqual(self.session.control.reason, 'motor_transition_record_unavailable')
        evidence = self.session.motor_mode_diagnostics[-1]
        self.assertEqual(evidence['outcome'], 'acknowledged')
        self.assertFalse(evidence['diagnostic_persisted'])
        self.assertEqual(sum(packet[:2] == b'\x3f\x19' for packet in self.packets()), 1)
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_negative_ack_is_saved_before_generic_fault_cleanup(self):
        self.zero_samples()
        self.robot.client.send_sync_msg.return_value = SimpleNamespace(
            get_proto=lambda: SimpleNamespace(_retcode=7))
        with self.assertRaises(ControlError):
            self.release()
        rows = [json.loads(line) for line in self.session.motor_trace.path.read_text().splitlines()]
        self.assertEqual(rows[-1]['stage'], 'release_mode')
        self.assertEqual(rows[-1]['outcome'], 'reply_not_successful')
        self.assertEqual(rows[-1]['retcode'], 7)

    def test_journal_latency_never_extends_the_original_press_deadline(self):
        self.zero_samples()
        self.release()
        wall = [1.]
        def slow_record(*args, **kwargs):
            wall[0] += .2
        with patch('ep_runtime.short_press_session.time.time', side_effect=lambda: wall[0]):
            with patch.object(self.session.motor_trace, 'append', side_effect=slow_record):
                self.session.handle('motor-activate', self.payload)
            with self.assertRaises(ControlError):
                self.session.handle('short-press-start', self.payload)
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_malformed_samples_and_unknown_stop_cannot_release(self):
        for values in (None, [0], ([False] * 4, [0] * 4, [1] * 4, [0] * 4)):
            self.zero_samples()
            self.deliver(values)
            self.assertFalse(self.session.wheels_at_rest())
        self.zero_samples()
        self.session.motor_stop_id = None
        with self.assertRaises(ControlError):
            self.release()
        self.robot.client.send_sync_msg.assert_not_called()

    def test_readonly_diagnostics_distinguish_missing_sequence_nonzero_and_stale(self):
        self.assertEqual(self.session.status()['esc_diagnostics']['received'], 0)
        self.assertEqual(self.session.status()['esc_diagnostics']['reason'], 'waiting_after_stop')
        self.zero_samples()
        data = ([0] * 4, [0] * 4, [self.seq] * 4, [0] * 4)
        self.deliver((data[0], [1, 0, 0, 0], data[2], data[3]))
        state = self.session.status()
        self.assertEqual(state['esc_diagnostics']['reason'], 'sequence_not_advancing')
        self.assertEqual(state['esc_diagnostics']['speeds_rpm'], (0, 0, 0, 0))
        self.assertFalse(state['wheel_rest_confirmed'])
        self.deliver(([0, 7, 0, 0], [0] * 4, [self.seq + 1] * 4, [0] * 4))
        diagnostic = self.session.status()['esc_diagnostics']
        self.assertEqual(diagnostic['reason'], 'collecting_body_window')
        self.assertEqual(diagnostic['first_signal_anomaly']['reason'], 'sequence_not_advancing')
        self.assertTrue(diagnostic['signal_recovery_pending'])
        self.clock[0] += .251
        self.assertEqual(self.session.status()['esc_diagnostics']['reason'], 'stale_sample')
        self.deliver(None)
        self.assertEqual(self.session.status()['esc_diagnostics']['reason'], 'invalid_sample')
        self.assertEqual(self.session.status()['esc_diagnostics']['invalid'], 1)
        self.robot.client.send_sync_msg.assert_not_called()
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_small_signed_speed_requires_bounded_angles_for_two_seconds(self):
        readings = ([4, -4, -3, 1], [-2, 1, -3, -3], [0, 1, -1, 1], [-6, -1, 0, -2])
        for step in range(23):
            self.clock[0] += .1
            self.seq += 1
            self.deliver((readings[step % 4], [123, 456, 789, 321], [self.seq] * 4, [0] * 4))
            if step < 20:
                self.assertFalse(self.session.wheels_at_rest())
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        self.assertTrue(self.session.status()['wheel_rest_confirmed'])
        self.assertEqual(self.session.status()['esc_diagnostics']['angles_raw'], (123, 456, 789, 321))
        with self.assertRaises(ControlError):
            self.release(confirmed_stationary=False)
        self.robot.client.send_sync_msg.assert_not_called()
        self.release()
        self.assertEqual(self.packets(), [b'\x3f\x19\x00'])
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_encoder_travel_blocks_release_even_with_zero_speed(self):
        self.zero_samples()
        for step in range(30):
            self.clock[0] += .1
            self.seq += 1
            self.deliver(([0] * 4, [step * 512, 0, 0, 0], [self.seq] * 4, [0] * 4))
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        self.assertFalse(self.session.wheels_at_rest())
        with self.assertRaises(ControlError):
            self.release()
        self.assertEqual(self.session.status()['esc_diagnostics']['reason'], 'wheel_rotation_in_window')
        self.robot.client.send_sync_msg.assert_not_called()

    def test_invalid_encoder_values_never_count_as_rest(self):
        for angles in ([None] * 4, [False] * 4, [32768] * 4):
            self.zero_samples()
            self.deliver(([0] * 4, angles, [self.seq + 1] * 4, [0] * 4))
            self.assertFalse(self.session.wheels_at_rest())
        self.robot.client.send_sync_msg.assert_not_called()

    def test_delayed_decode_callback_cannot_appear_fresh(self):
        self.zero_samples()
        frame = EscSnapshot(((0,)*4, (0,)*4, (self.seq + 1,)*4, (0,)*4), self.clock[0] - .3)
        self.session.receive_esc(frame)
        self.assertFalse(self.session.wheels_at_rest())
        self.assertEqual(self.session.status()['esc_diagnostics']['reason'], 'delayed_callback')
        self.robot.client.send_sync_msg.assert_not_called()

    def test_raw_mutable_callback_is_not_accepted_as_a_verified_snapshot(self):
        self.zero_samples()
        self.session.receive_esc(([0]*4, [0]*4, [self.seq + 1]*4, [0]*4))
        self.assertFalse(self.session.wheels_at_rest())
        self.assertEqual(self.session.status()['esc_diagnostics']['reason'], 'unverified_snapshot')
        with self.assertRaises(ControlError):
            self.release()

    def test_decode_timestamp_is_used_instead_of_callback_arrival_time(self):
        self.seq += 1
        self.clock[0] += .2
        self.session.receive_esc(EscSnapshot(((0,)*4, (0,)*4, (self.seq,)*4, (0,)*4), self.clock[0] - .15))
        diagnostic = self.session.status()['esc_diagnostics']
        self.assertTrue(diagnostic['atomic_snapshot'])
        self.assertGreaterEqual(diagnostic['sample_age_ms'], 149)

    def test_snapshot_subject_uses_native_esc_uid_without_mutating_sdk_class(self):
        import struct

        from robomaster.chassis import EscSubject
        old_decode, old_data = EscSubject.decode, EscSubject.data_info
        captured = []
        def add(subject, callback, args, kwargs):
            subject.set_callback(callback, args, kwargs)
            subject.decode(struct.pack('<hhhhhhhhIIIIBBBB', *range(16)))
            subject.exec()
            return True
        self.robot.dds.add_subject_info.side_effect = add
        self.assertTrue(subscribe_snapshot_esc(self.robot, captured.append))
        self.assertEqual(captured[0].values[0], (0, 1, 2, 3))
        self.assertEqual(captured[0].values[2], (8, 9, 10, 11))
        subject = self.robot.dds.add_subject_info.call_args.args[0]
        self.assertEqual(subject.freq, 10)
        self.assertEqual(subject.uid, EscSubject.uid)
        self.assertIs(EscSubject.decode, old_decode)
        self.assertIs(EscSubject.data_info, old_data)
        self.robot.client.send_sync_msg.assert_not_called()

    def test_duplicate_callback_does_not_reset_rest_or_make_old_data_fresh(self):
        self.zero_samples()
        payload = ((0,)*4, (0,)*4, (self.seq,)*4, (0,)*4)
        self.session.receive_esc(EscSnapshot(payload, self.clock[0]))
        self.assertTrue(self.session.wheels_at_rest())
        self.clock[0] += .2
        self.session.receive_esc(EscSnapshot(payload, self.clock[0]))
        self.assertGreaterEqual(self.session.esc_diagnostics()['sample_age_ms'], 199)
        self.clock[0] += .1
        self.session.receive_esc(EscSnapshot(payload, self.clock[0]))
        self.assertFalse(self.session.wheels_at_rest())
        self.assertEqual(self.session.esc_diagnostics()['duplicate_callbacks'], 3)

    def test_pre_stop_decode_cannot_be_counted_after_stop_ack(self):
        old_time = self.clock[0]
        self.clock[0] += .1
        self.session.record_stop()
        self.session.receive_esc(EscSnapshot(((0,)*4, (0,)*4, (1,)*4, (0,)*4), old_time))
        self.assertFalse(self.session.wheels_at_rest())
        self.assertIsNone(self.session.esc_at)
        self.robot.client.send_sync_msg.assert_not_called()

    def test_native_esc_data_aliasing_is_reproduced_and_snapshot_adapter_fixes_it(self):
        import struct

        from robomaster.chassis import EscSubject

        from ep_runtime.esc_snapshot import install_snapshot_decoder
        first = struct.pack('<hhhhhhhhIIIIBBBB', *range(16))
        second = bytes(36)
        native = EscSubject()
        native.decode(first)
        borrowed = native.data_info()
        native.decode(second)
        self.assertEqual(borrowed[0], [0]*4)  # callback's old data was overwritten
        patched = install_snapshot_decoder(EscSubject(), clock=lambda: 1.)
        patched.decode(first)
        frozen = patched.data_info()
        patched.decode(second)
        self.assertEqual(frozen.values[0], (0, 1, 2, 3))
        self.assertEqual(frozen.values[2], (8, 9, 10, 11))

    def test_reference_history_jitter_does_not_latch_or_bypass_operator_release_confirmation(self):
        pattern = (-2, 0, 0, 0, 2, 0, 0, 0)
        for index in range(58):
            self.clock[0] += .1
            self.seq += 1
            offset = pattern[index % 8] if index < 26 else 0
            self.deliver(([0]*4, [100 + offset, 0, 0, 0], [self.seq]*4, [0]*4))
        self.clock[0] += .1
        self.seq += 1
        self.deliver(([0]*4, [103, 0, 0, 0], [self.seq]*4, [0]*4))
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        state = self.session.status()
        self.assertEqual(state['rest_evidence_version'], 'body-window-v5')
        self.assertTrue(state['wheel_rest_confirmed'])
        self.assertIsNone(state['esc_diagnostics']['first_block_evidence'])
        with self.assertRaises(ControlError):
            self.release(confirmed_stationary=False)
        self.robot.client.send_sync_msg.assert_not_called()
        self.release()  # fake socket only; actual operator confirmation still required
        self.assertEqual(self.packets(), [b'\x3f\x19\x00'])
        self.robot.client._conn._sock.sendto.assert_not_called()

    def test_unknown_19_rpm_requires_new_window_and_operator_confirmation_not_new_origin(self):
        self.zero_samples()
        origin = self.session.rest_evidence.anchor
        self.clock[0] += .1
        self.seq += 1
        self.deliver(([19, 0, 0, 0], [0]*4, [self.seq]*4, [0]*4))
        self.assertFalse(self.session.wheels_at_rest())
        with self.assertRaises(ControlError):
            self.release()
        self.robot.client.send_sync_msg.assert_not_called()
        for _ in range(27):
            self.clock[0] += .1
            self.seq += 1
            self.deliver(([0]*4, [0]*4, [self.seq]*4, [0]*4))
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        state = self.session.status()
        self.assertTrue(state['wheel_rest_confirmed'])
        self.assertEqual(self.session.rest_evidence.anchor, origin)
        self.assertEqual(state['esc_diagnostics']['first_signal_anomaly']['max_abs_rpm'], 19)
        self.assertEqual(state['esc_diagnostics']['signal_recoveries'], 1)
        self.robot.client.send_sync_msg.assert_not_called()
        with self.assertRaises(ControlError):
            self.release(confirmed_stationary=False)
        self.release()  # fake mode packet, only after explicit confirmation
        self.assertEqual(self.packets(), [b'\x3f\x19\x00'])

    def test_quality_window_recovery_cannot_clear_application_fault_or_enable_release(self):
        self.zero_samples()
        for _ in range(3):
            self.clock[0] += .1
            self.seq += 1
            self.deliver(([19, 0, 0, 0], [0]*4, [self.seq]*4, [0]*4))
        self.session.control.state = 'fault'
        self.session.control.stop_latched = True
        for _ in range(30):
            self.clock[0] += .1
            self.seq += 1
            self.deliver(([0]*4, [0]*4, [self.seq]*4, [0]*4))
        self.session.receive_chassis_status((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        state = self.session.status()
        self.assertTrue(state['wheel_rest_confirmed'])
        self.assertEqual(state['esc_diagnostics']['first_signal_anomaly']['kind'], 'rpm_quality')
        self.assertEqual(state['control']['state'], 'fault')
        self.assertTrue(state['control']['software_stop_latched'])
        self.assertFalse(state['movement_enabled'])
        with self.assertRaises(ControlError):
            self.release()
        self.robot.client.send_sync_msg.assert_not_called()


if __name__ == '__main__':
    unittest.main()
