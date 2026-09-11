"""Timezone-aware time helpers and injectable clocks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alarm_clock.errors import InvalidTimezone


class Clock(Protocol):
    """Provides the current instant for scheduling and tests."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


class RealClock:
    """Production clock using the system wall clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    """Deterministic clock for tests. Advance explicitly; never sleeps.

    Optional ``on_change`` is invoked after ``set`` / ``advance`` so a
    scheduler can wake without real-time waiting.
    """

    def __init__(
        self,
        initial: datetime,
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        if initial.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = initial.astimezone(timezone.utc)
        self._on_change = on_change

    def now(self) -> datetime:
        return self._now

    def set_on_change(self, on_change: Optional[Callable[[], None]]) -> None:
        self._on_change = on_change

    def set(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = instant.astimezone(timezone.utc)
        if self._on_change is not None:
            self._on_change()

    def advance(self, delta) -> None:
        self._now = self._now + delta
        if self._on_change is not None:
            self._on_change()


def validate_timezone(name: str) -> ZoneInfo:
    """Validate and return a ZoneInfo for the given IANA timezone name."""
    if not name or not isinstance(name, str):
        raise InvalidTimezone(f"Invalid timezone: {name!r}")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError) as exc:
        raise InvalidTimezone(f"Invalid timezone: {name!r}") from exc


def get_local_timezone() -> ZoneInfo:
    """Return the system local timezone as a ZoneInfo when possible."""
    local = datetime.now().astimezone().tzinfo
    if isinstance(local, ZoneInfo):
        return local
    key = getattr(local, "key", None)
    if isinstance(key, str):
        try:
            return ZoneInfo(key)
        except (ZoneInfoNotFoundError, KeyError):
            pass
    # Resolve /etc/localtime on Unix to an IANA name when possible.
    try:
        from pathlib import Path

        path = Path("/etc/localtime").resolve()
        parts = path.parts
        if "zoneinfo" in parts:
            idx = parts.index("zoneinfo")
            name = "/".join(parts[idx + 1 :])
            return ZoneInfo(name)
    except (OSError, ValueError, ZoneInfoNotFoundError, IndexError):
        pass
    return ZoneInfo("UTC")


def current_time(
    clock: Clock,
    tz: Optional[str | ZoneInfo] = None,
) -> datetime:
    """Return the current time from *clock*, optionally converted to *tz*."""
    now = clock.now()
    if now.tzinfo is None:
        raise ValueError("Clock must return a timezone-aware datetime")
    if tz is None:
        return now
    zone = validate_timezone(tz) if isinstance(tz, str) else tz
    return now.astimezone(zone)


def convert_timezone(instant: datetime, tz: str | ZoneInfo) -> datetime:
    """Convert a timezone-aware instant into the target timezone."""
    if instant.tzinfo is None:
        raise ValueError("Cannot convert a naive datetime")
    zone = validate_timezone(tz) if isinstance(tz, str) else tz
    return instant.astimezone(zone)
