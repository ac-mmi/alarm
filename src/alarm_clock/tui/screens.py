"""Primary Textual screens: main list, detail, stopwatch, ringing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Static,
)

from alarm_clock.errors import AlarmError, AlarmNotFound
from alarm_clock.models import Alarm, AlarmState
from alarm_clock.stopwatch import Stopwatch
from alarm_clock.tui.formatting import (
    format_alarm_time,
    format_clock,
    format_next_fire,
    format_recurrence,
    format_status,
    format_status_glyph,
)
from alarm_clock.tui.forms import AlarmFormScreen

if TYPE_CHECKING:
    from alarm_clock.app import AlarmClockApp


class RingingScreen(ModalScreen[None]):
    """Polished ringing modal with animation, snooze, and dismiss."""

    BINDINGS = [
        Binding("s", "snooze", "Snooze", show=True),
        Binding("d", "dismiss", "Dismiss", show=True),
        Binding("escape", "dismiss", "Dismiss", show=False),
    ]

    ANIM_FRAMES = (
        "* * *   ALARM RINGING   * * *",
        " o o    ALARM RINGING    o o ",
        "* * *   ALARM RINGING   * * *",
        "  *     ALARM RINGING     *  ",
    )

    CSS = """
    RingingScreen {
        align: center middle;
    }
    #ring-dialog {
        width: 62;
        height: auto;
        border: heavy $error;
        background: $surface;
        padding: 1 2;
    }
    #ring-anim {
        text-align: center;
        text-style: bold;
        color: $error;
        height: 1;
        margin-bottom: 1;
    }
    #ring-title {
        text-align: center;
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }
    #ring-time {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #ring-label, #ring-meta, #ring-queue, #ring-keys {
        text-align: center;
        margin-bottom: 1;
    }
    #ring-keys {
        color: $text-muted;
    }
    #ring-actions {
        align: center middle;
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, alarm: Alarm, queue_size: int = 1) -> None:
        super().__init__()
        self.alarm_id = alarm.id
        self._alarm = alarm
        self._queue_size = queue_size
        self._frame = 0
        self._anim_timer = None
        self.animation_running = True

    def compose(self) -> ComposeResult:
        label = self._alarm.label or "(no label)"
        meta = (
            f"Alarm #{self._alarm.id}  ·  "
            f"{format_recurrence(self._alarm)}  ·  "
            f"{self._alarm.timezone}"
        )
        with Vertical(id="ring-dialog"):
            yield Static(self.ANIM_FRAMES[0], id="ring-anim")
            yield Static("AN ALARM IS RINGING", id="ring-title")
            yield Static(format_alarm_time(self._alarm.time), id="ring-time")
            yield Static(label.upper(), id="ring-label")
            yield Static(meta, id="ring-meta")
            if self._queue_size > 1:
                yield Static(
                    f"{self._queue_size} alarms ringing — handle this one first",
                    id="ring-queue",
                )
            else:
                yield Static("", id="ring-queue")
            yield Static("[S] Snooze   [D] Dismiss", id="ring-keys")
            with Horizontal(id="ring-actions"):
                yield Button("Snooze [S]", variant="warning", id="snooze")
                yield Button("Dismiss [D]", variant="primary", id="dismiss")

    def on_mount(self) -> None:
        self.animation_running = True
        self._anim_timer = self.set_interval(0.45, self._advance_animation)

    def on_unmount(self) -> None:
        self._stop_animation()

    def _advance_animation(self) -> None:
        if not self.animation_running:
            return
        try:
            self._frame = (self._frame + 1) % len(self.ANIM_FRAMES)
            self.query_one("#ring-anim", Static).update(
                self.ANIM_FRAMES[self._frame]
            )
        except Exception:
            self._stop_animation()

    def _stop_animation(self) -> None:
        self.animation_running = False
        if self._anim_timer is not None:
            try:
                self._anim_timer.stop()
            except Exception:
                pass
            self._anim_timer = None

    @on(Button.Pressed, "#snooze")
    def press_snooze(self) -> None:
        self.action_snooze()

    @on(Button.Pressed, "#dismiss")
    def press_dismiss(self) -> None:
        self.action_dismiss()

    def action_snooze(self) -> None:
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            self._stop_animation()
            app.manager.snooze(self.alarm_id)
            self.dismiss(None)
        except AlarmError as exc:
            self.notify(str(exc), severity="error")

    def action_dismiss(self) -> None:
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            self._stop_animation()
            app.manager.dismiss(self.alarm_id)
            self.dismiss(None)
        except AlarmError as exc:
            self.notify(str(exc), severity="error")


