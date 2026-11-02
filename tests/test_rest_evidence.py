import struct
from types import SimpleNamespace

from ep_runtime.esc_snapshot import install_snapshot_decoder
from ep_runtime.rest_evidence import RestEvidence


def feed(evidence, speeds, angles, count=26, start=0.):
    for index in range(count):
        evidence.add(start + index * .1, speeds(index), angles(index))
    return evidence.evaluate()


def test_sdk_style_mutable_buffers_cannot_change_a_published_snapshot():
    subject = install_snapshot_decoder(SimpleNamespace(), clock=lambda: 12.)
    raw = bytearray(struct.pack('<hhhhhhhhIIIIBBBB', *range(16)))
    subject.decode(raw)
    first = subject.data_info()
    raw[:] = bytes(len(raw))
    subject.decode(raw)
    assert first.values == (tuple(range(4)), tuple(range(4, 8)), tuple(range(8, 12)), tuple(range(12, 16)))
    assert first.decoded_at == 12.
    assert subject.data_info().values == ((0,)*4,)*4
    subject.decode(b'invalid')
    assert subject.data_info().values is None


def test_observed_signed_rpm_and_small_encoder_oscillation_are_not_directional_drift():
    # Synthetic replay of the four observed value groups, not a full live trace.
    speeds = [(-1, 4, -1, -3), (-3, 2, 0, 0), (1, 1, -2, 1), (0, -6, -15, 0)]
    angles = [(14860, 28543, 786, 2421), (14861, 28542, 787, 2421),
              (14860, 28541, 785, 2422), (14859, 28543, 787, 2419)]
    evidence = RestEvidence()
    assert feed(evidence, lambda i: speeds[i % 4], lambda i: angles[i % 4], count=25)
    assert evidence.metrics['isolated_rpm_outliers'][2] > 0
    assert evidence.metrics['encoder_span_counts'] == [2, 2, 2, 3]
    assert evidence.RPM_LIMIT == 6


def test_real_encoder_travel_is_rejected_even_when_reported_rpm_is_zero():
    evidence = RestEvidence()
    assert not feed(evidence, lambda _: (0,)*4, lambda i: (i, 0, 0, 0))
    assert evidence.reason == 'encoder_excursion'


def test_slow_directional_creep_is_rejected_before_it_exceeds_encoder_span():
    evidence = RestEvidence()
    assert not feed(evidence, lambda _: (0,)*4, lambda i: (i // 7, 0, 0, 0))
    assert evidence.reason == 'encoder_directional_drift'


def test_continuous_opposite_rpm_cannot_cancel_to_zero():
    evidence = RestEvidence()
    assert not feed(evidence, lambda i: (15 if i % 2 else -15, 0, 0, 0), lambda _: (0,)*4)
    assert evidence.reason == 'rpm_inconsistent'


def test_spike_on_current_frame_is_unresolved_and_cannot_enable_release():
    evidence = RestEvidence()
    assert not feed(evidence, lambda i: (15 if i == 25 else 0, 0, 0, 0), lambda _: (0,)*4)
    assert evidence.reason == 'rpm_unresolved_spike'


def test_isolated_rpm_spike_with_encoder_travel_cannot_be_filtered():
    evidence = RestEvidence()
    assert not feed(evidence, lambda i: (15 if i == 12 else 0, 0, 0, 0),
                    lambda i: (3 if i == 12 else 0, 0, 0, 0))
    assert evidence.reason == 'rpm_unresolved_spike'


def test_encoder_wrap_is_unwrapped_and_not_a_full_turn_jump():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda i: ((32767 if i % 2 else 0), 0, 0, 0))
    assert evidence.metrics['encoder_span_counts'][0] == 1


def test_established_reference_cannot_follow_slow_accumulated_drift():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4)
    for index in range(100):
        evidence.add(2.6 + index * .1, (0,)*4, (index // 15, 0, 0, 0))
        evidence.evaluate()
    assert not evidence.evaluate()
    assert evidence.reason == 'encoder_drift_since_rest'
    # Returning to the old position must not erase the detected excursion.
    assert not feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4, start=13.)


def test_gap_after_reference_does_not_silently_learn_a_new_origin():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4)
    evidence.invalidate('sample_gap')
    assert not feed(evidence, lambda _: (0,)*4, lambda _: (100,)*4, start=5.)


def test_large_speed_spike_is_never_filtered_even_with_frozen_angles():
    evidence = RestEvidence()
    assert not feed(evidence, lambda i: (600 if i == 12 else 0, 0, 0, 0), lambda _: (0,)*4)
    assert evidence.reason == 'rpm_inconsistent'


def test_unknown_rpm_anomaly_requires_a_full_new_window_without_changing_reference():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4)
    origin = evidence.anchor
    evidence.add(2.6, (19, 0, 0, 0), (0,)*4)
    assert not evidence.evaluate()
    original = dict(evidence.first_signal_anomaly)
    assert original['max_abs_rpm'] == 19 and evidence.blocked is None
    assert not feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4, start=2.7, count=21)
    assert evidence.signal_recovery_pending
    assert feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4, start=4.8, count=6)
    assert evidence.anchor == origin
    assert evidence.first_signal_anomaly == original
    assert not evidence.signal_recovery_pending and evidence.signal_recoveries == 1
    assert evidence.MAX_ISOLATED_RPM == 18 and evidence.RPM_LIMIT == 6


