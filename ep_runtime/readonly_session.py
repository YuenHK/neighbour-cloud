"""Stage two: SDK connection and passive telemetry, with no control authority."""
import sqlite3
from contextlib import closing

from edge_hub.robot_control import ControlError, RobotController, _read_safety_marker
from ep_runtime.console_session import EpSession, LiveTransport


class ReadOnlyEpSession(EpSession):
    def handle(self, operation, payload):
        # Enforce inside the worker as well as in Hub. No controller/lease,
        # zero-speed renewal, health probe, pairing, gimbal or camera operation.
        if operation not in {'status', 'connect', 'disconnect'}:
            raise ControlError('第二階段禁止移動、雲台、聲畫及控制租約。', 423)
        return super().handle(operation, payload)

    def status(self):
        return {**super().status(), 'acceptance_only': True, 'movement_enabled': False,
                'auto_reconnect': False, 'hardware_acceptance': False}


class PreparedIdleEpSession(ReadOnlyEpSession):
    """Stage three: one explicit preparation, no lease or direction API."""
    def __init__(self, *args, **kwargs):
        self.prepare_attempted = self.prepared_idle = False
        super().__init__(*args, **kwargs)

    def handle(self, operation, payload):
        if operation == 'reset-stop':
            with self.lock:
                if payload.get('confirmed_stationary') is not True:
                    raise ControlError('請先在現場確認機體完全靜止。', 422)
                self.require_grounded()
                marker = self.status().get('control') or {}
                if (self.prepared_idle or not marker.get('software_stop_latched')
                        or marker.get('state') == 'fault' or marker.get('lease_active')):
                    raise ControlError('本頁只可解除未準備機體的普通停止鎖定，故障必須保留。', 423)
                if self.control is None:
                    self.control = RobotController(self.control_path(), transport=LiveTransport(
                        self.robot, model='EP', on_site_motion_authorized=True))
                    self.control.start()
                # Existing controller rechecks fault, idle and lease atomically;
                # resetting ordinary stop emits no motor or gimbal command.
                self.control.reset_software_stop()
                self.prepare_attempted = False
                return self.status()
        if operation == 'disconnect':
            self.prepared_idle = False
        if operation == 'prepare-control':
            with self.lock:
                if self.prepare_attempted:
                    raise ControlError('本次已嘗試準備，請結束驗收；不會自動重試。', 409)
                self.prepare_attempted = True
                # Restore the selected EP's existing stop/fault before wheel
                # targets, mode changes or recenter. Never clear old markers.
                try:
                    self.require_idle()
                except ControlError:
                    if self.control and (self.control.stop_latched or self.control.state == 'fault'):
                        raise ControlError('這台保留舊停止鎖定；請先在本頁確認靜止並手動解除。故障不能解除。', 423) from None
                    raise
                self.prepare_control()
                self.prepared_idle = True
                return self.status()
        return super().handle(operation, payload)

    def status(self):
        result = {**super().status(), 'acceptance_stage': 3,
                  'prepare_attempted': self.prepare_attempted, 'prepared_idle': self.prepared_idle}
        # Show existing markers immediately after connect without starting a
        # controller, issuing a stop, modifying the database or retrying prepare.
        if self.robot and self.control is None and self.control_path().exists():
            try:
                with closing(sqlite3.connect(self.control_path().resolve().as_uri() + '?mode=ro', uri=True)) as db:
                    db.row_factory = sqlite3.Row
                    marker = _read_safety_marker(db)
                result['control'] = {'software_stop_latched': bool(marker['requires_reset'] or marker['fault']),
                    'state': 'fault' if marker['fault'] else 'safe_stop' if marker['requires_reset'] else 'idle',
                    'direction': 'stop', 'lease_active': False, 'persisted_only': True}
            except sqlite3.Error:
                result['control'] = {'software_stop_latched': True, 'state': 'fault', 'lease_active': False}
        return result

    def control_path(self):
        name = f'ep-control-{self.device_id}.sqlite3' if self.device_id else 'ep-control.sqlite3'
        return self.root / '.runtime' / name
