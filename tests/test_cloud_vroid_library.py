import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest
import test_cloud_bootstrap
import test_cloud_google_identity
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deploy.cloud.operations import Operations, migrate
from deploy.cloud.vroid_api import VroidUnavailable
from deploy.cloud.vroid_library import ConnectionInput, Library, library_router, reviewed_rows

NOW = 1793692800000
prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
keys = test_cloud_google_identity.keys


def bundle(**changes):
    return ConnectionInput(application_id=1745,owner_id='5115084',client_id='synthetic-client-1234',
        client_secret='synthetic-client-secret',access_token='synthetic-access-token',
        refresh_token='synthetic-refresh-token',expires_at_ms=NOW+3600000,**changes)


class Client:
    def __init__(self):
        self.calls=[]
        self.wait=None
        self.error=None

    async def request(self,method,path,**kwargs):
        self.calls.append((method,path))
        return {'data':{'user_detail':{'user':{'id':'5115084'}}}}

    async def refresh(self,*args):
        self.calls.append(('POST','/oauth/token'))
        if self.wait:
            await self.wait.wait()
        if self.error:
            raise self.error
        return {'access_token':'synthetic-rotated-access','refresh_token':'synthetic-rotated-refresh',
            'expires_in':3600,'token_type':'Bearer'}

    async def download_model(self,token,identity):
        self.calls.append(('download',identity))
        if self.error:
            raise self.error
        return b'original-synthetic-resource',{'id':identity,'latest_character_model_version':{'id':'222'}}

    async def list_models(self,token,**kwargs):
        assert kwargs.get('sort')=='first_published_at'
        self.calls.append(('GET','/api/search/character_models'))
        if self.error:
            raise self.error
        return {'data':[]}


@pytest.fixture
def system():
    db=sqlite3.connect(':memory:',check_same_thread=False)
    migrate(db)
    ops=Operations(db,b'v'*32)
    client=Client()
    library=Library(ops,lambda:client,reviewed={},now=lambda:NOW)
    yield library,ops,client,db
    db.close()


def test_connect_is_explicit_encrypted_and_catalogue_never_calls_provider(system):
    async def run():
        lib,_ops,client,db=system
        assert (await lib.catalog())['items']==[] and client.calls==[]
        result=await lib.enroll(bundle())
        assert result['connected'] and result['credentials_visible'] is False
        raw=db.execute('SELECT payload FROM cloud_operations').fetchone()[0]
        assert 'synthetic' not in raw and 'client_secret' not in raw
        assert lib.connection()['access_token']=='synthetic-access-token'
        assert client.calls==[('GET','/api/account')]
        assert (await lib.catalog())['connected']
        assert client.calls==[('GET','/api/account')]
        with pytest.raises(VroidUnavailable,match='already_enrolled'):
            await lib.enroll(bundle())
        assert len(client.calls)==1
        await lib.close()
    asyncio.run(run())


def test_bundle_repr_never_leaks_credentials():
    assert 'synthetic' not in repr(bundle())
    with pytest.raises(ValueError):
        ConnectionInput(**{**bundle().model_dump(),'extra_key':'secret'})


def test_expired_bundle_or_other_owner_never_reaches_provider(system):
    async def run():
        lib,_,client,_=system
        for change in ({'expires_at_ms':NOW},{'owner_id':'123'},{'application_id':999},
                       {'client_secret':'unsafe secret value'}):
            value=ConnectionInput(**{**bundle().model_dump(),**change})
            with pytest.raises(VroidUnavailable,match='not_accepted'):
                await lib.enroll(value)
        assert client.calls==[]
    asyncio.run(run())


def test_refresh_singleflight_survives_caller_cancel_and_persists_rotation(system):
    async def run():
        lib,_,client,_=system
        await lib.enroll(bundle())
        value=lib.connection();value['expires_at_ms']=NOW+1000;lib.write_connection(value)
        client.wait=asyncio.Event()
        first=asyncio.create_task(lib.owned(lib.access))
        while not client.calls or client.calls[-1]!=('POST','/oauth/token'):
            await asyncio.sleep(.001)
        assert lib.connection()['status']=='refreshing'
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(VroidUnavailable,match='busy'):
            await lib.owned(lib.access)
        client.wait.set()
        await lib.close()
        value=lib.connection()
        assert value['status']=='ready' and value['refresh_token']=='synthetic-rotated-refresh'
        assert client.calls.count(('POST','/oauth/token'))==1
    asyncio.run(run())


