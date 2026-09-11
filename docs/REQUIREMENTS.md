# Alarm Clock CLI — Requirements

## 1. Overview

Build a terminal-based alarm clock application in Python.

The application is a CLI-only terminal application. Its primary interface is an interactive TUI implemented with the **Textual** Python framework. This is not a web UI, React application, or desktop GUI.

The application should provide the core functionality expected from a modern alarm clock while remaining simple, reliable, and easy to use from the terminal.

Alarms must be persisted locally with SQLite so they survive application restarts.

The project is intentionally open-ended. The goal is not to maximize the number of features, but to demonstrate thoughtful engineering decisions, clear requirements, good software design, effective use of AI-assisted development, and reliable validation.

---

## 2. Goals

The application should allow a user to:

- View the current date and time.
- View or work with a timezone.
- Create and manage multiple alarms.
- Persist alarms so they survive application restarts.
- Configure one-time and recurring alarms.
- Enable and disable alarms.
- Update and delete alarms.
- Snooze or dismiss a ringing alarm.
- Receive a clear terminal notification when an alarm fires.
- Use terminal sound/notification capabilities where supported.
- Run a stopwatch.
- Interact with the application through a clean and intuitive Textual TUI.

The application should prioritize correctness and usability over unnecessary complexity. Core alarm behavior must remain independent of the presentation layer.

---

## 3. Constraints

### Required

- Python.
- CLI/terminal interface only (interactive Textual TUI in the terminal).
- Primary UI framework: **Textual**.
- No web UI.
- No React.
- No desktop GUI toolkit (for example, Tkinter/Qt) as the primary interface.
- Local SQLite persistence for alarms (no separate database server).
- No MySQL, PostgreSQL, or other external database systems.
- No external backend or cloud service.
- Must be runnable locally.
- Must be understandable and maintainable.
- Core functionality should be designed with the 30-minute implementation exercise in mind.

### Persistence

SQLite persistence is part of the application. Alarms must survive application restarts.

SQLite is appropriate because this is a local, single-user CLI application and does not require a separate database server.

Alarm configuration, enable/disable state, recurrence, timezone, lifecycle status needed after restart, and next-fire information required for correct scheduling must be stored durably.

Persistence does **not** replace the runtime scheduler. SQLite stores alarms; a running application process must still detect and trigger them.

---

## 3.1 Process Model

SQLite solves persistence. It does **not** run alarms by itself.

The application must distinguish:

```text
SQLite       → persistent storage
Scheduler    → runtime alarm detection and triggering
Textual TUI  → user interaction and presentation
```

The initial application should be a **long-running interactive Textual TUI session** that:

1. Opens the SQLite database.
2. Loads persisted alarms.
3. Starts the scheduler.
4. Runs the Textual application for interactive workflows.
5. Monitors and triggers alarms while the session is running.

A background daemon/service is **not** required for the initial implementation.

One-shot non-TUI command invocations that exit immediately are insufficient as the primary mode unless a separate long-running monitor exists. The primary product experience is the interactive long-running Textual session.

If the application is not running, due alarms are not expected to fire until the application is started again. On startup, the scheduler should detect enabled alarms whose next fire time is already due and trigger them (catch-up), subject to the lifecycle rules below.

---

# 4. Feature Requirements

## 4.1 Current Time

The application should be able to display:

- Current local time.
- Current date.
- Current timezone.

Example:

```text
Current Time: 10:42:31 PM
Date: Friday, September 11, 2026
Timezone: Asia/Kolkata
```

The application should use timezone-aware datetime handling rather than relying on naive datetime objects.

---

## 4.2 Timezone Support

The application should support timezone-aware clock/alarm behavior.

A user should be able to specify a timezone when appropriate.

Example:

```text
Timezone: America/New_York
Current Time: 01:12 PM
```

An alarm configured for a specific timezone should trigger according to that timezone's local time.

Weekday-based recurrence (weekdays, weekends, custom days) must evaluate the day of week in the **alarm's** timezone, not merely the host's local timezone.

Timezone handling should account for standard timezone rules, including daylight-saving transitions where applicable.

### DST gap (nonexistent local time)

If an alarm's local wall-clock time does not exist on a given day because of a spring-forward transition (for example, 02:30 on a day when clocks jump from 02:00 to 03:00), the occurrence for that day is skipped. The next occurrence is calculated from that skipped instant using the normal recurrence rules.

### DST fold (ambiguous local time)

