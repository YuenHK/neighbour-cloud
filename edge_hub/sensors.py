from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SustainedThreshold:
    threshold: float
    hold_ms: int = 500
    active_since_ms: int | None = None
    triggered: bool = False

    def update(self, value: float, now_ms: int) -> bool:
        if value < self.threshold:
            self.active_since_ms = None
            self.triggered = False
            return False
        if self.active_since_ms is None:
            self.active_since_ms = now_ms
            return False
        if not self.triggered and now_ms - self.active_since_ms >= self.hold_ms:
            self.triggered = True
            return True
        return False


@dataclass
class EnvironmentSensorSimulator:
    leak: SustainedThreshold
    temperature: SustainedThreshold
    maximum_safe_drill_celsius: float = 45.0

    @classmethod
    def default(cls) -> EnvironmentSensorSimulator:
        return cls(
            leak=SustainedThreshold(threshold=0.7),
            temperature=SustainedThreshold(threshold=35.0),
        )

    def update_leak(self, wetness: float, now_ms: int) -> bool:
        if not 0.0 <= wetness <= 1.0:
            raise ValueError("wetness must be between 0 and 1")
        return self.leak.update(wetness, now_ms)

    def update_temperature_drill(self, celsius: float, now_ms: int, *, drill: bool) -> bool:
        if not drill:
            raise ValueError("temperature input must be explicitly marked as a drill")
        if celsius >= self.maximum_safe_drill_celsius:
            raise ValueError("temperature drill must remain below 45 C")
        return self.temperature.update(celsius, now_ms)
