import asyncio
import json
import os

import httpx
import pytest
import test_cloud_google_identity
from fastapi.testclient import TestClient

from deploy.cloud.google_identity import GoogleIdentityVerifier, InvalidIdentity
from deploy.cloud.login_setup import SetupState, create_setup

keys = test_cloud_google_identity.keys
CLIENT = test_cloud_google_identity.CLIENT
ORIGIN = 'https://neighbour.example'
LOCAL = 'http://localhost:8924'


def make(tmp_path, keys, *, encryptor=None):
    encrypted, clients = [], []

    def factory(client_id, accounts):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={'keys': [keys[1]]}, headers={'cache-control': 'max-age=300'})))
        clients.append(client)
        verifier = GoogleIdentityVerifier(client_id, accounts, client=client)
        verifier._owned = True
        return verifier

    def encrypt(data):
        encrypted.append(data)
        return b'SYNTHETIC-ENCRYPTED-METADATA'

    state = SetupState((tmp_path / 'login.dpapi').absolute(), ORIGIN,
                       encryptor=encryptor or encrypt, verifier_factory=factory)
    return state, encrypted, clients


def jwt(keys, state, **changes):
    return test_cloud_google_identity.token(keys, nonce=state.nonce, **changes)


def test_signature_nonce_and_human_selected_email_required_before_metadata_only_save(tmp_path, keys):
    state, encrypted, clients = make(tmp_path, keys)

    async def run():
        await state.configure({'client_id': CLIENT, 'email': 'staff@example.test'})
        credential = jwt(keys, state)
        await state.enrol({'credential': credential})
        record = json.loads(encrypted[0])
        assert record['accounts'] == {'staff-subject': 'staff'}
        assert record['google_client_id'] == CLIENT and record['origin'] == ORIGIN
        assert credential.encode() not in encrypted[0]
        assert state.saved and state.output.read_bytes() == b'SYNTHETIC-ENCRYPTED-METADATA'
        assert clients[0].is_closed
        with pytest.raises(FileExistsError):
            await state.enrol({'credential': credential})
        with pytest.raises(FileExistsError):
            await state.configure({'client_id': CLIENT, 'email': 'other@example.test'})
        assert list(tmp_path.iterdir()) == [state.output]
    asyncio.run(run())


@pytest.mark.parametrize('changes', [{'email': 'different@example.test'}, {'email_verified': False},
    {'aud': 'other-client'}, {'iss': 'https://attacker.invalid'}, {'nonce': 'previous-page-nonce'},
    {'nonce': None}])
def test_wrong_account_nonce_signature_or_audience_never_saves(tmp_path, keys, changes):
    state, encrypted, clients = make(tmp_path, keys)

    async def run():
        await state.configure({'client_id': CLIENT, 'email': 'staff@example.test'})
        claims = {'nonce': state.nonce, **changes}
        credential = test_cloud_google_identity.token(keys, **claims)
        with pytest.raises(InvalidIdentity):
            await state.enrol({'credential': credential})
        assert not state.output.exists() and not state.saved and encrypted == []
        assert all(client.is_closed for client in clients)
    asyncio.run(run())


def test_unverified_subject_hint_cannot_authorize_unsigned_token(tmp_path, keys):
    import jwt as library

    state, encrypted, _ = make(tmp_path, keys)

    async def run():
        await state.configure({'client_id': CLIENT, 'email': 'staff@example.test'})
        claims = library.decode(jwt(keys, state), options={'verify_signature': False})
        credential = library.encode(claims, '', algorithm='none', headers={'kid': 'synthetic-1'})
        with pytest.raises(InvalidIdentity):
            await state.enrol({'credential': credential})
        assert not state.output.exists() and encrypted == []
    asyncio.run(run())


