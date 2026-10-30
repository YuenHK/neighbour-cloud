from __future__ import annotations

from pathlib import Path

from edge_hub.events import Event


def delete_event_evidence(events: list[Event], data_root: Path) -> int:
    root = data_root.resolve()
    candidates: list[Path] = []
    for event in events:
        if event.evidence is None:
            continue
        candidate = (root / event.evidence).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("evidence path escapes data root") from error
        if candidate.is_file():
            candidates.append(candidate)

    deleted = 0
    for candidate in dict.fromkeys(candidates):
        try:
            candidate.unlink()
        except FileNotFoundError:
            continue  # Another cleanup may have removed it after preflight.
        deleted += 1
    return deleted
