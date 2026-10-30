"""One manually selected EP, passive stage-two observation only."""
import threading
import time
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from edge_hub.ep_console import EpBroker
from edge_hub.local_operator import local_console_request, operator_page
from edge_hub.robot_control import ControlError


class AcceptanceConnect(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    device_id: str = Field(pattern=r'^ep-[1-8]$')
    confirmed_stationary: Literal[True]
    stage: Literal[2, 3, 4, 5, 6] = 2


class AcceptancePrepare(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmed_gimbal_recenter: Literal[True]


class AutomaticAcceptanceConnect(AcceptanceConnect):
    stage: Literal[6]
    confirmed_auto_connect: Literal[True]


class AcceptanceReset(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmed_stationary: Literal[True]


class ShortPressIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    press_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class ShortPressRelease(ShortPressIdentity):
    source: Literal['release', 'limit', 'blur', 'cancel', 'disconnect', 'pagehide'] = 'release'


class ShortPressStart(ShortPressIdentity):
    issued_at_ms: int = Field(ge=0)
    confirmed_clear_path: Literal[True]


class MotorRelease(AcceptanceReset):
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    stop_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class EpAcceptance:
    def __init__(self, fleet, broker=None):
        self.fleet = fleet
        # Separate process; normal fleet remains completely held.
        self.broker = broker if broker is not None else EpBroker(
            fleet.root, 'ep-8', 12008, acceptance_only=True)
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.selected = None
        self.started_at = None
        self.stage = 2
        self.prepare_attempted = False
        self.pairing_active = lambda: False
        self.last_short_receipt = None
        self.auto_attempts = 0
        self.auto_target = None
        self.auto_last_attempt = None

    def targets(self):
        with self.fleet.device_lock:
            return [{'id': item['id'], 'sn': item['known_sn']}
                    for item in self.fleet.devices.values() if item.get('known_sn')]

    def state(self):
        result = {'connection': 'connecting'}
        if not self.lock.locked():
            try:
                result = self.broker.request('status')
            except ControlError:
                result = {'connection': 'not_connected', 'error': '狀態未確認，請斷線並在現場關機。'}
        self.remember_short_receipt(result)
        return {**result, 'devices': self.targets(), 'selected_id': self.selected,
                'elapsed_seconds': int(time.monotonic() - self.started_at) if self.started_at else 0,
                'acceptance_stage': self.stage, 'prepare_attempted': self.prepare_attempted,
                'prepared_idle': result.get('prepared_idle', False),
                'observation_seconds': 120,
                'movement_enabled': self.stage in (4, 5, 6) and result.get('movement_enabled') is True,
                'last_short_receipt': self.last_short_receipt,
                'auto_connect_attempts': self.auto_attempts,
                'auto_reconnect': False,
                'hardware_acceptance': False, 'safety_hold': self.fleet.safety_hold()}

    def connect(self, device_id, stage=2, *, automatic=False):
        if stage not in (2, 3, 4, 5, 6) or type(stage) is not int:
            raise ControlError('驗收階段不符。', 422)
        if not self.fleet.safety_hold():
            raise ControlError('第二階段需要普通控制台保持停用。', 423)
        if not self.lock.acquire(blocking=False):
            raise ControlError('正在處理本次驗收，請稍候。', 409)
        try:
            if self.pairing_active():
                raise ControlError('請先結束手動配網，再由你手動連線驗收。', 423)
            if automatic:
                if (stage != 6 or self.auto_attempts >= 3
                        or self.auto_target not in (None, device_id)):
                    raise ControlError('自動連線已停止；每次只試同一台最多三次，請結束後核對配網。', 423)
                if self.auto_last_attempt is not None and time.monotonic() - self.auto_last_attempt < 5:
                    raise ControlError('請等待下一次自動連線，不會連續重試。', 409)
                if self.selected is not None:
                    state = self.broker.request('status')
                    control = state.get('control') or {}
                    error = state.get('last_connection_error') or {}
                    if (self.selected != device_id or self.stage != 6 or self.prepare_attempted
                            or self.started_at is not None or state.get('connection') != 'not_connected'
                            or state.get('prepared_idle') or control.get('lease_active')
                            or control.get('state') == 'fault' or control.get('software_stop_latched')
                            or error.get('code') != 'handshake_timeout'):
                        raise ControlError('目前狀態不可自動重試；不會中斷連線或解除鎖定。', 423)
                    self.broker.close()  # failed, unprepared connection only
                    self.selected = None
            if self.selected is not None:
                raise ControlError('一次只可驗收一台；請先斷線。', 409)
            with self.fleet.device_lock:
                item = self.fleet.devices.get(device_id)
                if item is None or not item.get('known_sn'):
                    raise ControlError('請選擇已保存且有機體 SN 的 EP。', 404)
                payload = {'ip': item['ip'], 'expected_sn': item['known_sn'], 'confirmed': True}
                regular = [self.fleet, *(entry['broker'] for entry in self.fleet.devices.values())]
                if any(peer.process is not None and peer.process.poll() is None for peer in regular):
                    raise ControlError('普通 EP 程序仍在運行，請先停止再驗收。', 423)
                # Match the normal fleet's control store, not the reserved SDK
                # port/device used by stage two. Old stop flags must apply.
                self.broker.device_id = None if item['broker'] is self.fleet else item['broker'].device_id
            if automatic:
                self.auto_target = device_id
                self.auto_attempts += 1
                self.auto_last_attempt = time.monotonic()
            else:
                self.auto_attempts, self.auto_target, self.auto_last_attempt = 0, None, None
            self.broker.acceptance_prepare = stage in (3, 4, 5, 6)
            self.broker.acceptance_short_press = stage in (4, 5, 6)
            self.broker.acceptance_release_check = stage in (5, 6)
            self.broker.acceptance_idle_motor = stage == 6
            self.last_short_receipt = None
            self.stage, self.prepare_attempted = stage, False
            self.cancel.clear()
            self.selected, self.started_at = device_id, None
            result = self.broker.request('connect', payload)
            if self.cancel.is_set():
                return {'connection': 'not_connected', 'cancelled': True}
            if stage == 2 and result.get('connection') == 'connected':
                self.started_at = time.monotonic()
            return {**result, 'selected_id': self.selected, 'elapsed_seconds': 0,
                    'movement_enabled': False, 'auto_reconnect': False, 'hardware_acceptance': False}
        finally:
            try:
                if self.cancel.is_set():
                    self.broker.close()
                    self.selected, self.started_at = None, None
            finally:
                self.lock.release()

    def prepare(self):
        if not self.lock.acquire(blocking=False):
            raise ControlError('正在處理本次驗收，請稍候。', 409)
        try:
            if not self.fleet.safety_hold() or self.stage not in (3, 4, 5, 6) or self.selected is None:
                raise ControlError('請先在本階段手動連線一台 EP。', 423)
            if self.prepare_attempted:
                raise ControlError('本次已嘗試準備，請先結束驗收。', 409)
            self.prepare_attempted = True
            self.cancel.clear()
            result = self.broker.request('prepare-control')
            if result.get('prepared_idle') is not True:
                raise ControlError('準備未確認，請結束驗收並在現場關機。', 503)
            if not self.cancel.is_set():
                self.started_at = time.monotonic()
            return result
        finally:
            try:
                if self.cancel.is_set():
                    self.broker.close()
                    self.selected, self.started_at = None, None
            finally:
                self.lock.release()

    def disconnect(self):
        # A page can close while connection setup is in flight. Cancel that setup
        # too, so a late result cannot silently leave a session behind.
        self.cancel.set()
        if not self.lock.acquire(blocking=False):
            return {'connection': 'disconnecting', 'movement_enabled': False}
        try:
            self.broker.close()
            self.selected, self.started_at = None, None
            self.auto_attempts, self.auto_target, self.auto_last_attempt = 0, None, None
            return {'connection': 'not_connected', 'selected_id': None, 'movement_enabled': False}
        finally:
            self.lock.release()

    def reset_stop(self):
        if not self.lock.acquire(blocking=False):
            raise ControlError('正在處理本次驗收，請稍候。', 409)
        try:
            if (not self.fleet.safety_hold() or self.stage not in (3, 4, 5, 6) or self.selected is None
                    or self.started_at is not None or self.cancel.is_set()):
                raise ControlError('只可在準備前手動解除普通停止。', 423)
            status = self.broker.request('status')
            control = status.get('control') or {}
            if (status.get('connection') != 'connected' or control.get('state') != 'safe_stop'
                    or control.get('software_stop_latched') is not True or control.get('lease_active')):
                raise ControlError('沒有可解除的普通停止鎖定；故障不會解除。', 423)
            result = self.broker.request('reset-stop', {'confirmed_stationary': True})
            control = result.get('control') or {}
            if (control.get('software_stop_latched') is not False or control.get('state') != 'idle'
                    or control.get('lease_active') is not False):
                raise ControlError('解除結果未確認，請結束驗收並在現場關機。', 503)
            self.prepare_attempted = False
            return result
        finally:
            try:
                if self.cancel.is_set():
                    self.broker.close()
                    self.selected, self.started_at = None, None
            finally:
                self.lock.release()

    def close(self):
        return self.disconnect()

    def short_press(self, operation, payload):
        # Do not take the connection transaction lock: a release must enter the
        # worker even if its corresponding start response has not yet arrived.
        if operation not in {'short-press-start', 'short-press-release'} or self.stage not in (4, 5, 6) or self.selected is None:
            raise ControlError('只有短按驗收階段可由你手動短按，其他操作仍停用。', 423)
        if operation == 'short-press-start' and (not self.fleet.safety_hold() or self.pairing_active()):
            raise ControlError('配網或停用狀態未確認，未發出移動。', 423)
        result = self.broker.request(operation, payload)
        self.remember_short_receipt(result)
        return result

    def motor(self, operation, payload):
        if (self.stage != 6 or self.selected is None or self.cancel.is_set()
                or not self.fleet.safety_hold() or self.pairing_active()
                or operation not in {'motor-release', 'motor-activate'}):
            raise ControlError('只有第六階段可手動驗收電機釋放。', 423)
        return self.broker.request(operation, payload)

    def remember_short_receipt(self, result):
        control = result.get('control') or {}
        origin = result.get('short_press_stop_origin')
        if (self.stage in (4, 5, 6) and result.get('short_press_used')
                and origin and control.get('direction') == 'stop' and control.get('lease_active') is False):
            self.last_short_receipt = {'stage': self.stage, 'device_id': self.selected,
                'stop_origin': origin, 'control_state': control.get('state'),
                'max_ms': result.get('short_press_max_ms'), 'reported_at_ms': int(time.time() * 1000),
                'physical_stop_verified': False}


def ep_acceptance_router(acceptance, authorize, static_root):
    router = APIRouter()
    headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}

    def check(request, key):
        if not local_console_request(request):
            raise HTTPException(403, '驗收入口只可在本機使用。')
        authorize(key)

    def invoke(task):
        try:
            return JSONResponse(task(), headers=headers)
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None

    @router.get('/ep-acceptance')
    def page(request: Request):
        if not local_console_request(request):
            raise HTTPException(403, '驗收入口只可在本機使用。')
        source = (static_root / 'ep-acceptance.html').read_text(encoding='utf-8')
        return HTMLResponse(operator_page(source, request), headers=headers)

    @router.get('/assets/ep-acceptance.js')
    def script():
        return FileResponse(static_root / 'ep-acceptance.js', media_type='text/javascript', headers=headers)

    @router.get('/ep-idle-acceptance')
    def idle_page(request: Request):
        if not local_console_request(request):
            raise HTTPException(403, '驗收入口只可在本機使用。')
        source = (static_root / 'ep-idle-acceptance.html').read_text(encoding='utf-8')
        return HTMLResponse(operator_page(source, request), headers=headers)

    @router.get('/ep-short-press-acceptance')
    def short_press_page(request: Request):
        if not local_console_request(request):
            raise HTTPException(403, '驗收入口只可在本機使用。')
        source = (static_root / 'ep-short-press-acceptance.html').read_text(encoding='utf-8')
        return HTMLResponse(operator_page(source, request), headers=headers)

    @router.get('/ep-release-check-acceptance')
    def release_check_page(request: Request):
        if not local_console_request(request):
            raise HTTPException(403, '驗收入口只可在本機使用。')
        source = (static_root / 'ep-release-check-acceptance.html').read_text(encoding='utf-8')
        return HTMLResponse(operator_page(source, request), headers=headers)

    @router.get('/ep-idle-motor-acceptance')
    def idle_motor_page(request: Request):
        if not local_console_request(request):
            raise HTTPException(403, '驗收入口只可在本機使用。')
        source = (static_root / 'ep-idle-motor-acceptance.html').read_text(encoding='utf-8')
        return HTMLResponse(operator_page(source, request), headers=headers)

    @router.post('/api/v1/robot/ep/acceptance/motor-release')
    def motor_release(data: MotorRelease, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(lambda: acceptance.motor('motor-release', data.model_dump()))

    @router.post('/api/v1/robot/ep/acceptance/motor-activate')
    def motor_activate(data: ShortPressStart, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(lambda: acceptance.motor('motor-activate', data.model_dump()))

    @router.get('/api/v1/robot/ep/acceptance/status')
    def status(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(acceptance.state)

    @router.post('/api/v1/robot/ep/acceptance/connect')
    def connect(data: AcceptanceConnect, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(lambda: acceptance.connect(data.device_id, data.stage))

    @router.post('/api/v1/robot/ep/acceptance/connect-auto')
    def connect_auto(data: AutomaticAcceptanceConnect, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(lambda: acceptance.connect(data.device_id, data.stage, automatic=True))

    @router.post('/api/v1/robot/ep/acceptance/prepare')
    def prepare(data: AcceptancePrepare, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(acceptance.prepare)

    @router.post('/api/v1/robot/ep/acceptance/disconnect')
    def disconnect(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(acceptance.disconnect)

    @router.post('/api/v1/robot/ep/acceptance/reset-stop')
    def reset_stop(data: AcceptanceReset, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(acceptance.reset_stop)

    @router.post('/api/v1/robot/ep/acceptance/short-press-start')
    def short_start(data: ShortPressStart, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(lambda: acceptance.short_press('short-press-start', data.model_dump()))

    @router.post('/api/v1/robot/ep/acceptance/short-press-release')
    def short_release(data: ShortPressRelease, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(lambda: acceptance.short_press('short-press-release', data.model_dump()))

    return router
