"""Notification boundary between the scheduler and presentation layers."""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional, Protocol, TextIO

from alarm_clock.models import Alarm

logger = logging.getLogger(__name__)


class AlarmNotifier(Protocol):
    """Called when the scheduler transitions an alarm to RINGING.

    Implementations may show a Textual UI, play sound, or record events in
    tests. The scheduler must not depend on any concrete notifier behavior.
    """

    def notify_ringing(self, alarm: Alarm) -> None:
        """Report that *alarm* has started ringing."""


class CallbackNotifier:
    """Adapter that forwards ringing events to a plain callable."""

    def __init__(self, callback: Callable[[Alarm], None]) -> None:
        self._callback = callback

    def notify_ringing(self, alarm: Alarm) -> None:
        self._callback(alarm)


def play_terminal_bell(stream: Optional[TextIO] = None) -> None:
    """Emit the ASCII BEL character (``\\a``) if the stream supports it.

    Failures are swallowed: missing TTY / closed stream must never crash
    the scheduler or TUI.
    """
    out = stream if stream is not None else sys.stderr
    try:
        out.write("\a")
        out.flush()
    except Exception:  # noqa: BLE001 — sound is best-effort
        logger.debug("Terminal bell unavailable", exc_info=True)


class CompositeNotifier:
    """Runs an audible alert then a visual/callback notifier.

    Audible work stays independent of Textual. Visual work is typically an
    ``App.call_from_thread`` bridge supplied by the application shell.
    """

    def __init__(
        self,
        visual: Callable[[Alarm], None],
        *,
        audible: Optional[Callable[[], None]] = None,
    ) -> None:
        self._visual = visual
        self._audible = audible if audible is not None else play_terminal_bell

    def notify_ringing(self, alarm: Alarm) -> None:
        try:
            self._audible()
        except Exception:  # noqa: BLE001
            logger.debug("Audible notification failed", exc_info=True)
        self._visual(alarm)
