"""Alarm create/edit form screen."""

from __future__ import annotations

from typing import FrozenSet, List, Optional, Tuple

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static
from zoneinfo import available_timezones

from alarm_clock.errors import AlarmError
from alarm_clock.models import Alarm, RecurrenceType, Weekday
from alarm_clock.time_service import get_local_timezone
from alarm_clock.tui.formatting import format_alarm_time, parse_alarm_time

_RECURRENCE_OPTIONS = [
    ("Once", RecurrenceType.ONCE),
    ("Daily", RecurrenceType.DAILY),
    ("Weekdays", RecurrenceType.WEEKDAYS),
    ("Weekends", RecurrenceType.WEEKENDS),
    ("Custom days", RecurrenceType.CUSTOM_DAYS),
]

# Cache IANA names once — the set is large but stable for a process.
_TIMEZONE_OPTIONS: Optional[List[Tuple[str, str]]] = None


def timezone_options(
    *,
    include: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Return sorted (label, value) pairs for all available IANA timezones."""
    global _TIMEZONE_OPTIONS
    if _TIMEZONE_OPTIONS is None:
        _TIMEZONE_OPTIONS = [(name, name) for name in sorted(available_timezones())]
    options = list(_TIMEZONE_OPTIONS)
    if include and include not in {value for _, value in options}:
        options.append((include, include))
        options.sort(key=lambda item: item[1])
    return options


def default_timezone_value() -> str:
    """System/local timezone key for new-alarm form defaults."""
    local = get_local_timezone()
    key = getattr(local, "key", None)
    if isinstance(key, str) and key:
        return key
    return "UTC"


class AlarmFormScreen(ModalScreen[Optional[dict]]):
    """Modal form for creating or editing an alarm."""

    CSS = """
    AlarmFormScreen {
        align: center middle;
    }
    #form-dialog {
        width: 72;
        max-height: 90%;
        border: heavy $accent;
        background: $surface;
        padding: 1 2;
    }
    #form-title {
        text-style: bold;
        margin-bottom: 1;
    }
    .row {
        height: auto;
        margin-bottom: 1;
    }
    #error {
        color: $error;
        margin-top: 1;
    }
    #days-box {
        height: auto;
        margin: 1 0;
    }
    #days-box.inactive {
        opacity: 0.45;
    }
    #timezone {
        width: 1fr;
    }
    """

    def __init__(self, alarm: Optional[Alarm] = None) -> None:
        super().__init__()
        self._alarm = alarm
        self._editing = alarm is not None

    def compose(self) -> ComposeResult:
        alarm = self._alarm
        time_value = format_alarm_time(alarm.time) if alarm else "07:30 AM"
        label_value = alarm.label if alarm else ""
        if alarm is not None:
            tz_value = alarm.timezone
        else:
            tz_value = default_timezone_value()
        recurrence = alarm.recurrence if alarm else RecurrenceType.ONCE
        days = alarm.days if alarm else frozenset()
        tz_options = timezone_options(include=tz_value)

        with Vertical(id="form-dialog"):
            yield Static(
                "Edit Alarm" if self._editing else "New Alarm",
                id="form-title",
            )
            yield Label("Time (e.g. 07:30 AM or 19:30)")
            yield Input(value=time_value, id="time", placeholder="07:30 AM")
            yield Label("Label")
            yield Input(value=label_value, id="label", placeholder="Wake up")
            yield Label("Timezone")
            yield Select(
                tz_options,
                value=tz_value,
                id="timezone",
                allow_blank=False,
                prompt="Select timezone",
            )
            yield Label("Recurrence")
            yield Select(
                [(label, value) for label, value in _RECURRENCE_OPTIONS],
                value=recurrence,
                id="recurrence",
                allow_blank=False,
            )
            with Vertical(id="days-box"):
                yield Label("Custom weekdays (active only for Custom days)")
                for day in Weekday:
                    yield Checkbox(
                        day.name.title()[:3],
                        value=day in days,
                        id=f"day-{day.value}",
                    )
            yield Static("", id="error")
            with Horizontal(classes="row"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.call_after_refresh(self._after_mount)

    def _after_mount(self) -> None:
        self._update_days_enabled()
        try:
            self.query_one("#time", Input).focus()
        except Exception:
            pass

    def _update_days_enabled(self) -> None:
        custom = self._selected_recurrence() is RecurrenceType.CUSTOM_DAYS
        days_box = self.query_one("#days-box", Vertical)
        if custom:
            days_box.remove_class("inactive")
        else:
            days_box.add_class("inactive")
        for day in Weekday:
            box = self.query_one(f"#day-{day.value}", Checkbox)
            box.disabled = not custom

    @on(Select.Changed, "#recurrence")
    def on_recurrence_changed(self, event: Select.Changed) -> None:
        self._update_days_enabled()

    def _selected_recurrence(self) -> RecurrenceType:
        value = self.query_one("#recurrence", Select).value
        if isinstance(value, RecurrenceType):
            return value
        return RecurrenceType.ONCE

    def _selected_timezone(self) -> str:
        value = self.query_one("#timezone", Select).value
        if isinstance(value, str) and value:
            return value
        return default_timezone_value()

    def _selected_days(self) -> FrozenSet[Weekday]:
        selected = set()
        for day in Weekday:
            box = self.query_one(f"#day-{day.value}", Checkbox)
            if box.value:
                selected.add(day)
        return frozenset(selected)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        error = self.query_one("#error", Static)
        try:
            alarm_time = parse_alarm_time(self.query_one("#time", Input).value)
            label = self.query_one("#label", Input).value.strip()
            timezone = self._selected_timezone()
            recurrence = self._selected_recurrence()
            days = (
                self._selected_days()
                if recurrence is RecurrenceType.CUSTOM_DAYS
                else None
            )
            payload = {
                "time": alarm_time,
                "label": label,
                "timezone": timezone,
                "recurrence": recurrence,
                "days": days,
            }
            self.dismiss(payload)
        except AlarmError as exc:
            error.update(str(exc))
