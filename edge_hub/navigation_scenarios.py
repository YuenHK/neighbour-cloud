"""Deterministic offline world/sensor/vehicle replay, without device access.

Ground-truth simulation poses are labelled explicitly. This is a controller and
failure-response benchmark, not evidence of camera accuracy or hardware stops.
Free space comes from an occlusion-aware synthetic range sensor, never by
copying the surveyed map into the controller's live observation argument.
"""
import math
from dataclasses import dataclass

from edge_hub.route_follower import RouteFollower

SCENARIOS = ('clear_route', 'obstacle_appears', 'pose_lost', 'sensor_stale',
             'frame_replayed', 'foreign_map', 'clock_reversed', 'emergency_at_speed')


@dataclass(frozen=True)
class World:
    width: int = 10
    height: int = 8
    cell_m: float = .5

    def __post_init__(self):
        if (type(self.width) is not int or type(self.height) is not int
                or not 4 <= self.width <= 64 or not 4 <= self.height <= 64
                or type(self.cell_m) not in (int, float) or not .1 <= self.cell_m <= 2):
            raise ValueError('invalid_offline_world_dimensions')

    def floor(self, cell, obstacles):
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height and cell not in obstacles

    def ray_clear(self, start, target, obstacles):
        """Supercover DDA: a diagonal corner cannot see through adjacent walls."""
        x, y = start
        dx, dy = target[0]-x, target[1]-y
        current = (math.floor(x/self.cell_m), math.floor(y/self.cell_m))
        end = (math.floor(target[0]/self.cell_m), math.floor(target[1]/self.cell_m))
        sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
        delta_x = self.cell_m/abs(dx) if dx else math.inf
        delta_y = self.cell_m/abs(dy) if dy else math.inf
        boundary_x = (current[0]+(dx > 0))*self.cell_m
        boundary_y = (current[1]+(dy > 0))*self.cell_m
        tx = (boundary_x-x)/dx if dx else math.inf
        ty = (boundary_y-y)/dy if dy else math.inf
        for _ in range(self.width+self.height+4):
            if not self.floor(current, obstacles):
                return False
            if current == end:
                return True
            if math.isclose(tx, ty, abs_tol=1e-12):
                if not self.floor((current[0]+sx, current[1]), obstacles) or not self.floor((current[0], current[1]+sy), obstacles):
                    return False
                current = (current[0]+sx, current[1]+sy)
                tx, ty = tx+delta_x, ty+delta_y
            elif tx < ty:
                current = (current[0]+sx, current[1])
                tx += delta_x
            else:
                current = (current[0], current[1]+sy)
                ty += delta_y
        return False

    def sense(self, position, obstacles, *, range_m=2.):
        observed = set()
        for y in range(self.height):
            for x in range(self.width):
                target = ((x+.5)*self.cell_m, (y+.5)*self.cell_m)
                if (math.dist(position, target) <= range_m and self.floor((x, y), obstacles)
                        and self.ray_clear(position, target, obstacles)):
                    observed.add((x, y))
        return frozenset(observed)

    def clearance(self, position, obstacles):
        x, y = position
        nearest = min(x, y, self.width*self.cell_m-x, self.height*self.cell_m-y)
        for cx, cy in obstacles:
            px = max(cx*self.cell_m, min(x, (cx+1)*self.cell_m))
            py = max(cy*self.cell_m, min(y, (cy+1)*self.cell_m))
            nearest = min(nearest, math.hypot(x-px, y-py))
        return nearest


def approach(actual, target, dt):
    # Independent finite braking, rather than instantly obeying a zero command.
    acceleration = .6 if actual*target <= 0 or abs(target) < abs(actual) else .3
    return actual + max(-acceleration*dt, min(acceleration*dt, target-actual))


def vehicle_step(position, velocity, requested, dt=.1):
    """Linearly ramp each axis; integrate substeps at their midpoint velocity."""
    vx, vy = velocity
    nx, ny = approach(vx, requested[0], dt), approach(vy, requested[1], dt)
    x, y = position
    samples = []
    for index in range(5):
        fraction = (index+.5)/5
        x += (vx+(nx-vx)*fraction)*dt/5
        y += (vy+(ny-vy)*fraction)*dt/5
        samples.append((x, y))
    return (x, y), (nx, ny), samples


