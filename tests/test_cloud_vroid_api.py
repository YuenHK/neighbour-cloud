import asyncio
import base64
import copy
import hashlib
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from deploy.cloud.vroid_api import (
    Authorization,
    VroidClient,
    VroidUnavailable,
    catalogue_models,
    official_storage,
    shared_candidate,
)


def authorization():
    return Authorization('synthetic-client-1234', 'http://localhost:8925/callback')


def test_pkce_and_independent_short_lived_one_shot_state():
    first, other = authorization(), authorization()
    query = parse_qs(urlsplit(first.url()).query)
    expected = base64.urlsafe_b64encode(hashlib.sha256(first.verifier.encode()).digest()).rstrip(b'=').decode()
    assert query['code_challenge'] == [expected] and query['code_challenge_method'] == ['S256']
    assert query['scope'] == ['default'] and first.state != other.state and first.verifier != other.verifier
    assert first.client_id not in repr(first) and first.verifier not in repr(first)
    assert first.consume(urlencode({'state': first.state, 'code': 'synthetic-code'})) == 'synthetic-code'
    with pytest.raises(ValueError):
        first.consume(urlencode({'state': first.state, 'code': 'synthetic-code'}))
    with pytest.raises(ValueError):
        first.url()
    other.created -= 601
    with pytest.raises(ValueError):
        other.url()


@pytest.mark.parametrize('query', ['state=wrong&code=secret', 'state=%E4%BD%A0&code=secret',
                                   'state=x&state=y&code=secret', 'state=x&code=a&extra=b', 'error=access_denied'])
def test_callback_rejects_before_any_exchange(query):
    pending = authorization()
    with pytest.raises(ValueError, match='callback_not_accepted'):
        pending.consume(query)
    assert not pending.consumed


def test_exchange_uses_exact_official_host_pkce_and_minimum_fields():
    async def run():
        pending, calls = authorization(), []
        def endpoint(request):
            calls.append(request)
            assert str(request.url) == 'https://hub.vroid.com/oauth/token'
            assert request.headers['X-Api-Version'] == '11' and 'Authorization' not in request.headers
            form = parse_qs(request.content.decode())
            assert form['code_verifier'] == [pending.verifier] and form['grant_type'] == ['authorization_code']
            return httpx.Response(200, json={'access_token': 'access-synthetic-value-123456',
                'refresh_token': 'refresh-synthetic-value-123456', 'expires_in': 3600, 'token_type': 'Bearer',
                'irrelevant_private_field': 'must_not_be_retained'})
        client = VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            result = await client.exchange(pending, urlencode({'state':pending.state,'code':'code-synthetic'}), 'synthetic-secret-value')
            assert len(calls) == 1 and 'irrelevant_private_field' not in result
            with pytest.raises(ValueError):
                await client.exchange(pending, urlencode({'state':pending.state,'code':'code-synthetic'}), 'synthetic-secret-value')
            assert len(calls) == 1
        finally:
            await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('status,category', [(429,'rate_limited'),(401,'authorization_required'),(403,'not_permitted'),(302,'request_unavailable'),(503,'request_unavailable')])
def test_failure_never_retries_or_echoes_token_response(status, category):
    async def run():
        calls=[]
        def endpoint(request):
            calls.append(request)
            return httpx.Response(status, text='PRIVATE_TOKEN_AND_UPSTREAM_DETAIL', headers={'Location':'https://evil.test/token'})
        client=VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            with pytest.raises(VroidUnavailable) as error:
                await client.list_models('synthetic-access-token-123')
            assert str(error.value) == category and 'PRIVATE' not in str(error.value) and len(calls)==1
        finally:
            await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('cursor', ['https://hub.vroid.com.evil.test/api/staff_picks?max_id=1',
    'https://hub.vroid.com@evil.test/api/staff_picks?max_id=1', 'http://hub.vroid.com/api/staff_picks?max_id=1',
    'https://hub.vroid.com/api/account?max_id=1','https://hub.vroid.com/api/staff_picks?max_id=1&access_token=bad'])
def test_untrusted_next_url_cannot_receive_oauth_header(cursor):
    async def run():
        def forbidden(_request):
            pytest.fail('no request to unapproved paging target')
        client=VroidClient(transport=httpx.MockTransport(forbidden))
        try:
            with pytest.raises(ValueError):
                await client.list_models('synthetic-access-token-123',cursor=cursor)
        finally:
            await client.close()
    asyncio.run(run())


