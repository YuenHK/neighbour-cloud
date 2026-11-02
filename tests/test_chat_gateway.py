import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from edge_hub.app import app
from edge_hub.chat_gateway import (
    cloud_enabled,
    latest_user_text,
    local_chat_payload,
    modelscope_token,
    route_chat,
)


def test_local_payload_removes_airi_tools_and_action_prompt() -> None:
    payload = local_chat_payload(
        {
            "model": "qwen3:1.7b",
            "messages": [
                {"role": "system", "content": "Output <|ACT|>"},
                {"role": "user", "content": "你好"},
            ],
            "tools": [{"type": "function"}],
            "tool_choice": "auto",
            "stream": True,
        }
    )

    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert payload["messages"][0]["role"] == "system"
    assert "不要輸出 ACT" in payload["messages"][0]["content"]
    assert payload["messages"][1]["content"].endswith("/no_think")
from edge_hub.faq import OfflineFaq


def test_latest_user_text_supports_openai_text_parts() -> None:
    assert latest_user_text(
        {
            "messages": [
                {"role": "assistant", "content": "舊答案"},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "影像會否"}, {"type": "text", "text": "上雲？"}],
                },
            ]
        }
    ) == "影像會否 上雲？"


def test_faq_chat_completion_does_not_need_llm() -> None:
    response = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "qwen3.5:0.8b",
            "messages": [{"role": "user", "content": "相機影像會唔會傳上雲端？"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert "本機" in body["choices"][0]["message"]["content"]
    assert "影像" in body["choices"][0]["message"]["content"]


def test_faq_stream_is_openai_compatible_sse() -> None:
    response = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "qwen3.5:0.8b",
            "messages": [{"role": "user", "content": "講解智衛尖兵用途"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.startswith("data: {")]
    first_chunk = json.loads(lines[0].removeprefix("data: "))
    assert first_chunk["object"] == "chat.completion.chunk"
    assert "屋苑服務台" in first_chunk["choices"][0]["delta"]["content"]
    assert response.text.rstrip().endswith("data: [DONE]")


def test_modelscope_token_uses_local_app_data(monkeypatch, tmp_path) -> None:
    token_dir = tmp_path / "ZhiweiJianbing"
    token_dir.mkdir()
    (token_dir / "modelscope-token.txt").write_text("secret-token\n", encoding="utf-8")
    monkeypatch.delenv("MODELSCOPE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert modelscope_token() == "secret-token"
    assert cloud_enabled() is True


def test_local_mode_disables_cloud_even_with_token(monkeypatch) -> None:
    monkeypatch.setenv("MODELSCOPE_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("ZHIWEI_LLM_PROVIDER", "local")

    assert cloud_enabled() is False


def test_unknown_question_falls_back_to_local_when_cloud_fails(monkeypatch) -> None:
    cloud = AsyncMock(side_effect=ValueError("cloud unavailable"))
    local_result = object()
    local = AsyncMock(return_value=local_result)
    monkeypatch.setenv("MODELSCOPE_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("ZHIWEI_LLM_PROVIDER", "auto")
    monkeypatch.setattr("edge_hub.chat_gateway.proxy_to_modelscope", cloud)
    monkeypatch.setattr("edge_hub.chat_gateway.proxy_to_ollama", local)

    import asyncio

    result = asyncio.run(
        route_chat(
            {"model": "local", "messages": [{"role": "user", "content": "未收錄問題 xyz"}]},
            OfflineFaq(),
        )
    )

    assert result is local_result
    cloud.assert_awaited_once()
    local.assert_awaited_once()
