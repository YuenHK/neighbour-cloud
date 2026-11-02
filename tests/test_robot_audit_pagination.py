"""Read-only audit pagination against in-memory simulation, never hardware."""
import pytest

from edge_hub.robot_control import ControlError, RobotController


@pytest.mark.parametrize('limit', [-1, 0, 201, 2**63, True, 1.0, '2', None])
def test_controller_rejects_unbounded_or_coerced_limits(limit):
    controller = RobotController()
    try:
        with pytest.raises(ControlError, match='^invalid_audit_limit$') as error:
            controller.audit(limit)
        assert error.value.status == 422
        assert controller.audit() == []
        assert not controller.stop_latched
    finally:
        controller.close()


@pytest.mark.parametrize('cursor', [-1, 0, 2**63, True, 1.0, '2'])
def test_controller_rejects_invalid_cursor_without_audit_mutation(cursor):
    controller = RobotController()
    try:
        with pytest.raises(ControlError, match='^invalid_audit_cursor$') as error:
            controller.audit(before_id=cursor)
        assert error.value.status == 422
        assert controller.audit() == []
    finally:
        controller.close()


def test_same_time_history_pages_survive_new_insert_and_id_gaps():
    controller = RobotController(wall_clock=lambda: 1000)
    try:
        controller.db.executemany('INSERT INTO control_audit(id,at_ms,action,reason) VALUES (?,1000,?,?)',
                                  [(i, 'stop', 'fixture') for i in (1, 3, 4, 8, 10)])
        controller.db.commit()
        page = controller.audit(2)
        assert [row['id'] for row in page] == [10, 8]
        controller.software_stop()  # Newer record cannot shift the older-history cursor.
        history = list(page)
        while page:
            page = controller.audit(2, before_id=page[-1]['id'])
            history.extend(page)
        assert [row['id'] for row in history] == [10, 8, 4, 3, 1]
        assert controller.audit(200, before_id=1) == []
        assert len(controller.audit()) == 6
        assert controller.audit(1, before_id=2**63 - 1)[0]['id'] == 11
    finally:
        controller.close()


def test_default_and_max_page_are_bounded():
    controller = RobotController()
    try:
        controller.db.executemany('INSERT INTO control_audit(at_ms,action,reason) VALUES (1,?,?)',
                                  [('stop', 'fixture')] * 205)
        controller.db.commit()
        assert len(controller.audit()) == 100
        assert len(controller.audit(200)) == 200
        assert len(controller.audit(200, before_id=6)) == 5
    finally:
        controller.close()
