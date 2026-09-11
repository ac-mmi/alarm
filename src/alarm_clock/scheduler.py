"""Background alarm scheduler."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional, Union

from alarm_clock.manager import AlarmManager
from alarm_clock.models import Alarm
from alarm_clock.notifications import AlarmNotifier, CallbackNotifier
from alarm_clock.time_service import Clock, FakeClock, RealClock

logger = logging.getLogger(__name__)


class Scheduler:
    """Single background thread that detects due alarms and notifies.

    Wait model:
    - Compute the next eligible ``next_fire_at``.
    - Wait on ``_wake`` until that time, a mutation, or shutdown.
    - With ``FakeClock``, wall-clock timeout is ignored; waits only for
      ``_wake`` / ``_stop`` so tests stay deterministic.
    """

    def __init__(
        self,
        manager: AlarmManager,
        notifier: Union[AlarmNotifier, Callable[[Alarm], None]],
        clock: Optional[Clock] = None,
    ) -> None:
        self._manager = manager
        self._clock = clock if clock is not None else RealClock()
        if callable(notifier) and not hasattr(notifier, "notify_ringing"):
            self._notifier: AlarmNotifier = CallbackNotifier(notifier)
        else:
            self._notifier = notifier  # type: ignore[assignment]

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()

        # Wire mutation / fake-clock advances to the wake event.
        self._manager.set_on_change(self.notify_changes)
        if isinstance(self._clock, FakeClock):
            self._clock.set_on_change(self.notify_changes)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the background scheduler thread (idempotent if already running)."""
        if self.is_running:
            return
        self._stop.clear()
        self._wake.clear()
        self._started.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="alarm-scheduler",
            daemon=True,
        )
        self._thread.start()
        # Wait until the loop has entered once so tests can coordinate.
        self._started.wait(timeout=5.0)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and join the scheduler thread. Safe to call repeatedly."""
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def notify_changes(self) -> None:
        """Wake the scheduler so it recalculates the next fire time."""
        self._wake.set()

    def _run(self) -> None:
        self._started.set()
        try:
            while not self._stop.is_set():
                try:
                    self._tick()
                except Exception:  # noqa: BLE001 — keep scheduler alive
                    logger.exception("Scheduler tick failed; continuing")
                if self._stop.is_set():
                    break
                self._wait_for_next()
        finally:
            self._started.clear()

    def _tick(self) -> None:
        now = self._clock.now()
        due = self._manager.due_alarms(now)
        for alarm in due:
            if self._stop.is_set():
                return
            self._trigger(alarm)

    def _trigger(self, alarm: Alarm) -> None:
        try:
            ringing = self._manager.start_ringing(alarm.id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to start ringing for alarm #%s", alarm.id)
            return
        try:
            self._notifier.notify_ringing(ringing)
        except Exception:  # noqa: BLE001
            # Callback failures must not kill the scheduler thread.
            logger.exception(
                "Notification callback failed for alarm #%s", ringing.id
            )

    def _wait_for_next(self) -> None:
        if self._stop.is_set():
            return

        now = self._clock.now()
        # If anything is already due, do not sleep.
        if self._manager.due_alarms(now):
            return

        next_at = self._manager.next_fire_at(now)
        self._wake.clear()

        # Re-check after clearing to avoid a lost wake-up.
        now = self._clock.now()
        if self._stop.is_set() or self._manager.due_alarms(now):
            return
        next_at = self._manager.next_fire_at(now)
        if next_at is not None and next_at <= now:
            return
        if self._wake.is_set():
            return

        if isinstance(self._clock, FakeClock):
            # Deterministic mode: ignore wall duration; wait for wake/stop.
            while not self._stop.is_set():
                if self._wake.wait(timeout=0.05):
                    return
                now = self._clock.now()
                if next_at is not None and next_at <= now:
                    return
                if self._manager.due_alarms(now):
                    return
            return

        timeout: Optional[float]
        if next_at is None:
            timeout = None
        else:
            timeout = max(0.0, (next_at - now).total_seconds())
        self._wake.wait(timeout=timeout)
