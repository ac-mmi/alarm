"""Tests for alarm creation, validation, enable/disable, and lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from alarm_clock.alarms import create_alarm, is_due, update_alarm
from alarm_clock.errors import (
    InvalidAlarmState,
    InvalidAlarmTime,
    InvalidRecurrence,
    InvalidTimezone,
)
from alarm_clock.models import (
    DEFAULT_SNOOZE,
    Alarm,
    AlarmState,
    AlarmTime,
    RecurrenceType,
    Weekday,
)
from alarm_clock.time_service import FakeClock


TZ = "America/New_York"


def _dt(year, month, day, hour, minute, tz=TZ) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz))


class TestAlarmTime:
    def test_valid_time(self):
        t = AlarmTime(7, 30)
        assert t.hour == 7
        assert t.minute == 30
        assert str(t) == "07:30"

    def test_midnight_and_end_of_day(self):
        assert AlarmTime(0, 0).to_time().hour == 0
        assert AlarmTime(23, 59).minute == 59

    def test_invalid_hour(self):
        with pytest.raises(InvalidAlarmTime):
            AlarmTime(24, 0)
        with pytest.raises(InvalidAlarmTime):
            AlarmTime(-1, 0)

    def test_invalid_minute(self):
        with pytest.raises(InvalidAlarmTime):
            AlarmTime(10, 60)
        with pytest.raises(InvalidAlarmTime):
            AlarmTime(10, -1)


class TestAlarmCreation:
    def test_create_basic_once_alarm(self):
        after = _dt(2026, 9, 11, 10, 0)
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=after,
            label="Wake up",
            recurrence=RecurrenceType.ONCE,
            timezone=TZ,
        )
        assert alarm.id == 1
        assert alarm.label == "Wake up"
        assert alarm.enabled is True
        assert alarm.state is AlarmState.SCHEDULED
        assert alarm.recurrence is RecurrenceType.ONCE
        assert alarm.timezone == TZ
        assert alarm.next_fire_at == _dt(2026, 9, 12, 7, 30)

    def test_create_future_today(self):
        after = _dt(2026, 9, 11, 6, 0)
        alarm = create_alarm(
            id=2,
            time=AlarmTime(7, 30),
            after=after,
            timezone=TZ,
        )
        assert alarm.next_fire_at == _dt(2026, 9, 11, 7, 30)

    def test_multiple_alarms_same_time_distinct_ids(self):
        after = _dt(2026, 9, 11, 6, 0)
        a1 = create_alarm(id=1, time=AlarmTime(7, 30), after=after, timezone=TZ)
        a2 = create_alarm(
            id=2,
            time=AlarmTime(7, 30),
            after=after,
            label="Meds",
            timezone=TZ,
        )
        assert a1.id != a2.id
        assert a1.next_fire_at == a2.next_fire_at

    def test_default_label_empty(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(8, 0),
            after=_dt(2026, 9, 11, 7, 0),
            timezone=TZ,
        )
        assert alarm.label == ""

    def test_invalid_timezone_on_create(self):
        with pytest.raises(InvalidTimezone):
            create_alarm(
                id=1,
                time=AlarmTime(8, 0),
                after=_dt(2026, 9, 11, 7, 0),
                timezone="Not/A_Zone",
            )

    def test_custom_days_requires_selection(self):
        with pytest.raises(InvalidRecurrence):
            create_alarm(
                id=1,
                time=AlarmTime(8, 0),
                after=_dt(2026, 9, 11, 7, 0),
                recurrence=RecurrenceType.CUSTOM_DAYS,
                days=frozenset(),
                timezone=TZ,
            )

    def test_non_custom_must_not_have_days(self):
        with pytest.raises(InvalidRecurrence):
            Alarm(
                id=1,
                time=AlarmTime(8, 0),
                label="",
                enabled=True,
                recurrence=RecurrenceType.DAILY,
                days=frozenset({Weekday.MONDAY}),
                timezone=TZ,
                state=AlarmState.SCHEDULED,
                next_fire_at=_dt(2026, 9, 12, 8, 0),
            )


class TestEnableDisable:
    def test_disable_prevents_due(self):
        after = _dt(2026, 9, 11, 6, 0)
        alarm = create_alarm(
            id=1, time=AlarmTime(7, 30), after=after, timezone=TZ
        )
        alarm.disable()
        assert alarm.enabled is False
        assert is_due(alarm, _dt(2026, 9, 11, 7, 30)) is False

    def test_enable_restores_eligibility(self):
        after = _dt(2026, 9, 11, 6, 0)
        alarm = create_alarm(
            id=1, time=AlarmTime(7, 30), after=after, timezone=TZ
        )
        alarm.disable()
        alarm.enable()
        assert alarm.enabled is True
        assert is_due(alarm, _dt(2026, 9, 11, 7, 30)) is True

    def test_disable_while_ringing_stops_ringing(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        alarm.disable()
        assert alarm.enabled is False
        assert alarm.state is AlarmState.SCHEDULED

    def test_enable_does_not_rearm_completed(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        alarm.dismiss(_dt(2026, 9, 11, 7, 30))
        assert alarm.state is AlarmState.COMPLETED
        alarm.disable()
        alarm.enable()
        assert alarm.state is AlarmState.COMPLETED
        assert alarm.next_fire_at is None
        assert is_due(alarm, _dt(2026, 9, 12, 7, 30)) is False


class TestLifecycle:
    def test_scheduled_to_ringing(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        assert alarm.state is AlarmState.RINGING

    def test_cannot_ring_when_disabled(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.disable()
        with pytest.raises(InvalidAlarmState):
            alarm.start_ringing()

    def test_cannot_ring_when_completed(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        alarm.dismiss(_dt(2026, 9, 11, 7, 31))
        with pytest.raises(InvalidAlarmState):
            alarm.start_ringing()

    def test_cannot_ring_twice(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        with pytest.raises(InvalidAlarmState):
            alarm.start_ringing()

    def test_dismiss_once_completes(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        alarm.dismiss(_dt(2026, 9, 11, 7, 31))
        assert alarm.state is AlarmState.COMPLETED
        assert alarm.next_fire_at is None

    def test_dismiss_daily_reschedules(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            recurrence=RecurrenceType.DAILY,
            timezone=TZ,
        )
        alarm.start_ringing()
        now = _dt(2026, 9, 11, 7, 31)
        alarm.dismiss(now)
        assert alarm.state is AlarmState.SCHEDULED
        assert alarm.next_fire_at == _dt(2026, 9, 12, 7, 30)

    def test_dismiss_when_not_ringing_invalid(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        with pytest.raises(InvalidAlarmState):
            alarm.dismiss(_dt(2026, 9, 11, 7, 31))

    def test_snooze_sets_next_fire_at(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            recurrence=RecurrenceType.WEEKDAYS,
            timezone=TZ,
        )
        alarm.start_ringing()
        now = _dt(2026, 9, 11, 7, 30)
        alarm.snooze(now)
        assert alarm.state is AlarmState.SCHEDULED
        assert alarm.next_fire_at == now + DEFAULT_SNOOZE
        # Configured schedule unchanged.
        assert alarm.time == AlarmTime(7, 30)
        assert alarm.recurrence is RecurrenceType.WEEKDAYS

    def test_repeated_snooze(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        t1 = _dt(2026, 9, 11, 7, 30)
        alarm.snooze(t1)
        alarm.start_ringing()
        t2 = t1 + DEFAULT_SNOOZE
        alarm.snooze(t2)
        assert alarm.next_fire_at == t2 + DEFAULT_SNOOZE

    def test_snooze_when_not_ringing_invalid(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        with pytest.raises(InvalidAlarmState):
            alarm.snooze(_dt(2026, 9, 11, 7, 30))

    def test_snooze_rejects_non_positive_duration(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        with pytest.raises(InvalidAlarmTime):
            alarm.snooze(_dt(2026, 9, 11, 7, 30), duration=timedelta(0))


class TestDueDetection:
    def test_due_uses_less_or_equal(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        assert is_due(alarm, _dt(2026, 9, 11, 7, 29)) is False
        assert is_due(alarm, _dt(2026, 9, 11, 7, 30)) is True
        assert is_due(alarm, _dt(2026, 9, 11, 7, 31)) is True

    def test_completed_not_due(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        alarm.dismiss(_dt(2026, 9, 11, 7, 30))
        assert is_due(alarm, _dt(2026, 9, 12, 7, 30)) is False


class TestUpdateAlarm:
    def test_update_time_recomputes_next_fire(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        update_alarm(
            alarm,
            after=_dt(2026, 9, 11, 6, 0),
            time=AlarmTime(8, 0),
        )
        assert alarm.time == AlarmTime(8, 0)
        assert alarm.next_fire_at == _dt(2026, 9, 11, 8, 0)
        assert alarm.id == 1

    def test_update_preserves_id(self):
        alarm = create_alarm(
            id=42,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        update_alarm(alarm, after=_dt(2026, 9, 11, 6, 0), label="New")
        assert alarm.id == 42
        assert alarm.label == "New"

    def test_update_completed_with_new_time_rearms(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 6, 0),
            timezone=TZ,
        )
        alarm.start_ringing()
        alarm.dismiss(_dt(2026, 9, 11, 7, 30))
        update_alarm(
            alarm,
            after=_dt(2026, 9, 11, 8, 0),
            time=AlarmTime(9, 0),
        )
        assert alarm.state is AlarmState.SCHEDULED
        assert alarm.next_fire_at == _dt(2026, 9, 11, 9, 0)


class TestFakeClockIntegration:
    def test_deterministic_clock_advance(self):
        clock = FakeClock(_dt(2026, 9, 11, 7, 29))
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=clock.now(),
            timezone=TZ,
        )
        assert is_due(alarm, clock.now()) is False
        clock.advance(timedelta(minutes=1))
        assert is_due(alarm, clock.now()) is True