If an alarm's local wall-clock time occurs twice because of a fall-back transition, the earlier occurrence (the first matching local time) is used.

Timezone functionality should not unnecessarily complicate the core local-time alarm experience.

---

# 5. Alarm Management

The application must support multiple alarms simultaneously.

Every alarm should have a unique identifier.

An alarm should contain, at minimum:

```text
id
time
label
enabled
recurrence
timezone
state
next_fire_at
```

Where:

- `time` is the configured wall-clock time of day for the alarm.
- `enabled` indicates whether the alarm is allowed to trigger.
- `state` is the lifecycle status (`SCHEDULED`, `RINGING`, `COMPLETED`).
- `next_fire_at` is the next concrete fire instant used by the scheduler (including after snooze).

The exact internal representation is an implementation decision, but these concepts must be reconstructible after restart from SQLite.

---

## 5.1 Create Alarm

Users should be able to create an alarm with:

- Time.
- Optional label.
- Recurrence configuration.
- Optional timezone.

Example:

```text
07:30 AM
Label: Wake up
Repeat: Weekdays
Timezone: Local
```

Successful creation should provide clear confirmation and persist the alarm immediately.

Example:

```text
✓ Alarm #1 created
  Time: 07:30 AM
  Label: Wake up
  Repeat: Weekdays
```

---

## 5.2 Multiple Alarms

Multiple alarms must be supported.

Two alarms may have the same scheduled time.

Creating a new alarm must **not silently overwrite an existing alarm**.

Each alarm receives its own unique ID.

Example:

```text
ID   Time       Label
1    07:30 AM   Wake up
2    07:30 AM   Take medication
```

---

## 5.3 List Alarms

Users should be able to view their alarms.

The list should clearly communicate:

- ID.
- Time.
- Label.
- Recurrence.
- Enabled/disabled state.
- Relevant timezone.

Example:

```text
ID   TIME       LABEL       REPEAT       STATUS
1    07:30 AM   Wake up     Weekdays     ON
2    09:00 AM   Meeting     Once         ON
3    10:00 PM   Reading     Daily        OFF
```

Completed one-time alarms may be shown as completed/inactive, or omitted from the default list, as long as behavior is consistent and documented in the design. They must not fire again after restart.

---

## 5.4 Update Alarm

Users should be able to modify an existing alarm without deleting and recreating it.

Possible properties to update include:

- Time.
- Label.
- Recurrence.
- Timezone.
- Enabled state.

Example:

```text
alarm update 1 --time 08:00
```

Updating an alarm should preserve its identity/ID and persist the change immediately.

Updating time, recurrence, or timezone should recalculate `next_fire_at` according to the past-time and recurrence rules.

---

## 5.5 Delete Alarm

Users should be able to delete an alarm using its ID.

Example:

```text
alarm delete 2

✓ Alarm #2 deleted
```

Deleting a nonexistent alarm should result in a clear error rather than an application crash.

Deletion must remove the alarm from SQLite.

If the deleted alarm is currently ringing, its notification must stop.

---

## 5.6 Enable / Disable

Users should be able to temporarily disable an alarm without deleting it.

Example:

```text
alarm disable 1
alarm enable 1
```

A disabled alarm must not trigger.

Enable/disable state must persist across restarts.

If a ringing alarm is disabled, the current notification stops and the alarm remains disabled and non-triggering until enabled again.

A completed one-time alarm cannot be re-armed merely by enabling it; the user should create a new alarm (or explicitly update it in a way that recalculates a future `next_fire_at`, if that path is supported).

---

# 6. Alarm Recurrence

An alarm should support several recurrence modes.

## 6.1 Once

The alarm triggers one time.

After it has been dismissed, it becomes completed/inactive and must not fire again after restart.

---

## 6.2 Every Day

The alarm triggers every day at the configured time.

Example:

```text
07:30 AM
Repeat: Every day
```

After dismissal, the next occurrence remains scheduled for the following day.

---

## 6.3 Weekdays

The alarm triggers Monday through Friday in the alarm's timezone.

Example:

```text
07:30 AM
Repeat: Weekdays
```

---

## 6.4 Weekends

The alarm triggers Saturday and Sunday in the alarm's timezone.

Example:

```text
09:00 AM
Repeat: Weekends
```

---

## 6.5 Custom Days

The user should be able to select individual weekdays.

Example:

