from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from edge_hub import local_resources


def test_percentages_are_real_used_metrics_with_one_failed_probe_staying_unknown(monkeypatch):
    monkeypatch.setattr(local_resources.psutil, 'cpu_percent', lambda interval: 23.5)
    monkeypatch.setattr(local_resources.psutil, 'virtual_memory', lambda: SimpleNamespace(percent=50, total=100, available=50))
    monkeypatch.setattr(local_resources.psutil, 'disk_usage', lambda path: (_ for _ in ()).throw(OSError()))
    result = local_resources.sample()
    assert result['metrics']['cpu']['percent'] == 23.5
    assert result['metrics']['ram']['used_bytes'] == 50
    assert result['metrics']['storage']['percent'] is None
    assert result['scope'] == 'whole_notebook'


def test_resources_are_authenticated_and_cached_without_cloud_or_inventory():
    calls=[]
    def authorize(key):
        if key != 'synthetic':
            raise HTTPException(403)
    def sampler():
        calls.append(1)
        return {'metrics': {'cpu': {'percent': 25}}, 'updated_at_ms':1000}
    app=FastAPI();app.include_router(local_resources.resources_router(authorize,sampler))
    with TestClient(app) as client:
        assert client.get('/api/v1/service-desk/resources').status_code==403
        for _ in range(2):
            response=client.get('/api/v1/service-desk/resources',headers={'X-Operator-Key':'synthetic'})
            assert response.json()['metrics']['cpu']['percent']==25
            assert response.headers['cache-control']=='no-store'
    assert calls==[1]


def test_disk_probe_passes_native_string_path_on_windows(monkeypatch):
    def disk(path):
        assert isinstance(path,str)
        return SimpleNamespace(percent=75,used=75,total=100)
    monkeypatch.setattr(local_resources.psutil,'disk_usage',disk)
    assert local_resources.sample()['metrics']['storage']['percent']==75
