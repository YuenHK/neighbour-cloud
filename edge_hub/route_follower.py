"""Closed-loop route computation for offline replay; no actuator adapter.

Fresh surveyed localisation and observed free cells are separate inputs. The
surveyed static map is never promoted to evidence of live obstacle clearance.
Even a valid velocity here is a simulation result, not hardware permission.
"""
import math


def digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def bounded_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and abs(value) <= 1_000_000
    except OverflowError:
        return False


class RouteFollower:
    def __init__(self, *, path, cell_m, allowed, map_sha256, calibration_sha256):
        if (not digest(map_sha256) or not digest(calibration_sha256)
                or type(cell_m) not in (int, float) or not .1 <= cell_m <= 2
                or type(path) is not list or not 1 <= len(path) <= 128):
            raise ValueError('bounded_surveyed_route_required')
        self.path = []
        self.allowed = frozenset(allowed)
        for row in path:
            if (type(row) not in (tuple, list) or len(row) != 2
                    or any(type(i) is not int or not 0 <= i < 64 for i in row)
                    or tuple(row) not in self.allowed):
                raise ValueError('path_outside_clearance_map')
            point = tuple(row)
            if self.path and abs(point[0]-self.path[-1][0])+abs(point[1]-self.path[-1][1]) != 1:
                raise ValueError('route_must_have_adjacent_cells')
            self.path.append(point)
        if (len(path)-1)*cell_m > 20:
            raise ValueError('route_too_long')
        self.cell_m, self.map_sha, self.calibration_sha = float(cell_m), map_sha256, calibration_sha256
        self.index, self.started, self.last_time, self.last_pose, self.last_capture = 0, None, None, None, None
        self.last_frame, self.seen_frames = None, set()
        self.stopped = None

    def stop(self, reason):
        self.stopped = reason
        return self.result(0., 0., reason)

    def result(self, vx, vy, reason):
        return {'state': reason, 'body_vx_mps': vx, 'body_vy_mps': vy, 'yaw_rate_dps': 0.,
                'waypoint': self.index, 'hardware_commands': 0, 'execution_enabled': False,
                'mode': 'offline_closed_loop_replay'}

    def tick(self, *, now_ms, pose, observed_free, observed_at_ms):
        if self.stopped:
            return self.result(0., 0., self.stopped)
        if type(now_ms) is not int or self.last_time is not None and now_ms <= self.last_time:
            return self.stop('clock_not_increasing')
        if self.started is None:
            self.started = now_ms
        self.last_time = now_ms
        if now_ms-self.started > 20_000:
            return self.stop('mission_timeout')
        if (type(pose) is not dict or pose.get('state') != 'located'
                or pose.get('map_sha256') != self.map_sha or pose.get('calibration_sha256') != self.calibration_sha):
            return self.stop('fresh_matching_localisation_required')
        captured = pose.get('captured_at_ms')
        if (type(captured) is not int or not 0 <= now_ms-captured <= 500
                or self.last_capture is not None and captured < self.last_capture):
            return self.stop('localisation_stale_future_or_reordered')
        xyz = [pose.get(k) for k in ('x_m', 'y_m', 'yaw_rad')]
        if any(not bounded_number(v) for v in xyz):
            return self.stop('invalid_pose')
        x, y, yaw = xyz
        frame = pose.get('frame_key')
        if type(frame) is not str or not 1 <= len(frame) <= 128:
            return self.stop('frame_identity_required')
        if self.last_capture is not None and captured == self.last_capture:
            if frame != self.last_frame or tuple(xyz) != self.last_pose:
                return self.stop('replayed_or_changed_frame')
        elif frame in self.seen_frames:
            return self.stop('replayed_or_changed_frame')
        if len(self.seen_frames) >= 1024:
            return self.stop('frame_bound_exceeded')
        if self.last_pose and captured > self.last_capture:
            dt = (captured-self.last_capture)/1000
            if math.hypot(x-self.last_pose[0], y-self.last_pose[1]) > .25*dt+.10:
                return self.stop('localisation_jump')
        initial = self.last_pose is None
        self.last_pose, self.last_capture, self.last_frame = tuple(xyz), captured, frame
        self.seen_frames.add(frame)
        current = (math.floor(x/self.cell_m), math.floor(y/self.cell_m))
        if current not in self.allowed:
            return self.stop('outside_surveyed_clearance')
        # No obstacle sensing is fabricated from the stored map. Caller must
        # supply a separate new free-space observation for the local footprint.
        if (type(observed_at_ms) is not int or not 0 <= now_ms-observed_at_ms <= 250
                or type(observed_free) not in (set, frozenset) or len(observed_free) > 4096):
            return self.stop('live_clearance_missing_or_stale')
        target = self.path[self.index]
        tx, ty = ((target[0]+.5)*self.cell_m, (target[1]+.5)*self.cell_m)
        if initial and math.hypot(x-tx, y-ty) > .07:
            return self.stop('route_start_confirmation_required')
        if self.index:
            previous = self.path[self.index-1]
            px, py = ((previous[0]+.5)*self.cell_m, (previous[1]+.5)*self.cell_m)
            along = ((x-px)*(tx-px)+(y-py)*(ty-py))/self.cell_m
            across = abs((x-px)*(ty-py)-(y-py)*(tx-px))/self.cell_m
            if across > .08 or not -.07 <= along <= self.cell_m+.07:
                return self.stop('outside_current_route_segment')
        # Observe current/next footprint plus 35cm clearance, including unknown
        # cells. This deliberately refuses a map-only autonomous drive.
        radius = math.ceil(.35/self.cell_m)
        steps = max(1, math.ceil(math.hypot(tx-x, ty-y)/min(.05, self.cell_m/4)))
        swept = {(math.floor((x+(tx-x)*i/steps)/self.cell_m),
                  math.floor((y+(ty-y)*i/steps)/self.cell_m)) for i in range(steps+1)}
        if not swept.issubset(self.allowed):
            return self.stop('unsurveyed_route_corridor')
        needed = {(px+dx, py+dy) for px, py in swept
                  for dx in range(-radius, radius+1) for dy in range(-radius, radius+1)}
        if not needed.issubset(observed_free):
            return self.stop('obstacle_or_unobserved_footprint')
        dx, dy = tx-x, ty-y
        distance = math.hypot(dx, dy)
        if distance <= .07:
            if self.index == len(self.path)-1:
                return self.stop('arrived')
            self.index += 1
            return self.result(0., 0., 'waypoint_reached')
        speed = min(.15, distance*.8)
        world_x, world_y = dx/distance*speed, dy/distance*speed
        return self.result(math.cos(yaw)*world_x+math.sin(yaw)*world_y,
                           -math.sin(yaw)*world_x+math.cos(yaw)*world_y, 'following')
