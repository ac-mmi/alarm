"""Deterministic tests for AlarmManager + Scheduler."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from alarm_clock.manager import AlarmManager
from alarm_clock.models import (
    DEFAULT_SNOOZE,
    AlarmState,
    AlarmTime,
    RecurrenceType,
    Weekday,
)
from alarm_clock.repository import AlarmRepository
from alarm_clock.scheduler import Scheduler
from alarm_clock.time_service import FakeClock


TZ = "America/New_York"


def _dt(year, month, day, hour, minute, tz=TZ) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz))


class RingRecorder:
    def __init__(self) -> None:
        self.alarms = []
        self.event = threading.Event()
        self.lock = threading.Lock()

    def __call__(self, alarm) -> None:
        with self.lock:
            self.alarms.append(alarm)
            self.event.set()

    def wait_n(self, n: int, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if len(self.alarms) >= n:
                    return True
            self.event.wait(timeout=0.05)
            self.event.clear()
        with self.lock:
            return len(self.alarms) >= n

    def ids(self):
        with self.lock:
            return [a.id for a in self.alarms]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "alarms.db"


@pytest.fixture
def clock():
    return FakeClock(_dt(2026, 9, 11, 6, 0))


@pytest.fixture
def repo(db_path: Path):
    repository = AlarmRepository(db_path)
    yield repository
    repository.close()


@pytest.fixture
def manager(repo, clock):
    return AlarmManager(repo, clock=clock)


@pytest.fixture
def recorder():
    return RingRecorder()


@pytest.fixture
def scheduler(manager, recorder, clock):
    sched = Scheduler(manager, recorder, clock=clock)
    sched.start()
    assert sched.is_running
    yield sched
    sched.stop()
    assert not sched.is_running


class TestSchedulerLifecycle:
    def test_start_and_stop(self, manager, recorder, clock):
        sched = Scheduler(manager, recorder, clock=clock)
        sched.start()
        assert sched.is_running
        sched.stop()
        assert not sched.is_running

    def test_repeated_stop_is_safe(self, manager, recorder, clock):
        sched = Scheduler(manager, recorder, clock=clock)
        sched.start()
        sched.stop()
        sched.stop()
        assert not sched.is_running

    def test_stop_without_start_is_safe(self, manager, recorder, clock):
        sched = Scheduler(manager, recorder, clock=clock)
        sched.stop()

    def test_shutdown_does_not_deadlock(self, manager, recorder, clock):
        sched = Scheduler(manager, recorder, clock=clock)
        sched.start()
        manager.create(time=AlarmTime(10, 0), timezone=TZ)
        sched.stop(timeout=2.0)
        assert not sched.is_running


class TestScheduling:
    def test_no_alarms(self, scheduler, recorder, clock):
        clock.advance(timedelta(hours=5))
        assert recorder.wait_n(1, timeout=0.2) is False
        assert recorder.ids() == []

    def test_future_alarm_not_due_yet(self, scheduler, manager, recorder, clock):
        manager.create(time=AlarmTime(7, 30), timezone=TZ, label="Later")
        assert recorder.wait_n(1, timeout=0.2) is False

    def test_alarm_becomes_due(self, scheduler, manager, recorder, clock):
        alarm = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="Wake")
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        assert recorder.ids() == [alarm.id]
        assert manager.get(alarm.id).state is AlarmState.RINGING

    def test_disabled_alarms_ignored(self, scheduler, manager, recorder, clock):
        alarm = manager.create(time=AlarmTime(7, 30), timezone=TZ)
        manager.disable(alarm.id)
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1, timeout=0.2) is False
        assert manager.get(alarm.id).state is AlarmState.SCHEDULED

    def test_deleted_alarms_ignored(self, scheduler, manager, recorder, clock):
        alarm = manager.create(time=AlarmTime(7, 30), timezone=TZ)
        manager.delete(alarm.id)
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1, timeout=0.2) is False

    def test_multiple_simultaneous_alarms(self, scheduler, manager, recorder, clock):
        a1 = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="A")
        a2 = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="B")
        a3 = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="C")
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(3)
        assert recorder.ids() == [a1.id, a2.id, a3.id]
        for alarm_id in (a1.id, a2.id, a3.id):
            assert manager.get(alarm_id).state is AlarmState.RINGING

    def test_same_occurrence_not_retrigged(self, scheduler, manager, recorder, clock):
        alarm = manager.create(time=AlarmTime(7, 30), timezone=TZ)
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        clock.advance(timedelta(seconds=30))
        scheduler.notify_changes()
        assert recorder.wait_n(2, timeout=0.2) is False
        assert recorder.ids() == [alarm.id]


class TestWakeOnMutation:
    def test_earlier_new_alarm_wakes_and_fires(
        self, scheduler, manager, recorder, clock
    ):
        manager.create(time=AlarmTime(10, 0), timezone=TZ, label="Late")
        earlier = manager.create(
            time=AlarmTime(9, 30), timezone=TZ, label="Early"
        )
        clock.set(_dt(2026, 9, 11, 9, 30))
        assert recorder.wait_n(1)
        assert recorder.ids() == [earlier.id]

    def test_updated_time_rescheduled(self, scheduler, manager, recorder, clock):
        alarm = manager.create(time=AlarmTime(10, 0), timezone=TZ)
        manager.update(alarm.id, time=AlarmTime(7, 30))
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        assert recorder.ids() == [alarm.id]

    def test_disable_next_alarm_moves_on(
        self, scheduler, manager, recorder, clock
    ):
        first = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="First")
        second = manager.create(
            time=AlarmTime(8, 0), timezone=TZ, label="Second"
        )
        manager.disable(first.id)
        clock.set(_dt(2026, 9, 11, 8, 0))
        assert recorder.wait_n(1)
        assert recorder.ids() == [second.id]

    def test_delete_next_alarm_moves_on(
        self, scheduler, manager, recorder, clock
    ):
        first = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="First")
        second = manager.create(
            time=AlarmTime(8, 0), timezone=TZ, label="Second"
        )
        manager.delete(first.id)
        clock.set(_dt(2026, 9, 11, 8, 0))
        assert recorder.wait_n(1)
        assert recorder.ids() == [second.id]

    def test_enable_makes_alarm_eligible(
        self, scheduler, manager, recorder, clock
    ):
        alarm = manager.create(
            time=AlarmTime(7, 30), timezone=TZ, enabled=False
        )
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1, timeout=0.2) is False
        manager.enable(alarm.id)
        assert recorder.wait_n(1)
        assert recorder.ids() == [alarm.id]


class TestRecurrenceAfterDismiss:
    def test_one_time_completes(self, scheduler, manager, recorder, clock):
        alarm = manager.create(
            time=AlarmTime(7, 30),
            timezone=TZ,
            recurrence=RecurrenceType.ONCE,
        )
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        manager.dismiss(alarm.id)
        completed = manager.get(alarm.id)
        assert completed.state is AlarmState.COMPLETED
        assert completed.next_fire_at is None
        clock.advance(timedelta(days=1))
        assert recorder.wait_n(2, timeout=0.2) is False

    def test_daily_reschedules_on_dismiss(
        self, scheduler, manager, recorder, clock
    ):
        alarm = manager.create(
            time=AlarmTime(7, 30),
            timezone=TZ,
            recurrence=RecurrenceType.DAILY,
        )
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        manager.dismiss(alarm.id)
        refreshed = manager.get(alarm.id)
        assert refreshed.state is AlarmState.SCHEDULED
        assert refreshed.next_fire_at == _dt(2026, 9, 12, 7, 30)

    def test_weekdays_reschedules_to_monday(
        self, scheduler, manager, recorder, clock
    ):
        alarm = manager.create(
            time=AlarmTime(7, 30),
            timezone=TZ,
            recurrence=RecurrenceType.WEEKDAYS,
        )
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        manager.dismiss(alarm.id)
        assert manager.get(alarm.id).next_fire_at == _dt(2026, 9, 14, 7, 30)

    def test_weekends_reschedules(self, scheduler, manager, recorder, clock):
        clock.set(_dt(2026, 9, 12, 6, 0))  # Saturday
        alarm = manager.create(
            time=AlarmTime(9, 0),
            timezone=TZ,
            recurrence=RecurrenceType.WEEKENDS,
        )
        clock.set(_dt(2026, 9, 12, 9, 0))
        assert recorder.wait_n(1)
        manager.dismiss(alarm.id)
        assert manager.get(alarm.id).next_fire_at == _dt(2026, 9, 13, 9, 0)

    def test_custom_days_reschedules(self, scheduler, manager, recorder, clock):
        days = frozenset({Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY})
        alarm = manager.create(
            time=AlarmTime(7, 30),
            timezone=TZ,
            recurrence=RecurrenceType.CUSTOM_DAYS,
            days=days,
        )
        clock.set(_dt(2026, 9, 11, 7, 30))  # Friday
        assert recorder.wait_n(1)
        manager.dismiss(alarm.id)
        assert manager.get(alarm.id).next_fire_at == _dt(2026, 9, 14, 7, 30)


class TestSnooze:
    def test_snooze_fires_at_new_next_fire_at(
        self, scheduler, manager, recorder, clock
    ):
        alarm = manager.create(
            time=AlarmTime(7, 30),
            timezone=TZ,
            recurrence=RecurrenceType.DAILY,
        )
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        manager.snooze(alarm.id)
        snoozed = manager.get(alarm.id)
        assert snoozed.state is AlarmState.SCHEDULED
        assert snoozed.next_fire_at == _dt(2026, 9, 11, 7, 30) + DEFAULT_SNOOZE
        assert snoozed.time == AlarmTime(7, 30)

        clock.set(snoozed.next_fire_at)
        assert recorder.wait_n(2)
        assert recorder.ids() == [alarm.id, alarm.id]


class TestCatchUp:
    def test_already_due_on_start(self, manager, recorder, clock):
        alarm = manager.create(time=AlarmTime(7, 30), timezone=TZ)
        clock.set(_dt(2026, 9, 11, 8, 0))
        sched = Scheduler(manager, recorder, clock=clock)
        sched.start()
        try:
            assert recorder.wait_n(1)
            assert recorder.ids() == [alarm.id]
            assert manager.get(alarm.id).state is AlarmState.RINGING
        finally:
            sched.stop()

    def test_completed_not_caught_up(self, manager, recorder, clock):
        alarm = manager.create(time=AlarmTime(7, 30), timezone=TZ)
        clock.set(_dt(2026, 9, 11, 7, 30))
        sched = Scheduler(manager, recorder, clock=clock)
        sched.start()
        try:
            assert recorder.wait_n(1)
            manager.dismiss(alarm.id)
        finally:
            sched.stop()

        recorder2 = RingRecorder()
        clock.advance(timedelta(hours=1))
        sched2 = Scheduler(manager, recorder2, clock=clock)
        sched2.start()
        try:
            assert recorder2.wait_n(1, timeout=0.2) is False
            assert manager.get(alarm.id).state is AlarmState.COMPLETED
        finally:
            sched2.stop()


class TestCallbackResilience:
    def test_callback_exception_does_not_kill_scheduler(self, manager, clock):
        calls = []
        fail_once = {"done": False}
        gate = threading.Event()

        def flaky(alarm):
            calls.append(alarm.id)
            gate.set()
            if not fail_once["done"]:
                fail_once["done"] = True
                raise RuntimeError("boom")

        a1 = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="One")
        a2 = manager.create(time=AlarmTime(7, 30), timezone=TZ, label="Two")
        sched = Scheduler(manager, flaky, clock=clock)
        sched.start()
        try:
            clock.set(_dt(2026, 9, 11, 7, 30))
            assert gate.wait(timeout=2.0)
            deadline_ok = False
            for _ in range(40):
                if len(calls) >= 2:
                    deadline_ok = True
                    break
                gate.wait(timeout=0.05)
                gate.clear()
            assert deadline_ok
            assert a1.id in calls and a2.id in calls
            assert sched.is_running
        finally:
            sched.stop()


class TestManagerPersistenceCoordination:
    def test_ringing_survives_in_memory_not_retrigged_via_repo(
        self, scheduler, manager, recorder, clock, repo
    ):
        alarm = manager.create(time=AlarmTime(7, 30), timezone=TZ)
        clock.set(_dt(2026, 9, 11, 7, 30))
        assert recorder.wait_n(1)
        from_disk = repo.get(alarm.id)
        assert from_disk.state is AlarmState.SCHEDULED
        assert manager.get(alarm.id).state is AlarmState.RINGING
        clock.advance(timedelta(minutes=1))
        scheduler.notify_changes()
        assert recorder.wait_n(2, timeout=0.2) is False