def test_exact_valid_cursor_is_rebuilt_and_response_is_bounded():
    async def run():
        def endpoint(request):
            assert str(request.url) == 'https://hub.vroid.com/api/staff_picks?count=20&max_id=1234'
            assert request.headers['Authorization'] == 'Bearer synthetic-access-token-123'
            return httpx.Response(200, content=b' '*(2*1024*1024+1))
        client=VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            with pytest.raises(VroidUnavailable,match='response_too_large'):
                await client.list_models('synthetic-access-token-123',cursor='https://hub.vroid.com/api/staff_picks?count=100&max_id=1234')
        finally:
            await client.close()
    asyncio.run(run())


def model():
    return {'id':'1234','is_private':False,'is_other_users_available':True,'is_downloadable':True,
        'age_limit':{'is_r18':False,'is_r15':False,'is_adult':False},
        'latest_character_model_version':{'original_file_size':10000,'spec_version':'0.0',
            'is_vendor_forbidden_use_by_others':False,'is_vendor_protected_download':False},
        'license':{'characterization_allowed_user':'everyone','redistribution':'allow'}}


def test_actual_staff_pick_wrapper_and_direct_search_model_share_one_parser():
    row=model()
    document={'data':[{'id':'9000','character_model':row,'created_at':'2026-11-03'}],
              '_links':{'next':{'href':'https://hub.vroid.com/api/staff_picks?max_id=9000'}}}
    before=copy.deepcopy(document)
    assert catalogue_models(document,kind='staff')==[row]
    assert catalogue_models({'data':[row]},kind='search')==[row]
    assert document==before
    with pytest.raises(VroidUnavailable):
        catalogue_models({'data':[{'id':'9000','character_model':'invalid'}]},kind='staff')


def test_actual_relative_search_cursor_is_rebuilt_on_fixed_origin():
    async def run():
        def endpoint(request):
            assert request.url.host=='hub.vroid.com' and request.url.path=='/api/search/character_models'
            assert request.url.params.get_list('search_after[]')==['1','2']
            assert request.url.params['keyword']=='VRoid' and request.url.params['count']=='100'
            return httpx.Response(200,json={'data':[model()]})
        client=VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            result=await client.list_models('synthetic-access-token-123',kind='search',keyword='VRoid',count=100,
                cursor='/api/search/character_models?count=100&keyword=VRoid&search_after[]=1&search_after[]=2')
            assert len(result['data'])==1
        finally:
            await client.close()
    asyncio.run(run())


def test_free_student_app_does_not_override_reuse_or_age_terms():
    original=model()
    assert shared_candidate(original)
    for change in ('private','download','reuse','adult','size','vendor','format','unknown_age'):
        row=copy.deepcopy(original)
        if change=='private':row['is_private']=True
        if change=='download':row['is_downloadable']=False
        if change=='reuse':row['license']['redistribution']='disallow'
        if change=='adult':row['age_limit']['is_r18']=True
        if change=='size':row['latest_character_model_version']['original_file_size']=33*1024*1024
        if change=='vendor':row['latest_character_model_version']['is_vendor_protected_download']=True
        if change=='format':row['latest_character_model_version']['spec_version']='unknown'
        if change=='unknown_age':del row['age_limit']['is_adult']
        assert not shared_candidate(row),change
    assert original==model()
    v1=model();v1['latest_character_model_version'].update({'spec_version':'1.0','vrm_meta':{'avatarPermission':'everyone','allowRedistribution':True}})
    assert shared_candidate(v1)
    v1['latest_character_model_version']['vrm_meta']['allowRedistribution']=False
    assert not shared_candidate(v1)


@pytest.mark.parametrize('field,value', [('latest_character_model_version', ['not-an-object']),
    ('age_limit', 'false'), ('license', ['allow'])])
def test_malformed_remote_metadata_is_not_admitted_or_crashes(field, value):
    row = model()
    row[field] = value
    assert shared_candidate(row) is False
    row = model()
    row['latest_character_model_version'].update({'spec_version': '1.0', 'vrm_meta': ['allow']})
    assert shared_candidate(row) is False


@pytest.mark.parametrize('method,path', [('POST','/api/photos'),('POST','/api/videos'),
    ('POST','/api/artworks'),('POST','/api/account'),('DELETE','/api/account')])
def test_default_scope_never_allows_publication_or_account_mutation(method, path):
    async def run():
        def forbidden(_request):
            pytest.fail('no media publication or account mutation request allowed')
        client=VroidClient(transport=httpx.MockTransport(forbidden))
        try:
            with pytest.raises(ValueError,match='endpoint_not_allowed'):
                await client.request(method,path,token='synthetic-access-token-123')
        finally:
            await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('url', ['http://bucket.s3.amazonaws.com/model', 'https://127.0.0.1/model',
    'https://bucket.s3.amazonaws.com.evil.test/model', 'https://user:secret@bucket.s3.amazonaws.com/model',
    'https://bucket.s3.amazonaws.com:444/model','https://unreviewed.cloudfront.net/model',
    'https://dzn1p4kfcvio2.cloudfront.net.evil.test/model'])
