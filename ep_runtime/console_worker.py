"""Private stdin/stdout IPC. Never run a network listener on import or startup."""
import argparse
import contextlib
import json
import logging
import sys
import threading
from pathlib import Path

from edge_hub.robot_control import ControlError
from ep_runtime.console_session import EpSession


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--device-id', choices=[f'ep-{value}' for value in range(1, 9)])
    parser.add_argument('--sdk-port', type=int, choices=range(12001, 12009))
    parser.add_argument('--acceptance-only', action='store_true')
    parser.add_argument('--acceptance-prepare', action='store_true')
    parser.add_argument('--pairing-only', action='store_true')
    parser.add_argument('--acceptance-short-press', action='store_true')
    parser.add_argument('--acceptance-release-check', action='store_true')
    parser.add_argument('--acceptance-idle-motor', action='store_true')
    options = parser.parse_args()
    if options.acceptance_idle_motor and not options.acceptance_release_check:
        parser.error('idle motor requires acceptance-release-check')
    if options.acceptance_release_check and not options.acceptance_short_press:
        parser.error('release check requires acceptance-short-press')
    if options.acceptance_short_press and not (options.acceptance_only and options.acceptance_prepare):
        parser.error('short press requires acceptance-only and acceptance-prepare')
    if options.pairing_only and (options.acceptance_only or options.acceptance_prepare):
        parser.error('pairing and acceptance worker roles are mutually exclusive')
    if options.acceptance_prepare and not options.acceptance_only:
        parser.error('--acceptance-prepare requires --acceptance-only')
    if (options.acceptance_only or options.pairing_only) and not (root / '.runtime/ep-safety-hold.json').exists():
        print(json.dumps({'ok': False, 'detail': 'Stage two requires normal control hold', 'status': 423}))
        return
    if (root / '.runtime/ep-safety-hold.json').exists() and not (options.acceptance_only or options.pairing_only):
        # Refuse direct invocation too; no SDK load or background guard starts.
        print(json.dumps({'ok': False, 'error': 'EP safety hold', 'status': 423}))
        return

    def load():
        from ep_runtime.bootstrap import load_sdk
        logging.disable(logging.CRITICAL)
        from contextlib import redirect_stdout
        with redirect_stdout(sys.stderr):
            robot, _ = load_sdk(root / '.runtime/ep-sdk/source/src')
        return robot

    ipc = sys.stdout
    ipc_lock = threading.Lock()
    def send(message):
        with ipc_lock:
            ipc.write(json.dumps(message, ensure_ascii=True) + '\n')
            ipc.flush()
    def progress(stage):
        send({'event': 'connection_stage', 'stage': stage})
    if options.pairing_only:
        from ep_runtime.pairing_session import PairingOnlyEpSession
        session = PairingOnlyEpSession(root, load, progress)
    elif options.acceptance_only:
        from ep_runtime.readonly_session import PreparedIdleEpSession, ReadOnlyEpSession
        if options.acceptance_short_press:
            from ep_runtime.short_press_session import ReleaseCheckEpSession, ShortPressEpSession
            session_type = ReleaseCheckEpSession if options.acceptance_release_check else ShortPressEpSession
            if options.acceptance_idle_motor:
                from ep_runtime.idle_motor_session import IdleMotorEpSession
                session_type = IdleMotorEpSession
        else:
            session_type = PreparedIdleEpSession if options.acceptance_prepare else ReadOnlyEpSession
        session = session_type(root, load, progress)
    else:
        session = EpSession(root, load, progress)
    session.video_sink = send
    session.device_id, session.sdk_port = options.device_id, options.sdk_port
    session.realtime_controls_enabled = options.acceptance_short_press or not (options.acceptance_only or options.pairing_only)
    try:
        for line in sys.stdin:
            if len(line) > 16384:
                break
            try:
                request = json.loads(line)
                # Keep third-party prints out of the IPC response channel.
                with contextlib.redirect_stdout(sys.stderr):
                    result = session.handle(request['operation'], request.get('payload', {}))
                response = {'ok': True, 'result': result}
            except ControlError as error:
                response = {'ok': False, 'status': error.status, 'detail': error.reason}
            except Exception:  # noqa: BLE001 -- isolate third-party SDK failures at the IPC boundary
                response = {'ok': False, 'status': 503, 'detail': 'EP 工具未能完成；未確認的動作不會自動重試。'}
            send(response)
    finally:
        session.stopping.set()
        session.disconnect()
        session.cancel_pairing()


if __name__ == '__main__':
    main()
