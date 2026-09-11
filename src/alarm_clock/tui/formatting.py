"""Display formatting helpers for the TUI (no domain rules)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from alarm_clock.errors import InvalidAlarmTime
from alarm_clock.models import Alarm, AlarmState, AlarmTime, RecurrenceType, Weekday

_WEEKDAY_SHORT = {
    Weekday.MONDAY: "Mon",
    Weekday.TUESDAY: "Tue",
    Weekday.WEDNESDAY: "Wed",
    Weekday.THURSDAY: "Thu",
    Weekday.FRIDAY: "Fri",
    Weekday.SATURDAY: "Sat",
    Weekday.SUNDAY: "Sun",
}

_WEEKDAY_LONG = {
    Weekday.MONDAY: "Monday",
    Weekday.TUESDAY: "Tuesday",
    Weekday.WEDNESDAY: "Wednesday",
    Weekday.THURSDAY: "Thursday",
    Weekday.FRIDAY: "Friday",
    Weekday.SATURDAY: "Saturday",
    Weekday.SUNDAY: "Sunday",
}


def format_alarm_time(alarm_time: AlarmTime) -> str:
    hour = alarm_time.hour % 12
    if hour == 0:
        hour = 12
    suffix = "AM" if alarm_time.hour < 12 else "PM"
    return f"{hour:02d}:{alarm_time.minute:02d} {suffix}"


def format_recurrence(alarm: Alarm) -> str:
    if alarm.recurrence is RecurrenceType.ONCE:
        return "Once"
    if alarm.recurrence is RecurrenceType.DAILY:
        return "Daily"
    if alarm.recurrence is RecurrenceType.WEEKDAYS:
        return "Weekdays"
    if alarm.recurrence is RecurrenceType.WEEKENDS:
        return "Weekends"
    days = sorted(alarm.days, key=lambda d: d.value)
    return "/".join(_WEEKDAY_SHORT[d] for d in days) or "Custom"


def format_status(alarm: Alarm) -> str:
    if alarm.state is AlarmState.RINGING:
        return "RING"
    if alarm.state is AlarmState.COMPLETED:
        return "DONE"
    if not alarm.enabled:
        return "OFF"
    return "ON"


def format_status_glyph(alarm: Alarm) -> str:
    if alarm.state is AlarmState.RINGING:
        return "!"
    if alarm.state is AlarmState.COMPLETED:
        return "x"
    if alarm.enabled:
        return "*"
    return "o"


def format_next_fire(alarm: Alarm, now: Optional[datetime] = None) -> str:
    if alarm.state is AlarmState.COMPLETED or alarm.next_fire_at is None:
        return "-"
    if alarm.state is AlarmState.RINGING:
        return "Now"
    fire_local = alarm.next_fire_at.astimezone(ZoneInfo(alarm.timezone))
    if now is None:
        ref = datetime.now(tz=fire_local.tzinfo)
    else:
        ref = now.astimezone(fire_local.tzinfo)
    if fire_local.date() == ref.date():
        return "Today"
    if fire_local.date() == ref.date() + timedelta(days=1):
        return "Tomorrow"
    return _WEEKDAY_LONG[Weekday(fire_local.weekday())]


def format_clock(now: datetime) -> tuple[str, str, str]:
    """Return (time, date, timezone) strings for the header clock."""
    local = now.astimezone()
    time_str = local.strftime("%I:%M:%S %p").lstrip("0")
    date_str = local.strftime("%A, %B %d, %Y")
    tz = getattr(local.tzinfo, "key", None) or str(local.tzinfo)
    return time_str, date_str, tz


def parse_alarm_time(text: str) -> AlarmTime:
    """Parse user time input into AlarmTime."""
    raw = text.strip().upper().replace(".", "")
    if not raw:
        raise InvalidAlarmTime("Time is required")

    suffix = None
    if raw.endswith("AM") or raw.endswith("PM"):
        suffix = raw[-2:]
        raw = raw[:-2].strip()

    parts = raw.split(":")
    if len(parts) != 2:
        raise InvalidAlarmTime(f"Invalid time format: {text!r} (use HH:MM)")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise InvalidAlarmTime(f"Invalid time format: {text!r}") from exc

    if suffix == "AM":
        if hour == 12:
            hour = 0
        elif hour > 12:
            raise InvalidAlarmTime(f"Invalid hour for AM: {hour}")
    elif suffix == "PM":
        if hour == 12:
            pass
        elif 1 <= hour <= 11:
            hour += 12
        else:
            raise InvalidAlarmTime(f"Invalid hour for PM: {hour}")

    return AlarmTime(hour, minute)
