"""Validate existing platform staff sessions, with no Google login or new key.

The onsite gateway asks the pinned cloud session endpoint to verify the Bearer
token. Only a short in-memory digest cache is kept; tokens are not persisted.
"""
import base64
import hashlib
import json
import time

import httpx


class PlatformStaff:
    def __init__(self, origin, *, clock=time.monotonic):
        self.origin, self.clock = origin, clock
        self.cache = {}

    async def accepts(self, authorization, client):
        if (not isinstance(authorization, str) or not authorization.startswith('Bearer ')
                or not 15 <= len(authorization) <= 16391 or any(ord(c) < 33 or ord(c) > 126 for c in authorization[7:])):
            return False
        key = hashlib.sha256(authorization.encode('ascii')).digest()
        now = self.clock()
        if self.cache.get(key, 0) > now:
            return True
        try:
            response = await client.get(self.origin + '/api/v1/resident/session',
                headers={'Authorization': authorization, 'Origin': self.origin}, timeout=5)
            data = response.json() if response.status_code == 200 else {}
            allowed = (data.get('authenticated') is True and data.get('role') == 'staff'
                       and data.get('storage_acceptance') is False)
        except (httpx.HTTPError, ValueError, TypeError):
            allowed = False
        self.cache = {item: expiry for item, expiry in self.cache.items() if expiry > now}
        if allowed:
            if len(self.cache) >= 32:
                self.cache.pop(next(iter(self.cache)))
            try:
                payload = authorization[7:].split('.')[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
                ttl = min(10, max(0, claims['exp'] - time.time()))
            except (ValueError, KeyError, IndexError, TypeError):
                ttl = 0  # Unexpected tokens are never cached.
            self.cache[key] = now + ttl
        return allowed
