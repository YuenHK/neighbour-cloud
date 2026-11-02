import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_local_profile_has_required_local_providers() -> None:
    profile = json.loads(
        (PROJECT_ROOT / "config" / "airi-local-profile.json").read_text(encoding="utf-8")
    )

    assert profile["version"] == 1
    assert profile["audio"]["enableInput"] is False
    assert profile["providers"]["chat"]["id"] == "openai-compatible"
    assert profile["providers"]["chat"]["model"] == "gemma-4-26b-a4b-it"
    assert profile["providers"]["vision"]["id"] == "vision-ollama"
    assert profile["providers"]["vision"]["thinking"] is False
    assert profile["providers"]["transcription"]["model"] == "sensevoice-yue"
    assert profile["providers"]["speech"]["model"] == "azure-hiumaan-f0"
    assert profile["providers"]["speech"]["voice"] == "zh-HK-HiuMaanNeural"
    assert profile["hearing"]["vadThreshold"] == 0.15
    assert profile["hearing"]["minSilenceDurationMs"] == 1200
    assert profile["hearing"]["minSpeechDurationMs"] == 250
    assert profile["hearing"]["voiceMergeDelayMs"] == 500
    assert profile["hearing"]["minVoiceTextLength"] == 1

    for provider in profile["providers"].values():
        assert provider["baseUrl"].startswith("http://127.0.0.1:")
        assert provider["baseUrl"].endswith("/")


def test_bootstrap_writes_all_active_module_keys() -> None:
    bootstrap = (PROJECT_ROOT / "airi_overlay" / "local-profile-bootstrap.ts").read_text(
        encoding="utf-8"
    )

    required_keys = {
        "settings/credentials/providers",
        "settings/providers/added",
        "settings/consciousness/active-provider",
        "settings/consciousness/active-model",
        "settings/vision/active-provider",
        "settings/vision/active-model",
        "settings/hearing/active-provider",
        "settings/hearing/active-model",
        "settings/speech/active-provider",
        "settings/speech/active-model",
        "settings/speech/voice",
    }

    for key in required_keys:
        assert key in bootstrap


def test_bootstrap_explicitly_disables_previously_enabled_microphone() -> None:
    bootstrap = (PROJECT_ROOT / "airi_overlay" / "local-profile-bootstrap.ts").read_text(
        encoding="utf-8"
    )
    assignment = "setValue('settings/audio/input/enabled', profile.audio?.enableInput === true)"
    assert assignment in bootstrap
    assert bootstrap.index(assignment) < bootstrap.index('if (!profile.audio?.enableInput)')


def test_old_microphone_diagnostic_is_retired_without_capture_code() -> None:
    diagnostic = (
        PROJECT_ROOT / "airi_overlay" / "microphone-diagnostic.html"
    ).read_text(encoding="utf-8")

    assert 'admin#settings' in diagnostic
    assert 'http-equiv="refresh"' in diagnostic
    assert "getUserMedia" not in diagnostic
    assert "MediaRecorder" not in diagnostic
    assert "localStorage" not in diagnostic
    assert "indexedDB" not in diagnostic
