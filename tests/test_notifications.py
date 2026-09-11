"""Tests for the notification boundary (bell / composite)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from alarm_clock.models import (
    Alarm,
    AlarmState,
    AlarmTime,
    RecurrenceType,
)
from alarm_clock.notifications import (
    CallbackNotifier,
    CompositeNotifier,
    play_terminal_bell,
)


def _alarm() -> Alarm:
    return Alarm(
        id=1,
        time=AlarmTime(7, 30),
        label="Test",
        enabled=True,
        recurrence=RecurrenceType.ONCE,
        timezone="UTC",
        state=AlarmState.RINGING,
        next_fire_at=datetime(2026, 9, 11, 7, 30, tzinfo=ZoneInfo("UTC")),
    )


def test_play_terminal_bell_writes_bel():
    class Buf:
        def __init__(self):
            self.data = ""

        def write(self, s):
            self.data += s

        def flush(self):
            pass

    buf = Buf()
    play_terminal_bell(buf)
    assert "\a" in buf.data


def test_play_terminal_bell_failure_is_swallowed():
    class Bad:
        def write(self, s):
            raise OSError("no tty")

        def flush(self):
            raise OSError("no tty")

    play_terminal_bell(Bad())  # must not raise


def test_composite_runs_audible_then_visual():
    order = []

    def audible():
        order.append("sound")

    def visual(alarm):
        order.append(("visual", alarm.id))

    CompositeNotifier(visual, audible=audible).notify_ringing(_alarm())
    assert order == ["sound", ("visual", 1)]


def test_composite_audible_failure_still_notifies_visual():
    seen = []

    def audible():
        raise RuntimeError("speaker dead")

    def visual(alarm):
        seen.append(alarm.id)

    CompositeNotifier(visual, audible=audible).notify_ringing(_alarm())
    assert seen == [1]


def test_callback_notifier():
    seen = []
    CallbackNotifier(lambda a: seen.append(a.id)).notify_ringing(_alarm())
    assert seen == [1]