def test_model_download_destination_requires_official_https_storage(url):
    assert official_storage(url) is False


def test_exact_observed_official_cdn_is_allowed_without_signature_logging():
    assert official_storage('https://dzn1p4kfcvio2.cloudfront.net/model?Signature=synthetic')


def test_resource_download_license_is_not_media_upload_and_bearer_never_reaches_s3():
    async def run():
        calls=[]
        row=model();row['latest_character_model_version']['id']='222'
        def endpoint(request):
            calls.append(request)
            if request.url.host=='bucket.s3.ap-northeast-1.amazonaws.com':
                assert 'Authorization' not in request.headers
                return httpx.Response(200,content=b'x'*10000)
            assert request.headers['Authorization']=='Bearer synthetic-access-token-123'
            if request.url.path=='/api/character_models/1234':
                return httpx.Response(200,json={'data':{'character_model':row}})
            if request.url.path=='/api/download_licenses':
                assert request.method=='POST' and parse_qs(request.content.decode())=={'character_model_id':['1234']}
                return httpx.Response(200,json={'data':{'id':'synthetic-license-1','character_model_id':'1234','character_model_version_id':'222'}})
            assert request.url.path=='/api/download_licenses/synthetic-license-1/download'
            return httpx.Response(302,headers={'Location':'https://bucket.s3.ap-northeast-1.amazonaws.com/model?temporary-signature=synthetic'})
        client=VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            data,actual=await client.download_model('synthetic-access-token-123','1234')
            assert len(data)==10000 and actual==row and len(calls)==4
            with pytest.raises(ValueError):
                await client.request('POST','/api/download_licenses',token='synthetic-access-token-123',
                    data={'character_model_id':'1234','upload':'forbidden'})
            assert len(calls)==4
        finally:
            await client.close()
    asyncio.run(run())


def test_refresh_rotation_keeps_only_tokens_on_fixed_official_endpoint():
    async def run():
        def endpoint(request):
            assert str(request.url)=='https://hub.vroid.com/oauth/token'
            assert 'Authorization' not in request.headers
            assert parse_qs(request.content.decode())=={'client_id':['synthetic-client-1234'],
                'client_secret':['synthetic-secret-value'],'grant_type':['refresh_token'],
                'refresh_token':['synthetic-refresh-token']}
            return httpx.Response(200,json={'access_token':'synthetic-new-access-token',
                'refresh_token':'synthetic-new-refresh-token','token_type':'Bearer','expires_in':3600,
                'extra':'discard'})
        client=VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            result=await client.refresh('synthetic-client-1234','synthetic-secret-value','synthetic-refresh-token')
            assert result['refresh_token']=='synthetic-new-refresh-token' and 'extra' not in result
        finally:
            await client.close()
    asyncio.run(run())


def test_latest_discovery_uses_documented_date_order_and_cannot_change_cursor_query():
    async def run():
        calls=[]
        def endpoint(request):
            calls.append(request)
            assert request.url.params['sort']=='first_published_at'
            return httpx.Response(200,json={'data':[]})
        client=VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            await client.list_models('synthetic-access-token',kind='search',keyword='VRoid',sort='first_published_at')
            with pytest.raises(ValueError):
                await client.list_models('synthetic-access-token',kind='search',keyword='VRoid',sort='unknown')
            with pytest.raises(ValueError):
                await client.list_models('synthetic-access-token',kind='search',keyword='VRoid',sort='first_published_at',
                    cursor='/api/search/character_models?search_after[]=1&sort=_score')
            assert len(calls)==1
        finally:
            await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('limited_stage',['license_redirect','resource_CDN'])
def test_resource_rate_limit_is_propagated_without_retry(limited_stage):
    async def run():
        row=model();row['latest_character_model_version']['id']='222'
        license={'id':'synthetic-license','character_model_id':row['id'],'character_model_version_id':'222'}
        calls=[]
        def endpoint(request):
            calls.append(request)
            if request.url.host=='hub.vroid.com':
                if limited_stage=='license_redirect':
                    return httpx.Response(429,text='PRIVATE')
                return httpx.Response(302,headers={'Location':'https://dzn1p4kfcvio2.cloudfront.net/file'})
            assert 'Authorization' not in request.headers
            return httpx.Response(429,text='PRIVATE')
        client=VroidClient(transport=httpx.MockTransport(endpoint))
        try:
            with pytest.raises(VroidUnavailable,match='rate_limited'):
                await client.download_licensed('synthetic-access-token',license,row)
            assert len(calls)==(1 if limited_stage=='license_redirect' else 2)
        finally:
            await client.close()
    asyncio.run(run())
