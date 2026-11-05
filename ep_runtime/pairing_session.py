"""Provisioning QR and its reply listener; never creates a Robot instance."""
from edge_hub.robot_control import ControlError
from ep_runtime.console_session import EpSession


class PairingOnlyEpSession(EpSession):
    def handle(self, operation, payload):
        if operation not in {'qr', 'qr-status', 'status', 'cancel-pairing', 'disconnect'}:
            raise ControlError('配網程序禁止 SDK 控制連線、移動、雲台及聲畫。', 423)
        if operation == 'disconnect':
            with self.lock:
                self.cancel_pairing()
                return self.status()
        return super().handle(operation, payload)

    def status(self):
        return {**super().status(), 'pairing_only': True, 'movement_enabled': False,
                'auto_reconnect': False, 'identity_verified': False}
