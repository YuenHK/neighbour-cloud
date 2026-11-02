from fastapi.testclient import TestClient

from edge_hub.app import app


def test_short_project_introduction_is_short_and_reviewed() -> None:
    from edge_hub.faq import OfflineFaq

    result = OfflineFaq().query('你好，我係 Anson，請簡短介紹智衛尖兵。')
    assert result.source_id == 'project-purpose'
    assert result.answer.startswith('我係屋苑服務台')
    assert len(result.answer) <= 30
    # Match known project-name homophones without altering the raw transcript.
    assert OfflineFaq().query('请简短介绍智慧煎兵').source_id == 'project-purpose'


def test_offline_faq_has_twenty_reviewable_entries() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/faq")

    assert response.status_code == 200
    assert len(response.json()) >= 20


def test_offline_faq_answers_privacy_without_llm() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/faq/query", json={"question": "相機影像會唔會傳上雲端？"}
    )

    assert response.status_code == 200
    result = response.json()
    assert result["matched"] is True
    assert result["source_id"] in {"offline", "privacy-image"}
    assert "雲端" in result["answer"] or "原始畫面" in result["answer"]


def test_offline_faq_uses_safe_fallback_for_unknown_question() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/faq/query", json={"question": "今日邊一隊足球會贏？"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "matched": False,
        "answer": "呢方面我暫時未有確認資料。你講多啲想了解嘅事，我幫你整理同跟進，唔使你自己搵同事。",
        "source_id": None,
        "category": None,
    }


def test_temperature_answer_does_not_claim_fire_detection() -> None:
    client = TestClient(app)

    result = client.post(
        "/api/v1/faq/query", json={"question": "偵測到火警點算？"}
    ).json()

    assert result["matched"] is True
    assert "並非正式火警偵測" in result["answer"]
