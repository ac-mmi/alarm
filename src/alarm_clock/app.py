"""Textual application shell and lifecycle."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Deque, Optional, Union

from textual.app import App

from alarm_clock.manager import AlarmManager
from alarm_clock.models import Alarm, AlarmState
from alarm_clock.notifications import CompositeNotifier
from alarm_clock.repository import AlarmRepository, default_db_path
from alarm_clock.scheduler import Scheduler
from alarm_clock.stopwatch import Stopwatch
from alarm_clock.time_service import Clock, RealClock
from alarm_clock.tui.screens import MainScreen, RingingScreen


class AlarmClockApp(App[None]):
    """Interactive Textual alarm clock.

    The scheduler notifies this app from a background thread via
    ``notify_ringing_from_thread``, which marshals work onto the UI thread
    with ``call_from_thread``.
    """

    TITLE = "Alarm Clock"
    CSS = """
    Screen {
        background: $background;
    }
    """
    BINDINGS = []

    def __init__(
        self,
        manager: AlarmManager,
        clock: Optional[Clock] = None,
        stopwatch: Optional[Stopwatch] = None,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.clock = clock if clock is not None else RealClock()
        self.stopwatch = stopwatch if stopwatch is not None else Stopwatch()
        self._ring_queue: Deque[int] = deque()
        self._ringing_screen_active = False
        self._pending_rings: Deque[int] = deque()
        self.bell_events = 0  # tests may assert audible attempts

    def on_mount(self) -> None:
        self.push_screen(MainScreen())
        while self._pending_rings:
            alarm_id = self._pending_rings.popleft()
            self.handle_ringing(alarm_id)

    def notify_ringing_from_thread(self, alarm: Alarm) -> None:
        """Scheduler-thread entry point. Must not touch widgets directly."""
        try:
            self.call_from_thread(self.handle_ringing, alarm.id)
        except RuntimeError:
            # App event loop not running yet (startup race).
            self._pending_rings.append(alarm.id)

    def handle_ringing(self, alarm_id: int) -> None:
        """UI-thread handler: enqueue ringing alarm and show modal if needed."""
        if alarm_id not in self._ring_queue:
            self._ring_queue.append(alarm_id)
        self._refresh_main_if_present()
        self._show_next_ringing()

    def record_bell(self) -> None:
        """Track that an audible alert was attempted (also used by tests)."""
        self.bell_events += 1

    def after_ring_action(self) -> None:
        """Called after the ringing modal closes (snooze/dismiss)."""
        self._ringing_screen_active = False
        remaining: Deque[int] = deque()
        for alarm_id in self._ring_queue:
            try:
                alarm = self.manager.get(alarm_id)
            except Exception:
                continue
            if alarm.state is AlarmState.RINGING:
                remaining.append(alarm_id)
        self._ring_queue = remaining
        self._refresh_main_if_present()
        self._show_next_ringing()

    def _on_ring_screen_closed(self, _result=None) -> None:
        self.after_ring_action()

    def _show_next_ringing(self) -> None:
        if self._ringing_screen_active:
            return
        while self._ring_queue:
            alarm_id = self._ring_queue[0]
            try:
                alarm = self.manager.get(alarm_id)
            except Exception:
                self._ring_queue.popleft()
                continue
            if alarm.state is not AlarmState.RINGING:
                self._ring_queue.popleft()
                continue
            self._ringing_screen_active = True
            queue_size = sum(1 for aid in self._ring_queue if self._is_ringing(aid))
            self.push_screen(
                RingingScreen(alarm, queue_size=queue_size),
                self._on_ring_screen_closed,
            )
            return

    def _is_ringing(self, alarm_id: int) -> bool:
        try:
            return self.manager.get(alarm_id).state is AlarmState.RINGING
        except Exception:
            return False

    def _refresh_main_if_present(self) -> None:
        screen = self.screen
        if isinstance(screen, MainScreen):
            screen.refresh_alarms()
        # Also refresh if main is under a modal.
        for s in self.screen_stack:
            if isinstance(s, MainScreen):
                s.refresh_alarms()


def create_app(
    db_path: Optional[Union[str, Path]] = None,
    clock: Optional[Clock] = None,
) -> tuple[AlarmClockApp, AlarmRepository, Scheduler]:
    """Wire repository, manager, scheduler, and Textual app."""
    path = Path(db_path) if db_path is not None else default_db_path()
    clock = clock if clock is not None else RealClock()
    repository = AlarmRepository(path)
    manager = AlarmManager(repository, clock=clock)
    app = AlarmClockApp(manager, clock=clock)

    def audible() -> None:
        from alarm_clock.notifications import play_terminal_bell

        play_terminal_bell()
        app.record_bell()

    notifier = CompositeNotifier(
        app.notify_ringing_from_thread,
        audible=audible,
    )
    scheduler = Scheduler(manager, notifier, clock=clock)
    return app, repository, scheduler


def run_app(db_path: Optional[Union[str, Path]] = None) -> None:
    """Start the full application and shut down cleanly on exit."""
    app, repository, scheduler = create_app(db_path=db_path)
    scheduler.start()
    try:
        app.run()
    finally:
        scheduler.stop()
        repository.close()