```text
Repeat: Custom

[x] Monday
[ ] Tuesday
[x] Wednesday
[ ] Thursday
[x] Friday
[ ] Saturday
[ ] Sunday
```

The resulting alarm:

```text
07:30 AM
Repeat: Mon, Wed, Fri
```

At each occurrence, dismissing the alarm should schedule the same alarm for its next selected weekday.

If no custom days are selected, the application should reject the configuration with a useful validation message.

Custom day selections must persist across restarts.

---

# 7. Alarm State

An alarm should have a clear lifecycle.

Stored lifecycle states:

```text
SCHEDULED
RINGING
COMPLETED
```

`enabled` is a separate boolean flag, not a lifecycle state.

- Only enabled alarms in `SCHEDULED` may become `RINGING`.
- `RINGING` is a runtime state while the application is presenting the alarm.
- `COMPLETED` applies to finished one-time alarms and must persist so they do not fire after restart.

Conceptually:

```text
SCHEDULED
    |
    | scheduled time reached (and enabled)
    v
RINGING
   / \
  /   \
 v     v
dismiss  snooze
  |        |
  |        v
  |     SCHEDULED  (with snoozed next_fire_at)
  v
once → COMPLETED
recurring → SCHEDULED (next occurrence)
```

For one-time alarms:

```text
SCHEDULED → RINGING → COMPLETED
```

For recurring alarms:

```text
SCHEDULED → RINGING → SCHEDULED (next occurrence)
```

Disabled alarms should not enter the ringing state.

### Restart behavior

Across application restarts:

- Enabled recurring alarms remain enabled and keep their recurrence configuration.
- Disabled alarms remain disabled.
- Completed one-time alarms remain completed and must not fire again.
- `RINGING` is not expected to survive process death as an active UI state. On startup, if an enabled non-completed alarm has `next_fire_at <= now`, the scheduler should treat it as due and enter `RINGING` (catch-up).
- Snoozed alarms persist their snoozed `next_fire_at` so the postponed ring survives restart.

---

# 8. Alarm Triggering

When an enabled alarm reaches its scheduled time, the application must trigger an obvious notification.

The notification should include:

- Alarm indicator.
- Time.
- Label.
- Available actions.

Example:

```text
╔══════════════════════════════════════════╗
║                                          ║
║             🔔  ALARM!  🔔              ║
║                                          ║
║                07:30 AM                 ║
║                                          ║
║               WAKE UP!                  ║
║                                          ║
║        [S] Snooze   [D] Dismiss         ║
║                                          ║
╚══════════════════════════════════════════╝
```

The exact visual presentation is an implementation/UX decision.

An alarm remains ringing until the user snoozes or dismisses it, or until the alarm is disabled/deleted. There is no automatic ring timeout in the initial scope.

When multiple alarms are due at once, each becomes ringing independently. The Textual TUI should present them in a deterministic order (for example, by ID ascending) and accept snooze/dismiss for the currently focused ringing alarm, then proceed to the next. Simultaneous due alarms must not be silently dropped.

Snooze and dismiss input is handled by the Textual TUI while an alarm is ringing (for example, dedicated keybindings). Notification presentation must not permanently block the scheduler from detecting other due alarms or accepting shutdown.

---

# 9. Alarm Sound

The application should attempt to provide an audible alarm notification where the terminal/operating system supports it.

At minimum, the implementation may use a terminal bell or equivalent terminal notification.

Sound should not be tightly coupled to the core scheduling logic.

The alarm system should remain functional even if an audible notification cannot be produced.

The notification layer should therefore be designed so that visual and audible notifications can be handled independently.

---

# 10. Snooze

A ringing alarm should support snoozing.

Default snooze duration:

```text
5 minutes
```

Repeated snoozes are allowed. Each snooze postpones from the current moment by the snooze duration.

Example:

```text
[S] Snooze
[D] Dismiss
```

When snoozed:

```text
Alarm #1 snoozed for 5 minutes.
Next ring: 07:35 AM
```

Snoozing a recurring alarm should postpone the current occurrence without changing the underlying recurrence schedule (the configured time-of-day and recurrence rule remain unchanged).

Snooze must update and persist `next_fire_at` so a snoozed alarm still fires at the postponed time after an application restart.

---

# 11. Dismiss

The user should be able to dismiss a ringing alarm.

For a one-time alarm:

```text
RINGING → COMPLETED
```

For a recurring alarm:

```text
RINGING → SCHEDULED (next occurrence)
```

Dismissing an alarm should stop its current notification/sound and persist the resulting state / next fire time.

