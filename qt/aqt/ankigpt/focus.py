# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Small, process-local state machine for an optional focused study session."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class FocusSession:
    card_goal: int
    duration_minutes: int
    started_at: float
    answered: int = 0
    paused_at: float | None = None
    paused_seconds: float = 0

    def elapsed_seconds(self, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        if self.paused_at is not None:
            current = self.paused_at
        return max(0, int(current - self.started_at - self.paused_seconds))

    def remaining_seconds(self, now: float | None = None) -> int:
        if not self.duration_minutes:
            return 0
        return max(0, self.duration_minutes * 60 - self.elapsed_seconds(now))

    def pause(self, now: float | None = None) -> None:
        if self.paused_at is None:
            self.paused_at = time.monotonic() if now is None else now

    def resume(self, now: float | None = None) -> None:
        if self.paused_at is None:
            return
        current = time.monotonic() if now is None else now
        self.paused_seconds += max(0, current - self.paused_at)
        self.paused_at = None

    @property
    def complete(self) -> bool:
        return self.answered >= self.card_goal or (
            self.duration_minutes > 0 and self.remaining_seconds() == 0
        )


_session: FocusSession | None = None
_last_summary: dict[str, int] | None = None


def start(card_goal: int, duration_minutes: int) -> FocusSession:
    global _session, _last_summary
    _last_summary = None
    _session = FocusSession(
        card_goal=max(1, min(100, card_goal)),
        duration_minutes=max(0, min(120, duration_minutes)),
        started_at=time.monotonic(),
    )
    return _session


def stop() -> None:
    global _session
    _session = None


def current() -> FocusSession | None:
    return _session


def finish() -> dict[str, int] | None:
    global _session, _last_summary
    if _session is None:
        return None
    _last_summary = {
        "answered": _session.answered,
        "goal": _session.card_goal,
        "minutes": max(1, (_session.elapsed_seconds() + 59) // 60),
    }
    _session = None
    return _last_summary


def last_summary() -> dict[str, int] | None:
    return _last_summary
