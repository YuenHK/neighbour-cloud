"""Explicit, temporary Windows loopback enrolment for the cloud's first staff.

This is never a public signup endpoint. It requires a human-created Web OAuth
client and a matching Google sign-in, verifies Google's signature/audience and
a fresh nonce, and saves only deployment metadata under CurrentUser DPAPI.
No Google ID token, client secret, passwords or resident data are persisted.
"""
import argparse
import asyncio
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from deploy.cloud.database_profile import unique_object
from deploy.cloud.google_identity import (
    GoogleIdentityVerifier,
    IdentityUnavailable,
    InvalidIdentity,
)
from deploy.cloud.http_app import validate_origin
from edge_hub.cloud_credentials import _crypt

CLIENT = re.compile(r'[0-9]+(?:-[A-Za-z0-9_-]+)?\.apps\.googleusercontent\.com')
EMAIL = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')
ASSETS = Path(__file__).with_name('login-setup')


class SetupState:
    def __init__(self, output, origin, *, encryptor=None, verifier_factory=GoogleIdentityVerifier):
        self.output = Path(output)
        validate_origin(origin)
        if (not self.output.is_absolute() or self.output.suffix != '.dpapi'
                or not self.output.parent.is_dir() or self.output.exists()
                or self.output.is_symlink() or any(parent.is_symlink() for parent in self.output.parents)
                or (encryptor is None and os.name != 'nt')):
            raise ValueError('new_explicit_encrypted_setup_target_required')
        self.origin = origin
        self.encryptor = encryptor or (lambda value: _crypt(value, decrypt=False))
        self.verifier_factory = verifier_factory
        self.csrf = secrets.token_urlsafe(32)
        self.client_id = self.email = self.nonce = None
        self.saved = False
        self.lock = asyncio.Lock()

    async def configure(self, value):
        async with self.lock:
            if self.saved or self.output.exists():
                raise FileExistsError('setup_already_saved')
            if (not isinstance(value, dict) or set(value) != {'client_id', 'email'}
                    or not isinstance(value['client_id'], str) or len(value['client_id']) > 256
                    or not CLIENT.fullmatch(value['client_id']) or not isinstance(value['email'], str)
                    or not 3 <= len(value['email']) <= 254 or not value['email'].isascii()
                    or not EMAIL.fullmatch(value['email'])):
                raise ValueError('invalid_setup_configuration')
            self.client_id, self.email = value['client_id'], value['email'].lower()
            self.nonce = secrets.token_urlsafe(32)
            return {'client_id': self.client_id, 'nonce': self.nonce}

    async def enrol(self, value):
        async with self.lock:
            if self.saved or self.output.exists():
                raise FileExistsError('setup_already_saved')
            if (self.client_id is None or not isinstance(value, dict) or set(value) != {'credential'}
                    or not isinstance(value['credential'], str)
                    or not 1 <= len(value['credential']) <= 16384 or not value['credential'].isascii()):
                raise InvalidIdentity('setup_identity_not_accepted')
            import jwt

            try:
                # These unverified fields are routing hints only. The same
                # exact token MUST pass the normal full verifier before save.
                claims = jwt.decode(value['credential'], options={'verify_signature': False})
                subject = claims.get('sub')
                if not isinstance(subject, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', subject):
                    raise InvalidIdentity('setup_identity_not_accepted')
                verifier = self.verifier_factory(self.client_id, {subject: 'staff'})
                try:
                    principal = await verifier.verify(value['credential'])
                finally:
                    await verifier.aclose()
                if (principal.subject != subject or principal.email.lower() != self.email
                        or principal.role != 'staff' or not isinstance(claims.get('nonce'), str)
                        or not hmac.compare_digest(claims['nonce'], self.nonce)):
                    raise InvalidIdentity('setup_identity_not_accepted')
            except (jwt.PyJWTError, KeyError, TypeError, ValueError):
                raise InvalidIdentity('setup_identity_not_accepted') from None
            record = {'format': 'neighbour-google-login-v1', 'origin': self.origin,
                'google_client_id': self.client_id, 'accounts': {principal.subject: 'staff'},
                'approved_email': principal.email, 'created_utc': datetime.now(UTC).isoformat()}
            try:
                encrypted = self.encryptor(json.dumps(record, separators=(',', ':')).encode('utf-8'))
            except (OSError, RuntimeError, ValueError):
                raise OSError('encrypted_setup_unavailable') from None
            if not isinstance(encrypted, bytes) or not encrypted:
                raise OSError('encrypted_setup_unavailable')
            # No plaintext temporary file or overwrite of an existing setup.
            with self.output.open('xb') as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            self.saved = True


def create_setup(state, *, port=8924):
    if not isinstance(state, SetupState) or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('explicit_loopback_setup_required')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    local_origin = f'http://localhost:{port}'

    @app.middleware('http')
    async def boundary(request, call_next):
        headers = request.scope.get('headers', [])
        hosts = [value for name, value in headers if name.lower() == b'host']
        origins = [value for name, value in headers if name.lower() == b'origin']
        csrf = [value for name, value in headers if name.lower() == b'x-setup-nonce']
        try:
            local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if (not local or hosts != [f'localhost:{port}'.encode('ascii')]
                or len(origins) > 1 or (origins and origins != [local_origin.encode('ascii')])
                or (request.method == 'POST' and (origins != [local_origin.encode('ascii')]
                    or csrf != [state.csrf.encode('ascii')]))):
            return JSONResponse({'detail': '只可在本機設定頁操作。'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer-when-downgrade',
            'Cross-Origin-Opener-Policy': 'same-origin-allow-popups',
            'Content-Security-Policy': "default-src 'none'; script-src 'self' https://accounts.google.com/gsi/client; "
                "style-src 'unsafe-inline' https://accounts.google.com/gsi/style; "
                "frame-src https://accounts.google.com/gsi/; connect-src 'self' https://accounts.google.com/gsi/; "
                "img-src 'self' data: https://*.googleusercontent.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    async def body(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise ValueError('json_required')
        raw = bytearray()
        async for part in request.stream():
            if len(raw) + len(part) > 18000:
                raise ValueError('setup_request_too_large')
            raw.extend(part)
        return json.loads(raw, object_pairs_hook=unique_object)

    @app.get('/')
    async def page():
        return HTMLResponse((ASSETS / 'index.html').read_text(encoding='utf-8'))

    @app.get('/setup.js')
    async def script():
        return Response((ASSETS / 'setup.js').read_bytes(), media_type='text/javascript')

    @app.get('/setup')
    async def configuration():
        return JSONResponse({'csrf': state.csrf, 'origin': state.origin,
                             'local_origin': local_origin, 'saved': state.saved})

    @app.post('/configure')
    async def configure(request: Request):
        try:
            return JSONResponse(await state.configure(await body(request)))
        except FileExistsError:
            return JSONResponse({'detail': '設定已加密保存，沒有覆寫。'}, status_code=409)
        except (ValueError, UnicodeError):
            return JSONResponse({'detail': '請核對 Web Client ID 同允許登入嘅 Google 電郵。'}, status_code=400)

    @app.post('/enrol')
    async def enrol(request: Request):
        try:
            await state.enrol(await body(request))
            return JSONResponse({'status': 'saved'})
        except FileExistsError:
            return JSONResponse({'detail': '設定已加密保存，沒有覆寫。'}, status_code=409)
        except IdentityUnavailable:
            return JSONResponse({'detail': '暫時未能向 Google 核對身份，未保存設定。'}, status_code=503)
        except (ValueError, UnicodeError):
            return JSONResponse({'detail': '登入未通過核對，請用剛才指定嘅 Google 帳戶。'}, status_code=400)
        except OSError:
            return JSONResponse({'detail': '未能確認加密保存結果，請先保留現場。'}, status_code=503)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--port', type=int, default=8924)
    args = parser.parse_args()
    state = SetupState(args.output, args.origin)
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(create_setup(state, port=args.port),
        host='127.0.0.1', port=args.port, access_log=False, log_level='critical'))
    timer = threading.Timer(1800, lambda: setattr(server, 'should_exit', True))
    timer.daemon = True
    timer.start()
    try:
        print(f'local_google_setup http://localhost:{args.port} (30 minute lifetime)', flush=True)
        server.run()
    finally:
        timer.cancel()
        print('local_google_setup_saved' if state.saved else 'local_google_setup_not_saved', flush=True)


if __name__ == '__main__':
    main()
