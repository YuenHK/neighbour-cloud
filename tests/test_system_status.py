from edge_hub.system_status import local_system_status


def test_status_does_not_claim_missing_model_or_hardware(tmp_path) -> None:
    status = local_system_status(tmp_path)

    assert status["vision_model"]["configured"] is False
    assert status["camera_processing"] == "local-only"
    assert status["raw_image_persistence"] == "forbidden"
    assert status["robot_transport"] == "simulation"
    assert status["hardware_acceptance"] is False


def test_configured_port_is_not_proof_of_connected_hardware(monkeypatch, tmp_path):
    monkeypatch.setenv('ZHIWEI_ROBOT_PORT', 'COM3')
    status = local_system_status(tmp_path)
    assert status['robot_transport'] == 'simulation'
    assert status['robot_connected'] is False
