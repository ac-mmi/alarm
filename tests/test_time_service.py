"""Tests for clocks and timezone helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from alarm_clock.errors import InvalidTimezone
from alarm_clock.time_service import (
    FakeClock,
    RealClock,
    convert_timezone,
    current_time,
    validate_timezone,
)


class TestValidateTimezone:
    def test_valid_timezone(self):
        tz = validate_timezone("Asia/Kolkata")
        assert isinstance(tz, ZoneInfo)
        assert tz.key == "Asia/Kolkata"

    def test_invalid_timezone(self):
        with pytest.raises(InvalidTimezone):
            validate_timezone("Mars/Olympus")

    def test_empty_timezone(self):
        with pytest.raises(InvalidTimezone):
            validate_timezone("")


class TestClocks:
    def test_fake_clock_now_and_advance(self):
        start = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
        clock = FakeClock(start)
        assert clock.now() == start
        clock.advance(timedelta(minutes=5))
        assert clock.now() == start + timedelta(minutes=5)

    def test_fake_clock_set(self):
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        target = datetime(2026, 9, 11, 12, 0, tzinfo=ZoneInfo("UTC"))
        clock.set(target)
        assert clock.now() == target.astimezone(timezone.utc)

    def test_fake_clock_rejects_naive(self):
        with pytest.raises(ValueError):
            FakeClock(datetime(2026, 9, 11, 10, 0))

    def test_real_clock_is_aware(self):
        now = RealClock().now()
        assert now.tzinfo is not None


class TestCurrentAndConvert:
    def test_current_time_with_timezone(self):
        clock = FakeClock(
            datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
        )
        local = current_time(clock, "America/New_York")
        assert local.tzinfo.key == "America/New_York"
        assert local.hour == 8  # EDT in September

    def test_convert_timezone(self):
        instant = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
        converted = convert_timezone(instant, "Asia/Kolkata")
        assert converted.hour == 17
        assert converted.minute == 30

    def test_convert_rejects_naive(self):
        with pytest.raises(ValueError):
            convert_timezone(datetime(2026, 9, 11, 12, 0), "UTC")
