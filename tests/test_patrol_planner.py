import sqlite3
from itertools import pairwise

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from deploy.cloud.operations import Operations, migrate
from deploy.cloud.patrol_planner import (
    PATH,
    FloorMap,
    MapEdit,
    MapStore,
    RouteRequest,
    plan_route,
    planning_router,
)


def floor_map(**updates):
    value = {'name': '合成樓層', 'width': 10, 'height': 10, 'cell_cm': 50,
             'floor': [{'x': x, 'y': y} for x in range(10) for y in range(10)]}
    return FloorMap.model_validate({**value, **updates})


def request(floor=None, **updates):
    return RouteRequest.model_validate({'map': (floor or floor_map()).model_dump(),
        'start': {'x': 2, 'y': 2}, 'goal': {'x': 7, 'y': 7}, **updates})


def test_route_cannot_cut_corner_or_enter_blocked_clearance():
    floor = floor_map(blocked=[{'x': 4, 'y': 4}, {'x': 4, 'y': 5}])
    value = plan_route(request(floor))
    path = value['path']
    assert path[0] == {'x': 2, 'y': 2} and path[-1] == {'x': 7, 'y': 7}
    for a, b in pairwise(path):
        assert abs(a['x']-b['x']) + abs(a['y']-b['y']) == 1
    assert all(max(abs(p['x']-4), abs(p['y']-y)) > 1 for p in path for y in (4, 5))
    assert value['distance_m'] == (len(path)-1)*.5
    assert value['hardware_commands'] == 0 and not value['execution_enabled']


def test_unsurveyed_map_is_never_assumed_walkable():
    with pytest.raises(HTTPException) as error:
        plan_route(request(floor_map(floor=[])))
    assert error.value.status_code == 422


def test_wall_without_safe_gap_is_unreachable():
    wall = [{'x': 5, 'y': y} for y in range(10)]
    with pytest.raises(HTTPException) as error:
        plan_route(request(floor_map(blocked=wall)))
    assert error.value.status_code == 422


def test_edge_requires_physical_clearance_and_large_maps_are_bounded():
    with pytest.raises(HTTPException):
        plan_route(request(start={'x': 0, 'y': 2}))
    with pytest.raises(ValidationError):
        floor_map(width=65)
    with pytest.raises(ValidationError):
        floor_map(floor=[{'x': 2, 'y': 2}, {'x': 2, 'y': 2}])
    with pytest.raises(ValidationError):
        floor_map(width=True)
    with pytest.raises(ValidationError):
        floor_map(blocked=[{'x': 60, 'y': 0}])


@pytest.mark.parametrize('profile', ['ep', 's1', 'simulation'])
def test_profiles_never_enable_automatic_movement(profile):
    result = plan_route(request(profile=profile))
    assert result['mode'] == 'simulation_only'
    assert result['hardware_commands'] == 0
    assert result['profile']['navigation_execution'] is False
    if profile == 's1':
        assert result['profile']['connection'] == 'official_lab_and_sbus_preparation'


def test_map_encrypted_restart_conflict_and_idempotent_save(tmp_path):
    path = tmp_path/'estate.sqlite3'
    db = sqlite3.connect(path, check_same_thread=False)
    migrate(db)
    operations = Operations(db, b'test-only-key-not-secret-32-bytes!')
    store = MapStore(operations)
    edit = MapEdit(revision=0, map=floor_map())
    first = store.save(edit)
    assert first['revision'] == 1
    assert '合成樓層' not in db.execute('SELECT payload FROM cloud_operations').fetchone()[0]
    assert store.save(MapEdit(revision=1, map=floor_map())) == first
    with pytest.raises(HTTPException) as error:
        store.save(edit)
    assert error.value.status_code == 409
    db.close()
    reopened = sqlite3.connect(path)
    assert MapStore(Operations(reopened, b'test-only-key-not-secret-32-bytes!')).current() == first
    reopened.close()


def test_routes_are_staff_only_and_simulation_never_persists(tmp_path):
    db = sqlite3.connect(tmp_path/'isolated.sqlite3', check_same_thread=False)
    migrate(db)
    operations = Operations(db, b'test-only-key-not-secret-32-bytes!')
    app = FastAPI()
    # Production authorization is a context function, tested here using an
    # explicit dependency-free request boundary. No real staff credential.
    from contextvars import ContextVar
    permitted = ContextVar('permitted', default=False)
    def authorize():
        if not permitted.get():
            raise HTTPException(401, 'staff only')
    @app.middleware('http')
    async def role(request, call_next):
        token = permitted.set(request.headers.get('x-test-role') == 'staff')
        try:
            return await call_next(request)
        finally:
            permitted.reset(token)
    app.include_router(planning_router(operations, authorize))
    with TestClient(app) as client:
        for method, path, body in [('GET', PATH, None), ('PUT', PATH, {'revision': 0, 'map': floor_map().model_dump()}),
                                    ('POST', PATH+'/simulate', request().model_dump()), ('GET', PATH+'/offline-kit.zip', None)]:
            assert client.request(method, path, json=body).status_code == 401
        assert client.post(PATH+'/simulate', headers={'x-test-role': 'staff'}, json=request().model_dump()).status_code == 200
        assert operations.count('patrol-map-v1') == 0
        response = client.put(PATH, headers={'x-test-role': 'staff'}, json={'revision': 0, 'map': floor_map().model_dump()})
        assert response.status_code == 200 and response.json()['revision'] == 1
        assert client.get(PATH, headers={'x-test-role': 'staff'}).json()['map']['name'] == '合成樓層'
        assert operations.count('patrol-map-v1') == 1
        import io
        import json
        import zipfile
        kit = client.get(PATH+'/offline-kit.zip', headers={'x-test-role': 'staff'})
        assert kit.status_code == 200 and kit.headers['cache-control'] == 'no-store'
        with zipfile.ZipFile(io.BytesIO(kit.content)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['hardware_commands'] == 0 and not manifest['execution_enabled']
            assert 's1-lab-readonly.py' in archive.namelist()
        assert operations.count('patrol-map-v1') == 1
    db.close()
