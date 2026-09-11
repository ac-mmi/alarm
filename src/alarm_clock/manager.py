"""Application-facing alarm coordination over the repository."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, FrozenSet, List, Optional

from alarm_clock.alarms import create_alarm, is_due, update_alarm
from alarm_clock.errors import AlarmNotFound
from alarm_clock.models import (
    DEFAULT_SNOOZE,
    Alarm,
    AlarmState,
    AlarmTime,
    RecurrenceType,
    Weekday,
)
from alarm_clock.repository import AlarmRepository
from alarm_clock.time_service import Clock, RealClock


class AlarmManager:
    """Coordinates domain mutations, persistence, and scheduler wake-ups.

    Keeps an in-memory snapshot so runtime ``RINGING`` state is preserved even
    though the repository persists ``RINGING`` as ``SCHEDULED`` for restart
    safety (Stage 2). The scheduler must read alarms through this manager.
    """

    def __init__(
        self,
        repository: AlarmRepository,
        clock: Optional[Clock] = None,
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self._repo = repository
        self._clock = clock if clock is not None else RealClock()
        self._on_change = on_change
        self._lock = threading.RLock()
        self._alarms: Dict[int, Alarm] = {}
        self.reload()

    def set_on_change(self, on_change: Optional[Callable[[], None]]) -> None:
        self._on_change = on_change

    def _emit_change(self) -> None:
        callback = self._on_change
        if callback is not None:
            callback()

    def reload(self) -> None:
        """Load alarms from the repository into the in-memory snapshot."""
        with self._lock:
            loaded = self._repo.list_alarms()
            self._alarms = {alarm.id: alarm for alarm in loaded}

    def list_alarms(self) -> List[Alarm]:
        with self._lock:
            return [self._alarms[i] for i in sorted(self._alarms)]

    def get(self, alarm_id: int) -> Alarm:
        with self._lock:
            alarm = self._alarms.get(alarm_id)
            if alarm is None:
                raise AlarmNotFound(f"Alarm #{alarm_id} does not exist")
            return alarm

    def create(
        self,
        *,
        time: AlarmTime,
        label: str = "",
        recurrence: RecurrenceType = RecurrenceType.ONCE,
        days: Optional[FrozenSet[Weekday]] = None,
        timezone: Optional[str] = None,
        enabled: bool = True,
    ) -> Alarm:
        after = self._clock.now()
        draft = create_alarm(
            id=0,
            time=time,
            after=after,
            label=label,
            recurrence=recurrence,
            days=days,
            timezone=timezone,
            enabled=enabled,
        )
        with self._lock:
            saved = self._repo.create(draft)
            self._alarms[saved.id] = saved
        self._emit_change()
        return saved

    def update(
        self,
        alarm_id: int,
        *,
        time: Optional[AlarmTime] = None,
        label: Optional[str] = None,
        recurrence: Optional[RecurrenceType] = None,
        days: Optional[FrozenSet[Weekday]] = None,
        timezone: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Alarm:
        with self._lock:
            alarm = self.get(alarm_id)
            update_alarm(
                alarm,
                after=self._clock.now(),
                time=time,
                label=label,
                recurrence=recurrence,
                days=days,
                timezone=timezone,
                enabled=enabled,
            )
            self._persist_runtime(alarm)
        self._emit_change()
        return alarm

    def delete(self, alarm_id: int) -> None:
        with self._lock:
            if alarm_id not in self._alarms:
                raise AlarmNotFound(f"Alarm #{alarm_id} does not exist")
            self._repo.delete(alarm_id)
            del self._alarms[alarm_id]
        self._emit_change()

    def enable(self, alarm_id: int) -> Alarm:
        with self._lock:
            alarm = self.get(alarm_id)
            alarm.enable()
            self._persist_runtime(alarm)
        self._emit_change()
        return alarm

    def disable(self, alarm_id: int) -> Alarm:
        with self._lock:
            alarm = self.get(alarm_id)
            alarm.disable()
            self._persist_runtime(alarm)
        self._emit_change()
        return alarm

    def dismiss(self, alarm_id: int) -> Alarm:
        with self._lock:
            alarm = self.get(alarm_id)
            alarm.dismiss(self._clock.now())
            self._persist_runtime(alarm)
        self._emit_change()
        return alarm

    def snooze(
        self,
        alarm_id: int,
        duration: timedelta = DEFAULT_SNOOZE,
    ) -> Alarm:
        with self._lock:
            alarm = self.get(alarm_id)
            alarm.snooze(self._clock.now(), duration=duration)
            self._persist_runtime(alarm)
        self._emit_change()
        return alarm

    def start_ringing(self, alarm_id: int) -> Alarm:
        """Transition a due/scheduled alarm to RINGING and persist."""
        with self._lock:
            alarm = self.get(alarm_id)
            if alarm.state is AlarmState.RINGING:
                return alarm
            alarm.start_ringing()
            self._persist_runtime(alarm)
            return alarm

    def due_alarms(self, now: Optional[datetime] = None) -> List[Alarm]:
        """Return enabled due alarms in ascending ID order."""
        instant = now if now is not None else self._clock.now()
        with self._lock:
            due = [a for a in self._alarms.values() if is_due(a, instant)]
            due.sort(key=lambda a: a.id)
            return due

    def next_fire_at(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """Earliest future ``next_fire_at`` among eligible scheduled alarms."""
        instant = now if now is not None else self._clock.now()
        with self._lock:
            candidates = []
            for alarm in self._alarms.values():
                if not alarm.enabled:
                    continue
                if alarm.state is not AlarmState.SCHEDULED:
                    continue
                if alarm.next_fire_at is None:
                    continue
                if alarm.next_fire_at <= instant:
                    # Already due — wake immediately (delay 0).
                    return alarm.next_fire_at
                candidates.append(alarm.next_fire_at)
            if not candidates:
                return None
            return min(candidates)

    def _persist_runtime(self, alarm: Alarm) -> None:
        """Write alarm to SQLite while keeping the in-memory runtime object.

        The repository may normalize ``RINGING`` → ``SCHEDULED`` on disk; we
        intentionally keep the caller's object (and cache entry) unchanged so
        the scheduler does not re-trigger the same occurrence.
        """
        self._repo.update(alarm)
        self._alarms[alarm.id] = alarm