class AlarmDetailScreen(ModalScreen[None]):
    """Read-only detail view for a single alarm."""

    BINDINGS = [Binding("escape", "close", "Close", show=True)]

    CSS = """
    AlarmDetailScreen {
        align: center middle;
    }
    #detail-dialog {
        width: 64;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, alarm: Alarm) -> None:
        super().__init__()
        self._alarm = alarm

    def compose(self) -> ComposeResult:
        alarm = self._alarm
        days = (
            ", ".join(sorted(d.name.title() for d in alarm.days))
            if alarm.days
            else "-"
        )
        next_fire = (
            alarm.next_fire_at.isoformat()
            if alarm.next_fire_at is not None
            else "-"
        )
        lines = [
            f"ID:          {alarm.id}",
            f"Time:        {format_alarm_time(alarm.time)}",
            f"Label:       {alarm.label or '-'}",
            f"Enabled:     {'Yes' if alarm.enabled else 'No'}",
            f"Status:      {alarm.state.value}",
            f"Recurrence:  {format_recurrence(alarm)}",
            f"Custom days: {days}",
            f"Timezone:    {alarm.timezone}",
            f"Next fire:   {next_fire}",
        ]
        with Vertical(id="detail-dialog"):
            yield Static("Alarm Details", classes="title")
            yield Static("\n".join(lines), id="detail-body")
            yield Button("Close", id="close", variant="primary")

    @on(Button.Pressed, "#close")
    def close_pressed(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class StopwatchScreen(Screen):
    """Live stopwatch screen using the stopwatch domain object."""

    BINDINGS = [
        Binding("s", "start", "Start", show=True),
        Binding("p", "pause", "Pause", show=True),
        Binding("r", "resume", "Resume", show=True),
        Binding("z", "reset", "Reset", show=True),
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("q", "app.pop_screen", "Back", show=False),
    ]

    CSS = """
    StopwatchScreen {
        align: center middle;
    }
    #sw-panel {
        width: 48;
        height: auto;
        border: solid $accent;
        padding: 2;
        text-align: center;
    }
    #sw-display {
        text-style: bold;
        text-align: center;
        margin: 1 0;
    }
    #sw-state {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def __init__(self, stopwatch: Stopwatch) -> None:
        super().__init__()
        self.stopwatch = stopwatch

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="sw-panel"):
            yield Static("Stopwatch", classes="title")
            yield Static(self.stopwatch.format_elapsed(), id="sw-display")
            yield Static(self.stopwatch.state.value, id="sw-state")
            yield Static("[S] Start  [P] Pause  [R] Resume  [Z] Reset  [Esc] Back")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.05, self._tick)

    def _tick(self) -> None:
        self.query_one("#sw-display", Static).update(
            self.stopwatch.format_elapsed()
        )
        self.query_one("#sw-state", Static).update(self.stopwatch.state.value)

    def _safe(self, action) -> None:
        try:
            action()
            self._tick()
        except AlarmError as exc:
            self.notify(str(exc), severity="error")

    def action_start(self) -> None:
        self._safe(self.stopwatch.start)

    def action_pause(self) -> None:
        self._safe(self.stopwatch.pause)

    def action_resume(self) -> None:
        self._safe(self.stopwatch.resume)

    def action_reset(self) -> None:
        self._safe(self.stopwatch.reset)


