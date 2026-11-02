import re
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from edge_hub.app import OPERATOR_KEY, app


def test_health_reports_offline_faq() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["faq_entries"] >= 20


def test_system_status_reports_simulation_without_false_hardware_claims() -> None:
    response = TestClient(app).get("/api/v1/system-status")

    assert response.status_code == 200
    assert response.json()["robot_transport"] == "simulation"
    assert response.json()["hardware_acceptance"] is False


def test_vision_calibration_requires_operator() -> None:
    client = TestClient(app)

    assert client.post("/api/v1/vision/calibrate").status_code == 403
    response = client.post(
        "/api/v1/vision/calibrate", headers={"X-Operator-Key": OPERATOR_KEY}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "calibration_requested"


def test_operator_can_persistently_disable_vision(monkeypatch, tmp_path: Path) -> None:
    marker = tmp_path / "vision-enabled.txt"
    monkeypatch.setattr("edge_hub.app.VISION_ENABLE_FILE", marker)
    monkeypatch.setattr("edge_hub.app.vision_runtime.disable", lambda: None)
    client = TestClient(app)

    assert client.post("/api/v1/vision/disable").status_code == 403
    response = client.post(
        "/api/v1/vision/disable", headers={"X-Operator-Key": OPERATOR_KEY}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert marker.read_text(encoding="ascii") == "false\n"


def test_admin_page_uses_bounded_local_requests_and_loopback_navigation() -> None:
    response = TestClient(app).get("/admin")

    assert response.status_code == 200
    assert "屋苑服務台 · 管理工作台" in response.text
    assert "ZhiweiAdminRequest.json('/api/v1/events?limit=100')" in response.text
    assert 'id="faqForm"' not in response.text
    assert "workspace-navigation.js" in response.text
    assert "redirect: 'error'" in response.text
    assert "'/api/v1/system-status'" in response.text
    assert "'/api/v1/vision/status'" in response.text
    assert "'/api/v1/robot/status'" in response.text
    assert "ZhiweiAdminStatus.read()" in response.text
    assert "ZhiweiAdminStatus.format(snapshot)" in response.text
    links = re.findall(r'href="([^"]+)"', response.text)
    assert all((link.startswith(('/', '#')) and not link.startswith('//'))
               or link == 'http://127.0.0.1:4173' for link in links)
    assert "https://" not in response.text


def test_console_chat_origin_uses_existing_memory_gate_and_rejects_external_origin() -> None:
    client = TestClient(app)
    # Explicit memory always requires pairing, even from the local console.
    payload = {'messages': [{'role': 'user', 'content': '記住：公開測試，不應寫入'}]}
    response = client.post('/v1/chat/completions', headers={'Origin': 'http://127.0.0.1:8000'},
                           json=payload)
    assert response.status_code == 403
    assert '請先在本機記憶後台授權' in response.json()['detail']
    external = client.post('/v1/chat/completions', headers={'Origin': 'https://example.com'},
                           json=payload)
    assert external.status_code == 403
    assert '來源不允許' in external.json()['detail']


def test_create_and_list_event() -> None:
    client = TestClient(app)
    payload = {"id": f"evt-{uuid4().hex}", "type": "leak_detected", "zone": "A1", "at_ms": 10,
               "severity": "warning", "details": {"wet": True}}
    assert client.post("/api/v1/events", headers={"X-Operator-Key": OPERATOR_KEY}, json=payload).status_code == 201
    events = client.get("/api/v1/events").json()
    created = next(event for event in events if event["id"] == payload["id"])
    assert created == {**payload, "status": "pending"}
    assert payload["id"] in {
        event["id"] for event in client.get("/api/v1/events?since_ms=10").json()
    }
    assert payload["id"] not in {
        event["id"] for event in client.get("/api/v1/events?since_ms=11").json()
    }


def test_event_websocket_receives_new_event() -> None:
    payload = {
        "id": f"evt-{uuid4().hex}",
        "type": "leak_detected",
        "zone": "A1",
        "at_ms": 12,
        "severity": "warning",
    }
    with TestClient(app) as client, client.websocket_connect("/ws/events") as websocket:
        assert client.post("/api/v1/events", headers={"X-Operator-Key": OPERATOR_KEY}, json=payload).status_code == 201
        received = websocket.receive_json()

    assert received["id"] == payload["id"]


def test_operator_can_update_status_but_resident_cannot() -> None:
    client = TestClient(app)
    event_id = f"evt-{uuid4().hex}"
    client.post(
        "/api/v1/events",
        headers={"X-Operator-Key": OPERATOR_KEY},
        json={
            "id": event_id,
            "type": "robot_fault",
            "zone": "A1",
            "at_ms": 20,
            "severity": "critical",
        },
    )

    assert client.patch(
        f"/api/v1/events/{event_id}", json={"status": "resolved"}
    ).status_code == 403
    response = client.patch(
        f"/api/v1/events/{event_id}",
        json={"status": "resolved"},
        headers={"X-Operator-Key": OPERATOR_KEY},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_clear_events_also_deletes_referenced_evidence(monkeypatch, tmp_path: Path) -> None:
    client = TestClient(app)
    event_id = f"evt-{uuid4().hex}"
    evidence_name = f"{event_id}-blurred.jpg"
    evidence = tmp_path / "events" / evidence_name
    evidence.parent.mkdir()
    evidence.write_bytes(b"blurred")
    monkeypatch.setattr("edge_hub.app.EVENT_DATA_ROOT", tmp_path)
    client.post(
        "/api/v1/events",
        headers={"X-Operator-Key": OPERATOR_KEY},
        json={
            "id": event_id,
            "type": "litter_detected",
            "zone": "A1",
            "at_ms": 30,
            "severity": "notice",
            "evidence": f"events/{evidence_name}",
        },
    )

    response = client.delete("/api/v1/events", headers={"X-Operator-Key": OPERATOR_KEY})

    assert response.status_code == 200
    assert response.json()["deleted_evidence"] == 1
    assert not evidence.exists()
