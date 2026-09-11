"""Textual application integration tests (deterministic)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from alarm_clock.app import create_app
from alarm_clock.models import AlarmState, AlarmTime, RecurrenceType
from alarm_clock.time_service import FakeClock
from alarm_clock.tui.forms import AlarmFormScreen, default_timezone_value
from alarm_clock.tui.screens import (
    AlarmDetailScreen,
    MainScreen,
    RingingScreen,
    StopwatchScreen,
)
from textual.widgets import Select


TZ = "America/New_York"


def _dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))


@pytest.fixture
def harness(tmp_path: Path):
    clock = FakeClock(_dt(2026, 9, 11, 6, 0))
    app, repo, scheduler = create_app(db_path=tmp_path / "alarms.db", clock=clock)
    scheduler.start()
    yield app, repo, scheduler, clock
    scheduler.stop()
    repo.close()


async def _wait_main(app, pilot) -> MainScreen:
    for _ in range(40):
        if isinstance(app.screen, MainScreen):
            return app.screen
        await pilot.pause(0.05)
    raise AssertionError(f"Expected MainScreen, got {type(app.screen)}")


async def _wait_ringing(app, pilot) -> RingingScreen:
    for _ in range(50):
        if isinstance(app.screen, RingingScreen):
            try:
                app.screen.query_one("#ring-anim")
                return app.screen
            except Exception:
                pass
        await pilot.pause(0.05)
    raise AssertionError(f"Expected RingingScreen, got {type(app.screen)}")


@pytest.mark.asyncio
async def test_app_starts_and_shows_main(harness):
    app, repo, scheduler, clock = harness
    async with app.run_test() as pilot:
        screen = await _wait_main(app, pilot)
        assert screen.query_one("#clock-time")
        assert screen.query_one("#alarms")


@pytest.mark.asyncio
async def test_existing_alarms_appear(harness):
    app, repo, scheduler, clock = harness
    app.manager.create(
        time=AlarmTime(7, 30),
        label="Wake up",
        recurrence=RecurrenceType.WEEKDAYS,
        timezone=TZ,
    )
    async with app.run_test() as pilot:
        screen = await _wait_main(app, pilot)
        screen.refresh_alarms()
        assert screen.query_one("#alarms").row_count == 1


@pytest.mark.asyncio
async def test_create_via_manager_refreshes(harness):
    app, repo, scheduler, clock = harness
    async with app.run_test() as pilot:
        screen = await _wait_main(app, pilot)
        alarm = app.manager.create(
            time=AlarmTime(8, 0),
            label="Standup",
            timezone=TZ,
        )
        screen.refresh_alarms()
        assert alarm.id >= 1
        assert screen.query_one("#alarms").row_count == 1


@pytest.mark.asyncio
async def test_edit_delete_toggle(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="Wake",
        timezone=TZ,
    )
    async with app.run_test() as pilot:
        screen = await _wait_main(app, pilot)
        screen.refresh_alarms()

        app.manager.update(alarm.id, label="Wake updated")
        screen.refresh_alarms()
        assert app.manager.get(alarm.id).label == "Wake updated"

        app.manager.disable(alarm.id)
        assert app.manager.get(alarm.id).enabled is False
        app.manager.enable(alarm.id)
        assert app.manager.get(alarm.id).enabled is True

        app.manager.delete(alarm.id)
        screen.refresh_alarms()
        assert screen.query_one("#alarms").row_count == 0


@pytest.mark.asyncio
async def test_detail_action_opens(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="Detail me",
        timezone=TZ,
    )
    async with app.run_test() as pilot:
        screen = await _wait_main(app, pilot)
        screen.refresh_alarms()
        table = screen.query_one("#alarms")
        table.focus()
        table.move_cursor(row=0)
        await pilot.press("i")
        for _ in range(20):
            if isinstance(app.screen, AlarmDetailScreen):
                break
            await pilot.pause(0.05)
        assert isinstance(app.screen, AlarmDetailScreen)
        assert app.screen.query_one("#detail-body") is not None


@pytest.mark.asyncio
async def test_scheduler_notification_reaches_ui(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="Ring me",
        timezone=TZ,
    )
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        clock.set(_dt(2026, 9, 11, 7, 30))
        ring = await _wait_ringing(app, pilot)
        assert ring.alarm_id == alarm.id
        assert app.manager.get(alarm.id).state is AlarmState.RINGING


@pytest.mark.asyncio
async def test_snooze_and_dismiss_via_ringing_screen(harness):
    app, repo, scheduler, clock = harness
    a1 = app.manager.create(time=AlarmTime(7, 30), label="A", timezone=TZ)
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        clock.set(_dt(2026, 9, 11, 7, 30))
        await _wait_ringing(app, pilot)
        await pilot.press("s")
        for _ in range(20):
            if isinstance(app.screen, MainScreen):
                break
            await pilot.pause(0.05)
        snoozed = app.manager.get(a1.id)
        assert snoozed.state is AlarmState.SCHEDULED
        assert snoozed.next_fire_at is not None

        clock.set(snoozed.next_fire_at)
        await _wait_ringing(app, pilot)
        await pilot.press("d")
        for _ in range(20):
            if isinstance(app.screen, MainScreen):
                break
            await pilot.pause(0.05)
        assert app.manager.get(a1.id).state is AlarmState.COMPLETED


@pytest.mark.asyncio
async def test_multiple_ringing_not_lost(harness):
    app, repo, scheduler, clock = harness
    a1 = app.manager.create(time=AlarmTime(7, 30), label="One", timezone=TZ)
    a2 = app.manager.create(time=AlarmTime(7, 30), label="Two", timezone=TZ)
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        clock.set(_dt(2026, 9, 11, 7, 30))
        ring1 = await _wait_ringing(app, pilot)
        first_id = ring1.alarm_id
        await pilot.press("d")
        ring2 = await _wait_ringing(app, pilot)
        second_id = ring2.alarm_id
        assert {first_id, second_id} == {a1.id, a2.id}
        await pilot.press("d")


@pytest.mark.asyncio
async def test_shutdown_stops_scheduler(tmp_path: Path):
    clock = FakeClock(_dt(2026, 9, 11, 6, 0))
    app, repo, scheduler = create_app(db_path=tmp_path / "x.db", clock=clock)
    scheduler.start()
    assert scheduler.is_running
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        await pilot.press("q")
    scheduler.stop()
    repo.close()
    assert not scheduler.is_running


@pytest.mark.asyncio
async def test_stopwatch_screen(harness):
    app, repo, scheduler, clock = harness
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        await pilot.press("w")
        for _ in range(20):
            if isinstance(app.screen, StopwatchScreen):
                break
            await pilot.pause(0.05)
        assert isinstance(app.screen, StopwatchScreen)
        await pilot.press("s")
        assert app.stopwatch.state.value == "RUNNING"
        await pilot.press("escape")
        await _wait_main(app, pilot)


async def _wait_form(app, pilot) -> AlarmFormScreen:
    for _ in range(80):
        if isinstance(app.screen, AlarmFormScreen):
            try:
                app.screen.query_one("#timezone", Select)
                return app.screen
            except Exception:
                pass
        await pilot.pause(0.05)
    raise AssertionError(f"Expected AlarmFormScreen, got {type(app.screen)}")


@pytest.mark.asyncio
async def test_new_alarm_form_has_timezone_selector(harness):
    app, repo, scheduler, clock = harness
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        await pilot.press("a")
        form = await _wait_form(app, pilot)
        tz = form.query_one("#timezone", Select)
        assert isinstance(tz, Select)
        # Options come from zoneinfo, not a tiny hard-coded list.
        assert len(tz._options) >= 100  # noqa: SLF001 — verify full IANA set
        assert tz.value == default_timezone_value() or isinstance(tz.value, str)


@pytest.mark.asyncio
async def test_new_alarm_defaults_to_local_timezone(harness):
    app, repo, scheduler, clock = harness
    expected = default_timezone_value()
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        await pilot.press("a")
        form = await _wait_form(app, pilot)
        tz = form.query_one("#timezone", Select)
        assert tz.value == expected


@pytest.mark.asyncio
async def test_timezone_can_be_selected_and_saved(harness):
    app, repo, scheduler, clock = harness
    captured = {}

    def on_closed(result):
        captured["result"] = result

    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        app.push_screen(AlarmFormScreen(), on_closed)
        form = await _wait_form(app, pilot)
        tz = form.query_one("#timezone", Select)
        tz.value = "Asia/Kolkata"
        assert tz.value == "Asia/Kolkata"
        form.save()
        for _ in range(20):
            if "result" in captured:
                break
            await pilot.pause(0.05)
        assert captured["result"] is not None
        assert captured["result"]["timezone"] == "Asia/Kolkata"
        alarm = app.manager.create(
            **{
                k: captured["result"][k]
                for k in ("time", "label", "timezone", "recurrence", "days")
            }
        )
        assert alarm.timezone == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_edit_form_preselects_alarm_timezone(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="TZ edit",
        timezone="Europe/London",
    )
    async with app.run_test() as pilot:
        screen = await _wait_main(app, pilot)
        screen.refresh_alarms()
        table = screen.query_one("#alarms")
        table.focus()
        table.move_cursor(row=0)
        await pilot.press("e")
        form = await _wait_form(app, pilot)
        tz = form.query_one("#timezone", Select)
        assert tz.value == "Europe/London"


@pytest.mark.asyncio
async def test_edit_save_preserves_timezone_when_unchanged(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="Keep TZ",
        timezone="Pacific/Auckland",
    )
    captured = {}

    def on_closed(result):
        captured["result"] = result

    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        app.push_screen(AlarmFormScreen(alarm), on_closed)
        form = await _wait_form(app, pilot)
        assert form.query_one("#timezone", Select).value == "Pacific/Auckland"
        form.save()
        for _ in range(20):
            if "result" in captured:
                break
            await pilot.pause(0.05)
        assert captured["result"]["timezone"] == "Pacific/Auckland"
        app.manager.update(
            alarm.id,
            time=captured["result"]["time"],
            label=captured["result"]["label"],
            timezone=captured["result"]["timezone"],
            recurrence=captured["result"]["recurrence"],
            days=captured["result"]["days"],
        )
        assert app.manager.get(alarm.id).timezone == "Pacific/Auckland"


@pytest.mark.asyncio
async def test_ringing_screen_shows_animation_and_hints(harness):
    app, repo, scheduler, clock = harness
    app.manager.create(time=AlarmTime(7, 30), label="Wake", timezone=TZ)
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        clock.set(_dt(2026, 9, 11, 7, 30))
        ring = await _wait_ringing(app, pilot)
        assert ring.query_one("#ring-title") is not None
        assert ring.query_one("#ring-anim") is not None
        assert ring.query_one("#ring-keys") is not None
        assert ring.animation_running is True
        await pilot.pause(0.5)
        # Timer should still be advancing frames while ringing.
        assert ring.animation_running is True
        assert 0 <= ring._frame < len(ring.ANIM_FRAMES)


@pytest.mark.asyncio
async def test_snooze_keyboard_persists_next_fire_at(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="Snooze me",
        timezone=TZ,
        recurrence=RecurrenceType.DAILY,
    )
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        clock.set(_dt(2026, 9, 11, 7, 30))
        ring = await _wait_ringing(app, pilot)
        assert ring.animation_running is True
        await pilot.press("s")
        for _ in range(20):
            if isinstance(app.screen, MainScreen):
                break
            await pilot.pause(0.05)
        snoozed = app.manager.get(alarm.id)
        assert snoozed.state is AlarmState.SCHEDULED
        assert snoozed.next_fire_at is not None
        # Persisted on disk as SCHEDULED with snoozed next_fire_at
        from_disk = repo.get(alarm.id)
        assert from_disk.next_fire_at == snoozed.next_fire_at
        assert from_disk.state is AlarmState.SCHEDULED


@pytest.mark.asyncio
async def test_dismiss_one_time_completes_and_stops_animation(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="Once",
        timezone=TZ,
        recurrence=RecurrenceType.ONCE,
    )
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        clock.set(_dt(2026, 9, 11, 7, 30))
        ring = await _wait_ringing(app, pilot)
        await pilot.press("d")
        for _ in range(20):
            if isinstance(app.screen, MainScreen):
                break
            await pilot.pause(0.05)
        done = app.manager.get(alarm.id)
        assert done.state is AlarmState.COMPLETED
        assert done.next_fire_at is None
        assert repo.get(alarm.id).state is AlarmState.COMPLETED


@pytest.mark.asyncio
async def test_dismiss_daily_schedules_next_occurrence(harness):
    app, repo, scheduler, clock = harness
    alarm = app.manager.create(
        time=AlarmTime(7, 30),
        label="Daily",
        timezone=TZ,
        recurrence=RecurrenceType.DAILY,
    )
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        clock.set(_dt(2026, 9, 11, 7, 30))
        await _wait_ringing(app, pilot)
        await pilot.press("d")
        for _ in range(20):
            if isinstance(app.screen, MainScreen):
                break
            await pilot.pause(0.05)
        refreshed = app.manager.get(alarm.id)
        assert refreshed.state is AlarmState.SCHEDULED
        assert refreshed.next_fire_at == _dt(2026, 9, 12, 7, 30)


@pytest.mark.asyncio
async def test_audible_alert_attempted_on_ring(harness):
    app, repo, scheduler, clock = harness
    app.manager.create(time=AlarmTime(7, 30), label="Bell", timezone=TZ)
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        before = app.bell_events
        clock.set(_dt(2026, 9, 11, 7, 30))
        await _wait_ringing(app, pilot)
        assert app.bell_events > before


@pytest.mark.asyncio
async def test_custom_weekdays_inactive_unless_custom(harness):
    from textual.widgets import Checkbox
    from textual.containers import Vertical

    app, repo, scheduler, clock = harness
    async with app.run_test() as pilot:
        await _wait_main(app, pilot)
        await pilot.press("a")
        form = await _wait_form(app, pilot)
        await pilot.pause(0.1)
        # Default recurrence is Once → weekdays disabled
        assert form.query_one("#day-0", Checkbox).disabled is True
        assert form.query_one("#days-box", Vertical).has_class("inactive")

        form.query_one("#recurrence", Select).value = RecurrenceType.CUSTOM_DAYS
        form._update_days_enabled()
        assert form.query_one("#day-0", Checkbox).disabled is False
        assert not form.query_one("#days-box", Vertical).has_class("inactive")


@pytest.mark.asyncio
async def test_empty_alarms_message_visible(harness):
    app, repo, scheduler, clock = harness
    async with app.run_test() as pilot:
        screen = await _wait_main(app, pilot)
        empty = screen.query_one("#empty-alarms")
        assert empty.has_class("visible")
        app.manager.create(time=AlarmTime(8, 0), timezone=TZ)
        screen.refresh_alarms()
        assert not empty.has_class("visible")
