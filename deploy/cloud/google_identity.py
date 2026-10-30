"""Google-signed bearer ID-token verifier for the unactivated cloud candidate.

Subjects/roles and OAuth audience must be provisioned explicitly. No enrolment,
login UI, cookies, tokeninfo calls or client-supplied role/email authorization.
Only Google's fixed public JWKS URL is contacted; no resident data is sent.
"""
import asyncio
import json
import re
import time
from dataclasses import dataclass
from types import MappingProxyType

import httpx

JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
ISSUERS = ('https://accounts.google.com', 'accounts.google.com')


class InvalidIdentity(ValueError):
    pass


class IdentityUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str
    role: str


class GoogleIdentityVerifier:
    def __init__(self, client_id, accounts, *, client=None, clock=None):
        if (not isinstance(client_id, str) or len(client_id) > 256
                or not re.fullmatch(r'[0-9]+(?:-[A-Za-z0-9_-]+)?\.apps\.googleusercontent\.com', client_id)
                or not isinstance(accounts, dict) or not 1 <= len(accounts) <= 100
                or any(not isinstance(sub, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', sub)
                       or role not in ('staff', 'resident') for sub, role in accounts.items())
                or (clock is not None and not callable(clock))):
            raise ValueError('explicit_google_audience_and_pinned_accounts_required')
        import jwt
        self.jwt = jwt
        self.client_id, self.accounts = client_id, MappingProxyType(dict(accounts))
        self._client, self._owned = client, client is None
        self.clock = clock or time.monotonic
        self._keys, self._expires, self._next_refresh = {}, 0, 0
        self._lock, self._closed = asyncio.Lock(), False

    async def _key(self, kid):
        if self._closed:
            raise IdentityUnavailable('identity_verifier_closed')
        if kid in self._keys and self.clock() < self._expires:
            return self._keys[kid]
        async with self._lock:
            now = self.clock()
            if kid in self._keys and now < self._expires:
                return self._keys[kid]
            if now < self._next_refresh:
                if now < self._expires:
                    raise InvalidIdentity('identity_not_accepted')
                raise IdentityUnavailable('identity_keys_unavailable')
            self._next_refresh = now + 30  # Bound unknown-kid and outage traffic.
            try:
                if self._client is None:
                    self._client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
                async with asyncio.timeout(5), self._client.stream('GET', JWKS_URL, timeout=3,
                        follow_redirects=False, headers={'Accept': 'application/json'}) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(chunk) > 65536 - len(raw):
                            raise ValueError('oversized_keys')
                        raw.extend(chunk)
                    document = json.loads(raw)
                    values = document['keys']
                    if not isinstance(values, list) or not 1 <= len(values) <= 10:
                        raise ValueError('invalid_keys')
                    keys = {}
                    for value in values:
                        identifier = value.get('kid')
                        if (not isinstance(identifier, str) or not re.fullmatch('[A-Za-z0-9_-]{1,180}', identifier)
                                or identifier in keys or value.get('kty') != 'RSA'
                                or value.get('alg', 'RS256') != 'RS256' or value.get('use', 'sig') != 'sig'
                                or any(field in value for field in ('d', 'p', 'q', 'dp', 'dq', 'qi'))):
                            raise ValueError('invalid_keys')
                        key = self.jwt.PyJWK.from_dict(value, algorithm='RS256').key
                        if not 2048 <= key.key_size <= 8192:
                            raise ValueError('invalid_key_size')
                        keys[identifier] = key
                    control = response.headers.get('cache-control', '').lower()
                    found = re.search(r'(?:^|,)\s*max-age=(\d+)', control)
                    ttl = min(3600, int(found[1])) if found else 300
                    if 'no-store' in control or 'no-cache' in control:
                        ttl = 0
                    self._keys, self._expires = keys, self.clock() + ttl
            except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, AttributeError,
                    self.jwt.PyJWTError):
                raise IdentityUnavailable('identity_keys_unavailable') from None
            if kid not in self._keys:
                raise InvalidIdentity('identity_not_accepted')
            return self._keys[kid]

    async def verify(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 16384 or not token.isascii():
            raise InvalidIdentity('identity_not_accepted')
        try:
            header = self.jwt.get_unverified_header(token)
            kid = header.get('kid')
            if (header.get('alg') != 'RS256' or header.get('typ', 'JWT') != 'JWT'
                    or set(header).intersection(('jku', 'jwk', 'x5u', 'crit', 'b64'))
                    or not isinstance(kid, str) or not re.fullmatch('[A-Za-z0-9_-]{1,180}', kid)):
                raise InvalidIdentity('identity_not_accepted')
            key = await self._key(kid)
            claims = self.jwt.decode(token, key, algorithms=['RS256'], audience=self.client_id,
                issuer=ISSUERS, leeway=30, options={'strict_aud': True,
                    'require': ['iss', 'aud', 'sub', 'iat', 'exp', 'email', 'email_verified']})
            subject, email = claims['sub'], claims['email']
            if (type(claims['iat']) is not int or type(claims['exp']) is not int
                    or not 0 < claims['exp'] - claims['iat'] <= 3700
                    or claims.get('azp', self.client_id) != self.client_id
                    or not (claims['email_verified'] is True or claims['email_verified'] == 'true')
                    or subject not in self.accounts or not isinstance(email, str) or len(email) > 254
                    or not email.isascii() or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)):
                raise InvalidIdentity('identity_not_accepted')
            return Principal(subject, email, self.accounts[subject])
        except (self.jwt.PyJWTError, KeyError, TypeError, ValueError):
            raise InvalidIdentity('identity_not_accepted') from None

    async def aclose(self):
        self._closed = True
        if self._owned and self._client is not None:
            await self._client.aclose()
