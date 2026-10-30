"""Run the approved Store agent and local gateway; never restart local AIRI or EP."""
import argparse
import ctypes
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

from edge_hub.cloud_credentials import _crypt, settings_root
from edge_hub.remote_gateway import HOP_HEADER


def traffic_policy(email, proof):
    if not re.fullmatch(r'[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}', email):
        raise ValueError('Invalid operator account')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', proof):
        raise ValueError('Invalid hop proof')
    return {'on_http_request': [
        {'actions': [{'type': 'oauth', 'config': {'provider': 'google', 'max_session_duration': '8h',
                                                'idle_session_timeout': '1h'}}]},
        {'expressions': ['actions.ngrok.oauth.identity.email != '+json.dumps(email)],
         'actions': [{'type': 'deny'}]},
        {'actions': [{'type': 'remove-headers', 'config': {'headers': [HOP_HEADER]}},
                     {'type': 'add-headers', 'config': {'headers': {HOP_HEADER: proof}}}]},
    ]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ngrok', type=Path, required=True)
    args = parser.parse_args()
    allowed = Path(os.environ['LOCALAPPDATA'])/'Microsoft/WindowsApps/ngrok.exe'
    if args.ngrok.absolute() != allowed.absolute():
        raise SystemExit('Use the ngrok Microsoft Store application alias only.')
    root = Path(__file__).resolve().parents[1]
    private = settings_root()/'remote-access'
    if not (private/'READY.json').is_file():
        raise SystemExit('Complete local remote-access setup first.')
    profile = json.loads((private/'settings.json').read_text(encoding='utf-8'))
    if profile['plan'] != 'Free' or profile['automatic_paid_upgrade'] is not False:
        raise SystemExit('Only the verified Free profile is supported.')
    domain = profile['domain']
    if not re.fullmatch(r'[a-z0-9-]+\.ngrok-free\.(app|dev)', domain) or len(profile['allowed_emails']) != 1:
        raise SystemExit('Use one operator and the existing free domain.')
    token = _crypt((private/'ngrok-token.dpapi').read_bytes(), decrypt=True).decode()
    proof = secrets.token_urlsafe(40)
    live = root/'.runtime/remote-access-live'
    live.mkdir(exist_ok=True)
    stop = live/'stop'
    if stop.exists():
        stop.unlink()  # This application's own prior stop signal, never user data.
    run = Path(tempfile.mkdtemp(prefix='session-', dir=live))
    policy = run/'policy.json'
    policy.write_text(json.dumps(traffic_policy(profile['allowed_emails'][0], proof)), encoding='utf-8')
    config = run/'agent.json'
    config.write_text(json.dumps({'version': '3', 'agent': {'web_addr': '127.0.0.1:4041', 'update_check': False}}), encoding='utf-8')
    # Policy has only a per-run hop proof and an account allowlist; the persistent
    # ngrok token is supplied through this child's environment, never a command.
    state = {'pid': os.getpid(), 'status': 'starting', 'url': 'https://'+domain,
             'plan': 'Free', 'automatic_paid_upgrade': False, 'gateway_pid': None, 'agent_pid': None,
             'last_error_code': None, 'sleep_request': False}
    destination = live/'state.json'
    def save():
        temporary = run/'state.tmp'
        temporary.write_text(json.dumps(state), encoding='utf-8')
        os.replace(temporary, destination)
    save()
    processes = []
    kernel = None
    try:
        hidden = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        gateway_env = {**os.environ, 'NEIGHBOUR_PROXY_TOKEN': proof, 'NEIGHBOUR_REMOTE_HOSTS': json.dumps([domain])}
        gateway = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'edge_hub.remote_gateway:from_environment', '--factory',
                                    '--host', '127.0.0.1', '--port', '8001', '--no-access-log', '--log-level', 'warning'],
                                   cwd=root, env=gateway_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden)
        processes.append(gateway)
        state['gateway_pid'] = gateway.pid
        with httpx.Client(trust_env=False, timeout=2) as client:
            for _ in range(30):
                if gateway.poll() is not None:
                    raise RuntimeError('gateway_start_failed')
                try:
                    response = client.get('http://127.0.0.1:8001/__remote/runtime.js', headers={HOP_HEADER: proof, 'Host': domain})
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError('gateway_not_ready')
            env = {**os.environ, 'NGROK_AUTHTOKEN': token}
            agent = subprocess.Popen([str(args.ngrok), 'http', 'http://127.0.0.1:8001', '--url', state['url'],
                                      '--traffic-policy-file', str(policy), '--config', str(config), '--inspect=false',
                                      '--log', 'stdout', '--log-format', 'json', '--log-level', 'warn'],
                                     cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding='utf-8', errors='replace', **hidden)
            processes.append(agent)
            state['agent_pid'] = agent.pid
            state['status'] = 'connecting'
            save()
            def safe_errors():
                # Never persist raw agent output: invalid-token errors may echo
                # credentials. Keep only vendor error-code identifiers.
                for line in agent.stdout:
                    match = re.search(r'ERR_NGROK_[A-Z0-9_]+', line)
                    if match:
                        state['last_error_code'] = match[0]
            threading.Thread(target=safe_errors, daemon=True).start()
            for _ in range(40):
                if agent.poll() is not None:
                    raise RuntimeError('agent_start_failed')
                try:
                    data = client.get('http://127.0.0.1:4041/api/tunnels').json()
                    if any(item.get('public_url') == state['url'] for item in data.get('tunnels', [])):
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError('endpoint_not_ready')
            state['status'] = 'online'
            if os.name == 'nt':
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
                kernel.SetThreadExecutionState.restype = ctypes.c_uint32
                state['sleep_request'] = bool(kernel.SetThreadExecutionState(0x80000000 | 1))
            save()
            while not stop.exists():
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError('remote_process_exited')
                time.sleep(1)
            state['status'] = 'stopped'
    except Exception as error:  # noqa: BLE001 -- only a fixed class/reason is persisted, never credentials
        state['status'] = 'failed'
        state['failure'] = str(error) if type(error) is RuntimeError else type(error).__name__
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        if kernel:
            kernel.SetThreadExecutionState(0x80000000)
        state['sleep_request'] = False
        save()
        policy.unlink(missing_ok=True)  # Own ephemeral hop proof; no user key is deleted.


if __name__ == '__main__':
    main()
