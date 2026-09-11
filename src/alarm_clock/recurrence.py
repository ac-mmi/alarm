"""Recurrence rules and next-occurrence calculation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import FrozenSet, Optional

from alarm_clock.errors import InvalidRecurrence
from alarm_clock.models import AlarmTime, RecurrenceType, Weekday
from alarm_clock.time_service import validate_timezone

# Bound search so pathological inputs cannot loop forever.
_MAX_SEARCH_DAYS = 366 * 2


def _weekday_allowed(
    day: date,
    recurrence: RecurrenceType,
    days: FrozenSet[Weekday],
) -> bool:
    weekday = Weekday(day.weekday())
    if recurrence is RecurrenceType.ONCE:
        return True
    if recurrence is RecurrenceType.DAILY:
        return True
    if recurrence is RecurrenceType.WEEKDAYS:
        return weekday.value <= Weekday.FRIDAY.value
    if recurrence is RecurrenceType.WEEKENDS:
        return weekday in {Weekday.SATURDAY, Weekday.SUNDAY}
    if recurrence is RecurrenceType.CUSTOM_DAYS:
        return weekday in days
    raise InvalidRecurrence(f"Unknown recurrence: {recurrence!r}")


def resolve_local_occurrence(
    day: date,
    alarm_time: AlarmTime,
    tz_name: str,
) -> Optional[datetime]:
    """Build a timezone-aware local occurrence for *day* at *alarm_time*.

    DST gap (nonexistent local time): return None (caller skips the day).
    DST fold (ambiguous local time): return the earlier occurrence (fold=0).
    """
    tz = validate_timezone(tz_name)
    wall = datetime(
        day.year,
        day.month,
        day.day,
        alarm_time.hour,
        alarm_time.minute,
        0,
        0,
    )

    earlier = wall.replace(tzinfo=tz, fold=0)
    later = wall.replace(tzinfo=tz, fold=1)

    def wall_matches(candidate: datetime) -> bool:
        round_trip = candidate.astimezone(timezone.utc).astimezone(tz)
        return (
            round_trip.year == wall.year
            and round_trip.month == wall.month
            and round_trip.day == wall.day
            and round_trip.hour == wall.hour
            and round_trip.minute == wall.minute
        )

    # Prefer the earlier fold when the local time is ambiguous.
    if wall_matches(earlier):
        return earlier
    if wall_matches(later):
        return later
    # Nonexistent local time (spring-forward gap).
    return None


def next_occurrence(
    *,
    alarm_time: AlarmTime,
    recurrence: RecurrenceType,
    days: FrozenSet[Weekday],
    timezone: str,
    after: datetime,
) -> Optional[datetime]:
    """Return the next valid fire instant strictly after *after*.

    Considers recurrence, weekday in the alarm timezone, and DST gap/fold
    rules. Returns None only if no occurrence is found within the search
    window (should not happen for valid recurring rules).
    """
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")

    tz = validate_timezone(timezone)
    after_local = after.astimezone(tz)
    start_day = after_local.date()

    if recurrence is RecurrenceType.CUSTOM_DAYS and not days:
        raise InvalidRecurrence(
            "CUSTOM_DAYS recurrence requires at least one weekday"
        )

    for offset in range(0, _MAX_SEARCH_DAYS):
        day = start_day + timedelta(days=offset)
        if not _weekday_allowed(day, recurrence, days):
            continue

        occurrence = resolve_local_occurrence(day, alarm_time, timezone)
        if occurrence is None:
            continue
        if occurrence > after:
            return occurrence

        # For ONCE, only the first calendar candidate that is in the future
        # (or today's time if still ahead) matters; if today's time is not
        # strictly after `after`, keep searching — which yields tomorrow.
        if recurrence is RecurrenceType.ONCE and offset > 0:
            # Should have returned above once we found a future day.
            continue

    return None
