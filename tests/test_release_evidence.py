import struct
from types import SimpleNamespace

from ep_runtime.body_snapshot import BodySnapshot, install_body_decoder
from ep_runtime.release_evidence import ReleaseEvidence


def sample(model, i, *, x=0., yaw=0., velocity=0., angle=0, rpm=0, skip=None):
    now = i / 10
    for topic, values in [('position', (x, 0., 0.)), ('attitude', (yaw, 0., 0.)),
                          ('velocity', (velocity, 0., 0., velocity, 0., 0.))]:
        if topic != skip:
            model.add_body(BodySnapshot(topic, values, now, i + 1), now)
    model.add_wheels(now, [rpm]*4, [angle % 32768]*4)
    return model.evaluate(now)


def ready():
    model = ReleaseEvidence()
    for i in range(25):
        sample(model, i)
    assert model.evaluate(2.4)
    return model


def test_body_snapshot_is_immutable_and_repeated_reads_never_transform_position():
    subject = install_body_decoder(SimpleNamespace(), 'position', clock=lambda: 1.)
    subject.decode(struct.pack('<fff', 2., 3., 4.))
    first = subject.data_info()
    assert subject.data_info() is first
    assert first.values == (2., 3., 4.)
    subject.decode(struct.pack('<fff', 5., 6., 7.))
    assert first.values == (2., 3., 4.)
    assert subject.data_info().serial == first.serial + 1
    subject.decode(b'bad')
    assert subject.data_info().values is None


def test_motor_micro_adjustment_is_not_body_displacement():
    model = ReleaseEvidence()
    for i in range(60):
        # Motor count drifts past the old 4-count anchor, stationary body/velocity.
        sample(model, i, angle=i // 3, rpm=(-4 if i % 2 else 4))
    assert model.evaluate(5.9)
    assert model.body_reference == (0, 0, 0)
    assert max(model.metrics['wheel_path_rpm']) < 1


def test_body_data_required_no_fallback_to_encoder_only():
    model = ReleaseEvidence()
    for i in range(30):
        assert not sample(model, i, skip='position')
    assert model.reason == 'waiting_body_telemetry'


def test_body_slow_departure_cannot_move_reference_or_recover_by_waiting():
    model = ready()
    origin = model.body_reference
    for i in range(25, 75):
        sample(model, i, x=(i - 24) * .0001)
    assert model.first_block['reason'] == 'confirmed_body_departure'
    for i in range(75, 110):
        sample(model, i)
    assert not model.evaluate(10.9)
    assert model.body_reference == origin


def test_wheel_motion_with_frozen_body_still_blocks_and_net_cancellation_is_not_zero():
    for angles in (lambda i: i * 512, lambda i: (i % 2) * 512):
        model = ReleaseEvidence()
        for i in range(25):
            sample(model, i, angle=angles(i))
        assert not model.evaluate(2.4)
        assert model.reason == 'wheel_rotation_in_window'


def test_velocity_and_yaw_independently_block_even_with_zero_rpm():
    for extra in ({'velocity': .02}, {'yaw': .2}):
        model = ready()
        for i in range(25, 50):
            sample(model, i, **extra)
        assert not model.evaluate(4.9)


def test_release_epoch_resets_motor_origin_but_preserves_body_origin_and_excludes_old_data():
    model = ready()
    model.transition(2.45, 'released')
    model.add_body(BodySnapshot('position', (1., 0., 0.), 2.4, 999), 2.5)
    assert not model.body['position']
    for i in range(25, 52):
        sample(model, i, angle=24000)
    assert model.evaluate(5.1)
    assert model.body_reference == (0, 0, 0)
    for i in range(52, 56):
        sample(model, i, x=.01, angle=24000)
    assert not model.evaluate(5.5)
    assert model.first_block


def test_duplicate_and_stale_topics_cannot_keep_old_body_proof_fresh():
    model = ready()
    frame = BodySnapshot('position', (0.,)*3, 2.4, 25)
    model.add_body(frame, 2.6)
    assert model.body['position'][-1][0] == 2.4
    assert not model.evaluate(2.7)
    model.add_body(BodySnapshot('position', (float('nan'), 0., 0.), 2.7, 26), 2.7)
    assert not model.body['position']


def test_latest_wheel_motion_cannot_hide_behind_lagging_body_window():
    model = ready()
    model.add_wheels(2.5, [0]*4, [500]*4)
    assert not model.evaluate(2.5)
    assert model.reason == 'wheel_rotation_in_window'


def test_intermediate_new_rpm_anomaly_cannot_hide_behind_body_topic_lag():
    model = ready()
    model.add_wheels(2.5, [19]*4, [0]*4)
    model.add_wheels(2.6, [0]*4, [0]*4)
    assert not model.evaluate(2.6)
    assert model.reason == 'wheel_rpm_quality'


def test_yaw_wrap_across_release_does_not_invent_full_revolution():
    model = ReleaseEvidence()
    for i in range(25):
        sample(model, i, yaw=179.98)
    assert model.evaluate(2.4)
    model.transition(2.45, 'released')
    for i in range(25, 52):
        sample(model, i, yaw=-179.98)
    assert model.evaluate(5.1)


def test_public_unit_boundaries_are_integer_based_not_float_roundoff():
    model = ready()
    for i in range(25, 50):
        sample(model, i, x=.001, yaw=.1)
    assert model.evaluate(4.9)
    assert model.first_block is None


def test_window_start_keeps_real_predecessor_for_isolated_spike():
    model = ReleaseEvidence()
    for i in range(25):
        sample(model, i, rpm=12 if i == 1 else 0)
    assert model.evaluate(2.4)
    assert model.metrics['wheel_rpm_outside_normal_samples'] == [1]*4


def test_body_lag_does_not_turn_an_already_bracketed_spike_into_an_unresolved_tail():
    model = ready()
    model.add_wheels(2.5, [12]*4, [0]*4)
    assert not model.evaluate(2.5)  # latest sample has no successor yet
    assert model.metrics['rpm_blocker']['at_latest_sample']
    model.add_wheels(2.6, [0]*4, [0]*4)
    assert model.evaluate(2.6)  # same raw spike, unchanged limits, now corroborated


def test_rolling_trim_retains_exactly_the_predecessor_needed_by_the_body_window():
    model = ReleaseEvidence()
    for i in range(31):
        sample(model, i, rpm=12 if i == 5 else 0)
    assert model.evaluate(3.)
    assert model.wheels[0][0] < model.body['position'][0][0]


def test_bad_real_neighbours_and_bursts_remain_blocked_at_window_edges():
    for mode in ('angle', 'burst', 'gap'):
        model = ready()
        model.add_wheels(2.5, [12]*4, [3 if mode == 'angle' else 0]*4)
        model.add_wheels(2.8 if mode == 'gap' else 2.6,
                         [12 if mode == 'burst' else 0]*4, [0]*4)
        assert not model.evaluate(2.6 if mode != 'gap' else 2.8)


def test_more_than_quarter_of_samples_or_absolute_19_rpm_still_fails():
    for speeds in (lambda i: 19 if i == 3 else 0, lambda i: 12 if i % 3 == 1 else 0):
        model = ReleaseEvidence()
        for i in range(25):
            sample(model, i, rpm=speeds(i))
        assert not model.evaluate(2.4)
        assert model.reason == 'wheel_rpm_quality'
