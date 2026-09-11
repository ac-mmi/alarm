"""Minimal stopwatch domain tests."""

from __future__ import annotations

import pytest

from alarm_clock.errors import InvalidStopwatchOperation
from alarm_clock.stopwatch import Stopwatch, StopwatchState


class FakeMono:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_start_pause_resume_reset():
    mono = FakeMono()
    sw = Stopwatch(monotonic=mono)
    assert sw.state is StopwatchState.IDLE
    sw.start()
    mono.advance(1.5)
    assert sw.elapsed_seconds() == pytest.approx(1.5)
    sw.pause()
    assert sw.state is StopwatchState.PAUSED
    mono.advance(10)
    assert sw.elapsed_seconds() == pytest.approx(1.5)
    sw.resume()
    mono.advance(0.5)
    assert sw.elapsed_seconds() == pytest.approx(2.0)
    sw.reset()
    assert sw.state is StopwatchState.IDLE
    assert sw.elapsed_seconds() == 0.0


def test_invalid_transitions():
    sw = Stopwatch(monotonic=FakeMono())
    with pytest.raises(InvalidStopwatchOperation):
        sw.pause()
    sw.start()
    with pytest.raises(InvalidStopwatchOperation):
        sw.start()
    with pytest.raises(InvalidStopwatchOperation):
        sw.resume()