def test_sustained_rpm_never_passes_while_present_and_requires_complete_new_window():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4)
    for index in range(26):
        stamp = 2.6 + index * .1
        evidence.add(stamp, (19, 0, 0, 0), (0,)*4)
        assert not evidence.evaluate()
    assert evidence.signal_recovery_pending
    assert not feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4, start=5.2, count=21)
    assert feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4, start=7.3, count=6)
    assert evidence.anchor == (0.,)*4


def test_data_gap_requires_fresh_evidence_at_same_origin_and_keeps_anomaly_record():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100,)*4)
    origin = evidence.anchor
    evidence.invalidate('sample_gap')
    assert not evidence.evaluate()
    assert not feed(evidence, lambda _: (0,)*4, lambda _: (100,)*4, start=5., count=15)
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100,)*4, start=6.5, count=9)
    assert evidence.anchor == origin
    assert evidence.first_signal_anomaly['reason'] == 'sample_gap'


def test_provisional_tail_spike_is_neither_a_pass_nor_a_permanent_failure():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (0,)*4)
    evidence.add(2.6, (15, 0, 0, 0), (0,)*4)
    assert not evidence.evaluate()
    assert not evidence.signal_recovery_pending
    evidence.add(2.7, (0,)*4, (0,)*4)
    assert evidence.evaluate()


def test_far_apart_opposite_extremes_do_not_become_a_permanent_drift():
    evidence = RestEvidence()
    jitter = (-2, 0, 0, 0, 2, 0, 0, 0)
    assert feed(evidence, lambda _: (0,)*4, lambda i: (100 + jitter[i % 8], 0, 0, 0))
    origin = evidence.anchor
    assert origin == (100., 0., 0., 0.)
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0), start=2.6, count=31)
    evidence.add(5.7, (0,)*4, (103, 0, 0, 0))
    assert evidence.evaluate()  # old lifetime min=98, max=103 falsely latched
    assert evidence.blocked is None
    assert evidence.anchor == origin
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0), start=5.8, count=31)
    evidence.add(8.9, (0,)*4, (97, 0, 0, 0))
    assert evidence.evaluate()
    assert evidence.metrics['encoder_span_counts'][0] == 3
    assert evidence.anchor == origin
    assert evidence.MAX_SPAN == 4 and evidence.RPM_LIMIT == 6


def test_single_unresolved_angle_jump_blocks_until_a_clean_window_without_moving_reference():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0))
    origin = evidence.anchor
    evidence.add(2.6, (0,)*4, (105, 0, 0, 0))
    assert not evidence.evaluate()
    assert evidence.reason == 'encoder_excursion' and evidence.blocked is None
    assert not feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0), start=2.7, count=21)
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0), start=4.8, count=26)
    assert evidence.anchor == origin


def test_persistent_reference_departure_is_latched_with_first_cause_and_live_metrics():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0))
    for stamp in (2.6, 2.7):
        evidence.add(stamp, (0,)*4, (105, 0, 0, 0))
        assert not evidence.evaluate()
        assert evidence.blocked is None
    evidence.add(2.8, (0,)*4, (105, 0, 0, 0))
    assert not evidence.evaluate()
    cause = dict(evidence.blocked_evidence)
    assert cause['kind'] == 'sustained_reference_excursion'
    assert cause['offset_counts'] == 5 and cause['confirmed_samples'] == 3
    assert cause['confirmed_ms'] == 200
    assert not feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0), start=2.9, count=31)
    assert evidence.blocked_evidence == cause
    assert evidence.metrics['encoder_span_counts'][0] == 0
    assert evidence.metrics['encoder_center_counts'][0] == 100
    assert evidence.metrics['encoder_reference_offset_counts'][0] == 0
    assert evidence.reason == 'encoder_drift_since_rest'


def test_alternating_unknown_excursions_cannot_prove_rest_or_confirm_one_way_drift():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0))
    for index in range(12):
        evidence.add(2.6 + index * .1, (0,)*4, (105 if index % 2 else 95, 0, 0, 0))
        assert not evidence.evaluate()
    assert evidence.blocked is None  # unresolved oscillation still blocks the window
    assert evidence.reason == 'encoder_excursion'


def test_three_fast_samples_are_not_two_hundred_milliseconds_of_motion():
    evidence = RestEvidence()
    assert feed(evidence, lambda _: (0,)*4, lambda _: (100, 0, 0, 0))
    for index in range(3):
        evidence.add(2.6 + index * .01, (0,)*4, (105, 0, 0, 0))
        assert not evidence.evaluate()
    assert evidence.blocked is None
    for index in range(3, 22):
        evidence.add(2.6 + index * .01, (0,)*4, (105, 0, 0, 0))
        evidence.evaluate()
    assert evidence.reason == 'encoder_drift_since_rest'
