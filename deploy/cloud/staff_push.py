"""Opt-in, generic Web Push. Subscription capabilities are encrypted at rest.

Active-host delivery only; never pings Render to keep a Free instance awake.
Delivery is at least once (stable tag collapses duplicates), not guaranteed by OS.
"""
import base64
import hashlib
import hmac
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


def send_push(subscription, private_key, origin, notification_id, test=False):
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
                data=json.dumps({'type': 'staff-test' if test else 'staff-update',
                                 'notification_id': notification_id}),
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
            record = dict(old) if old is not None else {'cursor': self.latest(), 'next': 0, 'failures': 0}
            # Reconfirming an existing subscription must not skip pending work
            # or reset a persisted test cooldown after reload/network recovery.
            record.update(sealed=self.ops.seal('push-subscription', identity, subscription),
                          updated=self.clock())
            self.ops.put('push-subscription', identity, record)
        return identity

    def _send(self, identity, record, kind, version):
        key = self.keys()
        private = self.ops.open('push-config', 'vapid', key['sealed'])
        notification_id = hmac.new(private.encode(), f'{identity}:{kind}:{version}'.encode(),
                                   hashlib.sha256).hexdigest()
        return self.sender(self.ops.open('push-subscription', identity, record['sealed']),
                           private, self.origin, notification_id, kind == 'test')

    def subscription_status(self, identity):
        with self.lock:
            record = self.ops.get('push-subscription', identity)
            if record is None or self.clock() - record['updated'] > 90 * 86400:
                return {'registered': False}
            return {'registered': True,
                    'test_retry_after_seconds': max(0, int(record.get('test_next', 0) - self.clock() + .999)),
                    'last_test': record.get('test_result', 'not_tested'),
                    'device_delivery_confirmed': False}

    def test_subscription(self, identity):
        """User-triggered generic notification, without creating a case or moving its cursor."""
        with self.lock:
            record = self.ops.get('push-subscription', identity)
            if record is None or self.clock() - record['updated'] > 90 * 86400:
                return {'state': 'not_registered', 'accepted': False}
            now = self.clock()
            if now < record.get('test_next', 0):
                return {'state': 'cooldown', 'accepted': False,
                        'retry_after_seconds': max(1, int(record['test_next'] - now + .999))}
            # Durable reservation before network activity; an unknown response
            # must not cause repeated messages or an unbounded retry loop.
            record.update(test_next=now + 60, test_result='unknown')
            self.ops.put('push-subscription', identity, record)
            try:
                status = self._send(identity, record, 'test', now)
            except Exception:  # noqa: BLE001 -- no capabilities/exception text in response
                status = 503
            if status in (404, 410):
                self.ops.delete('push-subscription', identity)
                return {'state': 'expired', 'accepted': False}
            accepted = 200 <= status < 300
            record['test_result'] = 'push_service_accepted' if accepted else 'not_accepted'
            self.ops.put('push-subscription', identity, record)
            return {'state': record['test_result'], 'accepted': accepted,
                    'retry_after_seconds': 60, 'device_delivery_confirmed': False}

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
                try:
                    status = self._send(identity, record, 'work', latest)
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

    @router.get(PREFIX + '/{identity}/status')
    def status(identity: str):
        authorize()
        if not re.fullmatch('[a-f0-9]{64}', identity):
            raise HTTPException(422)
        return service.subscription_status(identity)

    @router.post(PREFIX + '/{identity}/test')
    def test(identity: str):
        authorize()
        if not re.fullmatch('[a-f0-9]{64}', identity):
            raise HTTPException(422)
        return service.test_subscription(identity)
    return router
