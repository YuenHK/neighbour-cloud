"""Loopback console -> isolated EP process. No SDK imports in Edge Hub."""
import base64
import binascii
import json
import queue
import re
import subprocess
import threading
import time
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from edge_hub.local_operator import local_console_request
from edge_hub.robot_control import ControlError, RobotCommand
from edge_hub.wifi_profile import WifiError, current_wifi


class EpBroker:
    def safety_hold(self):
        return (self.root / '.runtime/ep-safety-hold.json').exists()

    def __init__(self, root, device_id=None, sdk_port=None, *, acceptance_only=False, pairing_only=False):
        if acceptance_only and pairing_only:
            raise ValueError('EP worker roles are mutually exclusive')
        self.root = root
        self.acceptance_only = acceptance_only
        self.pairing_only = pairing_only
        self.acceptance_prepare = False
        self.acceptance_short_press = False
        self.acceptance_release_check = False
        self.acceptance_idle_motor = False
        self.device_id, self.sdk_port = device_id, sdk_port
        self.process = None
        self.lock = threading.Lock()
        self.responses = queue.Queue(maxsize=32)
        self.last_connection_stage = 'idle'
        self.last_connection_error = None
        self.cached_status = None
        self.cached_status_at = 0
        self.latest_frame = None
        self.last_view_request = 0

    def receive_frame_event(self, message):
        if message.get('event') == 'video_stopped':
            self.latest_frame = None
            return True
        if message.get('event') != 'video_frame':
            return False
        try:
            encoded = message['jpeg_base64']
            key = message['frame_key']
            captured = message['captured_at_ms']
            if (not isinstance(encoded, str) or len(encoded) > 500000
                    or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key)
                    or type(captured) is not int):
                return True
            data = base64.b64decode(encoded, validate=True)
            if not data.startswith(b'\xff\xd8') or len(data) > 350000:
                return True
            self.latest_frame = {'jpeg': data, 'key': key, 'captured_at_ms': captured,
                                 'received_at': time.monotonic(), 'camera_pose': message.get('camera_pose')}
        except (KeyError, ValueError, binascii.Error):
            pass
        return True

    def frame_snapshot(self, after='', *, touch=True):
        if self.safety_hold():
            return {'state': 'safety_hold'}
        if touch:
            self.last_view_request = time.monotonic()
        frame = self.latest_frame
        if not frame or self.process is None or self.process.poll() is not None:
            return {'state': 'waiting'}
        wall_age = int(time.time() * 1000) - frame['captured_at_ms']
        age = max(wall_age, int((time.monotonic() - frame['received_at']) * 1000))
        if wall_age < -100 or age >= 1200:
            return {'state': 'stale'}
        return {'state': 'unchanged' if frame['key'] == after else 'frame',
                'jpeg': frame['jpeg'], 'key': frame['key'], 'age_ms': max(0, age), 'captured_at_ms': frame['captured_at_ms'],
                'camera_pose': frame.get('camera_pose')}

    def _start(self):
        if (self.acceptance_only or self.pairing_only) and not self.safety_hold():
            raise ControlError('單機驗收需要普通控制保持停用。', 423)
        if self.safety_hold() and not (self.acceptance_only or self.pairing_only):
            raise ControlError('EP 已暫停使用：請在現場關機，等待飄移問題排查。', 423)
        python = self.root / '.runtime/ep-sdk/venv/Scripts/python.exe'
        source = self.root / '.runtime/ep-sdk/source/src/robomaster/robot.py'
        if not python.is_file() or not source.is_file():
            raise ControlError('本機 EP 工具尚未準備完成。', 503)
        self.responses = queue.Queue(maxsize=32)
        self.latest_frame = None
        self.cached_status = None
        responses = self.responses
        arguments = [str(python), '-B', '-m', 'ep_runtime.console_worker']
        if self.pairing_only:
            arguments.append('--pairing-only')
        if self.acceptance_only:
            arguments.append('--acceptance-only')
            if self.acceptance_prepare:
                arguments.append('--acceptance-prepare')
            if self.acceptance_short_press:
                arguments.append('--acceptance-short-press')
            if self.acceptance_release_check:
                arguments.append('--acceptance-release-check')
            if self.acceptance_idle_motor:
                arguments.append('--acceptance-idle-motor')
        if self.device_id:
            arguments += ['--device-id', self.device_id]
        if self.sdk_port is not None:
            arguments += ['--sdk-port', str(self.sdk_port)]
        self.process = subprocess.Popen(arguments,
            cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
        process = self.process

        def receive():
            try:
                for line in process.stdout:
                    if process is not self.process:
                        break
                    if len(line) > 1024 * 1024:
                        break
                    try:
                        message = json.loads(line)
                        if self.receive_frame_event(message):
                            continue
                    except (ValueError, TypeError, AttributeError):
                        pass
                    responses.put_nowait(line)
            finally:
                try:
                    responses.put_nowait(None)
                except queue.Full:
                    pass
        threading.Thread(target=receive, daemon=True).start()

    def request(self, operation, payload=None):
        if operation in {'check-stop', 'infrared-warning', 'manual-warning', 'context-arm', 'context-start', 'context-status', 'context-cancel'} and (self.process is None or self.process.poll() is not None):
            raise ControlError('請先手動連線 EP。', 409)
        if self.pairing_only:
            if operation not in {'qr', 'qr-status', 'status', 'cancel-pairing', 'disconnect'}:
                raise ControlError('手動配網禁止控制連線、租約、移動及聲畫。', 423)
            if operation == 'qr' and not self.safety_hold():
                raise ControlError('手動配網需要普通控制保持停用。', 423)
        if self.acceptance_only and operation == 'connect' and not self.safety_hold():
            raise ControlError('單機驗收需要普通控制保持停用。', 423)
        allowed = {'status', 'connect', 'disconnect'}
        if self.acceptance_prepare:
            allowed.update({'prepare-control', 'reset-stop'})
        if self.acceptance_short_press:
            allowed.update({'short-press-start', 'short-press-release'})
        if self.acceptance_idle_motor:
            allowed.update({'motor-release', 'motor-activate'})
        if self.acceptance_only and operation not in allowed:
            raise ControlError('第二階段只可手動連線、查看狀態及斷線。', 423)
        if self.safety_hold() and not (self.acceptance_only or self.pairing_only):
            # Do not start a worker or dispatch even a purported stop packet.
            if operation in {'status', 'health', 'disconnect', 'cancel-pairing'}:
                return {'connection': 'not_connected', 'control': None, 'pairing': 'idle',
                        'video_enabled': False, 'audio_enabled': False, 'safety_hold': True,
                        'physical_stop_verified': False,
                        'last_connection_error': 'EP 已暫停使用；請在現場關機，等待飄移問題排查。'}
            if operation == 'qr-status':
                return {'svg_base64': None, 'pairing': 'idle', 'safety_hold': True}
            raise ControlError('EP 已暫停使用：請在現場關機，等待飄移問題排查。', 423)
        # Acceptance evidence expires at 250ms. The ordinary 300ms display cache
        # must not recycle an old readiness/age during physical acceptance.
        if operation == 'status' and self.cached_status is not None and not self.acceptance_only:
            if self.process is not None and self.process.poll() is None:
                age = time.monotonic() - self.cached_status_at
                if age < .3 or self.lock.locked():
                    return {**self.cached_status, 'status_age_ms': int(age * 1000), 'status_busy': self.lock.locked()}
            else:
                self.cached_status = None
                self.latest_frame = None
        if not self.lock.acquire(timeout=.5):
            raise ControlError('EP 正在處理另一個操作；請稍候。', 409)
        try:
            if self.process is None or self.process.poll() is not None:
                if operation == 'qr-status':
                    return {'svg_base64': None, 'expires_in_seconds': None, 'ssid': '', 'pairing': 'idle'}
                if operation in {'status', 'health', 'cancel-pairing', 'disconnect'}:
                    return {'connection': 'not_connected', 'pairing': 'idle', 'control': None,
                            'detected_ip': '', 'qr_expires_in_seconds': 0,
                            'video_enabled': False, 'audio_enabled': False, 'hardware_acceptance': False,
                            'connection_stage': self.last_connection_stage,
                            'last_connection_error': self.last_connection_error}
                if operation not in {'qr', 'connect'}:
                    raise ControlError('EP 尚未連線。')
                self._start()
            try:
                self.process.stdin.write(json.dumps({'operation': operation, 'payload': payload or {}},
                                                    ensure_ascii=True) + '\n')
                self.process.stdin.flush()
                deadline = time.monotonic() + (18 if operation in {'connect', 'video-start', 'prepare-control', 'gimbal-follow'} else 6)
                while True:
                    raw = self.responses.get(timeout=max(.01, deadline - time.monotonic()))
                    if raw is None:
                        raise ValueError()
                    response = json.loads(raw)
                    if response.get('event') == 'connection_stage':
                        stage = response.get('stage')
                        if stage not in {'load_runtime', 'select_interface', 'create_client', 'sdk_initialize',
                                         'network_handshake', 'network_ready', 'read_firmware', 'read_identity',
                                         'enable_sdk', 'reset_sdk', 'ftp_setup', 'confirm_stationary', 'connected'}:
                            raise ValueError()
                        self.last_connection_stage = stage
                        if time.monotonic() >= deadline:
                            raise queue.Empty()
                        continue
                    break
            except (OSError, ValueError, queue.Empty) as error:
                self.last_connection_error = {'stage': self.last_connection_stage,
                    'code': 'worker_timeout' if isinstance(error, queue.Empty) else 'worker_communication_failed'}
                self.process.kill()
                self.process.wait(timeout=3)
                self.cached_status = self.latest_frame = None
                raise ControlError('EP 工具逾時或已中斷；停止未確認，請現場核對。重新連線不會自動恢復行走。', 503) from None
            if response.get('ok') is not True:
                self.cached_status = None
                raise ControlError(response.get('detail', 'EP 操作失敗'), response.get('status', 503))
            result = response['result']
            if operation in {'status', 'health', 'connect', 'disconnect', 'prepare-control', 'gimbal-follow', 'speed', 'video-start'}:
                self.cached_status, self.cached_status_at = result, time.monotonic()
            elif operation != 'video-heartbeat':
                self.cached_status = None
            if operation in {'disconnect', 'video-stop'}:
                self.latest_frame = None
            return result
        finally:
            self.lock.release()

    def close(self):
        if self.process and self.process.poll() is None:
            try:
                self.request('disconnect')
            except ControlError:
                pass
            finally:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)


class InfraredWarningRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    press_id: str = Field(min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    active: bool


class QrRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    use_current_wifi: bool = False
    ssid: str = Field(default='', max_length=32)
    password: SecretStr = Field(default=SecretStr(''))


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ip: str = Field(min_length=7, max_length=15)
    confirmed: Literal[True]


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmed_stationary: Literal[True]


class SpeedRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    level: int = Field(ge=1, le=4)


class FollowRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool


class GimbalTargetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    generation: int = Field(ge=0)
    seq: int = Field(ge=0, le=2**31 - 1)
    issued_at_ms: int = Field(ge=0)
    yaw: float = Field(ge=-60, le=60)
    pitch: float = Field(ge=-20, le=25)


class GimbalStopRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    generation: int = Field(ge=0)


def ep_console_router(broker, authorize, static_root):
    router = APIRouter()

    def check(request, key):
        authorize(key)
        if not local_console_request(request):
            raise HTTPException(403, 'EP 控制只可由本機控制台操作')

    def invoke(operation, payload=None):
        try:
            return JSONResponse(broker.request(operation, payload), headers={'Cache-Control': 'no-store'})
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None

    @router.get('/assets/ep-console.js')
    def script():
        return FileResponse(static_root / 'ep-console.js', media_type='text/javascript',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/assets/ep-console.css')
    def stylesheet():
        return FileResponse(static_root / 'ep-console.css', media_type='text/css',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/assets/ep-fleet.js')
    def fleet_script():
        return FileResponse(static_root / 'ep-fleet.js', media_type='text/javascript',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/assets/ep-fleet.css')
    def fleet_stylesheet():
        return FileResponse(static_root / 'ep-fleet.css', media_type='text/css',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.post('/api/v1/robot/ep/discovery')
    def start_discovery(request: Request, x_operator_key: str | None = Header(default=None)):
        from edge_hub.local_operator import local_console_request
        # Resident pages need only this restricted loopback action, never an operator key.
        if not local_console_request(request):
            raise HTTPException(403)
        return JSONResponse(broker.renew_discovery(), headers={'Cache-Control': 'no-store'})

    @router.delete('/api/v1/robot/ep/devices/{device_id}')
    def forget_device(device_id: str, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        try:
            return JSONResponse(broker.forget(device_id), headers={'Cache-Control': 'no-store'})
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None

    @router.get('/api/v1/robot/ep/fleet')
    def fleet_status(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        try:
            return JSONResponse(broker.fleet_snapshot(), headers={'Cache-Control': 'no-store'})
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None

    @router.get('/api/v1/robot/ep/devices/{device_id}/frame.jpg')
    def jpeg_frame(device_id: str, request: Request, after: str = Query(default='', max_length=64),
                   x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        try:
            frame = broker.device_frame(device_id, after)
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None
        headers = {'Cache-Control': 'no-store', 'X-Frame-State': frame['state'],
                   'X-Frame-Key': frame.get('key', ''), 'X-Frame-Age-Ms': str(frame.get('age_ms', 0)),
                   'X-Content-Type-Options': 'nosniff'}
        if frame['state'] != 'frame':
            return Response(status_code=204, headers=headers)
        return Response(frame['jpeg'], media_type='image/jpeg', headers=headers)

    def fleet_action(operation):
        def action(device_id: str, request: Request, x_operator_key: str | None = Header(default=None)):
            check(request, x_operator_key)
            try:
                return JSONResponse(broker.device_request(device_id, operation), headers={'Cache-Control': 'no-store'})
            except ControlError as error:
                raise HTTPException(error.status, error.reason) from None
        return action

    for operation in ('connect', 'disconnect', 'prepare-control', 'lease', 'stop', 'video-start', 'video-stop', 'gimbal-start', 'manual-warning'):
        router.add_api_route('/api/v1/robot/ep/devices/{device_id}/' + operation,
                             fleet_action(operation), methods=['POST'], name='ep_device_' + operation)
    for operation in ('connection', 'video-frame'):
        router.add_api_route('/api/v1/robot/ep/devices/{device_id}/' + operation,
                             fleet_action('status' if operation == 'connection' else operation),
                             methods=['GET'], name='ep_device_' + operation)

    @router.post('/api/v1/robot/ep/devices/{device_id}/command')
    def fleet_command(device_id: str, data: RobotCommand, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        try:
            return JSONResponse(broker.device_request(device_id, 'command', data.model_dump()),
                                headers={'Cache-Control': 'no-store'})
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None

    def configured(device_id, operation, data):
        try:
            return JSONResponse(broker.device_request(device_id, operation, data.model_dump()),
                                headers={'Cache-Control': 'no-store'})
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None

    @router.post('/api/v1/robot/ep/devices/{device_id}/infrared-warning')
    def infrared_warning(device_id: str, data: InfraredWarningRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return configured(device_id, 'infrared-warning', data)

    @router.post('/api/v1/robot/ep/devices/{device_id}/speed')
    def speed(device_id: str, data: SpeedRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return configured(device_id, 'speed', data)

    @router.post('/api/v1/robot/ep/devices/{device_id}/gimbal-follow')
    def follow(device_id: str, data: FollowRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return configured(device_id, 'gimbal-follow', data)

    @router.post('/api/v1/robot/ep/devices/{device_id}/gimbal-target')
    def gimbal_target(device_id: str, data: GimbalTargetRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return configured(device_id, 'gimbal-target', data)

    @router.post('/api/v1/robot/ep/devices/{device_id}/gimbal-stop')
    def gimbal_stop(device_id: str, data: GimbalStopRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return configured(device_id, 'gimbal-stop', data)

    @router.post('/api/v1/robot/ep/devices/{device_id}/check-stop')
    def fleet_stop_check(device_id: str, data: ResetRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return configured(device_id, 'check-stop', data)

    @router.post('/api/v1/robot/ep/devices/{device_id}/reset-stop')
    def fleet_reset(device_id: str, data: ResetRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        try:
            return JSONResponse(broker.device_request(device_id, 'reset-stop', data.model_dump()),
                                headers={'Cache-Control': 'no-store'})
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None

    @router.get('/api/v1/robot/ep/connection')
    def status(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke('status')

    @router.post('/api/v1/robot/ep/qr')
    def qr(data: QrRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        if broker.safety_hold():
            raise HTTPException(423, 'EP 暫停使用，未讀取 Wi-Fi。')
        try:
            wifi = (current_wifi(include_password=True) if data.use_current_wifi
                    else {'ssid': data.ssid, 'password': data.password.get_secret_value()})
            return invoke('qr', wifi)
        except WifiError as error:
            raise HTTPException(409, str(error)) from None

    @router.get('/api/v1/robot/ep/qr')
    def existing_qr(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke('qr-status')

    @router.post('/api/v1/robot/ep/connect')
    def connect(data: ConnectRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke('connect', data.model_dump())

    @router.post('/api/v1/robot/ep/command')
    def command(data: RobotCommand, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke('command', data.model_dump())

    @router.post('/api/v1/robot/ep/reset-stop')
    def reset(data: ResetRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke('reset-stop', data.model_dump())

    def action_handler(operation):
        def action(request: Request, x_operator_key: str | None = Header(default=None)):
            check(request, x_operator_key)
            return invoke(operation)
        return action

    for operation in ('disconnect', 'cancel-pairing', 'lease', 'stop', 'prepare-control'):
        router.add_api_route(f'/api/v1/robot/ep/{operation}', action_handler(operation),
                             methods=['POST'], name=f'ep_{operation}')

    return router