def test_configuration_generation_rejects_old_callback(tmp_path, keys):
    state, encrypted, _ = make(tmp_path, keys)

    async def run():
        first = await state.configure({'client_id': CLIENT, 'email': 'staff@example.test'})
        old = jwt(keys, state)
        second = await state.configure({'client_id': CLIENT, 'email': 'staff@example.test'})
        assert first['nonce'] != second['nonce']
        with pytest.raises(InvalidIdentity):
            await state.enrol({'credential': old})
        assert encrypted == []
    asyncio.run(run())


def test_loopback_host_origin_nonce_body_limits_and_no_raw_error_output(tmp_path, keys):
    state, _, _ = make(tmp_path, keys)
    with TestClient(create_setup(state), base_url=LOCAL, client=('127.0.0.1', 54321)) as client:
        page = client.get('/')
        assert page.status_code == 200 and 'Client secret' in page.text
        assert page.headers['cache-control'] == 'no-store'
        csrf = client.get('/setup').json()['csrf']
        payload = {'client_id': CLIENT, 'email': 'staff@example.test'}
        headers = {'Origin': LOCAL, 'X-Setup-Nonce': csrf}
        assert client.post('/configure', json=payload).status_code == 403
        assert client.post('/configure', json=payload, headers={**headers, 'Origin': 'https://attacker.invalid'}).status_code == 403
        assert client.post('/configure', json=payload, headers={**headers, 'Host': 'attacker.invalid'}).status_code == 403
        assert client.post('/configure', json=payload, headers=headers).status_code == 200
        for value in ['PRIVATE-INVALID-TOKEN', 'X' * 20000]:
            response = client.post('/enrol', json={'credential': value}, headers=headers)
            assert response.status_code == 400 and value not in response.text
        response = client.post('/configure', content='{"client_id":"x","client_id":"y"}',
                              headers={**headers, 'Content-Type': 'application/json'})
        assert response.status_code == 400
        assert client.get('/setup.js').status_code == 200
        assert client.get('/settings.json').status_code == 404
        assert client.post('/enrol', json={'credential': jwt(keys, state)}, headers=headers).json() == {'status': 'saved'}
        assert client.get('/setup').json()['saved'] is True
    assert state.saved


def test_network_origin_is_rejected_before_configuration_or_credential_read(tmp_path, keys):
    state, _, _ = make(tmp_path, keys)
    with TestClient(create_setup(state), base_url=LOCAL, client=('192.0.2.1', 54321)) as client:
        assert client.get('/setup').status_code == 403
    assert state.client_id is None


def test_encryption_failure_does_not_write_plaintext_or_echo_token(tmp_path, keys):
    def encrypt(_data):
        raise RuntimeError('PRIVATE-ENCRYPTION-ERROR')
    state, _, _ = make(tmp_path, keys, encryptor=encrypt)
    with TestClient(create_setup(state), base_url=LOCAL, client=('127.0.0.1', 54321)) as client:
        headers = {'Origin': LOCAL, 'X-Setup-Nonce': state.csrf}
        client.post('/configure', json={'client_id': CLIENT, 'email': 'staff@example.test'}, headers=headers)
        response = client.post('/enrol', json={'credential': jwt(keys, state)}, headers=headers)
        assert response.status_code == 503 and 'PRIVATE' not in response.text
    assert not state.output.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Actual CurrentUser DPAPI requires Windows')
def test_actual_dpapi_roundtrip_contains_only_verified_metadata(tmp_path, keys):
    from edge_hub.cloud_credentials import _crypt

    state, _, clients = make(tmp_path, keys, encryptor=lambda data: _crypt(data, decrypt=False))

    async def run():
        await state.configure({'client_id': CLIENT, 'email': 'staff@example.test'})
        credential = jwt(keys, state)
        await state.enrol({'credential': credential})
        blob = state.output.read_bytes()
        assert b'staff@example.test' not in blob and credential.encode() not in blob
        record = json.loads(_crypt(blob, decrypt=True))
        assert record['accounts'] == {'staff-subject': 'staff'}
        assert all(client.is_closed for client in clients)
    asyncio.run(run())
