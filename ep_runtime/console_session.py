"""Explicit UI-triggered EP session, loaded only by the dedicated worker."""
import base64
import io
import ipaddress
import json
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import closing

from edge_hub.robot_control import (
    ControlError,
    DjiEpTransport,
    RobotCommand,
    RobotController,
    _read_safety_marker,
)
from ep_runtime.control_ack import ControlReplyError, confirm_sdk_enable, request_ack
from ep_runtime.handshake import HandshakeError, attach_handshake
from ep_runtime.infrared_warning import InfraredWarning
from ep_runtime.manual_warning import ManualWarning
from ep_runtime.patrol_context import PatrolContext


class Utf8Wifi(str):
    # DJI's pack() uses len(str) for byte offsets. Keep sources pristine while
    # supplying UTF-8 byte lengths for non-ASCII router names.
    def __len__(self):
        return len(self.encode('utf-8'))


class LiveTransport(DjiEpTransport):
    mode = 'dji-ep-sdk-live'
    connected = True

    def command_client(self):
        client = self.robot.client
        connection = client._conn
        if (connection._proto_type != 'udp' or connection._sock is None
                or connection._target_addr != (self.robot.ip, 20020)):
            raise RuntimeError('EP UDP command connection unavailable')
        return client

    def emit_speed(self, x, y, z):
        from robomaster import protocol
        client = self.command_client()
        connection = client._conn
        proto = protocol.ProtoChassisSpeedMode()
        proto._x_spd, proto._y_spd, proto._z_spd = float(x), float(y), float(z)
        message = protocol.Msg(client.hostbyte, self.robot.chassis._host, proto)
        # DJI marks this protocol PUSH / no ACK. Its public drive_speed()
        # sends successfully but returns False through _send_sync_proto().
        # Verify local socket dispatch only; never represent it as robot ACK.
        packet = message.pack()
        if connection._sock.sendto(packet, connection._target_addr) != len(packet):
            raise RuntimeError('EP UDP command dispatch failed')

    def drive(self, direction, ttl_ms):
        if (type(direction) is not str or direction not in self.VELOCITIES
                or type(ttl_ms) is not int or not 1 <= ttl_ms <= 500):
            raise ControlError('unsupported_motion')
        self.emit_speed(*(value * getattr(self, 'speed_level', 1) for value in self.VELOCITIES[direction]))

    def stop(self):
        from robomaster import protocol
        try:
            client = self.command_client()
        except RuntimeError:
            diagnostic = {'code': 'command_channel_unavailable', 'retcode': None, 'cmdset': 0x3f, 'cmdid': 0x20}
            if hasattr(self, 'diagnostic_sink'):
                self.diagnostic_sink(diagnostic)
            raise ControlReplyError(diagnostic) from None
        # End body-velocity control with four zero wheel targets. A successful
        # protocol reply is still not physical-stop verification.
        proto = protocol.ProtoSetWheelSpeed()
        message = protocol.Msg(client.hostbyte, self.robot.chassis._host, proto)
        try:
            diagnostic = request_ack(client, message, timeout=.5)
        except ControlReplyError as error:
            if hasattr(self, 'diagnostic_sink'):
                self.diagnostic_sink(error.diagnostic)
            raise
        if hasattr(self, 'diagnostic_sink'):
            self.diagnostic_sink(diagnostic)



def local_ep_ip(target, adapters):
    matches = []
    for adapter in adapters:
        for address in adapter.ips:
            if not isinstance(address.ip, str):
                continue
            network = ipaddress.IPv4Network(f'{address.ip}/{address.network_prefix}', strict=False)
            if target in network and not network.is_loopback:
                matches.append((network.prefixlen, address.ip))
    if not matches:
        raise ControlError('本機與 EP 不在同一 IPv4 網段，請核對路由器及 IP。', 409)
    prefix = max(item[0] for item in matches)
    addresses = {ip for bits, ip in matches if bits == prefix}
    if len(addresses) != 1:
        raise ControlError('多個本機網卡與 EP 網段重疊，請先核對網絡介面。', 409)
    return addresses.pop()


