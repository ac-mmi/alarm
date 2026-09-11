"""Alarm creation and configuration helpers."""

from __future__ import annotations

from datetime import datetime
from typing import FrozenSet, Optional

from alarm_clock.errors import InvalidAlarmState
from alarm_clock.models import (
    Alarm,
    AlarmState,
    AlarmTime,
    RecurrenceType,
    Weekday,
)
from alarm_clock.recurrence import next_occurrence
from alarm_clock.time_service import get_local_timezone, validate_timezone


def create_alarm(
    *,
    id: int,
    time: AlarmTime,
    after: datetime,
    label: str = "",
    recurrence: RecurrenceType = RecurrenceType.ONCE,
    days: Optional[FrozenSet[Weekday]] = None,
    timezone: Optional[str] = None,
    enabled: bool = True,
) -> Alarm:
    """Create a SCHEDULED alarm with ``next_fire_at`` rolled forward past *after*.

    If *timezone* is omitted, the system local timezone is used.
    Past times of day never fire immediately; they schedule the next valid
    future occurrence.
    """
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")

    tz_name = timezone if timezone is not None else get_local_timezone().key
    validate_timezone(tz_name)

    day_set = frozenset(days) if days is not None else frozenset()
    fire_at = next_occurrence(
        alarm_time=time,
        recurrence=recurrence,
        days=day_set,
        timezone=tz_name,
        after=after,
    )
    if fire_at is None:
        raise InvalidAlarmState(
            "Could not calculate a next fire time for the alarm"
        )

    return Alarm(
        id=id,
        time=time,
        label=label or "",
        enabled=enabled,
        recurrence=recurrence,
        days=day_set,
        timezone=tz_name,
        state=AlarmState.SCHEDULED,
        next_fire_at=fire_at,
    )


def recompute_next_fire_at(alarm: Alarm, after: datetime) -> Alarm:
    """Recompute ``next_fire_at`` as the next valid occurrence after *after*.

    Used after updates to time, recurrence, or timezone. Completed one-time
    alarms are left completed with no next fire time unless the caller first
    changes state.
    """
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")

    if alarm.state is AlarmState.COMPLETED:
        alarm.next_fire_at = None
        return alarm

    fire_at = next_occurrence(
        alarm_time=alarm.time,
        recurrence=alarm.recurrence,
        days=alarm.days,
        timezone=alarm.timezone,
        after=after,
    )
    if fire_at is None:
        raise InvalidAlarmState(
            "Could not calculate a next fire time for the alarm"
        )
    alarm.next_fire_at = fire_at
    if alarm.state is AlarmState.RINGING:
        # Configuration changed while ringing: return to scheduled.
        alarm.state = AlarmState.SCHEDULED
    return alarm


def update_alarm(
    alarm: Alarm,
    *,
    after: datetime,
    time: Optional[AlarmTime] = None,
    label: Optional[str] = None,
    recurrence: Optional[RecurrenceType] = None,
    days: Optional[FrozenSet[Weekday]] = None,
    timezone: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Alarm:
    """Update alarm configuration and recalculate ``next_fire_at``.

    Preserves identity. Updating time/recurrence/timezone recomputes the next
    valid future occurrence (past-time roll-forward). Enabling a COMPLETED
    one-time alarm alone does not re-arm it.
    """
    if timezone is not None:
        validate_timezone(timezone)

    config_changed = any(
        value is not None
        for value in (time, recurrence, days, timezone)
    )

    updated = alarm.with_updates(
        time=time,
        label=label,
        recurrence=recurrence,
        days=days,
        timezone=timezone,
        enabled=enabled,
    )

    # Copy mutable fields back onto the original instance so callers that
    # hold a reference observe the update (domain object identity).
    alarm.time = updated.time
    alarm.label = updated.label
    alarm.enabled = updated.enabled
    alarm.recurrence = updated.recurrence
    alarm.days = updated.days
    alarm.timezone = updated.timezone

    if alarm.state is AlarmState.COMPLETED and not config_changed:
        return alarm

    if config_changed or alarm.state is not AlarmState.COMPLETED:
        if alarm.state is AlarmState.COMPLETED and config_changed:
            # Explicit configuration change can re-arm a completed alarm.
            alarm.state = AlarmState.SCHEDULED
        recompute_next_fire_at(alarm, after)

    return alarm


def is_due(alarm: Alarm, now: datetime) -> bool:
    """Return True if the alarm should fire at *now* (scheduler predicate)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not alarm.enabled:
        return False
    if alarm.state is AlarmState.COMPLETED:
        return False
    if alarm.state is AlarmState.RINGING:
        return False
    if alarm.next_fire_at is None:
        return False
    return alarm.next_fire_at <= now
