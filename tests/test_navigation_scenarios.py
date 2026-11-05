import pytest

from edge_hub.navigation_scenarios import SCENARIOS, World, replay, vehicle_step


def test_occluded_space_cannot_be_reported_as_observed_free():
    world = World()
    free = world.sense((1.25, 1.25), {(3, 2)})
    assert (3, 2) not in free
    assert (4, 2) not in free
    assert (2, 3) in free
    assert (9, 7) not in free


def test_corner_touch_does_not_see_through_two_walls():
    assert not World().ray_clear((1.25, 1.25), (2.25, 2.25), {(3, 2)})
    assert World().ray_clear((1.25, 1.25), (2.25, 2.25), set())


@pytest.mark.parametrize('name', SCENARIOS)
def test_scene_has_zero_collisions_and_bounded_stop(name):
    result = replay(name)
    assert result['hardware_commands'] == 0 and result['execution_enabled'] is False
    assert result['collisions'] == 0
    assert result['maximum_speed_mps'] <= .15
    assert result['minimum_body_clearance_m'] > 0
    if name == 'clear_route':
        assert result['final_state'] == 'arrived'
        assert abs(result['trace'][-1]['x_m']-2.75) < .09
    else:
        assert result['final_state'] not in ('arrived', 'replay_bound')
        # A hazard beyond the current segment becomes relevant on the next
        # waypoint transition; that transition already requests zero velocity.
        assert 0 <= result['first_stop_ms']-result['injection_ms'] <= 100
        assert result['fully_stopped_ms']-result['first_stop_ms'] <= 300
        tail = [row for row in result['trace'] if row['t_ms'] >= result['first_stop_ms']]
        assert all(row['command_speed_mps'] == 0 for row in tail)


def test_no_unknown_scenario_is_executed():
    with pytest.raises(ValueError):
        replay('connect_s1')


def test_emergency_obstacle_really_interrupts_maximum_speed():
    result = replay('emergency_at_speed')
    assert result['speed_before_injection_mps'] == .15
    assert result['first_stop_ms'] == result['injection_ms']
    assert result['fully_stopped_ms'] - result['first_stop_ms'] == 300
    assert result['minimum_body_clearance_m'] > .25


def test_braking_is_not_instantaneous_and_matches_ramp_integration():
    position, velocity = (1., 1.), (.15, 0.)
    distances = []
    for _ in range(3):
        position, velocity, samples = vehicle_step(position, velocity, (0., 0.))
        distances.append(position[0]-1.)
        assert len(samples) == 5
    assert distances[0] == pytest.approx(.012)
    assert distances[1] > distances[0]
    assert velocity == (0., 0.)
    # Three100ms control intervals, continuous bounded ramps at each interval.
    assert distances[-1] == pytest.approx(.0195)


@pytest.mark.parametrize('updates', [{'cell_m': 0}, {'width': 100}, {'height': True}, {'cell_m': float('nan')}])
def test_unbounded_world_input_rejected(updates):
    with pytest.raises(ValueError):
        World(**updates)