class EpSession:
    def __init__(self, root, sdk_loader, progress=None):
        self.root, self.sdk_loader = root, sdk_loader
        self.sdk = self.robot = self.control = None
        self.manual_warning = ManualWarning()
        self.infrared_warning = InfraredWarning()
        self.patrol_context = PatrolContext(self)
        self.version = self.sn = self.ip = ''
        self.progress = progress or (lambda stage: None)
        self.connection_stage = 'idle'
        self.last_connection_error = None
        self.sdk_confirmation = None
        self.stop_confirmation = None
        self.qr_image = None
        self.qr_revision = ''
        self.qr_ssid = ''
        self.scan_counter = 0
        self.last_pair_reply_at = 0
        self.last_pair_reply_wall = 0
        self.last_pairing_flag = False
        self.auto_connect_suppressed_scan = 0
        self.pair_socket = None
        self.pair_thread = None
        self.pair_cancel = threading.Event()
        self.pair_generation = 0
        self.pair_state = 'idle'
        self.pair_expires = 0
        self.detected_ip = ''
        self.last_request = time.monotonic()
        self.candidates = {}
        self.battery_percent = None
        self.battery_at = 0
        self.video_enabled = False
        self.video_error = None
        self.video_frame = None
        self.video_at = 0
        self.video_cancel = threading.Event()
        self.video_thread = None
        self.video_sink = None
        self.video_sequence = 0
        self.video_epoch = ''
        self.video_snapshot = None
        self.view_last_request = 0
        self.device_id = None
        self.sdk_port = None
        self.drive_mode = None
        self.follow_enabled = True
        self.gimbal_mode_applied = False
        self.speed_level = 1
        self.realtime_controls_enabled = False
        self.last_idle_zero = 0
        self.last_idle_success = 0
        self.idle_zero_count = 0
        self.idle_stop_error = False
        self.chassis_status = None
        self.chassis_status_at = 0
        self.gimbal_angles = None
        self.gimbal_angles_at = 0
        self.gimbal_generation = 0
        self.gimbal_sequence = -1
        self.gimbal_until = 0
        self.gimbal_target_angles = None
        self.gimbal_driving = False
        self.pair_diagnostics = {'received': 0, 'accepted': 0, 'wrong_code': 0, 'invalid': 0,
                                 'last_packet_at_ms': 0, 'last_wrong_code_at_ms': 0}
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.guard_thread = threading.Thread(target=self._watch_parent, daemon=True)
        self.guard_thread.start()

    def _watch_parent(self):
        while not self.stopping.wait(.1):
            if self.realtime_controls_enabled:
                with self.lock:
                    try:
                        self.guard_chassis()
                        self.update_gimbal()
                    except Exception:
                        self.idle_stop_error = True
            # Hub death or a closed/hidden page cannot leave a live lease renewed.
            if self.control and time.monotonic() - self.last_request > 3:
                with self.lock:
                    if self.control and self.control.lease:
                        self.control.software_stop()
            if self.video_enabled and time.monotonic() - self.view_last_request > 12:
                with self.lock:
                    self.stop_video()

    def load(self):
        if self.sdk is None:
            self.sdk = self.sdk_loader()
        return self.sdk

    def health(self):
        if not self.robot:
            return self.status()
        # Battery DDS is an independent live packet, unlike a locally dispatched speed PUSH.
        if self.battery_at and time.monotonic() - self.battery_at < 5:
            return self.status()
        if self.control and self.control.lease:
            if self.battery_at:
                self.disconnect()  # Stale telemetry: revoke control rather than renew blindly.
            return self.status()
        from robomaster import protocol
        try:
            message = protocol.Msg(self.robot.client.hostbyte, protocol.host2byte(8, 1), protocol.ProtoGetSn())
            response = self.robot.client.send_sync_msg(message, timeout=.5)
            alive = response is not None and response.get_proto()._sn == self.sn
        except Exception:
            alive = False
        if not alive:
            self.disconnect()
        return self.status()

    def status(self):
        control = self.control.status() if self.control else None
        return {'connection': 'connected' if self.robot else 'not_connected', 'warning': self.manual_warning.snapshot(),
                'context_capture_busy': self.patrol_context.busy, 'context_capture_state': self.patrol_context.job.get('state'),
                'ip': self.ip, 'firmware': self.version, 'sn': self.sn,
                'pairing': self.pair_state, 'detected_ip': self.detected_ip,
                'qr_expires_in_seconds': max(0, int(self.pair_expires - time.monotonic())),
                'control': control, 'video_enabled': self.video_enabled, 'audio_enabled': False,
                'battery_percent': self.battery_percent if time.monotonic() - self.battery_at < 5 else None,
                'battery_age_ms': int((time.monotonic() - self.battery_at) * 1000) if self.battery_at else None,
                'candidates': [{key: item[key] for key in ('ip', 'scan_id', 'scan_received_at_ms', 'first_seen_ms')}
                               for item in list(self.candidates.values())],
                'hardware_acceptance': False, 'autonomous_navigation': False,
                'sdk_confirmation': self.sdk_confirmation, 'stop_confirmation': self.stop_confirmation,
                'connection_stage': self.connection_stage, 'last_connection_error': self.last_connection_error,
                'scan_id': self.scan_counter, 'scan_received_at_ms': self.last_pair_reply_wall,
                'auto_connect_suppressed_scan': self.auto_connect_suppressed_scan,
                'command_delivery_scope': 'udp_local_dispatch_no_robot_ack', 'physical_stop_verified': False,
                'drive_mode': self.drive_mode, 'requested_drive_mode': 'chassis_lead',
                'pairing_diagnostics': dict(self.pair_diagnostics), 'qr_revision': self.qr_revision,
                'follow_enabled': self.follow_enabled, 'speed_level': self.speed_level,
                'idle_hold_enabled': False, 'idle_stop_error': self.idle_stop_error,
                'stop_delivery_scope': 'wheel_zero_protocol_reply_not_physical_stop',
                'chassis_motion_allowed': self.grounded(),
                'chassis_status_age_ms': int((time.monotonic() - self.chassis_status_at) * 1000)
                    if self.chassis_status_at else None,
                'idle_zero_count': self.idle_zero_count,
                'idle_zero_age_ms': int((time.monotonic() - self.last_idle_success) * 1000) if self.last_idle_success else None,
                'idle_guard_alive': self.guard_thread.is_alive()}

    def hold_idle(self):
        # Compatibility entry point; never renew chassis speed mode while idle.
        # The controller watchdog owns bounded motion expiry.
        if self.control:
            self.control.tick()

    def receive_chassis_status(self, values):
        # DJI SaStatusSubject: pickup index 4, rollover index 9. Do not infer
        # ground contact from connection, a battery callback or a missing flag.
        if (not isinstance(values, (tuple, list)) or len(values) != 11
                or any(type(value) not in (int, bool) or value not in (0, 1) for value in values)):
            self.chassis_status = None
            self.chassis_status_at = 0
            return
        self.chassis_status = tuple(values)
        self.chassis_status_at = time.monotonic()

    def grounded(self):
        return bool(self.chassis_status is not None
                    and time.monotonic() - self.chassis_status_at < .5
                    and not self.chassis_status[4] and not self.chassis_status[9])

    def guard_chassis(self):
        if self.grounded():
            return
        if self.control and self.control.lease:
            self.control.software_stop()
        if self.gimbal_driving:
            self.stop_gimbal()

    def require_grounded(self):
        if not self.grounded():
            self.guard_chassis()
            raise ControlError('EP 抱起／翻轉或底盤狀態未確認，已禁止操作。', 423)

    def require_idle(self):
        if not self.robot:
            raise ControlError('EP 尚未連線。')
        self.require_grounded()
        filename = f'ep-control-{self.device_id}.sqlite3' if self.device_id else 'ep-control.sqlite3'
        database = self.root / '.runtime' / filename
        if self.control is None and database.exists():
            try:
                with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as saved:
                    saved.row_factory = sqlite3.Row
                    marker = _read_safety_marker(saved)
                    pending = bool(marker['requires_reset'] or marker['fault'])
            except sqlite3.Error:
                pending = True
            if pending:
                # Restore the stop marker before any gimbal-mode command can run.
                transport = LiveTransport(self.robot, model='EP', on_site_motion_authorized=True)
                transport.speed_level = self.speed_level
                self.control = RobotController(database, transport=transport)
                self.control.start()
        if self.control and self.control.lease:
            raise ControlError('請先放開方向，待機體停止後再調整。')
        if self.control and (self.control.stop_latched or self.control.state == 'fault'):
            raise ControlError('請先確認靜止並解除停止鎖定。')

    def set_speed(self, level):
        self.require_idle()
        if type(level) is not int or not 1 <= level <= 4:
            raise ControlError('速度設定不符。', 422)
        self.speed_level = level
        if self.control:
            self.control.transport.speed_level = level
        return self.status()

    def configure_follow(self, enabled):
        self.require_idle()
        if type(enabled) is not bool:
            raise ControlError('跟隨設定不符。', 422)
        self.stop_gimbal()
        self.gimbal_mode_applied = False
        try:
            LiveTransport(self.robot, model='EP', on_site_motion_authorized=True).stop()
            if self.robot.set_robot_mode(mode='free') is not True:
                raise RuntimeError()
            if enabled:
                centered = self.robot.gimbal.recenter(pitch_speed=30, yaw_speed=60)
                if centered.wait_for_completed(timeout=6) is not True or centered.has_succeeded is not True:
                    raise RuntimeError()
                if self.robot.set_robot_mode(mode='chassis_lead') is not True:
                    raise RuntimeError()
            mode = 'chassis_lead' if enabled else 'free'
            if self.robot.get_robot_mode() != mode:
                raise RuntimeError()
        except Exception:
            self.drive_mode = None
            raise ControlError('EP 未確認雲台模式，請停止操作後重試。', 503) from None
        self.follow_enabled = enabled
        self.drive_mode = mode
        self.gimbal_mode_applied = True
        if not enabled:
            owner = self.robot
            self.robot.gimbal.sub_angle(freq=10,
                callback=lambda values: self.receive_gimbal_angles(values) if self.robot is owner else None)
        return self.status()

    def receive_gimbal_angles(self, values):
        if (isinstance(values, (tuple, list)) and len(values) == 4
                and all(type(value) in (float, int) and -360 <= value <= 360 for value in values)):
            self.gimbal_angles = (float(values[0]), float(values[1]))
            self.gimbal_angles_at = time.monotonic()

    def start_gimbal(self):
        self.require_grounded()
        if not self.robot or self.follow_enabled or not self.gimbal_mode_applied or self.drive_mode != 'free':
            raise ControlError('請先關閉雲台跟隨底盤。')
        if self.control and (self.control.stop_latched or self.control.state == 'fault'):
            raise ControlError('停止鎖定期間不可轉動雲台。')
        self.stop_gimbal()
        return {'generation': self.gimbal_generation, 'server_time_ms': int(time.time() * 1000)}

    def target_gimbal(self, payload):
        self.require_grounded()
        if (not isinstance(payload.get('pitch'), (int, float)) or not -20 <= payload['pitch'] <= 25
                or not isinstance(payload.get('yaw'), (int, float)) or not -60 <= payload['yaw'] <= 60):
            raise ControlError('雲台角度超出範圍。', 422)
        age = int(time.time() * 1000) - payload['issued_at_ms']
        if (self.follow_enabled or self.drive_mode != 'free' or payload['generation'] != self.gimbal_generation
                or payload['seq'] <= self.gimbal_sequence or not -100 <= age < 300
                or (self.control and (self.control.stop_latched or self.control.state == 'fault'))):
            raise ControlError('雲台指令已過期。')
        self.gimbal_sequence = payload['seq']
        self.gimbal_until = time.monotonic() + max(0, (300 - max(0, age)) / 1000)
        self.gimbal_target_angles = (payload['pitch'], payload['yaw'])
        return {'accepted': True}

    def stop_gimbal(self, generation=None):
        if generation is not None and generation != self.gimbal_generation:
            return {'stopped': True}
        self.gimbal_generation += 1
        self.gimbal_sequence = -1
        self.gimbal_until = 0
        self.gimbal_target_angles = None
        if self.gimbal_driving and self.robot:
            try:
                self.robot.gimbal.drive_speed(pitch_speed=0, yaw_speed=0)
            except Exception:
                pass
        self.gimbal_driving = False
        return {'stopped': True}

    def update_gimbal(self):
        if not self.robot or not self.gimbal_target_angles:
            return
        if not self.grounded():
            self.stop_gimbal()
            return
        if self.follow_enabled or time.monotonic() >= self.gimbal_until:
            self.stop_gimbal()
            return
        if not self.gimbal_angles or time.monotonic() - self.gimbal_angles_at > .5:
            if self.gimbal_driving:
                self.robot.gimbal.drive_speed(pitch_speed=0, yaw_speed=0)
                self.gimbal_driving = False
            return
        pitch, yaw = self.gimbal_angles
        target_pitch, target_yaw = self.gimbal_target_angles
        pitch_speed = max(-30, min(30, (target_pitch - pitch) * 3))
        yaw_speed = max(-60, min(60, (target_yaw - yaw) * 3))
        if abs(target_pitch - pitch) < .8:
            pitch_speed = 0
        if abs(target_yaw - yaw) < .8:
            yaw_speed = 0
        try:
            if self.robot.gimbal.drive_speed(pitch_speed=pitch_speed, yaw_speed=yaw_speed) is not True:
                raise RuntimeError()
            self.gimbal_driving = bool(pitch_speed or yaw_speed)
        except Exception:
            self.stop_gimbal()

    def stage(self, name):
        self.connection_stage = name
        self.progress(name)

    def cancel_pairing(self):
        self.pair_generation += 1
        self.pair_cancel.set()
        if self.pair_socket:
            self.pair_socket.close()
        if self.pair_thread:
            self.pair_thread.join(timeout=1)
        self.pair_socket = self.pair_thread = None
        self.pair_state = 'idle'
        self.pair_expires = 0
        self.detected_ip = ''
        self.qr_image = None
        self.qr_ssid = ''
        self.last_pair_reply_at = 0
        self.qr_revision = ''
        self.last_pairing_flag = False
        self.candidates.clear()

    def qr(self, ssid, password):
        if (not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32
                or not isinstance(password, str)
                or (password != '' and not 8 <= len(password.encode('utf-8')) <= 63)
                or '\x00' in ssid or '\x00' in password):
            raise ControlError('Wi-Fi 名稱或密碼格式不符。', 422)
        self.cancel_pairing()
        self.load()
        import qrcode
        from qrcode.image.svg import SvgPathImage
        from robomaster import algo, conn, protocol
        helper = conn.ConnectionHelper()
        words = helper.build_qrcode_string(Utf8Wifi(ssid), Utf8Wifi(password))
        # The QR contains a recoverable Wi-Fi key: return only to the local page,
        # never a disk file, log, URL parameter or third-party QR service.
        image = qrcode.make(words, image_factory=SvgPathImage, box_size=8, border=4)
        output = io.BytesIO()
        image.save(output)
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            listener.bind(('0.0.0.0', 45678))
            listener.settimeout(.25)
        except Exception:
            listener.close()
            raise ControlError('組網接收端口 45678 不可用；請關閉其他 EP 配網工具後再試。', 503) from None
        appid = helper._appid
        self.pair_socket = listener
        self.pair_cancel = threading.Event()
        cancel = self.pair_cancel
        generation = self.pair_generation
        self.pair_state, self.pair_expires = 'waiting_for_scan', 0
        self.pair_diagnostics = {'received': 0, 'accepted': 0, 'wrong_code': 0, 'invalid': 0,
                                 'last_packet_at_ms': 0, 'last_wrong_code_at_ms': 0}

        def receive():
            try:
                while not cancel.is_set():
                    try:
                        data, address = listener.recvfrom(1024)
                    except TimeoutError:
                        continue
                    except OSError as error:
                        # Winsock can surface the peer closing its provisioning
                        # port after an ACK as an asynchronous UDP reset.
                        if getattr(error, 'winerror', None) == 10054:
                            continue
                        raise
                    try:
                        self.pair_diagnostics['received'] += 1
                        self.pair_diagnostics['last_packet_at_ms'] = int(time.time() * 1000)
                        info = protocol.STAConnInfo()
                        if not info.unpack(algo.simple_encrypt(data)):
                            self.pair_diagnostics['invalid'] += 1
                            continue
                        if info._recv_appid != appid:
                            self.pair_diagnostics['wrong_code'] += 1
                            self.pair_diagnostics['last_wrong_code_at_ms'] = int(time.time() * 1000)
                            continue
                        peer = ipaddress.IPv4Address(address[0])
                        if not peer.is_private or peer.is_loopback or peer.is_multicast:
                            continue
                        listener.sendto(appid.encode('ascii'), address)
                        self.pair_diagnostics['accepted'] += 1
                        if generation == self.pair_generation:
                            now = time.monotonic()
                            pairing = bool(info._is_pairing)
                            previous = self.candidates.get(str(peer), {})
                            fresh_scan = (not previous or (pairing and not previous.get('_pairing'))
                                          or now - previous.get('_reply_at', 0) > 10)
                            if fresh_scan:
                                self.scan_counter += 1
                            self.last_pair_reply_at = now
                            self.last_pair_reply_wall = int(time.time() * 1000)
                            self.last_pairing_flag = pairing
                            self.detected_ip = str(peer)
                            self.candidates[str(peer)] = {'ip': str(peer),
                                'scan_id': self.scan_counter if fresh_scan else previous['scan_id'],
                                'scan_received_at_ms': self.last_pair_reply_wall,
                                'first_seen_ms': previous.get('first_seen_ms', self.last_pair_reply_wall),
                                '_pairing': pairing, '_reply_at': now}
                            if len(self.candidates) > 32:
                                self.candidates.pop(next(iter(self.candidates)))
                            self.pair_state = 'joined_network'
                        # Keep acknowledging repeated pairing packets. A single UDP
                        # reply is not delivery confirmation and can be lost.
                        continue
                    except Exception as error:
                        # Never reflect a received packet or embedded data into logs.
                        if isinstance(error, OSError):
                            raise
                        self.pair_diagnostics['invalid'] += 1
                        continue
            except OSError:
                if generation == self.pair_generation and not cancel.is_set():
                    self.pair_state = 'receiver_failed'
            finally:
                listener.close()

        self.pair_thread = threading.Thread(target=receive, daemon=True)
        self.pair_thread.start()
        self.qr_image = base64.b64encode(output.getvalue()).decode('ascii')
        self.qr_revision = secrets.token_hex(8)
        self.qr_ssid = ssid
        return self.qr_snapshot()

    def qr_snapshot(self):
        return {'svg_base64': self.qr_image, 'expires_in_seconds': None,
                'ssid': self.qr_ssid, 'pairing': self.pair_state, 'revision': self.qr_revision}

    def connect(self, ip, confirmed, expected_sn=None):
        if confirmed is not True:
            raise ControlError('請先確認現場及人工停機準備。', 403)
        if self.robot:
            raise ControlError('EP 已連線；不會重複初始化。')
        try:
            address = ipaddress.IPv4Address(ip)
            if not (address.is_private and not address.is_loopback and not address.is_unspecified
                    and not address.is_multicast and not address.is_link_local):
                raise ValueError()
        except ValueError:
            raise ControlError('請輸入同一路由器內的 EP IPv4 位址。', 422) from None
        candidate = None
        self.last_connection_error = None
        try:
            self.stage('load_runtime')
            robot_module = self.load()
            import ifaddr
            from robomaster import config
            self.stage('select_interface')
            config.LOCAL_IP_STR = local_ep_ip(address, ifaddr.get_adapters())
            config.ROBOT_IP_STR = str(address)
            if self.sdk_port is not None:
                config.ROBOT_SDK_PORT_MIN = config.ROBOT_SDK_PORT_MAX = self.sdk_port
            self.stage('create_client')
            candidate = robot_module.Robot()
            attach_handshake(candidate, str(address), config.LOCAL_IP_STR, self.stage)
            def traced_operation(obj, name, stage):
                original = getattr(obj, name)
                def call(*args, **kwargs):
                    self.stage(stage)
                    if name == '_enable_sdk' and (args[0] if args else kwargs.get('enable', 1)) == 1:
                        try:
                            self.sdk_confirmation = confirm_sdk_enable(candidate)
                            return True
                        except ControlReplyError as error:
                            self.sdk_confirmation = error.diagnostic
                            raise HandshakeError('sdk_enable_'+error.diagnostic['code']) from None
                    return original(*args, **kwargs)
                setattr(obj, name, call)
            traced_operation(candidate, '_enable_sdk', 'enable_sdk')
            traced_operation(candidate, 'reset', 'reset_sdk')
            # Console operations do not upload files. Avoid optional FTP setup
            # delaying a usable SDK/control link (official source stays pristine).
            candidate._ftp.connect = lambda _ip: None
            original_wait = candidate._wait_for_connection
            def require_target_connection(*args, **kwargs):
                connection = original_wait(*args, **kwargs)
                if connection is None:
                    code = getattr(candidate._sdk_conn, '_console_error', None)
                    raise HandshakeError(code if isinstance(code, str) else 'explicit_target_connection_failed')
                return connection
            candidate._wait_for_connection = require_target_connection
            self.stage('sdk_initialize')
            if candidate.initialize(conn_type='sta', proto_type='udp') is not True:
                raise RuntimeError('connection_failed')
            self.stage('read_firmware')
            version = candidate.get_version()
            if not isinstance(version, str) or not version:
                raise HandshakeError('firmware_unavailable')
            self.stage('read_identity')
            sn = candidate.get_sn()
            if not isinstance(sn, str) or not sn:
                raise HandshakeError('identity_unavailable')
            if expected_sn is not None and sn != expected_sn:
                raise HandshakeError('identity_mismatch')
            # Connecting is read-only. Chassis commands belong to the separate
            # explicit "prepare controls" action, never firmware/SN verification.
            self.robot = candidate
            self.ip, self.version, self.sn = str(address), version[:128], sn[:64]
            self.chassis_status = None
            self.chassis_status_at = 0
            # Failure leaves control unavailable; connection status can still be read.
            candidate.chassis.sub_status(freq=10,
                callback=lambda values: self.receive_chassis_status(values) if self.robot is candidate else None)
            try:
                candidate.battery.sub_battery_info(freq=1,
                    callback=lambda percent: self.receive_battery(percent) if self.robot is candidate else None)
            except Exception:
                pass  # Unknown battery remains unknown; never invent a percentage.
            self.stage('connected')
            return self.status()
        except Exception as error:
            code = error.code if isinstance(error, HandshakeError) else type(error).__name__
            self.last_connection_error = {'stage': self.connection_stage, 'code': code}
            if self.robot is candidate:
                self.robot = None
                self.chassis_status = None
                self.chassis_status_at = 0
            try:
                if candidate is not None:
                    candidate.close()
            except Exception:
                pass
            messages = {'sdk_enable_reply_missing_or_unmatched': '機體有網絡回應，但未確認啟用 SDK 控制模式；沒有開始遙控。',
                        'sdk_enable_robot_rejected': '機體拒絕啟用 SDK 控制模式；沒有開始遙控。',
                        'sdk_enable_reply_malformed': 'SDK 控制模式回覆格式不符；沒有開始遙控。',
                        'handshake_timeout': 'EP 未回應連線，請核對機體已完成組網。',
                        'identity_mismatch': '機體位址已變更，請重新掃碼確認這台 EP。',
                        'robot_busy': 'EP 正被其他程式使用，請先退出原廠 App 再重試。',
                        'local_interface_mismatch': 'EP 回覆的網絡介面不符，請核對 Notebook 目前 Wi-Fi。'}
            if isinstance(error, ControlError):
                raise
            raise ControlError(messages.get(code, 'EP 連線未完成；請按「重試連線」，系統已記錄失敗步驟。'), 503) from None

    def record_stop_confirmation(self, diagnostic):
        self.stop_confirmation = dict(diagnostic)
        if diagnostic['code'] != 'confirmed' or diagnostic.get('source') == 'human_stop_check':
            try:
                folder = self.root/'.runtime/ep-stop-diagnostics'
                folder.mkdir(parents=True, exist_ok=True)
                with (folder/(str(int(time.time()*1000))+'-'+secrets.token_hex(6)+'.json')).open('x', encoding='utf-8') as output:
                    json.dump({'device_id': self.device_id, 'sn': self.sn, 'diagnostic': diagnostic}, output)
            except OSError:
                pass  # In-memory result remains available; never relax the stop requirement.

    def check_stop(self, payload):
        if payload.get('confirmed_stationary') is not True:
            raise ControlError('請先確認機體已停穩。', 422)
        self.require_grounded()
        if not self.robot or (self.control and self.control.lease):
            raise ControlError('請先停止操作；這項檢查不會取得控制租約。', 409)
        transport = LiveTransport(self.robot, model='EP', on_site_motion_authorized=True)
        transport.diagnostic_sink = lambda data: self.record_stop_confirmation({**data, 'source': 'human_stop_check'})
        try:
            transport.stop()
        except ControlReplyError as error:
            raise ControlError('停止回覆未確認：'+error.diagnostic['code']+'；沒有解鎖或移動。', 503) from None
        return self.status()

    def prepare_control(self):
        if not self.robot:
            raise ControlError('請先連線 EP。')
        self.require_grounded()
        if self.control is not None:
            if not self.gimbal_mode_applied:
                self.configure_follow(self.follow_enabled)
            return self.status()
        transport = LiveTransport(self.robot, model='EP', on_site_motion_authorized=True)
        transport.diagnostic_sink = self.record_stop_confirmation
        try:
            transport.stop()
        except Exception:
            raise ControlError('底盤停止指令回覆未確認，未準備遙控；故障診斷已保留，沒有發送移動。', 503) from None
        try:
            if not self.gimbal_mode_applied:
                self.configure_follow(self.follow_enabled)
        except Exception:
            raise ControlError('EP 未確認鏡頭跟隨底盤，已停用遙控；請保持機體靜止後重試。', 503) from None
        transport.speed_level = self.speed_level
        filename = f'ep-control-{self.device_id}.sqlite3' if self.device_id else 'ep-control.sqlite3'
        controller = RobotController(self.root / '.runtime' / filename, transport=transport)
        controller.start()
        self.control = controller
        return self.status()

    def disconnect(self):
        self.patrol_context.stop()
        self.infrared_warning.stop()
        self.manual_warning.stop()
        self.stop_gimbal()
        self.auto_connect_suppressed_scan = self.scan_counter
        self.stop_video()
        stop_failed = False
        if self.control:
            try:
                self.control.close()
            except Exception:
                stop_failed = True
            self.control = None
        if self.robot:
            try:
                self.robot.close()
            except Exception:
                stop_failed = True
            self.robot = None
        self.ip = self.version = self.sn = ''
        self.chassis_status = None
        self.chassis_status_at = 0
        self.drive_mode = None
        self.gimbal_mode_applied = False
        self.follow_enabled = True
        self.speed_level = 1
        self.gimbal_angles = None
        self.gimbal_angles_at = 0
        self.last_idle_success = 0
        self.last_idle_zero = 0
        self.idle_zero_count = 0
        self.battery_percent = None
        self.battery_at = 0
        if stop_failed:
            raise ControlError('已斷開；軟件停止未能確認，請現場核對機體。', 503)
        return self.status()

    def receive_battery(self, percent):
        if type(percent) is int and 0 <= percent <= 100:
            self.battery_percent = percent
            self.battery_at = time.monotonic()

    def start_video(self):
        if not self.robot:
            raise ControlError('EP 尚未連線。')
        self.view_last_request = time.monotonic()
        if self.video_enabled:
            return self.status()
        self.video_error = None
        try:
            if self.robot.camera.start_video_stream(display=False, resolution='360p') is not True:
                raise RuntimeError()
        except Exception:
            try:
                self.robot.camera.stop_video_stream()
            except Exception:
                pass
            raise ControlError('未能開啟機體影像，請核對連線後重試。', 503) from None
        self.video_cancel = threading.Event()
        self.video_epoch = secrets.token_hex(6)
        cancel = self.video_cancel
        camera = self.robot.camera
        self.video_enabled = True

        def capture():
            import cv2
            while not cancel.is_set():
                try:
                    frame = camera.read_cv2_image(timeout=.3, strategy='newest')
                    if frame is None:
                        continue
                    if frame.ndim != 3 or frame.shape[2] != 3:
                        raise ValueError()
                    if frame.shape[:2] != (360, 640):
                        frame = cv2.resize(frame, (640, 360))
                    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if not ok or len(encoded) > 350000:
                        raise ValueError()
                    if not cancel.is_set():
                        self.video_frame = base64.b64encode(encoded).decode('ascii')
                        self.video_at = time.monotonic()
                        self.video_error = None
                        self.video_sequence += 1
                        snapshot = {'jpeg_base64': self.video_frame, 'frame_key': f'{self.video_epoch}-{self.video_sequence}',
                                    'captured_at_ms': int(time.time()*1000), 'read_at': time.monotonic(),
                                    'camera_pose': list(self.gimbal_angles) if self.gimbal_angles and time.monotonic()-self.gimbal_angles_at < .5 else None}
                        self.video_snapshot = snapshot
                        if self.video_sink:
                            self.video_sink({'event': 'video_frame', **{key: value for key, value in snapshot.items() if key != 'read_at'}})
                except Exception:
                    if not cancel.is_set():
                        self.video_error = '等待機體影像'
                cancel.wait(.07)
        self.video_thread = threading.Thread(target=capture, daemon=True)
        self.video_thread.start()
        return self.status()

    def stop_video(self):
        self.patrol_context.stop()
        self.video_cancel.set()
        was_enabled = self.video_enabled
        self.video_enabled = False
        self.video_frame = None
        self.video_at = 0
        if was_enabled and self.robot:
            try:
                self.robot.camera.stop_video_stream()
            except Exception:
                self.video_error = '停止影像未確認'
        if self.video_thread:
            self.video_thread.join(timeout=1)
        self.video_thread = None
        if self.video_sink:
            self.video_sink({'event': 'video_stopped'})
        return {'video_enabled': False}

    def frame_snapshot(self):
        self.view_last_request = time.monotonic()
        age = int((time.monotonic() - self.video_at) * 1000) if self.video_at else None
        fresh = self.video_enabled and age is not None and 0 <= age < 1200
        return {'jpeg_base64': self.video_frame if fresh else None,
                'age_ms': age, 'video_enabled': self.video_enabled,
                'message': self.video_error if not fresh else None}

    def handle(self, operation, payload):
        with self.lock:
            if operation in {'stop', 'disconnect', 'video-stop'} or (operation == 'command' and payload.get('direction') == 'stop'):
                self.patrol_context.stop()
            if self.patrol_context.busy and operation in {'lease', 'prepare-control', 'gimbal-start', 'gimbal-target', 'gimbal-follow', 'speed'}:
                raise ControlError('正在拍攝左右環境相，方向及雲台暫停。', 409)
            if self.patrol_context.busy and operation == 'command' and payload.get('direction') != 'stop':
                raise ControlError('正在拍攝左右環境相，方向暫停。', 409)
            if operation in {'stop', 'disconnect', 'video-stop'}:
                self.infrared_warning.stop()
            self.last_request = time.monotonic()
            if operation == 'context-arm':
                return self.patrol_context.arm()
            if operation == 'context-start':
                return self.patrol_context.start(payload)
            if operation == 'context-status':
                return self.patrol_context.snapshot(payload.get('job_id'))
            if operation == 'context-cancel':
                self.patrol_context.stop()
                return {'cancelled': True}
            if operation == 'status':
                return self.status()
            if operation == 'health':
                return self.health()
            if operation == 'qr':
                return self.qr(payload['ssid'], payload['password'])
            if operation == 'qr-status':
                return self.qr_snapshot()
            if operation == 'cancel-pairing':
                self.cancel_pairing()
                return self.status()
            if operation == 'connect':
                return self.connect(payload['ip'], payload.get('confirmed'), payload.get('expected_sn'))
            if operation == 'disconnect':
                return self.disconnect()
            if operation == 'prepare-control':
                return self.prepare_control()
            if operation == 'stop' and self.robot and self.control is None:
                transport = LiveTransport(self.robot, model='EP', on_site_motion_authorized=True)
                transport.speed_level = self.speed_level
                filename = f'ep-control-{self.device_id}.sqlite3' if self.device_id else 'ep-control.sqlite3'
                self.control = RobotController(self.root / '.runtime' / filename, transport=transport)
                self.control.start()
            if operation == 'speed':
                return self.set_speed(payload['level'])
            if operation == 'gimbal-follow':
                return self.configure_follow(payload['enabled'])
            if operation == 'gimbal-start':
                return self.start_gimbal()
            if operation == 'gimbal-target':
                return self.target_gimbal(payload)
            if operation == 'gimbal-stop':
                return self.stop_gimbal(payload.get('generation'))
            if operation == 'video-start':
                return self.start_video()
            if operation == 'infrared-warning':
                if payload['active'] and self.manual_warning.thread and self.manual_warning.thread.is_alive():
                    raise ControlError('燈光提示仍在進行。', 409)
                return self.infrared_warning.update(self.robot, payload['press_id'], payload['active'])
            if operation == 'check-stop':
                return self.check_stop(payload)
            if operation == 'manual-warning':
                if self.infrared_warning.thread and self.infrared_warning.thread.is_alive():
                    raise ControlError('請先放開紅外線警示。', 409)
                return self.manual_warning.start(self.robot)
            if operation == 'video-stop':
                return self.stop_video()
            if operation == 'video-frame':
                return self.frame_snapshot()
            if operation == 'video-heartbeat':
                self.view_last_request = time.monotonic()
                return {'video_enabled': self.video_enabled}
            if not self.control:
                raise ControlError('EP 尚未連線。')
            if operation == 'lease':
                self.require_grounded()
                return self.control.acquire()
            if operation == 'command':
                if payload.get('direction') != 'stop':
                    self.require_grounded()
                return self.control.command(RobotCommand.model_validate(payload))
            if operation == 'stop':
                self.stop_gimbal()
                return self.control.software_stop()
            if operation == 'reset-stop' and payload.get('confirmed_stationary') is True:
                self.require_grounded()
                return self.control.reset_software_stop()
            raise ControlError('不支援的 EP 操作。', 422)
