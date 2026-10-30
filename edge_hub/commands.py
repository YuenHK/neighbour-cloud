from pydantic import BaseModel

ALLOWED = {"start_patrol", "pause", "resume", "enter_stair", "cancel_mission", "keepalive"}


class Command(BaseModel):
    seq: int
    type: str
    ttl_ms: int


def validate_command(command: Command) -> Command:
    if command.type not in ALLOWED:
        raise ValueError(f"command not allowed: {command.type}")
    if not 100 <= command.ttl_ms <= 500:
        raise ValueError("ttl_ms outside safe range")
    return command
