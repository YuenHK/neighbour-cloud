import asyncio
import json
import time

import httpx
import pytest

jwt = pytest.importorskip('jwt', reason='optional cloud authentication research dependency')
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENT = '123456789-synthetic.apps.googleusercontent.com'


@pytest.fixture(scope='module')
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    return private, {**public, 'kid': 'synthetic-1', 'use': 'sig', 'alg': 'RS256'}


def token(keys, **changes):
    now = int(time.time())
    claims = {'iss': 'https://accounts.google.com', 'aud': CLIENT, 'sub': 'staff-subject',
              'email': 'staff@example.test', 'email_verified': True, 'iat': now - 1, 'exp': now + 3500}
    claims.update(changes)
    return jwt.encode(claims, keys[0], algorithm='RS256', headers={'kid': keys[1]['kid']})


def test_google_signature_and_pinned_subject_determine_role_not_token_role_claim(keys):
    from deploy.cloud.google_identity import GoogleIdentityVerifier

    async def run():
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={'keys': [keys[1]]}, headers={'cache-control': 'max-age=300'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            verifier = GoogleIdentityVerifier(CLIENT, {'staff-subject': 'staff', 'resident-subject': 'resident'}, client=client)
            staff = await verifier.verify(token(keys))
            resident = await verifier.verify(token(keys, sub='resident-subject', roles=['staff']))
            assert staff.subject == 'staff-subject' and staff.role == 'staff'
            assert resident.role == 'resident'
            assert len(calls) == 1 and calls[0].url.host == 'www.googleapis.com'
    asyncio.run(run())


@pytest.mark.parametrize('changes', [
    {'aud': 'other-client'}, {'iss': 'https://attacker.invalid'}, {'sub': 'unapproved-subject'},
    {'email_verified': False}, {'exp': int(time.time()) - 100}, {'iat': int(time.time()) + 100},
    {'azp': 'other-client'}, {'exp': int(time.time()) + 100000}])
def test_invalid_or_unapproved_identity_is_rejected(keys, changes):
    from deploy.cloud.google_identity import GoogleIdentityVerifier, InvalidIdentity

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
                json={'keys': [keys[1]]}, headers={'cache-control': 'max-age=300'}))) as client:
            verifier = GoogleIdentityVerifier(CLIENT, {'staff-subject': 'staff'}, client=client)
            with pytest.raises(InvalidIdentity):
                await verifier.verify(token(keys, **changes))
    asyncio.run(run())


def test_algorithm_or_key_url_headers_cannot_trigger_lookup(keys):
    from deploy.cloud.google_identity import GoogleIdentityVerifier, InvalidIdentity

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail('no network lookup'))) as client:
            verifier = GoogleIdentityVerifier(CLIENT, {'staff-subject': 'staff'}, client=client)
            claims = jwt.decode(token(keys), options={'verify_signature': False})
            bad = [jwt.encode(claims, 'synthetic-test-secret-at-least-32-characters', algorithm='HS256', headers={'kid': 'synthetic-1'}),
                   jwt.encode(claims, '', algorithm='none', headers={'kid': 'synthetic-1'}),
                   jwt.encode(claims, keys[0], algorithm='RS256', headers={'kid': 'synthetic-1', 'jku': 'https://attacker.invalid/keys'}),
                   'x' * 16385]
            for value in bad:
                with pytest.raises(InvalidIdentity):
                    await verifier.verify(value)
    asyncio.run(run())


def test_jwks_cache_coalesces_and_expired_outage_fails_closed_without_retry_storm(keys):
    from deploy.cloud.google_identity import (
        GoogleIdentityVerifier,
        IdentityUnavailable,
        InvalidIdentity,
    )

    async def run():
        stamp, calls = [1000], []
        async def respond(request):
            calls.append(request)
            await asyncio.sleep(0)
            return (httpx.Response(200, json={'keys': [keys[1]]}, headers={'cache-control': 'max-age=300'})
                    if len(calls) == 1 else httpx.Response(503, text='PRIVATE-UPSTREAM-DETAIL'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            verifier = GoogleIdentityVerifier(CLIENT, {'staff-subject': 'staff'}, client=client, clock=lambda: stamp[0])
            values = await asyncio.gather(*(verifier.verify(token(keys)) for _ in range(8)))
            assert all(value.role == 'staff' for value in values) and len(calls) == 1
            claims = jwt.decode(token(keys), options={'verify_signature': False})
            unknown = jwt.encode(claims, keys[0], algorithm='RS256', headers={'kid': 'unknown'})
            with pytest.raises(InvalidIdentity):
                await verifier.verify(unknown)
            assert len(calls) == 1
            stamp[0] += 301
            for _ in range(4):
                with pytest.raises(IdentityUnavailable) as error:
                    await verifier.verify(token(keys))
                assert 'PRIVATE' not in str(error.value)
            assert len(calls) == 2
    asyncio.run(run())


@pytest.mark.parametrize('response', [httpx.Response(302, headers={'location': 'https://attacker.invalid'}),
    httpx.Response(200, content=b'x' * 65537), httpx.Response(200, json={'keys': []}),
    httpx.Response(200, json={'keys': [{'kid': 'x', 'kty': 'oct', 'k': 'x'}]})])
def test_unusable_google_keys_never_accept_identity(keys, response):
    from deploy.cloud.google_identity import GoogleIdentityVerifier, IdentityUnavailable

    async def run():
        calls = []
        def respond(request):
            calls.append(request)
            return response
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            verifier = GoogleIdentityVerifier(CLIENT, {'staff-subject': 'staff'}, client=client)
            with pytest.raises(IdentityUnavailable):
                await verifier.verify(token(keys))
        assert len(calls) == 1 and calls[0].url.host == 'www.googleapis.com'
    asyncio.run(run())
