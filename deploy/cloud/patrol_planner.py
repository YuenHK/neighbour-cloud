"""Staff-only map/route preparation. Pure simulation: no SDK, sockets or actuation.

Unknown cells, stairs and staff restrictions are obstacles. A route is not a
localisation system or permission to drive; execution is deliberately absent.
"""
import heapq
import math
import threading
from collections import deque

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

PATH = '/api/v1/service-desk/patrol-planning'
NAMESPACE = 'patrol-map-v1'
PROFILES = {
    'ep': {'name': 'RoboMaster EP', 'connection': 'existing_manual_console',
           'navigation_execution': False, 'reason': '定位、障礙感測及現場停止驗收未完成。'},
    's1': {'name': 'RoboMaster S1', 'connection': 'official_lab_and_sbus_preparation',
           'navigation_execution': False, 'reason': '官方 Lab／SBus 離機工具已準備；接線、定位及停止仍待真機核對。'},
    'simulation': {'name': '離機模擬', 'connection': 'none', 'navigation_execution': False,
                   'reason': '只模擬路線，沒有連線或移動機械人。'},
}


class Point(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    x: int = Field(ge=0, lt=64)
    y: int = Field(ge=0, lt=64)


class FloorMap(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=60, default='巡查區域')
    width: int = Field(ge=4, le=64, default=20)
    height: int = Field(ge=4, le=64, default=16)
    cell_cm: int = Field(ge=10, le=200, default=50)
    # Only cells explicitly surveyed as floor can be traversed.
    floor: list[Point] = Field(max_length=4096)
    blocked: list[Point] = Field(default_factory=list, max_length=4096)
    clearance_cm: int = Field(ge=20, le=100, default=35)

    @model_validator(mode='after')
    def bounds(self):
        if not self.name.strip() or any(ord(char) < 32 for char in self.name):
            raise ValueError('invalid_map_name')
        for points in (self.floor, self.blocked):
            coords = [(point.x, point.y) for point in points]
            if len(coords) != len(set(coords)) or any(x >= self.width or y >= self.height for x, y in coords):
                raise ValueError('map_coordinates_invalid')
        return self


class MapEdit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    map: FloorMap


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    map: FloorMap
    start: Point
    goal: Point
    profile: str = Field(default='simulation', pattern='^(simulation|ep|s1)$')


def traversable(floor):
    allowed = {(point.x, point.y) for point in floor.floor}
    walls = {(point.x, point.y) for point in floor.blocked}
    radius = math.ceil(floor.clearance_cm / floor.cell_cm)
    # Conservative square clearance includes the edge/outside of the map.
    return {(x, y) for x, y in allowed if all(
        (x + dx, y + dy) in allowed and (x + dx, y + dy) not in walls
        for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1))}


def plan_route(request):
    allowed = traversable(request.map)
    start, goal = (request.start.x, request.start.y), (request.goal.x, request.goal.y)
    if start not in allowed or goal not in allowed:
        raise HTTPException(422, '起點或終點太近障礙／邊界，或未標示為已勘察地面。')
    frontier, costs, parents = [(0, start)], {start: 0}, {}
    while frontier:
        _, node = heapq.heappop(frontier)
        if node == goal:
            break
        for candidate in ((node[0]+1, node[1]), (node[0]-1, node[1]),
                          (node[0], node[1]+1), (node[0], node[1]-1)):
            cost = costs[node] + 1
            if candidate in allowed and cost < costs.get(candidate, math.inf):
                costs[candidate], parents[candidate] = cost, node
                heuristic = abs(candidate[0]-goal[0]) + abs(candidate[1]-goal[1])
                heapq.heappush(frontier, (cost+heuristic, candidate))
    if goal not in costs:
        raise HTTPException(422, '沒有符合安全距離的通道；請修正地圖或選擇其他目的地。')
    path = deque([goal])
    while path[0] != start:
        path.appendleft(parents[path[0]])
    return {'path': [{'x': x, 'y': y} for x, y in path],
            'distance_m': round(costs[goal] * request.map.cell_cm / 100, 2),
            'mode': 'simulation_only', 'hardware_commands': 0, 'execution_enabled': False,
            'profile': PROFILES[request.profile], 'map_is_not_live_localisation': True}


class MapStore:
    def __init__(self, operations):
        self.operations, self.lock = operations, threading.RLock()

    def current(self):
        value = self.operations.get(NAMESPACE, 'current')
        if value is None:
            return {'revision': 0, 'map': None}
        return {'revision': value['revision'], 'map': self.operations.open(NAMESPACE, 'current', value['sealed'])}

    def save(self, edit):
        # Serialized by the same single formal-writer rule as other settings.
        with self.lock:
            current = self.current()
            if current['revision'] != edit.revision:
                raise HTTPException(409, '地圖已被另一位職員更新；本頁草稿保留，請重新讀取後核對。')
            data = edit.map.model_dump()
            if data == current['map']:
                return current
            revision = current['revision'] + 1
            self.operations.put(NAMESPACE, 'current', {
                'revision': revision, 'sealed': self.operations.seal(NAMESPACE, 'current', data)})
            return {'revision': revision, 'map': data}


def planning_router(operations, authorize):
    router, store = APIRouter(), MapStore(operations)

    @router.get(PATH)
    async def current():
        authorize()
        value = await run_in_threadpool(store.current)
        return {**value, 'profiles': PROFILES, 'execution_enabled': False}

    @router.put(PATH)
    async def save(edit: MapEdit):
        authorize()
        return await run_in_threadpool(store.save, edit)

    @router.post(PATH + '/simulate')
    async def simulate(request: RouteRequest):
        authorize()
        return await run_in_threadpool(plan_route, request)

    @router.get(PATH + '/offline-kit.zip')
    async def offline_kit():
        authorize()
        from deploy.cloud.patrol_kit import source_kit
        blob = await run_in_threadpool(source_kit)
        return Response(blob, media_type='application/zip', headers={
            'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="neighbour-patrol-review-kit.zip"'})

    return router
