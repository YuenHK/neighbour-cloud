"""First-party resident sessions and the user-selected shared management password.

Opaque tokens are random capabilities kept only in this process, never trusted
for their client-readable claims. Restart/expiry invalidates them; data and
quota authority remain in the durable stores. No Google account is needed.
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from deploy.cloud.google_identity import InvalidIdentity, Principal

PATH = '/api/v1/resident/access'


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


PREFIX = encoded(b'{"alg":"opaque","typ":"NEIGHBOUR"}') + '.'


def password_hash(password, *, rounds=310000):
    if not isinstance(password, str) or not 1 <= len(password) <= 128 or not 100000 <= rounds <= 1000000:
        raise ValueError('invalid_staff_password')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, rounds)
    return f'pbkdf2_sha256${rounds}${encoded(salt)}${encoded(digest)}'


class AccessInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    password: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator('password')
    @classmethod
    def valid_password(cls, value):
        if value is not None and ('\x00' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value)):
            raise ValueError('invalid_password_text')
        return value


class SiteSessions:
    def __init__(self, descriptor, *, clock=None):
        try:
            scheme, rounds, salt, digest = descriptor.split('$')
            self.rounds = int(rounds)
            self.salt = base64.urlsafe_b64decode(salt + '==')
            self.digest = base64.urlsafe_b64decode(digest + '==')
            if (scheme != 'pbkdf2_sha256' or not 100000 <= self.rounds <= 1000000
                    or len(self.salt) != 16 or len(self.digest) != 32):
                raise ValueError('invalid')
        except (ValueError, TypeError, AttributeError):
            raise ValueError('explicit_staff_password_hash_required') from None
        self.clock = clock or time.time
        self.lock = threading.RLock()
        self.entries = {}
        self.created, self.attempts = deque(), deque()
        self.closed = False

    @staticmethod
    def owns(token):
        return isinstance(token, str) and token.startswith(PREFIX)

    def _rate(self, queue, maximum):
        now = self.clock()
        while queue and queue[0] <= now - 60:
            queue.popleft()
        if self.closed:
            raise HTTPException(503, '服務正在重新連接。')
        if len(queue) >= maximum:
            raise HTTPException(429, '操作較頻密，請稍候再試。')
        queue.append(now)

    def _issue(self, role):
        now = self.clock()
        self.entries = {key: item for key, item in self.entries.items() if item[1] > now}
        if len(self.entries) >= 256:
            raise HTTPException(429, '目前服務較繁忙，請稍後再試。')
        expiry = int(now) + 3600
        subject = secrets.token_hex(16)
        body = encoded(json.dumps({'exp': expiry, 'sub': subject, 'role': role}, separators=(',', ':')).encode())
        token = PREFIX + body + '.' + secrets.token_urlsafe(32)
        self.entries[hashlib.sha256(token.encode()).digest()] = (Principal(subject, '', role), expiry)
        return {'token': token, 'expires_at_ms': expiry * 1000, 'role': role}

    def resident(self):
        with self.lock:
            self._rate(self.created, 60)
            return self._issue('resident')

    def login(self, password):
        with self.lock:
            self._rate(self.attempts, 5)
        provided = hashlib.pbkdf2_hmac('sha256', password.encode(), self.salt, self.rounds)
        if not hmac.compare_digest(provided, self.digest):
            raise HTTPException(401, '管理口令不正確。')
        with self.lock:
            return self._issue('staff')

    async def verify(self, token):
        if not self.owns(token) or not 32 <= len(token) <= 1024:
            raise InvalidIdentity('site_session_invalid')
        with self.lock:
            key = hashlib.sha256(token.encode()).digest()
            found = self.entries.get(key)
            if self.closed or found is None or found[1] <= self.clock():
                self.entries.pop(key, None)
                raise InvalidIdentity('site_session_expired')
            return found[0]

    def close(self):
        with self.lock:
            self.closed = True
            self.entries.clear()