def replay(name):
    if name not in SCENARIOS:
        raise ValueError('unknown_offline_scenario')
    world = World()
    allowed = {(x, y) for x in range(1, world.width-1) for y in range(1, world.height-1)}
    follower = RouteFollower(path=[(2, 3), (3, 3), (4, 3), (5, 3)], cell_m=world.cell_m,
        allowed=allowed, map_sha256='a'*64, calibration_sha256='b'*64)
    x, y, vx, vy = 1.25, 1.75, 0., 0.
    trace, collisions, first_stop, injection = [], 0, None, (1500 if name == 'emergency_at_speed' else 3500)
    minimum_clearance, max_speed, stopped_at = math.inf, 0., None
    for index in range(251):
        elapsed, now = index*100, 1000+index*100
        obstacle_cell = (4, 3) if name == 'emergency_at_speed' else (5, 3)
        obstacles = {obstacle_cell} if name in ('obstacle_appears', 'emergency_at_speed') and elapsed >= injection else set()
        pose = {'state': 'located', 'x_m': x, 'y_m': y, 'yaw_rad': 0.,
            'frame_key': f'sim-{index}', 'captured_at_ms': now,
            'map_sha256': 'a'*64, 'calibration_sha256': 'b'*64}
        observed, sensor_stamp, controller_clock = world.sense((x, y), obstacles), now, now
        if elapsed >= injection:
            if name == 'pose_lost':
                pose['state'] = 'unlocated'
            elif name == 'sensor_stale':
                sensor_stamp -= 500
            elif name == 'frame_replayed':
                pose.update(frame_key=f'sim-{index-1}', captured_at_ms=now-100)
            elif name == 'foreign_map':
                pose['map_sha256'] = 'c'*64
            elif name == 'clock_reversed':
                controller_clock = now-200
        result = follower.tick(now_ms=controller_clock, pose=pose,
            observed_free=observed, observed_at_ms=sensor_stamp)
        assert result['execution_enabled'] is False and result['hardware_commands'] == 0
        if follower.stopped and first_stop is None:
            first_stop = elapsed
        (x, y), (vx, vy), samples = vehicle_step((x, y), (vx, vy),
            (result['body_vx_mps'], result['body_vy_mps']))
        for point in samples:
            distance = world.clearance(point, obstacles)
            minimum_clearance = min(minimum_clearance, distance)
            collisions += distance <= .22
        max_speed = max(max_speed, math.hypot(vx, vy))
        trace.append({'t_ms': elapsed, 'physical_at_ms': elapsed+100,
            'x_m': round(x, 6), 'y_m': round(y, 6),
            'actual_speed_mps': round(math.hypot(vx, vy), 6), 'state': result['state'],
            'observed_free_cells': len(observed), 'command_speed_mps': round(math.hypot(
                result['body_vx_mps'], result['body_vy_mps']), 6)})
        if follower.stopped and abs(vx)+abs(vy) < 1e-8:
            stopped_at = elapsed+100
            break
    return {'scenario': name, 'final_state': follower.stopped or 'replay_bound',
        'pose_source': 'simulated_ground_truth_not_camera', 'sensor': 'synthetic_supercover_range_occlusion',
        'sensor_scope': 'cell-centre rays and full-cell obstacles; not a depth-camera coverage proof',
        'vehicle_scope': 'synthetic0.22m-radius disc, fixed-heading route; not EP/S1 calibrated dimensions',
        'hardware_commands': 0, 'execution_enabled': False, 'collisions': collisions,
        'maximum_speed_mps': round(max_speed, 6), 'minimum_body_clearance_m': round(minimum_clearance-.22, 6),
        'injection_ms': None if name == 'clear_route' else injection,
        'speed_before_injection_mps': next((row['actual_speed_mps'] for row in trace
            if row['physical_at_ms'] == injection), None) if name != 'clear_route' else None,
        'first_stop_ms': first_stop, 'fully_stopped_ms': stopped_at,
        'trace': trace}