class MainScreen(Screen):
    """Main alarm clock screen: live clock + alarm list."""

    BINDINGS = [
        Binding("a", "add", "Add", show=True),
        Binding("e", "edit", "Edit", show=True),
        Binding("delete", "delete", "Delete", show=True),
        Binding("d", "delete", "Delete", show=False),
        Binding("t", "toggle", "Enable/Disable", show=True),
        Binding("i", "details", "Details", show=True),
        Binding("enter", "details", "Details", show=False),
        Binding("w", "stopwatch", "Stopwatch", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    MainScreen {
        layout: vertical;
    }
    #clock-panel {
        height: 5;
        border: solid $accent;
        padding: 0 2;
        margin: 1;
    }
    #clock-time {
        text-style: bold;
        color: $accent;
    }
    #alarm-panel {
        height: 1fr;
        border: solid $primary;
        margin: 0 1 1 1;
        padding: 0 1;
    }
    #alarms-title {
        text-style: bold;
        padding: 1 0 0 0;
    }
    #empty-alarms {
        color: $text-muted;
        padding: 1 0;
        display: none;
    }
    #empty-alarms.visible {
        display: block;
    }
    #hint {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
    }
    DataTable > .datatable--cursor {
        background: $accent 30%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="clock-panel"):
            yield Static("", id="clock-time")
            yield Static("", id="clock-date")
            yield Static("", id="clock-tz")
        with Container(id="alarm-panel"):
            yield Static("Alarms", id="alarms-title")
            yield Static(
                "No alarms yet — press A to add one.",
                id="empty-alarms",
            )
            yield DataTable(id="alarms", cursor_type="row", zebra_stripes=True)
        yield Static(
            "A add · E edit · D delete · T on/off · I details · W stopwatch · Q quit",
            id="hint",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#alarms", DataTable)
        table.add_columns(" ", "Status", "Time", "Label", "Repeat", "Next")
        self.refresh_alarms()
        self.set_interval(0.5, self.refresh_clock)
        self.refresh_clock()

    def refresh_clock(self) -> None:
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        now = app.clock.now()
        time_str, date_str, tz = format_clock(now)
        self.query_one("#clock-time", Static).update(f"Current Time: {time_str}")
        self.query_one("#clock-date", Static).update(f"Date: {date_str}")
        self.query_one("#clock-tz", Static).update(f"Timezone: {tz}")

    def refresh_alarms(self) -> None:
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        table = self.query_one("#alarms", DataTable)
        table.clear()
        now = app.clock.now()
        alarms = app.manager.list_alarms()
        empty = self.query_one("#empty-alarms", Static)
        if not alarms:
            empty.add_class("visible")
        else:
            empty.remove_class("visible")
        for alarm in alarms:
            table.add_row(
                format_status_glyph(alarm),
                format_status(alarm),
                format_alarm_time(alarm.time),
                alarm.label or "-",
                format_recurrence(alarm),
                format_next_fire(alarm, now=now),
                key=str(alarm.id),
            )

    def _selected_alarm_id(self) -> Optional[int]:
        table = self.query_one("#alarms", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        try:
            return int(str(row_key.value))
        except (TypeError, ValueError):
            return None

    def action_add(self) -> None:
        self.app.push_screen(AlarmFormScreen(), self._on_form_closed)

    def action_edit(self) -> None:
        alarm_id = self._selected_alarm_id()
        if alarm_id is None:
            self.notify("Select an alarm first", severity="warning")
            return
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            alarm = app.manager.get(alarm_id)
        except AlarmNotFound as exc:
            self.notify(str(exc), severity="error")
            return
        self.app.push_screen(
            AlarmFormScreen(alarm),
            lambda result, aid=alarm_id: self._on_edit_closed(aid, result),
        )

    def action_delete(self) -> None:
        alarm_id = self._selected_alarm_id()
        if alarm_id is None:
            self.notify("Select an alarm first", severity="warning")
            return
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            app.manager.delete(alarm_id)
            self.refresh_alarms()
            self.notify(f"Alarm #{alarm_id} deleted")
        except AlarmError as exc:
            self.notify(str(exc), severity="error")

    def action_toggle(self) -> None:
        alarm_id = self._selected_alarm_id()
        if alarm_id is None:
            self.notify("Select an alarm first", severity="warning")
            return
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            alarm = app.manager.get(alarm_id)
            if alarm.enabled:
                app.manager.disable(alarm_id)
                self.notify(f"Alarm #{alarm_id} disabled")
            else:
                app.manager.enable(alarm_id)
                self.notify(f"Alarm #{alarm_id} enabled")
            self.refresh_alarms()
        except AlarmError as exc:
            self.notify(str(exc), severity="error")

    def action_details(self) -> None:
        alarm_id = self._selected_alarm_id()
        if alarm_id is None:
            self.notify("Select an alarm first", severity="warning")
            return
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            alarm = app.manager.get(alarm_id)
        except AlarmNotFound as exc:
            self.notify(str(exc), severity="error")
            return
        self.app.push_screen(AlarmDetailScreen(alarm))

    def action_stopwatch(self) -> None:
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        self.app.push_screen(StopwatchScreen(app.stopwatch))

    def action_quit(self) -> None:
        self.app.exit()

    def _on_form_closed(self, result: Optional[dict]) -> None:
        if result is None:
            return
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            alarm = app.manager.create(
                time=result["time"],
                label=result["label"],
                recurrence=result["recurrence"],
                days=result["days"],
                timezone=result["timezone"],
            )
            self.refresh_alarms()
            self.notify(f"Alarm #{alarm.id} created")
        except AlarmError as exc:
            self.notify(str(exc), severity="error")

    def _on_edit_closed(self, alarm_id: int, result: Optional[dict]) -> None:
        if result is None:
            return
        app: AlarmClockApp = self.app  # type: ignore[assignment]
        try:
            app.manager.update(
                alarm_id,
                time=result["time"],
                label=result["label"],
                recurrence=result["recurrence"],
                days=result["days"],
                timezone=result["timezone"],
            )
            self.refresh_alarms()
            self.notify(f"Alarm #{alarm_id} updated")
        except AlarmError as exc:
            self.notify(str(exc), severity="error")
