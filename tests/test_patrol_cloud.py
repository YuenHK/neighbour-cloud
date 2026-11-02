import json
from types import SimpleNamespace

import httpx

from edge_hub import patrol_cloud
from edge_hub.photo_privacy import ApprovedPhoto


def approved():
    return ApprovedPhoto(b'masked-photo', 'a'*64, 'b'*64)


def test_cloud_review_is_free_capped_and_honours_resident_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(patrol_cloud, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(patrol_cloud.cloudflare_gemma, 'configuration', lambda: {'account_id': 'synthetic'})
    monkeypatch.setattr(patrol_cloud.cloudflare_gemma, '_busy', True)
    assert patrol_cloud.review(approved(), {'litter'}) == ({'litter'}, 'not_reviewed')
    monkeypatch.setattr(patrol_cloud.cloudflare_gemma, '_busy', False)
    (tmp_path/'cloudflare-gemma-key.dpapi').write_bytes(b'synthetic')
    monkeypatch.setattr(patrol_cloud, '_crypt', lambda *a, **k: b'synthetic')
    reservations = []
    monkeypatch.setattr(patrol_cloud, 'CloudAllowance', lambda _: SimpleNamespace(reserve=reservations.append))
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['model'] == patrol_cloud.cloudflare_gemma.MODEL
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"findings":[]}'}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(patrol_cloud.httpx, 'Client', lambda **k: client)
    assert patrol_cloud.review(approved(), {'litter'}) == (set(), 'reviewed')
    assert len(calls) == len(reservations) == 1
    assert reservations[0]['patrol_cloud_checks'] == 1
    assert reservations[0]['cloudflare_gemma_neuron_reservations'] == 100


def test_cloud_limit_stops_future_calls_until_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(patrol_cloud, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(patrol_cloud.cloudflare_gemma, 'configuration', lambda: {'account_id': 'synthetic'})
    monkeypatch.setattr(patrol_cloud.cloudflare_gemma, '_busy', False)
    (tmp_path/'cloudflare-gemma-key.dpapi').write_bytes(b'synthetic')
    monkeypatch.setattr(patrol_cloud, '_crypt', lambda *a, **k: b'synthetic')
    reservations = []
    monkeypatch.setattr(patrol_cloud, 'CloudAllowance', lambda _: SimpleNamespace(reserve=reservations.append))
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    monkeypatch.setattr(patrol_cloud.httpx, 'Client', lambda **k: client)
    assert patrol_cloud.review(approved(), {'litter'})[1] == 'quota_exhausted'
    assert patrol_cloud.review(approved(), {'litter'})[1] == 'quota_exhausted'
    assert len(reservations) == 1


def test_raw_automatic_candidate_cannot_leave_device(monkeypatch):
    monkeypatch.setattr(patrol_cloud.cloudflare_gemma, 'configuration', lambda: (_ for _ in ()).throw(AssertionError('no dispatch or quota')))
    assert patrol_cloud.review(b'private-original', {'litter'}) == ({'litter'}, 'privacy_review_required')