---

# 12. Alarm Behavior During Other TUI Operations

The alarm scheduler should not depend on the user actively interacting with the TUI beyond keeping the long-running Textual session alive.

If an alarm reaches its scheduled time while the application is performing another operation, the alarm should still be detected and triggered.

The application should avoid unnecessarily freezing the entire application while waiting for an alarm.

The implementation should separate:

```text
User interaction (Textual TUI)
```

from:

```text
Alarm scheduling
```

where practical.

The exact concurrency/event-loop approach is an implementation decision, but shared alarm state must be updated safely and persistence must remain consistent.

Mutations such as add, update, delete, enable, disable, snooze, and dismiss must be visible to the scheduler promptly (the scheduler must wake or otherwise re-evaluate after relevant changes).

---

# 13. Past Alarm Times

Alarm `time` values are times of day, not absolute historical datetimes.

If a user creates an alarm for a time that has already passed today in the alarm's timezone, the application must **not** trigger it immediately.

**Chosen behavior:** schedule the next valid future occurrence.

- For a one-time alarm: if today's occurrence is already past, schedule tomorrow at the configured time.
- For recurring alarms: calculate the next valid future occurrence based on the recurrence rules and timezone.

The same rule applies when updating an alarm's time, recurrence, or timezone: recompute `next_fire_at` as the next valid future occurrence.

An alarm is considered due when `next_fire_at <= now` (not only on exact equality), so slight scheduling overshoot still fires correctly.

Next-occurrence calculation uses a strictly-after reference instant: the occurrence returned must be after the provided `after` datetime.

---

# 14. Stopwatch

The application should also provide a basic stopwatch.

The stopwatch should support:

- Start.
- Pause.
- Resume.
- Reset.
- Display elapsed time.

Example:

```text
Stopwatch

00:00:12.42

[S] Start
[P] Pause
[R] Reset
[Q] Quit
```

Pausing should preserve elapsed time.

Resuming should continue from the paused elapsed time.

Reset should return the stopwatch to zero.

Invalid transitions must produce clear errors rather than undefined behavior. At minimum:

- Pause is valid only while running.
- Resume is valid only while paused.
- Start is valid from idle/reset; starting while already running is invalid (or treated as a no-op with a clear message—choose one and keep it consistent).

The stopwatch should use a monotonic time source where appropriate rather than relying on wall-clock time for elapsed-duration measurement.

The stopwatch is session-only and does not need SQLite persistence.

If an alarm rings while the stopwatch UI is active, the alarm notification takes priority; the stopwatch remains paused or keeps measuring in the background according to its current state, but alarm dismiss/snooze input takes precedence until the ringing alarm is handled.

---

# 15. TUI Design (Textual)

The application is a CLI-only terminal application whose **primary interface is an interactive TUI**.

The TUI will be implemented using the **Textual** Python framework.

This does **not** mean:

- a web UI,
- a React application,
- or a desktop GUI.

The Textual TUI should support the core interactive workflows, including:

- Viewing the current time.
- Viewing and managing alarms.
- Creating, editing, and deleting alarms.
- Enabling and disabling alarms.
- Viewing alarm details / next occurrence.
- Using the stopwatch.
- Interacting with a ringing alarm (snooze / dismiss).

The TUI should be predictable, discoverable, and easy to understand. Clear error messages, keyboard-driven interaction, testability of non-UI layers, and ease of use remain required.

The long-running Textual session keeps the scheduler alive while the user interacts with the application.

Optional non-TUI entry points may exist for convenience later, but they are not a substitute for the interactive Textual monitoring session in the initial product.

Exact screen layout and widget composition may be refined during implementation, as long as the workflows above remain supported and domain logic stays outside the TUI.

---

# 16. Terminal UX / Visual Presentation

The application should have a polished terminal experience without becoming unnecessarily complicated.

Because the presentation layer is Textual, visual polish such as colors, panels, keyboard navigation, animation, and live updates may be used where they improve usability.

Visual enhancements may include:

- Textual styling / colors.
- Panels and structured layouts.
- Clear status indicators.
- Keyboard navigation and bindings.
- Unicode/emoji icons where terminal support allows.
- Alarm notification screens or overlays.
- Lightweight animation.
- Live clock display.
- Countdown to the next alarm.

Example alarm list presentation:

```text
✓ 07:30 AM  Wake up       Weekdays    ENABLED
```

Example ringing presentation:

```text
╔══════════════════════════════════════╗
║          🔔  ALARM!  🔔              ║
║                                      ║
║             07:30 AM                 ║
║             WAKE UP!                 ║
║                                      ║
║       [S] Snooze  [D] Dismiss        ║
╚══════════════════════════════════════╝
```

If the terminal cannot render emoji or rich styling, a simpler Textual/plain-text presentation is acceptable.

Do **not** turn visual effects into unnecessary functional requirements. Core alarm behavior must remain independent of the presentation layer.

Visual polish should be implemented after the core functionality is reliable.

---

# 17. Error Handling

The application should handle invalid user input gracefully.

Examples include:

- Invalid time format.
- Invalid alarm ID.
- Duplicate/invalid arguments.
- Invalid recurrence configuration.
- Empty custom-day selection.
- Invalid timezone.
- Invalid stopwatch operation.
- Attempting to update/delete an alarm that does not exist.
- Database open/initialization failures presented clearly.

Errors should be understandable to a normal terminal / TUI user.

The application should not crash for ordinary user input errors.

---

# 18. Graceful Shutdown

The application should handle normal termination gracefully.

Examples:

```text
Ctrl+C
```

or an explicit quit command.

The application should cleanly stop:

- Scheduler activity.
- Alarm notifications.
- Stopwatch activity.
- Background resources/threads if used.
- SQLite / database resources.

Normal termination must not corrupt persisted alarm data. In-flight writes should complete or roll back cleanly.

No unnecessary traceback should be shown for normal user-initiated shutdown.

---

# 19. Non-Goals

The following are intentionally outside the initial scope:

- Web UI.
- React.
- Desktop GUI frameworks as the primary interface (Textual TUI in the terminal is in scope).
- External database servers (MySQL, PostgreSQL, etc.).
- ORM-heavy data layers (unless a concrete need appears; prefer `sqlite3`).
- User authentication.
- Cloud synchronization.
- Multi-user support.
- Remote notifications.
- Mobile application.
- Complex audio management.
- Distributed scheduling.
- Background OS daemon/service for alarm monitoring.
- External backend services.

---

# 20. Prioritization

Given the 30-minute implementation constraint, functionality should be prioritized.

## Priority 1 — Core

- Current time.
- SQLite persistence (create/load/update/delete).
- Create alarm.
- Multiple alarms.
- List alarms.
- Update alarm.
- Delete alarm.
- Enable/disable.
- Alarm scheduling in a long-running Textual session.
- Alarm triggering.
- Dismiss.
- Input validation.
- Graceful shutdown (including database cleanup).

## Priority 2 — Important Alarm Features

- Recurring alarms.
- Daily recurrence.
- Weekday recurrence.
- Weekend recurrence.
- Custom weekday recurrence.
- Snooze (including persisted next fire time).
- Alarm labels.
- Timezone-aware behavior.

## Priority 3 — UX / Polish

- Textual styling / colors.
- Panels and keyboard navigation.
- Alarm notification screens.
- Alarm animation.
- Terminal sound/bell.
- Live clock.
- Countdown to next alarm.
- Rich terminal formatting.

## Priority 4 — Additional Utility

- Stopwatch.

The implementation should first make the core alarm lifecycle and persistence reliable before spending significant time on visual polish.

If time becomes constrained, lower-priority features should be simplified or deferred rather than compromising core correctness.

---

# 21. Technical Expectations

The implementation should favor:

- Clear separation of concerns.
- Presentation via Textual only (domain must not depend on Textual).
- Persistence isolated behind a repository layer.
- Domain logic free of embedded SQL.
- Small, understandable components.
- Testable business logic.
- Timezone-aware datetime handling.
- Monotonic clocks for elapsed-duration measurement.
- Minimal dependencies beyond those required (stdlib `sqlite3`, Textual for the TUI).
- Explicit error handling.
- Clean application lifecycle management.

The implementation should avoid unnecessary abstraction or architecture that is not justified by the requirements.

AI-generated code must be reviewed and validated rather than accepted blindly.

---

# 22. Testing Requirements

The project should include automated tests for important business behavior.

At minimum, tests should cover:

### Alarm creation

- Valid alarm creation.
- Invalid time.
- Alarm receives unique ID.
- Multiple alarms can coexist.

### Alarm management

- List alarms.
- Update alarm.
- Delete alarm.
- Enable alarm.
- Disable alarm.
- Invalid alarm ID.

