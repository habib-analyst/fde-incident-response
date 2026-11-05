"""Deterministic clock and ID generation."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone


class DeterministicClock:
    """Injected clock. Starts at a fixed instant, advances only when told."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0, minutes: float = 0, hours: float = 0) -> datetime:
        self._now = self._now + timedelta(seconds=seconds, minutes=minutes, hours=hours)
        return self._now

    def set(self, when: datetime) -> None:
        self._now = when


class SequentialIds:
    """Seeded, sequential IDs: e.g. trace-0001, span-0001."""

    def __init__(self, start: int = 1):
        self._counters: dict[str, int] = {}
        self._start = start

    def next(self, prefix: str) -> str:
        n = self._counters.get(prefix, self._start)
        self._counters[prefix] = n + 1
        return f"{prefix}-{n:04d}"
