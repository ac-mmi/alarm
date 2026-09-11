"""Session-only stopwatch domain (monotonic elapsed time)."""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional

from alarm_clock.errors import InvalidStopwatchOperation


class StopwatchState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class Stopwatch:
    """Measures elapsed duration with a monotonic clock.

    Invalid transitions raise ``InvalidStopwatchOperation`` rather than
    becoming silent no-ops.
    """

    def __init__(self, monotonic=time.monotonic) -> None:
        self._monotonic = monotonic
        self._state = StopwatchState.IDLE
        self._elapsed = 0.0
        self._started_at: Optional[float] = None

    @property
    def state(self) -> StopwatchState:
        return self._state

    def start(self) -> None:
        if self._state is StopwatchState.RUNNING:
            raise InvalidStopwatchOperation("Stopwatch is already running")
        if self._state is StopwatchState.PAUSED:
            raise InvalidStopwatchOperation(
                "Stopwatch is paused; use resume instead of start"
            )
        self._elapsed = 0.0
        self._started_at = self._monotonic()
        self._state = StopwatchState.RUNNING

    def pause(self) -> None:
        if self._state is not StopwatchState.RUNNING:
            raise InvalidStopwatchOperation("Pause is only valid while running")
        assert self._started_at is not None
        self._elapsed += self._monotonic() - self._started_at
        self._started_at = None
        self._state = StopwatchState.PAUSED

    def resume(self) -> None:
        if self._state is not StopwatchState.PAUSED:
            raise InvalidStopwatchOperation("Resume is only valid while paused")
        self._started_at = self._monotonic()
        self._state = StopwatchState.RUNNING

    def reset(self) -> None:
        self._state = StopwatchState.IDLE
        self._elapsed = 0.0
        self._started_at = None

    def elapsed_seconds(self) -> float:
        total = self._elapsed
        if self._state is StopwatchState.RUNNING and self._started_at is not None:
            total += self._monotonic() - self._started_at
        return total

    def format_elapsed(self) -> str:
        total = self.elapsed_seconds()
        if total < 0:
            total = 0.0
        hours = int(total // 3600)
        minutes = int((total % 3600) // 60)
        seconds = total % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:05.2f}"
