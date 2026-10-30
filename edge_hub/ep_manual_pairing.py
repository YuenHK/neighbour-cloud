"""Explicit, local provisioning only. Never connects an SDK Robot."""
import threading

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from edge_hub.ep_console import EpBroker
from edge_hub.local_operator import local_console_request, operator_page
from edge_hub.robot_control import ControlError
from edge_hub.wifi_profile import WifiError, current_wifi


class ManualQrRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    device_id: str = Field(pattern=r'^ep-[1-8]$')
    password: SecretStr | None = Field(default=None, max_length=63)


class EpManualPairing:
    def __init__(self, fleet, acceptance, broker=None):
        self.fleet, self.acceptance = fleet, acceptance
        self.broker = broker if broker is not None else EpBroker(fleet.root, pairing_only=True)
        self.active = False
        self.ssid = ''
        self.observed = []
        self.cancel_requested = threading.Event()
        acceptance.pairing_active = lambda: self.active

    def target(self):
        with self.fleet.device_lock:
            items = [item for item in self.fleet.devices.values() if item.get('known_sn', '').endswith('0930')]
        if len(items) != 1:
            return {'id': None, 'sn': '0930'}
        return {'id': items[0]['id'], 'sn': items[0]['known_sn']}

    def state(self):
        try:
            result = self.broker.request('status')
        except ControlError:
            result = {'pairing': 'updating' if self.acceptance.lock.locked() else 'unavailable'}
        if result.get('candidates'):
            self.observed = result['candidates']
        return {'target': self.target(), 'active': self.active, 'ssid': self.ssid,
                'pairing': result.get('pairing', 'idle'), 'candidates': list(self.observed),
                'qr_revision': result.get('qr_revision', ''),
                'acceptance_busy': self.acceptance.selected is not None,
                'safety_hold': self.fleet.safety_hold(), 'connection': 'not_connected',
                'movement_enabled': False, 'auto_reconnect': False, 'identity_verified': False}

    def generate(self, data):
        # Share the acceptance transaction lock: pairing and connection cannot
        # race. No read of WLAN credentials occurs until this explicit POST.
        if not self.acceptance.lock.acquire(blocking=False):
            raise ControlError('驗收正在處理，請先結束並斷線。', 409)
        try:
            if not self.fleet.safety_hold():
                raise ControlError('手動配網需要方向控制保持停用。', 423)
            if self.acceptance.selected is not None:
                raise ControlError('請先返回驗收頁按「結束並斷線」，再產生配網碼。', 409)
            target = self.target()
            if not target['id'] or data.device_id != target['id']:
                raise ControlError('此入口只供已保存的 0930 配網，不會任選其他機體。', 423)
            with self.fleet.device_lock:
                peers = [self.fleet, *(item['broker'] for item in self.fleet.devices.values())]
                if any(peer.process is not None and peer.process.poll() is None for peer in peers):
                    raise ControlError('普通 EP 程序尚未結束，請先停止驗收。', 423)
            self.cancel_requested.clear()
            wifi = current_wifi(include_password=data.password is None)
            password = wifi['password'] if data.password is None else data.password.get_secret_value()
            result = self.broker.request('qr', {'ssid': wifi['ssid'], 'password': password})
            self.active, self.ssid, self.observed = True, wifi['ssid'], []
            return {**result, 'target': target, 'connection': 'not_connected',
                    'movement_enabled': False, 'auto_reconnect': False, 'identity_verified': False}
        finally:
            try:
                if self.cancel_requested.is_set():
                    self.broker.close()
                    self.active, self.ssid = False, ''
            finally:
                self.acceptance.lock.release()

    def qr(self):
        # Only the browser should request this endpoint; it can contain a
        # recoverable WLAN key. Never put it in diagnostics or log output.
        return {**self.broker.request('qr-status'), 'target': self.target()}

    def close(self):
        self.cancel_requested.set()
        if not self.acceptance.lock.acquire(blocking=False):
            return {'cancel_pending': True}
        try:
            self.broker.close()
            self.active, self.ssid = False, ''
            return {'active': False, 'connection': 'not_connected'}
        finally:
            self.acceptance.lock.release()


def ep_manual_pairing_router(pairing, authorize, static_root):
    router = APIRouter()
    headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
               'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer'}

    def check(request, key):
        if not local_console_request(request):
            raise HTTPException(403, '手動配網只可在本機使用。')
        authorize(key)

    def invoke(task):
        try:
            return JSONResponse(task(), headers=headers)
        except ControlError as error:
            raise HTTPException(error.status, error.reason) from None
        except WifiError:
            raise HTTPException(409, 'Windows 未能讀取當前 Wi-Fi 帳密；請確認已連 Wi-Fi，或在本頁隱藏欄位輸入該 Wi-Fi 密碼。') from None

    @router.get('/ep-manual-pairing')
    def page(request: Request):
        if not local_console_request(request):
            raise HTTPException(403, '手動配網只可在本機使用。')
        source = (static_root / 'ep-manual-pairing.html').read_text(encoding='utf-8')
        return HTMLResponse(operator_page(source, request), headers=headers)

    @router.get('/assets/ep-manual-pairing.js')
    def script():
        return FileResponse(static_root / 'ep-manual-pairing.js', media_type='text/javascript', headers=headers)

    @router.get('/api/v1/robot/ep/manual-pairing/status')
    def status(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(pairing.state)

    @router.get('/api/v1/robot/ep/manual-pairing/qr')
    def qr(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(pairing.qr)

    @router.post('/api/v1/robot/ep/manual-pairing/qr')
    def generate(data: ManualQrRequest, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(lambda: pairing.generate(data))

    @router.post('/api/v1/robot/ep/manual-pairing/end')
    def end(request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        return invoke(pairing.close)

    return router