def test_unknown_refresh_ack_survives_restart_and_never_retries(system):
    async def run():
        lib,ops,client,_=system
        await lib.enroll(bundle())
        value=lib.connection();value['expires_at_ms']=NOW+1000;lib.write_connection(value)
        client.error=VroidUnavailable('request_unavailable')
        with pytest.raises(VroidUnavailable):
            await lib.owned(lib.access)
        other=Library(ops,lambda:client,reviewed={},now=lambda:NOW)
        with pytest.raises(VroidUnavailable,match='requires_review'):
            await other.owned(other.access)
        assert client.calls.count(('POST','/oauth/token'))==1
        assert lib.connection()['status']=='refreshing'
    asyncio.run(run())


def test_rotation_intent_failure_prevents_network(system,monkeypatch):
    async def run():
        lib,_,client,_=system
        await lib.enroll(bundle())
        value=lib.connection();value['expires_at_ms']=NOW+1000;lib.write_connection(value)
        def fail(_value):
            raise sqlite3.OperationalError('synthetic DB offline')
        monkeypatch.setattr(lib,'write_connection',fail)
        with pytest.raises(sqlite3.OperationalError):
            await lib.owned(lib.access)
        assert client.calls==[('GET','/api/account')]
    asyncio.run(run())


def test_model_version_or_hash_change_blocks_preview(system,monkeypatch):
    async def run():
        lib,_,client,_=system
        await lib.enroll(bundle())
        row={'id':'123','version':'222','bytes':len(b'original-synthetic-resource'),
            'sha256':hashlib.sha256(b'original-synthetic-resource').hexdigest()}
        lib.reviewed={'123':row}
        monkeypatch.setattr('deploy.cloud.vroid_library.shared_candidate',lambda _model:True)
        monkeypatch.setattr('deploy.cloud.vroid_library.validate_vrm',lambda _value:'model.vrm')
        content,actual=await lib.download('123')
        assert actual==row and content==b'original-synthetic-resource'
        row['version']='changed'
        with pytest.raises(VroidUnavailable,match='changed_requires_review'):
            await lib.download('123')
        row['version']='222';row['sha256']='0'*64
        with pytest.raises(VroidUnavailable,match='changed_requires_review'):
            await lib.download('123')
        with pytest.raises(VroidUnavailable,match='not_reviewed'):
            await lib.download('456')
        assert all(path!='/api/photos' for _,path in client.calls)
    asyncio.run(run())


def test_limit_is_durable_and_does_not_retry_or_affect_other_services(system):
    async def run():
        lib,ops,client,_=system
        await lib.enroll(bundle())
        lib.reviewed={'123':{}}
        # Empty entry intentionally is not reviewable, so use a truthy stub.
        lib.reviewed['123']={'id':'123'}
        client.error=VroidUnavailable('rate_limited')
        with pytest.raises(VroidUnavailable,match='rate_limited'):
            await lib.download('123')
        other=Library(ops,lambda:client,reviewed=lib.reviewed,now=lambda:NOW)
        with pytest.raises(VroidUnavailable,match='rate_limited'):
            await other.download('123')
        assert client.calls.count(('download','123'))==1
        assert ops.count('vroid_library')==1
        assert ops.count('quota')==0
    asyncio.run(run())


def test_resident_cannot_access_catalog_or_preview_or_enroll(system):
    async def run():
        lib,_,client,_=system
        def deny():
            raise HTTPException(403)
        app=FastAPI();app.include_router(library_router(deny,lib))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://isolated.test') as http:
            for method,path,body in [('GET','/models',None),('POST','/models/123/preview',None),
                                      ('POST','/connection',bundle().model_dump())]:
                response=await http.request(method,'/api/v1/service-desk/vroid'+path,json=body)
                assert response.status_code==403
        assert client.calls==[]
    asyncio.run(run())


def test_static_review_requires_native_proof_and_content_uniqueness(tmp_path):
    row={'id':'123','version':'222','bytes':10000,'sha256':'a'*64,'native_render_verified':True,'visual_reviewed':True,
        'name':'Synthetic','author':'Synthetic','source':'https://hub.vroid.com/en/characters/456/models/123','terms':'Read credit'}
    path=tmp_path/'reviewed.json'
    def write(rows):
        path.write_text(json.dumps({'format':'neighbour-vroid-reviewed-v1','models':rows}))
    write([row]);assert reviewed_rows(path)=={'123':row}
    for rows in ([{**row,'native_render_verified':False}],[{**row,'visual_reviewed':False}],[row,{**row,'id':'124'}],
                 [{**row,'source':'https://evil.test/model'}]):
        write(rows)
        with pytest.raises(ValueError):
            reviewed_rows(path)


