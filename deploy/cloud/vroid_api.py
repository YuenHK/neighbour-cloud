"""Opt-in VRoid Hub API building blocks; no startup, routes or automatic requests.

Official v11 OAuth uses state+S256 PKCE. Client credentials/tokens belong in the
operator's encrypted store, never a resident response or a public model URL.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

ORIGIN = 'https://hub.vroid.com'
CALLBACKS = {'http://localhost:8925/callback',
             'https://neighbour-yuenhk-live.onrender.com/api/v1/service-desk/vroid/callback'}
MAX_MODEL_BYTES = 32 * 1024 * 1024
# Exact host returned by the authenticated official v11 download endpoint on
# 2026-11-03. Do not trust arbitrary CloudFront distributions or carry bearer.
RESOURCE_CDN = {'dzn1p4kfcvio2.cloudfront.net'}


class VroidUnavailable(Exception):
    """Fixed operator category, deliberately no upstream body/token/URL."""


def opaque(value, *, minimum=16, maximum=4096):
    return (isinstance(value, str) and minimum <= len(value) <= maximum
            and re.fullmatch(r'[A-Za-z0-9._~\-]+', value) is not None)


@dataclass(repr=False)
class Authorization:
    client_id: str
    redirect_uri: str
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(64))
    created: float = field(default_factory=time.monotonic)
    consumed: bool = False

    def __post_init__(self):
        if not opaque(self.client_id, minimum=8, maximum=256) or self.redirect_uri not in CALLBACKS:
            raise ValueError('vroid_explicit_application_required')

    def url(self):
        if self.consumed or not 0 <= time.monotonic() - self.created <= 600:
            raise ValueError('vroid_authorization_expired')
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b'=').decode()
        return ORIGIN + '/oauth/authorize?' + urlencode({
            'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': self.redirect_uri,
            'scope': 'default', 'state': self.state, 'code_challenge': challenge,
            'code_challenge_method': 'S256'})

    def consume(self, query):
        parsed = parse_qs(query, keep_blank_values=True, max_num_fields=5)
        if (self.consumed or not 0 <= time.monotonic() - self.created <= 600
                or set(parsed) != {'code', 'state'} or any(len(v) != 1 for v in parsed.values())
                or not opaque(parsed['code'][0], minimum=1, maximum=2048)
                or not opaque(parsed['state'][0], minimum=43, maximum=128)
                or not hmac.compare_digest(parsed['state'][0], self.state)):
            raise ValueError('vroid_callback_not_accepted')
        # A transport failure may have consumed the upstream code. Never retry
        # automatically or pretend the same authorization is still unused.
        self.consumed = True
        return parsed['code'][0]


class VroidClient:
    def __init__(self, *, transport=None):
        self.client = httpx.AsyncClient(transport=transport, timeout=15,
                                       follow_redirects=False, trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def request(self, method, path, *, token=None, data=None, params=None):
        allowed = (method, path) in {
                ('POST', '/oauth/token'), ('GET', '/api/account'), ('GET', '/api/hearts'),
                ('GET', '/api/staff_picks'), ('GET', '/api/search/character_models')}
        detail = method == 'GET' and re.fullmatch(r'/api/character_models/[0-9]{1,32}', path)
        download = (method == 'POST' and path == '/api/download_licenses' and isinstance(data, dict)
                    and set(data) == {'character_model_id'}
                    and isinstance(data['character_model_id'], str)
                    and re.fullmatch(r'[0-9]{1,32}', data['character_model_id']))
        if not (allowed or detail or download):
            raise ValueError('vroid_endpoint_not_allowed')
        headers = {'X-Api-Version': '11', 'Accept': 'application/json'}
        if token is not None:
            if not opaque(token):
                raise ValueError('vroid_token_not_accepted')
            headers['Authorization'] = 'Bearer ' + token
        try:
            async with asyncio.timeout(18):
                async with self.client.stream(method, ORIGIN + path, headers=headers,
                                              data=data, params=params) as response:
                    if response.status_code != 200:
                        category = {429: 'rate_limited', 401: 'authorization_required',
                                    403: 'not_permitted'}.get(response.status_code, 'request_unavailable')
                        raise VroidUnavailable(category)
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        content.extend(chunk)
                        if len(content) > 2 * 1024 * 1024:
                            raise VroidUnavailable('response_too_large')
                    value = json.loads(content)
                    if not isinstance(value, dict):
                        raise VroidUnavailable('response_not_accepted')
                    return value
        except (httpx.HTTPError, TimeoutError, json.JSONDecodeError, UnicodeError):
            raise VroidUnavailable('request_unavailable') from None

    async def exchange(self, authorization, query, secret):
        if not opaque(secret):
            raise ValueError('vroid_client_secret_not_accepted')
        code = authorization.consume(query)
        value = await self.request('POST', '/oauth/token', data={
            'client_id': authorization.client_id, 'client_secret': secret,
            'redirect_uri': authorization.redirect_uri, 'grant_type': 'authorization_code',
            'code': code, 'code_verifier': authorization.verifier})
        return checked_tokens(value)

    async def refresh(self, client_id, secret, refresh_token):
        if not opaque(client_id, minimum=8, maximum=256) or not opaque(secret) or not opaque(refresh_token):
            raise ValueError('vroid_refresh_not_accepted')
        # A refresh token may rotate even when the acknowledgement is lost.
        # The caller must persist an intent before this once-only request.
        return checked_tokens(await self.request('POST', '/oauth/token', data={
            'client_id': client_id, 'client_secret': secret, 'grant_type': 'refresh_token',
            'refresh_token': refresh_token}))

    async def list_models(self, token, *, kind='staff', count=20, keyword='', cursor='', sort='_score'):
        if kind not in ('staff', 'search') or type(count) is not int or not 1 <= count <= 100:
            raise ValueError('vroid_bounded_catalogue_required')
        if not isinstance(keyword, str) or len(keyword) > 80 or (kind == 'search' and not keyword.strip()):
            raise ValueError('vroid_query_not_accepted')
        if sort not in ('_score','first_published_at') or kind=='staff' and sort!='_score':
            raise ValueError('vroid_sort_not_accepted')
        path = '/api/staff_picks' if kind == 'staff' else '/api/search/character_models'
        params = {'count': count}
        if kind == 'search':
            params['keyword'] = keyword.strip()
            params['sort'] = sort
        if cursor:
            # API-supplied paging links never select a different destination or
            # add unknown parameters that might weaken download/use filtering.
            url = urlsplit(cursor)
            absolute = url.scheme == 'https' and url.netloc == 'hub.vroid.com'
            relative = not url.scheme and not url.netloc and cursor.startswith(path + '?')
            if ((not absolute and not relative) or url.path != path or url.fragment
                    or any(ord(char) < 32 for char in cursor)):
                raise ValueError('vroid_paging_not_accepted')
            found = parse_qs(url.query, keep_blank_values=True, max_num_fields=8)
            expected = {'count', 'max_id'} if kind == 'staff' else {'count', 'keyword', 'search_after[]', 'sort'}
            if not set(found) <= expected or len(cursor) > 2048:
                raise ValueError('vroid_paging_not_accepted')
            if kind == 'staff':
                if len(found.get('max_id', [])) != 1 or not re.fullmatch(r'[0-9]{1,32}', found['max_id'][0]):
                    raise ValueError('vroid_paging_not_accepted')
                params['max_id'] = found['max_id'][0]
            else:
                if not 1 <= len(found.get('search_after[]', [])) <= 3:
                    raise ValueError('vroid_paging_not_accepted')
                if found.get('sort',[sort])!=[sort] or found.get('keyword',[keyword.strip()])!=[keyword.strip()]:
                    raise ValueError('vroid_paging_not_accepted')
                params['search_after[]'] = found['search_after[]']
        value = await self.request('GET', path, token=token, params=params)
        if not isinstance(value.get('data'), list) or len(value['data']) > 100:
            raise VroidUnavailable('catalogue_not_accepted')
        return value

    async def download_model(self, token, model_id, *, preserve_license=None):
        """Official resource-read flow, never a media/account write or raw proxy."""
        if not isinstance(model_id, str) or not re.fullmatch(r'[0-9]{1,32}', model_id) or not opaque(token):
            raise ValueError('vroid_model_not_accepted')
        detail = await self.request('GET', '/api/character_models/' + model_id, token=token)
        data = detail.get('data')
        model = data.get('character_model') if isinstance(data, dict) else None
        if not shared_candidate(model) or model['id'] != model_id:
            raise VroidUnavailable('model_permissions_not_accepted')
        version = model['latest_character_model_version'].get('id')
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]{1,32}', version):
            raise VroidUnavailable('model_version_not_accepted')
        value = await self.request('POST', '/api/download_licenses', token=token,
                                   data={'character_model_id': model_id})
        license = value.get('data')
        if not isinstance(license, dict):
            raise VroidUnavailable('download_license_not_accepted')
        identity = license.get('id')
        if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity)
                or str(license.get('character_model_id')) != model_id
                or str(license.get('character_model_version_id')) != version):
            raise VroidUnavailable('download_license_not_accepted')
        if preserve_license is not None:
            preserve_license({'license': license, 'model': model})
        return await self.download_licensed(token, license, model)

    async def download_licensed(self, token, license, model):
        """Resume a checked resource license without issuing another one."""
        if not opaque(token) or not shared_candidate(model) or not isinstance(license, dict):
            raise VroidUnavailable('download_license_not_accepted')
        identity = license.get('id')
        version = model['latest_character_model_version'].get('id')
        if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity)
                or str(license.get('character_model_id')) != model['id']
                or not isinstance(version, str) or str(license.get('character_model_version_id')) != version):
            raise VroidUnavailable('download_license_not_accepted')
        headers = {'X-Api-Version': '11', 'Authorization': 'Bearer ' + token}
        try:
            async with asyncio.timeout(60):
                async with self.client.stream('GET', ORIGIN + '/api/download_licenses/' + identity + '/download',
                                              headers=headers) as redirect:
                    if redirect.status_code != 302:
                        raise VroidUnavailable({429:'rate_limited',401:'authorization_required',
                            403:'not_permitted'}.get(redirect.status_code,'download_license_unavailable'))
                    destination = redirect.headers.get('location', '')
                    if not official_storage(destination):
                        error = VroidUnavailable('download_host_requires_review')
                        host = urlsplit(destination).hostname or ''
                        error.review_host = host if re.fullmatch(r'[a-z0-9.-]{1,253}', host) else 'not_accepted'
                        raise error
                # The temporary S3 signature is used only in memory. The Hub
                # bearer must never be forwarded, even to the official CDN.
                async with self.client.stream('GET', destination, headers={'Accept': 'application/octet-stream'}) as response:
                    if response.status_code != 200:
                        raise VroidUnavailable('rate_limited' if response.status_code==429 else 'model_file_unavailable')
                    content = bytearray()
                    expected = model['latest_character_model_version']['original_file_size']
                    async for part in response.aiter_bytes(chunk_size=65536):
                        if len(content) + len(part) > min(expected, MAX_MODEL_BYTES):
                            raise VroidUnavailable('model_file_too_large')
                        content.extend(part)
                    if len(content) != expected:
                        raise VroidUnavailable('model_file_incomplete')
                    return bytes(content), model
        except (httpx.HTTPError, TimeoutError):
            raise VroidUnavailable('model_download_unavailable') from None


def official_storage(value):
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and url.username is None and url.password is None
                and url.port in (None, 443) and not url.fragment and len(value) < 8192
                and (url.hostname in RESOURCE_CDN or re.fullmatch(
                    r'[a-z0-9.-]+\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com', url.hostname or '') is not None))
    except (ValueError, TypeError):
        return False


def checked_tokens(value):
    if (not opaque(value.get('access_token')) or not opaque(value.get('refresh_token'))
            or str(value.get('token_type', '')).lower() != 'bearer'
            or type(value.get('expires_in')) is not int or not 1 <= value['expires_in'] <= 31536000):
        raise VroidUnavailable('token_response_not_accepted')
    return {key: value[key] for key in ('access_token', 'refresh_token', 'expires_in', 'token_type')}


def catalogue_models(value, *, kind):
    """Staff picks wrap the model; preserve original response/paging metadata."""
    if not isinstance(value, dict) or not isinstance(value.get('data'), list) or len(value['data']) > 100:
        raise VroidUnavailable('catalogue_not_accepted')
    rows = []
    for item in value['data']:
        if not isinstance(item, dict):
            raise VroidUnavailable('catalogue_not_accepted')
        row = item.get('character_model') if kind == 'staff' and 'character_model' in item else item
        if not isinstance(row, dict) or not re.fullmatch(r'[0-9]{1,32}', str(row.get('id', ''))):
            raise VroidUnavailable('catalogue_not_accepted')
        rows.append(row)
    return rows


def shared_candidate(model):
    """Narrow candidate filter, not final licence/render/publish approval.

    Platform-wide publication copies raw VRM to multiple resident devices, so
    explicit redistribution permission is required even for a free student app.
    Other terms, credit, native rendering and the actual file remain to review.
    """
    if not isinstance(model, dict) or not re.fullmatch(r'[0-9]{1,32}', str(model.get('id', ''))):
        return False
    if (model.get('is_private') is not False or model.get('is_other_users_available') is not True
            or model.get('is_downloadable') is not True):
        return False
    age = model.get('age_limit')
    if not isinstance(age, dict) or any(age.get(name) is not False for name in ('is_r18', 'is_r15', 'is_adult')):
        return False
    version = model.get('latest_character_model_version') or {}
    if not isinstance(version, dict):
        return False
    size = version.get('original_file_size')
    if type(size) is not int or not 28 <= size <= MAX_MODEL_BYTES:
        return False
    if any(version.get(key) is not False for key in ('is_vendor_forbidden_use_by_others', 'is_vendor_protected_download')):
        return False
    if version.get('spec_version') == '1.0':
        meta = version.get('vrm_meta') or {}
        return (isinstance(meta, dict) and meta.get('avatarPermission') == 'everyone'
                and meta.get('allowRedistribution') is True)
    if version.get('spec_version') in ('0.0', '0.x'):
        terms = model.get('license') or {}
        return (isinstance(terms, dict) and terms.get('characterization_allowed_user') == 'everyone'
                and terms.get('redistribution') == 'allow')
    return False
