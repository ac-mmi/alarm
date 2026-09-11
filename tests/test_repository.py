"""Tests for SQLite AlarmRepository using temporary databases only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from alarm_clock.alarms import create_alarm
from alarm_clock.errors import AlarmNotFound
from alarm_clock.models import (
    DEFAULT_SNOOZE,
    AlarmState,
    AlarmTime,
    RecurrenceType,
    Weekday,
)
from alarm_clock.repository import AlarmRepository, default_db_path


TZ = "America/New_York"


def _dt(year, month, day, hour, minute, tz=TZ) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz))


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "alarms.db"


@pytest.fixture
def repo(db_path: Path):
    repository = AlarmRepository(db_path)
    yield repository
    repository.close()


def _make_alarm(**kwargs):
    defaults = dict(
        id=0,
        time=AlarmTime(7, 30),
        after=_dt(2026, 9, 11, 6, 0),
        label="Wake up",
        recurrence=RecurrenceType.ONCE,
        timezone=TZ,
    )
    defaults.update(kwargs)
    return create_alarm(**defaults)


class TestDatabaseLifecycle:
    def test_creates_database_file(self, db_path: Path):
        assert not db_path.exists()
        with AlarmRepository(db_path) as repo:
            assert db_path.exists()
            assert repo.path == db_path

    def test_schema_initialization_is_idempotent(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            assert repo.list_alarms() == []
        with AlarmRepository(db_path) as repo:
            assert repo.list_alarms() == []

    def test_empty_database_lists_nothing(self, repo: AlarmRepository):
        assert repo.list_alarms() == []

    def test_reopen_preserves_data(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            saved = repo.create(_make_alarm(label="Keep me"))
            alarm_id = saved.id
        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.label == "Keep me"

    def test_default_path_is_under_home_alarm_clock(self):
        path = default_db_path()
        assert path.name == "alarms.db"
        assert path.parent.name == ".alarm-clock"
        assert path == Path.home() / ".alarm-clock" / "alarms.db"

    def test_close_then_operations_fail(self, db_path: Path):
        repo = AlarmRepository(db_path)
        repo.close()
        with pytest.raises(Exception):
            repo.list_alarms()


class TestCRUD:
    def test_create_and_get(self, repo: AlarmRepository):
        saved = repo.create(_make_alarm())
        assert saved.id >= 1
        loaded = repo.get(saved.id)
        assert loaded.id == saved.id
        assert loaded.time == AlarmTime(7, 30)
        assert loaded.label == "Wake up"
        assert loaded.enabled is True
        assert loaded.recurrence is RecurrenceType.ONCE
        assert loaded.timezone == TZ
        assert loaded.state is AlarmState.SCHEDULED
        assert loaded.next_fire_at == _dt(2026, 9, 11, 7, 30)
        assert loaded.created_at is not None
        assert loaded.created_at.tzinfo is not None

    def test_create_assigns_unique_ids(self, repo: AlarmRepository):
        a1 = repo.create(_make_alarm(label="One"))
        a2 = repo.create(_make_alarm(label="Two"))
        assert a1.id != a2.id

    def test_list_alarms_ordered_by_id(self, repo: AlarmRepository):
        repo.create(_make_alarm(label="A"))
        repo.create(_make_alarm(label="B"))
        listed = repo.list_alarms()
        assert [a.label for a in listed] == ["A", "B"]
        assert listed[0].id < listed[1].id

    def test_update_alarm(self, repo: AlarmRepository):
        saved = repo.create(_make_alarm())
        saved.label = "Updated"
        saved.time = AlarmTime(8, 0)
        saved.next_fire_at = _dt(2026, 9, 11, 8, 0)
        updated = repo.update(saved)
        assert updated.label == "Updated"
        assert updated.time == AlarmTime(8, 0)
        assert updated.next_fire_at == _dt(2026, 9, 11, 8, 0)
        assert updated.id == saved.id

    def test_delete_alarm(self, repo: AlarmRepository):
        saved = repo.create(_make_alarm())
        repo.delete(saved.id)
        with pytest.raises(AlarmNotFound):
            repo.get(saved.id)

    def test_get_missing_raises(self, repo: AlarmRepository):
        with pytest.raises(AlarmNotFound, match="42"):
            repo.get(42)

    def test_update_missing_raises(self, repo: AlarmRepository):
        alarm = _make_alarm()
        alarm.id = 99
        with pytest.raises(AlarmNotFound):
            repo.update(alarm)

    def test_delete_missing_raises(self, repo: AlarmRepository):
        with pytest.raises(AlarmNotFound):
            repo.delete(99)


class TestPersistenceRoundTrip:
    def test_full_round_trip_all_fields(self, db_path: Path):
        days = frozenset({Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY})
        with AlarmRepository(db_path) as repo:
            alarm = create_alarm(
                id=0,
                time=AlarmTime(7, 30),
                after=_dt(2026, 9, 8, 6, 0),  # Tuesday
                label="Gym",
                recurrence=RecurrenceType.CUSTOM_DAYS,
                days=days,
                timezone=TZ,
            )
            saved = repo.create(alarm)
            alarm_id = saved.id
            created_at = saved.created_at

        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.time == AlarmTime(7, 30)
            assert loaded.label == "Gym"
            assert loaded.enabled is True
            assert loaded.recurrence is RecurrenceType.CUSTOM_DAYS
            assert loaded.days == days
            assert loaded.timezone == TZ
            assert loaded.state is AlarmState.SCHEDULED
            assert loaded.next_fire_at == _dt(2026, 9, 9, 7, 30)
            assert loaded.created_at == created_at

    def test_enabled_disabled_persists(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            alarm = _make_alarm()
            alarm.disable()
            saved = repo.create(alarm)
            alarm_id = saved.id
        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.enabled is False
            loaded.enable()
            repo.update(loaded)
        with AlarmRepository(db_path) as repo:
            assert repo.get(alarm_id).enabled is True

    def test_completed_one_time_persists(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            alarm = _make_alarm()
            saved = repo.create(alarm)
            saved.start_ringing()
            saved.dismiss(_dt(2026, 9, 11, 7, 31))
            assert saved.state is AlarmState.COMPLETED
            assert saved.next_fire_at is None
            repo.update(saved)
            alarm_id = saved.id
        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.state is AlarmState.COMPLETED
            assert loaded.next_fire_at is None

    def test_recurring_alarm_persists(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            alarm = create_alarm(
                id=0,
                time=AlarmTime(7, 30),
                after=_dt(2026, 9, 11, 6, 0),
                recurrence=RecurrenceType.WEEKDAYS,
                timezone=TZ,
                label="Weekday",
            )
            saved = repo.create(alarm)
            alarm_id = saved.id
        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.recurrence is RecurrenceType.WEEKDAYS
            assert loaded.next_fire_at == _dt(2026, 9, 11, 7, 30)

    def test_snoozed_next_fire_at_persists(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            alarm = create_alarm(
                id=0,
                time=AlarmTime(7, 30),
                after=_dt(2026, 9, 11, 6, 0),
                recurrence=RecurrenceType.DAILY,
                timezone=TZ,
            )
            saved = repo.create(alarm)
            saved.start_ringing()
            now = _dt(2026, 9, 11, 7, 30)
            saved.snooze(now)
            assert saved.state is AlarmState.SCHEDULED
            assert saved.next_fire_at == now + DEFAULT_SNOOZE
            repo.update(saved)
            alarm_id = saved.id
            expected = saved.next_fire_at
        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.state is AlarmState.SCHEDULED
            assert loaded.next_fire_at == expected
            # Absolute instant equality (may differ in tz display).
            assert loaded.next_fire_at.astimezone(timezone.utc) == (
                expected.astimezone(timezone.utc)
            )

    def test_ringing_normalized_to_scheduled_on_load(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            saved = repo.create(_make_alarm())
            saved.start_ringing()
            assert saved.state is AlarmState.RINGING
            repo.update(saved)
            alarm_id = saved.id
        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.state is AlarmState.SCHEDULED
            assert loaded.next_fire_at is not None

    def test_multiple_alarms_independent(self, db_path: Path):
        with AlarmRepository(db_path) as repo:
            a1 = repo.create(_make_alarm(label="One", time=AlarmTime(7, 0)))
            a2 = repo.create(
                create_alarm(
                    id=0,
                    time=AlarmTime(8, 0),
                    after=_dt(2026, 9, 11, 6, 0),
                    label="Two",
                    recurrence=RecurrenceType.DAILY,
                    timezone="Asia/Kolkata",
                )
            )
            id1, id2 = a1.id, a2.id
        with AlarmRepository(db_path) as repo:
            first = repo.get(id1)
            second = repo.get(id2)
            assert first.label == "One"
            assert first.time == AlarmTime(7, 0)
            assert first.timezone == TZ
            assert second.label == "Two"
            assert second.time == AlarmTime(8, 0)
            assert second.recurrence is RecurrenceType.DAILY
            assert second.timezone == "Asia/Kolkata"
            assert len(repo.list_alarms()) == 2

    def test_does_not_use_real_user_database(self, db_path: Path, repo):
        assert repo.path == db_path
        assert repo.path.resolve() != default_db_path().resolve()


class TestNextFireAtSerialization:
    def test_next_fire_at_round_trips_across_timezones(self, db_path: Path):
        fire_at = datetime(
            2026, 9, 11, 7, 35, tzinfo=ZoneInfo("America/New_York")
        )
        with AlarmRepository(db_path) as repo:
            alarm = _make_alarm()
            alarm.next_fire_at = fire_at
            saved = repo.create(alarm)
            alarm_id = saved.id
        with AlarmRepository(db_path) as repo:
            loaded = repo.get(alarm_id)
            assert loaded.next_fire_at is not None
            assert loaded.next_fire_at == fire_at
            assert abs(
                (loaded.next_fire_at - fire_at).total_seconds()
            ) < 0.001