def test_resident_credit_is_public_metadata_only_even_without_connected_credentials(system):
    lib,_,client,_=system
    lib.by_digest={'a'*64:{'name':'Synthetic','author':'Creator','source':'https://hub.vroid.com/en/characters/1/models/2',
                          'private_field':'never include','sha256':'a'*64}}
    assert lib.credit('cloud-vrm-'+'a'*64)=={'name':'Synthetic','author':'Creator',
        'source':'https://hub.vroid.com/en/characters/1/models/2'}
    assert lib.credit('preset-live2d-2') is None and lib.credit('cloud-vrm-'+'b'*64) is None
    assert client.calls==[]


def test_staff_entry_discovery_coalesces_across_restart_and_never_admits_unreviewed_files(system):
    async def run():
        lib,ops,client,_=system
        assert lib.schedule_refresh()
        await asyncio.gather(*list(lib.pending))
        assert client.calls==[]
        await lib.enroll(bundle())
        assert lib.schedule_refresh() and lib.schedule_refresh() is False
        await asyncio.gather(*list(lib.pending))
        assert client.calls.count(('GET','/api/search/character_models'))==1
        reopened=Library(ops,lambda:client,reviewed={},now=lambda:NOW)
        assert reopened.schedule_refresh()
        await reopened.close()
        assert client.calls.count(('GET','/api/search/character_models'))==1
        assert (await lib.catalog())['items']==[]
        assert (await lib.catalog())['discovery']['error']==''
    asyncio.run(run())


def test_background_visits_do_not_extend_existing_provider_cooldown(system):
    async def run():
        lib,_,client,_=system
        await lib.enroll(bundle())
        client.error=VroidUnavailable('rate_limited')
        assert lib.schedule_refresh()
        await asyncio.gather(*list(lib.pending))
        expiry=lib.connection()['cooldown_until_ms']
        lib.now=lambda:NOW+120000
        assert lib.schedule_refresh()
        await asyncio.gather(*list(lib.pending))
        assert lib.connection()['cooldown_until_ms']==expiry
        assert client.calls.count(('GET','/api/search/character_models'))==1
    asyncio.run(run())


def test_full_cloud_boundary_auth_origin_validation_and_audit_never_leak_credentials(seeded,keys):
    import time

    from deploy.cloud.bootstrap import open_services
    from deploy.cloud.google_identity import GoogleIdentityVerifier
    from deploy.cloud.http_app import create_app

    origin='https://neighbour.example'
    services=open_services(seeded[0],signing_key_loader=lambda:test_cloud_bootstrap.KEY)
    db=seeded[0].connect(str(services.estate.path),check_same_thread=False)
    migrate(db);ops=Operations(db,test_cloud_bootstrap.KEY)
    identity=httpx.AsyncClient(transport=httpx.MockTransport(lambda _request:httpx.Response(200,
        json={'keys':[keys[1]]},headers={'cache-control':'max-age=300'})))
    verifier=GoogleIdentityVerifier(test_cloud_google_identity.CLIENT,
        {'staff-subject':'staff','resident-subject':'resident'},client=identity)
    provider=Client()
    app=create_app(services,verifier,origin=origin,operations=ops,vroid_client=provider)
    staff={'Origin':origin,'Authorization':'Bearer '+test_cloud_google_identity.token(keys)}
    resident={'Origin':origin,'Authorization':'Bearer '+test_cloud_google_identity.token(keys,sub='resident-subject')}
    data={**bundle().model_dump(),'expires_at_ms':int(time.time()*1000)+3600000}
    path='/api/v1/service-desk/vroid/connection'
    try:
        with TestClient(app,base_url=origin) as browser:
            assert browser.post(path,headers={'Origin':origin},json=data).status_code==401
            assert browser.post(path,headers=resident,json=data).status_code==403
            assert provider.calls==[]
            invalid=browser.post(path,headers=staff,json={**data,'client_secret':'TOO-SHORT'})
            assert invalid.status_code==422 and 'TOO-SHORT' not in invalid.text
            assert browser.post(path,headers={**staff,'Origin':'https://evil.test'},json=data).status_code==403
            reply=browser.post(path,headers=staff,json=data)
            assert reply.status_code==200 and 'synthetic' not in reply.text
            read=browser.get('/api/v1/service-desk/vroid/models',headers=staff)
            assert read.status_code==200 and read.json()['connected'] and 'synthetic' not in read.text
            assert browser.get('/api/v1/service-desk/vroid/models',headers=resident).status_code==403
            journal=services.journal.recent(100)
            assert 'synthetic-client-secret' not in json.dumps(journal)
            assert any(row['route']==path for row in journal)
    finally:
        db.close();services.close();asyncio.run(identity.aclose())
