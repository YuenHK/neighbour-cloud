import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

ROOT = Path(__file__).parents[1]


def schema(name: str) -> dict:
    return json.loads((ROOT / "contracts" / name).read_text())


def test_litter_event_is_valid() -> None:
    validate(
        {"id": "evt-1", "type": "litter_detected", "zone": "A1", "at_ms": 1,
         "severity": "notice", "evidence": "events/evt-1-blurred.jpg"},
        schema("event.schema.json"),
    )


def test_raw_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate(
            {"id": "evt-2", "type": "litter_detected", "zone": "A1", "at_ms": 2,
             "severity": "notice", "evidence": "raw/frame.jpg"},
            schema("event.schema.json"),
        )


def test_motor_pwm_command_is_not_in_public_contract() -> None:
    with pytest.raises(ValidationError):
        validate({"seq": 1, "type": "set_pwm", "ttl_ms": 500}, schema("command.schema.json"))
