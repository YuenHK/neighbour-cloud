"""Opt-in, generic Web Push. Subscription capabilities are encrypted at rest.

Active-host delivery only; never pings Render to keep a Free instance awake.
Delivery is at least once (stable tag collapses duplicates), not guaranteed by OS.
"""
import base64
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException, Request

PREFIX = '/api/v1/service-desk/notifications'


def valid_subscription(value):
    if not isinstance(value, dict) or set(value) - {'endpoint', 'keys', 'expirationTime'}:
        raise ValueError('invalid_subscription')
    parsed = urlsplit(value.get('endpoint', ''))
    if (parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.fragment or not parsed.path or len(value['endpoint']) > 2048
            or not (parsed.hostname in ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com')
                    or re.fullmatch(r'[a-z0-9-]+\.notify\.windows\.com', parsed.hostname or ''))):
        raise ValueError('unsupported_push_endpoint')
    keys = value.get('keys', {})
    if set(keys) != {'auth', 'p256dh'}:
        raise ValueError('invalid_subscription')
    decoded = {}
    for key, length in (('auth', 16), ('p256dh', 65)):
        text = keys[key]
        if not isinstance(text, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}={0,2}', text):
            raise ValueError('invalid_subscription_key')
        decoded[key] = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
        if len(decoded[key]) != length:
            raise ValueError('invalid_subscription_key')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decoded['p256dh'])
    return {'endpoint': value['endpoint'], 'keys': keys}


def send_push(subscription, private_key, origin):
    import requests
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush

    class NoRedirect(requests.Session):
        def request(self, *args, **kwargs):
            kwargs['allow_redirects'] = False
            return super().request(*args, **kwargs)

    # Explicit fixed generic payload; no case ID, address, quotation or care label.
    with NoRedirect() as session:
        session.trust_env = False
        try:
            result = webpush(subscription_info=subscription,
                data=json.dumps({'type': 'staff-update', 'tag': 'neighbour-workbench'}),
                vapid_private_key=Vapid.from_pem(private_key.encode()), vapid_claims={'sub': origin},
                ttl=300, timeout=8, requests_session=session)
            return result.status_code
        except WebPushException as error:
            return error.response.status_code if error.response is not None else 503


class StaffPush:
    def __init__(self, ops, cases, origin, *, sender=send_push, clock=time.time):
        self.ops, self.cases, self.origin = ops, cases, origin
        self.sender, self.clock, self.lock = sender, clock, threading.Lock()
        self.next_subscription = 0

    def keys(self):
        record = self.ops.get('push-config', 'vapid')
        if record is None:
            key = ec.generate_private_key(ec.SECP256R1())
            private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
            public = base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962,
                      serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
            record = {'public': public, 'sealed': self.ops.seal('push-config', 'vapid', private)}
            self.ops.put('push-config', 'vapid', record)
        return record

    def latest(self):
        with self.cases.lock:
            return self.cases.db.execute('SELECT COALESCE(MAX(ordinal),0) FROM service_case_numbers').fetchone()[0]

    def subscribe(self, value):
        subscription = valid_subscription(value)
        identity = hashlib.sha256(subscription['endpoint'].encode()).hexdigest()
        with self.lock:
            old = self.ops.get('push-subscription', identity)
            if old is None and len(self.ops.items('push-subscription')) >= 32:
                raise ValueError('push_subscription_capacity')
            # New consent starts now; never notify about historical residents.
            record = {'sealed': self.ops.seal('push-subscription', identity, subscription),
                      'cursor': self.latest(), 'updated': self.clock(), 'next': 0, 'failures': 0}
            self.ops.put('push-subscription', identity, record)
        return identity

    def tick(self):
        with self.lock:
            subscriptions = self.ops.items('push-subscription')
            if not subscriptions:
                return
            latest, now = self.latest(), self.clock()
            start = self.next_subscription % len(subscriptions)
            selected = (subscriptions[start:] + subscriptions[:start])[:3]
            self.next_subscription += len(selected)
            for identity, record in selected:
                if now - record['updated'] > 90 * 86400:
                    self.ops.delete('push-subscription', identity)
                    continue
                if record['cursor'] >= latest or now < record['next']:
                    continue
                key = self.keys()
                try:
                    status = self.sender(self.ops.open('push-subscription', identity, record['sealed']),
                                         self.ops.open('push-config', 'vapid', key['sealed']), self.origin)
                except Exception:  # noqa: BLE001 -- capability/exception text must never enter logs
                    status = 503
                if status in (404, 410):
                    self.ops.delete('push-subscription', identity)
                    continue
                if 200 <= status < 300:
                    record.update(cursor=latest, failures=0, next=0)
                else:
                    record['failures'] += 1
                    record['next'] = now + min(3600, 30 * 2 ** min(record['failures'], 7))
                self.ops.put('push-subscription', identity, record)


def push_router(service, authorize):
    router = APIRouter()

    @router.get(PREFIX)
    def config():
        authorize()
        with service.lock:
            key = service.keys()
        return {'public_key': key['public'], 'private_content': False, 'delivery': 'active_host_best_effort'}

    @router.post(PREFIX)
    async def subscribe(request: Request):
        authorize()
        if len(await request.body()) > 5000:
            raise HTTPException(413)
        try:
            return {'subscription_id': service.subscribe(await request.json())}
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, '此瀏覽器推送服務未獲支援或訂閱無效。') from None

    @router.delete(PREFIX + '/{identity}')
    def unsubscribe(identity: str):
        authorize()
        if not re.fullmatch('[a-f0-9]{64}', identity):
            raise HTTPException(422)
        service.ops.delete('push-subscription', identity)
        return {'removed': True}
    return router
