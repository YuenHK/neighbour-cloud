from simulator.robot import RobotSimulator, RobotState


def test_patrol_to_stair_and_back() -> None:
    robot = RobotSimulator()
    robot.command("start_patrol", now_ms=0)
    robot.observe(stair_marker=True, aligned=True, now_ms=100)
    assert robot.state is RobotState.STAIR_ASCEND
    robot.observe(stair_complete=True, now_ms=400)
    assert robot.state is RobotState.PATROL


def test_deadman_stops_after_500_ms() -> None:
    robot = RobotSimulator()
    robot.command("start_patrol", now_ms=0)
    robot.tick(now_ms=501)
    assert robot.state is RobotState.SAFE_STOP


def test_two_stair_failures_latch_fault() -> None:
    robot = RobotSimulator()
    robot.command("start_patrol", now_ms=0)
    for at in (100, 200):
        robot.observe(stair_marker=True, aligned=False, now_ms=at)
    assert robot.state is RobotState.FAULT
