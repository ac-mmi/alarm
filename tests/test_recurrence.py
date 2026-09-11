"""Tests for recurrence and next-occurrence calculation."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alarm_clock.alarms import create_alarm
from alarm_clock.errors import InvalidRecurrence
from alarm_clock.models import AlarmTime, RecurrenceType, Weekday
from alarm_clock.recurrence import next_occurrence, resolve_local_occurrence


TZ = "America/New_York"


def _dt(year, month, day, hour, minute, tz=TZ) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz))


class TestOnce:
    def test_future_today(self):
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.ONCE,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 11, 6, 0),
        )
        assert result == _dt(2026, 9, 11, 7, 30)

    def test_past_today_rolls_to_tomorrow(self):
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.ONCE,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 11, 10, 0),
        )
        assert result == _dt(2026, 9, 12, 7, 30)

    def test_strictly_after_boundary(self):
        at = _dt(2026, 9, 11, 7, 30)
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.ONCE,
            days=frozenset(),
            timezone=TZ,
            after=at,
        )
        assert result == _dt(2026, 9, 12, 7, 30)
        assert result > at


class TestDaily:
    def test_next_day_when_past(self):
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.DAILY,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 11, 8, 0),
        )
        assert result == _dt(2026, 9, 12, 7, 30)

    def test_same_day_when_future(self):
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.DAILY,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 11, 6, 0),
        )
        assert result == _dt(2026, 9, 11, 7, 30)


class TestWeekdays:
    def test_monday_morning_before_alarm(self):
        # 2026-09-11 is a Friday.
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.WEEKDAYS,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 11, 6, 0),
        )
        assert result == _dt(2026, 9, 11, 7, 30)
        assert result.weekday() == Weekday.FRIDAY.value

    def test_friday_after_alarm_goes_to_monday(self):
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.WEEKDAYS,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 11, 10, 0),
        )
        assert result == _dt(2026, 9, 14, 7, 30)
        assert result.weekday() == Weekday.MONDAY.value

    def test_saturday_skips_to_monday(self):
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.WEEKDAYS,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 12, 10, 0),
        )
        assert result == _dt(2026, 9, 14, 7, 30)


class TestWeekends:
    def test_friday_goes_to_saturday(self):
        result = next_occurrence(
            alarm_time=AlarmTime(9, 0),
            recurrence=RecurrenceType.WEEKENDS,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 11, 10, 0),
        )
        assert result == _dt(2026, 9, 12, 9, 0)
        assert result.weekday() == Weekday.SATURDAY.value

    def test_sunday_after_goes_to_next_saturday(self):
        result = next_occurrence(
            alarm_time=AlarmTime(9, 0),
            recurrence=RecurrenceType.WEEKENDS,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 9, 13, 10, 0),
        )
        assert result == _dt(2026, 9, 19, 9, 0)


class TestCustomDays:
    def test_mon_wed_fri_from_tuesday(self):
        # 2026-09-08 is Tuesday.
        days = frozenset(
            {Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY}
        )
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.CUSTOM_DAYS,
            days=days,
            timezone=TZ,
            after=_dt(2026, 9, 8, 10, 0),
        )
        assert result == _dt(2026, 9, 9, 7, 30)
        assert result.weekday() == Weekday.WEDNESDAY.value

    def test_custom_from_selected_day_before_time(self):
        days = frozenset({Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY})
        result = next_occurrence(
            alarm_time=AlarmTime(7, 30),
            recurrence=RecurrenceType.CUSTOM_DAYS,
            days=days,
            timezone=TZ,
            after=_dt(2026, 9, 9, 6, 0),  # Wednesday
        )
        assert result == _dt(2026, 9, 9, 7, 30)

    def test_empty_custom_days_rejected(self):
        with pytest.raises(InvalidRecurrence):
            next_occurrence(
                alarm_time=AlarmTime(7, 30),
                recurrence=RecurrenceType.CUSTOM_DAYS,
                days=frozenset(),
                timezone=TZ,
                after=_dt(2026, 9, 11, 6, 0),
            )

    def test_create_custom_alarm(self):
        days = frozenset({Weekday.MONDAY, Weekday.FRIDAY})
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 10, 8, 0),  # Thursday
            recurrence=RecurrenceType.CUSTOM_DAYS,
            days=days,
            timezone=TZ,
        )
        assert alarm.next_fire_at == _dt(2026, 9, 11, 7, 30)
        assert alarm.days == days


class TestPastTimePolicy:
    def test_create_past_once_schedules_tomorrow(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 12, 0),
            recurrence=RecurrenceType.ONCE,
            timezone=TZ,
        )
        assert alarm.next_fire_at == _dt(2026, 9, 12, 7, 30)

    def test_create_past_weekdays_rolls_forward(self):
        alarm = create_alarm(
            id=1,
            time=AlarmTime(7, 30),
            after=_dt(2026, 9, 11, 12, 0),  # Friday past
            recurrence=RecurrenceType.WEEKDAYS,
            timezone=TZ,
        )
        assert alarm.next_fire_at == _dt(2026, 9, 14, 7, 30)


class TestTimezoneAwareWeekdays:
    def test_weekday_evaluated_in_alarm_timezone(self):
        # UTC Saturday 02:00 is Friday 22:00 in America/New_York.
        after_utc = datetime(2026, 9, 12, 2, 0, tzinfo=ZoneInfo("UTC"))
        result = next_occurrence(
            alarm_time=AlarmTime(22, 0),
            recurrence=RecurrenceType.WEEKDAYS,
            days=frozenset(),
            timezone=TZ,
            after=after_utc,
        )
        # after equals Friday 22:00 NY, so strictly-after → Monday 22:00.
        assert result == _dt(2026, 9, 14, 22, 0)

    def test_naive_after_rejected(self):
        with pytest.raises(ValueError):
            next_occurrence(
                alarm_time=AlarmTime(7, 30),
                recurrence=RecurrenceType.ONCE,
                days=frozenset(),
                timezone=TZ,
                after=datetime(2026, 9, 11, 6, 0),
            )


class TestDST:
    def test_spring_forward_gap_skips_nonexistent_time(self):
        # US spring forward 2026-03-08: 02:00 → 03:00 in America/New_York.
        result = next_occurrence(
            alarm_time=AlarmTime(2, 30),
            recurrence=RecurrenceType.DAILY,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 3, 7, 12, 0),
        )
        # Mar 7 02:30 is past; Mar 8 02:30 is a gap → Mar 9 02:30.
        assert result == _dt(2026, 3, 9, 2, 30)

    def test_spring_forward_gap_resolve_returns_none(self):
        assert (
            resolve_local_occurrence(date(2026, 3, 8), AlarmTime(2, 30), TZ)
            is None
        )

    def test_fall_back_fold_uses_earlier_occurrence(self):
        # US fall back 2026-11-01: 02:00 → 01:00. 01:30 occurs twice.
        occurrence = resolve_local_occurrence(
            date(2026, 11, 1), AlarmTime(1, 30), TZ
        )
        assert occurrence is not None
        assert occurrence.fold == 0
        # Earlier occurrence is still EDT (UTC-4).
        assert occurrence.utcoffset().total_seconds() == -4 * 3600

    def test_fall_back_next_occurrence_is_earlier_fold(self):
        result = next_occurrence(
            alarm_time=AlarmTime(1, 30),
            recurrence=RecurrenceType.ONCE,
            days=frozenset(),
            timezone=TZ,
            after=_dt(2026, 11, 1, 0, 0),
        )
        assert result is not None
        assert result.hour == 1
        assert result.minute == 30
        assert result.fold == 0