### Persistence

- Creating an alarm persists it.
- Persisted alarms can be loaded after reopening the database.
- Updating an alarm persists the update.
- Deleting an alarm removes it from persistence.
- Enable/disable state persists.
- Recurrence configuration persists.
- Multiple alarms persist correctly.
- Completed one-time alarms do not incorrectly become triggerable after restart.
- Snoozed `next_fire_at` survives reopen when applicable.

Persistence tests must use a temporary/test SQLite database, never the real application database file.

### Recurrence

- One-time alarm.
- Daily alarm.
- Weekday alarm.
- Weekend alarm.
- Custom-day alarm.
- Calculation of next occurrence.
- Strictly-after boundary behavior.
- Past-time roll-forward behavior.

### Alarm lifecycle

- Alarm becomes ringing at the correct time.
- Disabled alarm does not trigger.
- Dismissed one-time alarm completes.
- Dismissed recurring alarm schedules its next occurrence.
- Snooze calculates the correct next ring time.
- Due detection uses `next_fire_at <= now`.
- Catch-up of already-due alarms on startup / clock advance.
- Scheduler re-evaluates after alarm mutations.

### Timezone

- Valid timezone.
- Invalid timezone.
- Correct timezone-aware scheduling behavior.
- Weekday evaluation in the alarm timezone.
- DST gap and fold behavior where practical.

### Stopwatch

- Start.
- Pause.
- Resume.
- Reset.
- Elapsed-time calculation.
- Invalid transitions.

Tests should avoid depending on real waiting/sleeping wherever possible. Time-dependent logic should be designed so it can be tested deterministically (for example, with an injectable/fake clock).

---

# 23. Acceptance Criteria

The implementation is considered successful when:

1. A user can create an alarm from the Textual TUI.
2. Created alarms are persisted in SQLite and survive restart.
3. Multiple alarms can exist simultaneously.
4. Users can list, update, enable, disable, and delete alarms.
5. Alarms trigger at the correct scheduled time while the interactive Textual session is running.
6. Recurring alarms calculate their next occurrence correctly.
7. Custom weekday alarms work correctly.
8. A ringing alarm can be dismissed.
9. A ringing alarm can be snoozed, and the snoozed next fire time persists.
10. Disabled alarms do not trigger.
11. Completed one-time alarms do not fire again after restart.
12. Current time and timezone can be displayed.
13. Timezone-aware alarm behavior works where supported.
14. Stopwatch start/pause/resume/reset behavior works.
15. Invalid input produces useful errors rather than crashes.
16. Normal application shutdown is graceful and does not corrupt the database.
17. Core behavior is covered by automated tests, including persistence tests against a temporary database.
18. The Textual TUI is understandable without reading the source code.
19. Visual polish does not compromise core functionality.

---

# 24. Future Improvements

If this application were developed beyond the exercise, potential improvements could include:

- Configurable default snooze duration.
- Multiple snooze strategies.
- More advanced recurring schedules.
- Natural-language alarm creation.
- Configurable sounds.
- Desktop notifications.
- Better timezone management.
- Import/export of alarms.
- User configuration files.
- Plugin-based notification providers.
- Optional background daemon/service for monitoring while no interactive session is open.
- More advanced terminal interaction.

These are deliberately outside the initial implementation scope.

---

# 25. Implementation Principle

The application should be developed in two distinct stages:

### Stage 1 — Correctness

Build and validate:

```text
Clock
  ↓
Alarm model
  ↓
SQLite repository
  ↓
Alarm management
  ↓
Scheduler
  ↓
Alarm lifecycle
  ↓
Recurrence
  ↓
Snooze / dismiss
  ↓
Stopwatch
  ↓
Tests
```

### Stage 2 — Terminal UX (Textual)

After the functional behavior is stable:

```text
Textual screens / layouts
  ↓
Colors / panels
  ↓
Live clock
  ↓
Ringing alarm presentation
  ↓
Animation
  ↓
Sound/bell
  ↓
Final TUI polish
```

The visual layer should not determine or complicate the core alarm domain logic. Domain logic must not depend on Textual widgets.

Persistence belongs with correctness, not polish.

---

# 26. Source of Truth

This document defines the intended product behavior.

Before implementation, the developer/AI agent should read this document completely and identify any remaining ambiguities rather than silently inventing behavior.

If an implementation decision is necessary that is not explicitly covered here, the simplest behavior consistent with the requirements should be preferred and documented.
