"""Core alarm domain model and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from enum import Enum
from typing import FrozenSet, Optional
from zoneinfo import ZoneInfo

from alarm_clock.errors import (
    InvalidAlarmState,
    InvalidAlarmTime,
    InvalidRecurrence,
)
from alarm_clock.time_service import validate_timezone

DEFAULT_SNOOZE = timedelta(minutes=5)


class AlarmState(str, Enum):
    """Persisted / runtime lifecycle states for an alarm."""

    SCHEDULED = "SCHEDULED"
    RINGING = "RINGING"
    COMPLETED = "COMPLETED"


class RecurrenceType(str, Enum):
    """Supported recurrence modes."""

    ONCE = "ONCE"
    DAILY = "DAILY"
    WEEKDAYS = "WEEKDAYS"
    WEEKENDS = "WEEKENDS"
    CUSTOM_DAYS = "CUSTOM_DAYS"


class Weekday(int, Enum):
    """Weekdays matching datetime.date.weekday() (Monday=0 … Sunday=6)."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True)
class AlarmTime:
    """Configured wall-clock time of day (hour:minute)."""

    hour: int
    minute: int

    def __post_init__(self) -> None:
        if not isinstance(self.hour, int) or not isinstance(self.minute, int):
            raise InvalidAlarmTime(
                f"Alarm time must use integer hour and minute, got "
                f"{self.hour!r}:{self.minute!r}"
            )
        if not (0 <= self.hour <= 23):
            raise InvalidAlarmTime(f"Hour must be 0–23, got {self.hour}")
        if not (0 <= self.minute <= 59):
            raise InvalidAlarmTime(f"Minute must be 0–59, got {self.minute}")

    def to_time(self) -> time:
        return time(hour=self.hour, minute=self.minute)

    @classmethod
    def from_time(cls, value: time) -> AlarmTime:
        return cls(hour=value.hour, minute=value.minute)

    def __str__(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def _normalize_days(
    recurrence: RecurrenceType,
    days: Optional[FrozenSet[Weekday]],
) -> FrozenSet[Weekday]:
    if recurrence is RecurrenceType.CUSTOM_DAYS:
        if not days:
            raise InvalidRecurrence(
                "CUSTOM_DAYS recurrence requires at least one weekday"
            )
        normalized: set[Weekday] = set()
        for day in days:
            if isinstance(day, Weekday):
                normalized.add(day)
            elif isinstance(day, int) and day in {w.value for w in Weekday}:
                normalized.add(Weekday(day))
            else:
                raise InvalidRecurrence(f"Invalid weekday: {day!r}")
        return frozenset(normalized)

    if days:
        raise InvalidRecurrence(
            f"{recurrence.value} recurrence must not specify custom days"
        )
    return frozenset()


@dataclass
class Alarm:
    """Domain state for a single alarm.

    ``enabled`` is independent of ``state``. Lifecycle transitions are
    enforced by methods on this class; scheduling/threading live elsewhere.
    """

    id: int
    time: AlarmTime
    label: str
    enabled: bool
    recurrence: RecurrenceType
    timezone: str
    state: AlarmState
    next_fire_at: Optional[datetime]
    days: FrozenSet[Weekday] = field(default_factory=frozenset)
    created_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not isinstance(self.time, AlarmTime):
            raise InvalidAlarmTime("time must be an AlarmTime instance")
        if not isinstance(self.recurrence, RecurrenceType):
            raise InvalidRecurrence(
                f"Invalid recurrence: {self.recurrence!r}"
            )
        if not isinstance(self.state, AlarmState):
            raise InvalidAlarmState(f"Invalid state: {self.state!r}")
        object.__setattr__(
            self, "days", _normalize_days(self.recurrence, self.days)
        )
        validate_timezone(self.timezone)
        if self.next_fire_at is not None and self.next_fire_at.tzinfo is None:
            raise InvalidAlarmTime(
                "next_fire_at must be timezone-aware when set"
            )
        if self.created_at is not None and self.created_at.tzinfo is None:
            raise InvalidAlarmTime(
                "created_at must be timezone-aware when set"
            )
        if self.label is None:
            object.__setattr__(self, "label", "")

    @property
    def zone(self) -> ZoneInfo:
        return validate_timezone(self.timezone)

    @property
    def is_recurring(self) -> bool:
        return self.recurrence is not RecurrenceType.ONCE

    def enable(self) -> None:
        """Mark the alarm as enabled. Does not re-arm COMPLETED one-time alarms."""
        self.enabled = True

    def disable(self) -> None:
        """Disable the alarm. If ringing, return to SCHEDULED without firing."""
        self.enabled = False
        if self.state is AlarmState.RINGING:
            self.state = AlarmState.SCHEDULED

    def start_ringing(self) -> None:
        """Transition SCHEDULED → RINGING when enabled and not completed."""
        if self.state is AlarmState.COMPLETED:
            raise InvalidAlarmState(
                "Cannot ring a completed alarm; create or update it instead"
            )
        if self.state is AlarmState.RINGING:
            raise InvalidAlarmState("Alarm is already ringing")
        if self.state is not AlarmState.SCHEDULED:
            raise InvalidAlarmState(
                f"Cannot start ringing from state {self.state.value}"
            )
        if not self.enabled:
            raise InvalidAlarmState("Cannot ring a disabled alarm")
        self.state = AlarmState.RINGING

    def dismiss(self, now: datetime) -> None:
        """Dismiss a ringing alarm.

        One-time → COMPLETED. Recurring → SCHEDULED with next occurrence
        strictly after *now*.
        """
        if self.state is not AlarmState.RINGING:
            raise InvalidAlarmState(
                f"Cannot dismiss alarm in state {self.state.value}"
            )
        if now.tzinfo is None:
            raise InvalidAlarmTime("now must be timezone-aware")

        if self.recurrence is RecurrenceType.ONCE:
            self.state = AlarmState.COMPLETED
            self.next_fire_at = None
            return

        from alarm_clock.recurrence import next_occurrence

        self.next_fire_at = next_occurrence(
            alarm_time=self.time,
            recurrence=self.recurrence,
            days=self.days,
            timezone=self.timezone,
            after=now,
        )
        self.state = AlarmState.SCHEDULED

    def snooze(
        self,
        now: datetime,
        duration: timedelta = DEFAULT_SNOOZE,
    ) -> None:
        """Snooze a ringing alarm: SCHEDULED with next_fire_at = now + duration.

        Does not change the configured time-of-day or recurrence rule.
        """
        if self.state is not AlarmState.RINGING:
            raise InvalidAlarmState(
                f"Cannot snooze alarm in state {self.state.value}"
            )
        if now.tzinfo is None:
            raise InvalidAlarmTime("now must be timezone-aware")
        if duration <= timedelta(0):
            raise InvalidAlarmTime("Snooze duration must be positive")

        self.next_fire_at = now + duration
        self.state = AlarmState.SCHEDULED

    def with_updates(
        self,
        *,
        time: Optional[AlarmTime] = None,
        label: Optional[str] = None,
        recurrence: Optional[RecurrenceType] = None,
        days: Optional[FrozenSet[Weekday]] = None,
        timezone: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Alarm:
        """Return a copy with configuration updates (identity preserved).

        Does not recompute ``next_fire_at``; callers should use the alarm
        helpers in ``alarms`` for that.
        """
        new_recurrence = recurrence if recurrence is not None else self.recurrence
        if days is not None:
            new_days = days
        elif recurrence is not None and recurrence is not RecurrenceType.CUSTOM_DAYS:
            new_days = frozenset()
        else:
            new_days = self.days

        updated = replace(
            self,
            time=time if time is not None else self.time,
            label=label if label is not None else self.label,
            recurrence=new_recurrence,
            days=new_days,
            timezone=timezone if timezone is not None else self.timezone,
            enabled=enabled if enabled is not None else self.enabled,
        )
        # Re-run validation via __post_init__ path: replace doesn't call it
        # for dataclass replace of non-frozen — Alarm is mutable dataclass.
        # Manually validate fields that may have changed.
        _normalize_days(updated.recurrence, updated.days)
        validate_timezone(updated.timezone)
        if not isinstance(updated.time, AlarmTime):
            raise InvalidAlarmTime("time must be an AlarmTime instance")
        object.__setattr__(
            updated, "days", _normalize_days(updated.recurrence, updated.days)
        )
        return updated
