# Alarm Clock CLI — Technical Design

## 1. Purpose

This document describes the technical design for the Alarm Clock CLI.

`REQUIREMENTS.md` defines the product requirements and expected behavior. This document translates those requirements into an implementation approach.

The design prioritizes:

- Clear separation of responsibilities.
- SQLite persistence behind a repository layer.
- Textual as the presentation/TUI layer only.
- Testability of domain and scheduler without launching the TUI.
- Correct time and recurrence handling.
- Simple, maintainable Python code.
- A clean interactive Textual TUI experience.
- Separation between alarm logic, persistence, terminal presentation, and sound.
- The ability to extend the application without rewriting the core domain logic.

The implementation should avoid unnecessary abstraction and should favor simple solutions that are appropriate for a local terminal application.

---

# 2. High-Level Architecture

The application should be organized into several logical layers.

Alarm management flow:

```text
Textual TUI
 ↓
Application / Service Layer
 ↓
Alarm Manager / Domain
 ↓
Repository
 ↓
SQLite
```

Scheduler / notification flow (separate concern):

```text
Scheduler
 ↓
Notification layer
 ↓
Textual TUI + Sound
```

Combined view:

```text
                    Textual TUI
                          │
                          ▼
                  Application / Service
                          │
             ┌────────────┼────────────────┐
             ▼            ▼                ▼
        Alarm Manager   Scheduler       Stopwatch
             │            │
             ▼            ▼
        Alarm Model    Time Service
             │            │
             ▼            ▼
      Alarm Repository  Notification
             │           /        \
             ▼          ▼          ▼
          SQLite   Textual TUI   Sound
```

The scheduler loads persisted alarms (via the manager/repository) and monitors them while the application is running.

Important design principles:

- **Textual belongs only to the presentation layer.**
- **Domain logic must not depend on Textual widgets.**
- **Alarm scheduling must not depend on Textual rendering.**
- **SQLite / repository must not know about Textual.**
- **The TUI communicates with the application/service layer rather than directly manipulating SQLite.**
- **Core domain and scheduler must remain testable without launching the TUI.**
- **Domain models must not embed SQLite queries.**
- **Persistence concerns stay in the repository layer.**

For example:

```text
Alarm Scheduler
      │
      ▼
Alarm triggered
      │
      ▼
Notification interface
      │
      ├── Textual TUI presentation
      └── Sound notification
```

This allows scheduling and domain logic to remain testable without requiring a Textual app, audio device, or production database file.

### Dependency direction

```text
Textual → Application/Services → Domain → Repository → SQLite

Domain      must NOT depend on Textual
Repository  must NOT depend on Textual
Scheduler   must NOT depend on Textual widgets/rendering
```

Textual is the chosen TUI framework for this project.

---

# 2.1 Process Model

SQLite provides durable storage. It does **not** detect or fire alarms by itself.

Responsibilities:

```text
SQLite       → persistent storage of alarm data
Scheduler    → runtime detection and triggering
Textual TUI  → interactive presentation, input, and ringing UI
```

The initial application is a **long-running interactive Textual TUI session**:

1. Open/create the SQLite database.
2. Initialize schema if needed.
3. Load persisted alarms into domain objects.
4. Start the scheduler.
5. Start the Textual application.
6. On quit / Ctrl+C: stop scheduler and notifications, exit Textual cleanly, close the database.

No OS daemon or background service is required for the initial design.

If the process is not running, alarms do not fire until the next interactive session starts. On startup, the scheduler performs catch-up for enabled, non-completed alarms with `next_fire_at <= now`.

---

# 2.2 Application / Service Layer

The application/service layer orchestrates use cases. It exists so the Textual TUI does not talk to SQLite or the scheduler’s internals directly.

Responsibilities include:

- Create / update / delete / enable / disable alarms through the alarm manager + repository.
- Recalculate `next_fire_at` when configuration changes.
- Ask the scheduler to wake/re-evaluate after mutations.
- Coordinate snooze and dismiss transitions.
- Own startup and shutdown sequencing.

It should remain thin. Business rules live in the domain; SQL lives in the repository; widgets live in Textual.

---

# 2.3 Textual TUI Layer

Textual is the presentation/TUI framework.

The Textual layer is responsible for:

- Rendering the application screens.
- Keyboard interaction.
- Forms and user input.
- Navigation.
- Live clock updates.
- Alarm list/detail presentation.
- Ringing alarm presentation.
- Stopwatch presentation.
- Visual feedback and status messages.

The Textual layer must **not** contain business rules such as recurrence calculation, next-occurrence logic, DST handling, or SQL.

When the user performs an action in the TUI, the TUI calls the application/service layer and then refreshes presentation from the returned/domain state.

---

# 3. Suggested Project Structure

The implementation may use a structure similar to:

```text
alarm-clock/
│
├── docs/
│   ├── REQUIREMENTS.md
│   └── DESIGN.md
│
├── src/
│   └── alarm_clock/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py              # Textual app entry / composition
│       ├── tui/                # Textual screens/widgets (presentation only)
│       │   ├── __init__.py
│       │   ├── screens.py
│       │   └── widgets.py
│       ├── models.py
│       ├── alarms.py
│       ├── repository.py
│       ├── scheduler.py
│       ├── time_service.py
│       ├── notifications.py
│       └── stopwatch.py
│
├── tests/
│   ├── test_alarms.py
│   ├── test_recurrence.py
│   ├── test_repository.py
│   ├── test_scheduler.py
│   ├── test_time_service.py
│   └── test_stopwatch.py
│
├── README.md
├── pyproject.toml
└── ...
```

`repository.py` (or an equivalent clear name such as `db.py` / `storage.py`) owns SQLite access.

The `tui/` package (and/or `app.py`) owns Textual presentation. Domain modules under `alarm_clock/` must not import Textual.

This is a suggested organization, not a rigid requirement.

If implementation reveals that fewer modules provide a cleaner solution, the structure should be simplified rather than following this structure mechanically. Persistence and domain logic, however, should remain separated from Textual widgets.

---

# 4. Core Domain Model

The main domain object is an `Alarm`.

Conceptually:

```text
Alarm
├── id
├── time                 # configured wall-clock time of day
├── label
├── enabled              # boolean; not a lifecycle state
├── recurrence           # ONCE | DAILY | WEEKDAYS | WEEKENDS | CUSTOM_DAYS
├── days                 # for CUSTOM_DAYS
├── timezone
├── state                # SCHEDULED | RINGING | COMPLETED
└── next_fire_at         # concrete next fire instant (timezone-aware)
```

The exact Python representation is an implementation decision.

The model should represent the alarm's **domain state**, rather than containing terminal UI logic or SQL.

For example, an `Alarm` should not be responsible for:

- Printing terminal boxes.
- Playing sounds.
- Reading keyboard input.
- Managing threads.
- Executing SQLite statements.

Those responsibilities belong elsewhere.

`enabled` and `state` are distinct:

- `enabled=False` means the scheduler must ignore the alarm regardless of `next_fire_at`.
- `state=COMPLETED` means a one-time alarm is finished and must not fire again.
- `state=RINGING` is runtime UI/trigger state while the session is presenting the alarm.
- Snooze does **not** introduce a separate persisted state name; a snoozed alarm is `SCHEDULED` with an updated `next_fire_at`.

---

# 5. Alarm Lifecycle

An alarm should have an explicit lifecycle.

```text
                 ┌───────────────┐
                 │   SCHEDULED   │
                 └───────┬───────┘
                         │
                  time reached / due
                  (enabled, not completed)
                         │
                         ▼
                 ┌───────────────┐
                 │    RINGING    │
                 └───────┬───────┘
                    ┌────┴────┐
                    │         │
                 dismiss    snooze
                    │         │
                    ▼         ▼
               ┌────────┐  ┌───────────┐
               │ DONE / │  │ SCHEDULED │
               │ NEXT   │  │ + new     │
               │        │  │ next_fire │
               └────────┘  └───────────┘
```

For one-time alarms:

```text
SCHEDULED
    ↓
RINGING
    ↓
COMPLETED
```

For recurring alarms:

```text
SCHEDULED
    ↓
RINGING
    ↓
CALCULATE NEXT OCCURRENCE
    ↓
SCHEDULED
```

Disabled alarms remain inactive and should not be considered triggerable by the scheduler.

### Mutations while RINGING

- **Dismiss:** stop notification; transition as above; persist.
- **Snooze:** stop current notification; set `next_fire_at = now + snooze`; state `SCHEDULED`; persist; wake scheduler.
- **Disable:** stop notification; keep `enabled=False`; leave a non-triggering scheduled/completed configuration as appropriate; persist.
- **Delete:** stop notification; remove from repository; wake scheduler.
- **Update** of time/recurrence/timezone while ringing: stop notification if needed, apply update, recompute future `next_fire_at`, persist, wake scheduler.

### Persistence across restarts

- Enabled/disabled flags persist.
- Recurrence configuration persists.
- Timezone persists.
- Completed one-time alarms persist as `COMPLETED` and must not fire after restart.
- Snoozed alarms persist via `next_fire_at`.
- `RINGING` does not need to survive process death as an active UI state. On load, treat previously ringing rows as `SCHEDULED` (or equivalent) and let catch-up logic fire if `next_fire_at <= now`.

---

# 6. Recurrence Design

Recurrence should be represented as a domain concept rather than scattered conditional logic throughout the scheduler or repository.

Supported recurrence types:

```text
ONCE
DAILY
WEEKDAYS
WEEKENDS
CUSTOM_DAYS
```

For custom days, the alarm stores the selected weekdays.

Example:

```text
recurrence = CUSTOM_DAYS
days = [MONDAY, WEDNESDAY, FRIDAY]
```

Weekday checks use the alarm's timezone.

The scheduler should ask the recurrence logic for the **next valid occurrence** instead of implementing recurrence rules itself.

Conceptually:

```text
Alarm
  │
  ▼
Recurrence
  │
  ▼
next_occurrence(after=current_time)
  │
  ▼
datetime
```

This keeps recurrence calculations isolated and testable.

---

# 7. Next Occurrence Calculation

The application should centralize calculation of an alarm's next occurrence.

The calculation should consider:

- Reference datetime (`after`).
- Alarm time of day.
- Recurrence rule.
- Timezone.
- Day of week in that timezone.
- DST gap/fold rules from the requirements.

`next_occurrence(after=...)` must return the next valid occurrence **strictly after** `after`.

Due detection uses:

```text
enabled
and state != COMPLETED
and next_fire_at <= now
```

Example:

```text
Current:
Monday 10:00

Alarm:
07:30
Weekdays

Result:
Tuesday 07:30
```

For a custom recurrence:

```text
Current:
Tuesday

Alarm:
07:30
Mon/Wed/Fri

Result:
Wednesday 07:30
```

### Past-time policy

Configured times are times of day.

On create/update, if the would-be occurrence for “today” is already past in the alarm timezone, roll forward to the next valid future occurrence. Never fire immediately solely because the typed clock time is earlier than now.

The scheduler should not duplicate recurrence logic.

---

# 8. Time and Timezone Strategy

Time-related functionality should use timezone-aware datetime values.

The application should avoid mixing:

```text
naive datetime
```

with:

```text
timezone-aware datetime
```

unless there is an explicit reason to do so.

Prefer Python’s standard library timezone facilities (`zoneinfo` / `datetime.timezone`) rather than manually maintaining offsets. Avoid `pytz` unless there is a concrete compatibility reason.

The time service should provide functionality such as:

```text
current_time()
current_time(timezone)
validate_timezone()
convert_timezone()
```

The exact API is an implementation decision.

Injectable clocks are required for deterministic tests:

```text
Production: RealClock
Tests:      FakeClock
```

---

## 8.1 Local Time

If no timezone is explicitly specified, alarms should use the application's configured/local timezone (typically the system local timezone for the interactive Textual session).

---

## 8.2 Explicit Timezone

An alarm may specify a timezone.

Example:

```text
Alarm:
08:00
Timezone:
America/New_York
```

The scheduler should determine when that alarm's configured local time occurs relative to the current instant by comparing timezone-aware instants (`next_fire_at` vs `now`).

---

## 8.3 Daylight Saving Time

Timezone calculations should rely on a standard timezone database/library rather than manually implementing timezone offsets.

### Gap (nonexistent local time)

If the local wall time does not exist on that calendar day, skip that occurrence and continue searching for the next valid occurrence under the recurrence rule.

### Fold (ambiguous local time)

If the local wall time occurs twice, choose the earlier occurrence.

DST behavior should be covered by tests where practical.

---

# 9. Persistence / Repository Design

Persistence is required.

Use SQLite through Python’s built-in `sqlite3` module. Do not introduce MySQL, PostgreSQL, or an ORM unless a concrete justification appears during implementation. For this project, stdlib `sqlite3` is the preferred direction.

### Repository responsibilities

The repository is responsible for:

- Create alarm.
- Get alarm by ID.
- List alarms.
- Update alarm.
- Delete alarm.
- Persist enabled/disabled state.
- Persist recurrence configuration (including custom days).
- Persist timezone information.
- Persist lifecycle status needed after restart (`SCHEDULED` / `COMPLETED`; map `RINGING` on load as described above).
- Persist `next_fire_at` (including snoozed fire times).
- Persist any other alarm fields required to reconstruct domain objects after restart.
- Initialize schema on startup.
- Close database resources cleanly on shutdown.

The domain model and scheduler must not issue SQL directly.

Conceptually:

```text
AlarmManager
    │
    ▼
AlarmRepository
    │
    ▼
SQLite file
```

---

# 9.1 Suggested Schema

Keep the schema simple. One `alarms` table is sufficient initially.

Suggested fields:

```text
alarms
├── id                INTEGER PRIMARY KEY
├── time_minute       INTEGER or TEXT wall-clock representation
├── label             TEXT
├── enabled           INTEGER (0/1)
├── recurrence        TEXT  (ONCE/DAILY/WEEKDAYS/WEEKENDS/CUSTOM_DAYS)
├── days              TEXT  (nullable; e.g. JSON/CSV of weekdays for CUSTOM_DAYS)
├── timezone          TEXT
├── state             TEXT  (SCHEDULED/COMPLETED; RINGING may be stored transiently)
├── next_fire_at      TEXT  (ISO-8601 timezone-aware timestamp)
└── created_at        TEXT  (ISO-8601 timestamp)
```

These fields are design suggestions, not a mandatory schema. Use the simplest schema that can round-trip an `Alarm` faithfully.

Store timezone-aware timestamps in an unambiguous format. Avoid naive local timestamp strings without timezone information.

---

# 9.2 Startup Behavior

When the application starts:

1. Open or create the SQLite database file.
2. Initialize the required schema if necessary.
3. Load persisted alarms.
4. Reconstruct alarm domain objects.
5. Normalize runtime state (`RINGING` → `SCHEDULED` if found).
6. Start the scheduler (including catch-up for already-due alarms).
7. Start the Textual TUI.

The application must start successfully when the database is empty (no existing alarms).

---

# 9.3 Shutdown Behavior

On normal termination (`quit` or Ctrl+C):

1. Stop accepting new interactive work as appropriate.
2. Stop active alarm notifications.
3. Stop the scheduler and wait for it to exit cleanly.
4. Ensure pending repository writes have completed.
5. Exit the Textual application cleanly.
6. Close the SQLite connection.
7. Exit without an unnecessary traceback.

Normal shutdown must not corrupt persisted alarm data.

---

# 10. Scheduler Design

The scheduler is responsible for determining when alarms should fire **while the interactive Textual session is running**.

Conceptually:

```text
Scheduler
   │
   ├── obtain current time
   │
   ├── find enabled, non-completed alarms
   │
   ├── identify due alarms (next_fire_at <= now)
   │
   └── trigger notification / state transition
```

The scheduler should not:

- Own Textual widgets or screens.
- Depend on Textual rendering.
- Contain recurrence-specific business rules.
- Play audio directly.
- Execute SQL directly.

Those responsibilities should remain separated.

The scheduler obtains alarm data through the alarm manager (which uses the repository), not by owning persistence itself.

---

# 11. Scheduler Execution Model

The application needs to support alarms firing while the Textual TUI remains usable.

Recommended simple approach for the initial implementation:

- A background scheduler thread coordinated with Textual, **or**
- Another lightweight scheduling mechanism compatible with the Textual app lifecycle,

chosen for simplicity, correctness, and testability.

The scheduler must:

- Avoid busy-looping at maximum CPU usage.
- Support cancellation/shutdown.
- Wake early when alarms are added, updated, deleted, enabled, disabled, snoozed, or dismissed.
- Treat overshot times as due (`<= now`).

A reasonable wait strategy:

```text
Find next next_fire_at among eligible alarms
      ↓
Wait until that time OR wake event OR shutdown
      ↓
Identify all due alarms
      ↓
Trigger notifications / transitions
      ↓
Repeat
```

A simple capped poll (for example, sleep up to 1 second, or until the next fire time, whichever is sooner) is an acceptable first implementation if it keeps wake-on-mutation and shutdown reliable.

Wake-on-mutation should use a straightforward mechanism such as `threading.Event` / condition variable cleared whenever the alarm store changes.

Notification handling must not permanently block the scheduler thread from:

- detecting other due alarms,
- observing shutdown,
- observing mutations.

Hand off ringing presentation to the notification → Textual TUI path and continue scheduling safely. Domain/scheduler tests must not require launching Textual.

---

# 12. Concurrent / Simultaneous Alarms

Multiple alarms may have the same scheduled time.

Example:

```text
07:30 — Wake up
07:30 — Medication
07:30 — Meeting
```

The scheduler should identify **all** alarms that are due rather than arbitrarily triggering only one.

Present ringing alarms deterministically (for example, ascending ID). Focus snooze/dismiss on one ringing alarm at a time, then continue with the next still-due/ringing alarm.

The core scheduler should treat each alarm independently.

---

# 13. Alarm Notification Design

Notification should be separated from scheduling.

Conceptually:

```text
Scheduler
    │
    ▼
Alarm is due
    │
    ▼
Notification service
    ├───────────────┐
    ▼               ▼
Textual TUI       Sound
```

The notification service should support:

- Start alarm notification.
- Stop/dismiss notification.
- Snooze request handling coordination.
- Visual alarm state via the Textual TUI.
- Audible notification where available.

The scheduler should not know how the Textual screens are composed.

There is no automatic ring timeout in the initial design; ringing continues until snooze, dismiss, disable, delete, or shutdown.

---

# 14. Terminal Notification UX

The Textual ringing presentation should be visually obvious.

The final implementation may use Textual capabilities such as:

- Styled panels and colors.
- Unicode symbols.
- Overlay / modal screens.
- Animated updates.
- Terminal bell.

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

Visual effects should remain optional from the perspective of the core domain.

If terminal capabilities are limited, the application should still provide a usable Textual/text-based notification.

The Textual TUI owns keyboard handling for snooze/dismiss while alarms are ringing.

---

# 15. Sound Design

Sound should be treated as a notification mechanism rather than part of the alarm model.

Possible implementation options include:

```text
Terminal bell
OS-level audio
Python audio library
```

The implementation should choose the simplest reliable mechanism appropriate for the supported environment.

Sound failure should not cause the alarm scheduler or repository layer to crash.

Conceptually:

```text
Alarm triggered
      │
      ├── Visual notification
      │
      └── Attempt audible notification
                │
                └── Failure should be handled gracefully
```

---

# 16. Snooze Design

Snooze should modify the **current ringing occurrence**, not permanently change the alarm's recurrence configuration.

Example:

```text
Recurring alarm:
07:30 weekdays

Current occurrence:
Monday 07:30

Snooze:
5 minutes

Result:
Monday 07:35   (next_fire_at updated)
```

After dismissal of the snoozed occurrence:

```text
Next normal occurrence:
Tuesday 07:30
```

The recurrence remains:

```text
Monday-Friday at 07:30
```

Rules:

- Default snooze duration is five minutes.
- Repeated snoozes are allowed.
- Each snooze sets `next_fire_at = now + snooze_duration`.
- State returns to `SCHEDULED`.
- Persist `next_fire_at` immediately so snooze survives restart.
- Wake the scheduler after persisting.

---

# 17. Dismissal Design

Dismissal stops the current ringing notification.

For one-time alarms:

```text
RINGING
   ↓
COMPLETED
```

Persist `COMPLETED` so restart will not fire the alarm again.

For recurring alarms:

```text
RINGING
   ↓
next_occurrence(after=now)
   ↓
SCHEDULED
```

Persist the new `next_fire_at`.

Dismissing should stop associated visual animation and sound.

---

# 18. Textual TUI Layer (Presentation)

The Textual TUI is responsible for:

- Running the interactive long-lived Textual application.
- Rendering screens and widgets.
- Keyboard interaction and navigation.
- Forms and user input.
- Live clock updates.
- Alarm list/detail presentation.
- Ringing alarm presentation.
- Stopwatch presentation.
- Visual feedback and status messages.
- Calling application/service methods.
- Reporting errors to the user.

The Textual layer should not contain:

- Core scheduling algorithms.
- Recurrence / next-occurrence business rules.
- SQLite queries or repository internals.
- Domain state-transition rules beyond invoking service methods.

Conceptually:

```text
Textual TUI
 │
 ├── render / navigate / accept input
 │
 └── call application service
          │
          ▼
       Domain + Repository
```

---

# 19. TUI Interaction Model

Primary mode: a long-running Textual application in one process that also hosts the scheduler.

The TUI should support workflows such as:

- Viewing current time / timezone.
- Listing alarms.
- Creating / editing / deleting alarms.
- Enabling / disabling alarms.
- Viewing alarm details and next occurrence.
- Running the stopwatch.
- Handling ringing alarms (snooze / dismiss).

Exact screen names and layouts are an implementation detail.

Help / keybinding discoverability should remain available within the TUI.

Optional non-TUI process entry points are not the primary design and must not be mistaken for a complete alarm-monitoring solution without a running Textual session.

---

# 20. Stopwatch Design

The stopwatch should be independent from wall-clock alarm scheduling and from SQLite persistence.

A stopwatch measures elapsed duration and should therefore use a monotonic clock.

Conceptually:

```text
IDLE
  │
START
  ▼
RUNNING
  │
  ├── PAUSE ──► PAUSED
  │               │
  │             RESUME
  │               │
  └───────────────┘
  │
RESET → IDLE
```

Invalid transitions:

- Pause while not running → error.
- Resume while not paused → error.
- Start while already running → error (preferred explicit failure).

The stopwatch should track elapsed duration rather than relying on system wall-clock timestamps.

If an alarm rings during stopwatch interaction, alarm handling takes input priority until snoozed/dismissed.

---

# 21. Error Handling

Errors should be handled at appropriate boundaries.

Domain-level errors should represent meaningful failures such as:

```text
AlarmNotFound
InvalidAlarmTime
InvalidRecurrence
InvalidTimezone
InvalidAlarmState
InvalidStopwatchOperation
RepositoryError
```

The Textual / presentation layer should convert these into user-friendly messages.

Example:

```text
Error: Alarm #42 does not exist.
```

rather than exposing an internal Python traceback for ordinary user mistakes.

Unexpected programming errors should still be visible during development/testing rather than being silently swallowed.

Database open/schema failures should fail startup with a clear message.

---

# 22. Concurrency and Thread Safety

If the scheduler runs concurrently with Textual TUI operations, access to shared alarm state and repository operations must be safe.

Potential concurrent operations include:

```text
TUI → update alarm
Scheduler → check alarm
Scheduler → trigger alarm
TUI → delete alarm
TUI → snooze/dismiss
Repository → read/write SQLite
```

Use a straightforward synchronization approach, for example:

- One lock guarding alarm-manager mutations and scheduler reads of the in-memory snapshot, and/or
- Serialized repository access on a single connection with clear ownership rules.

SQLite connections should not be casually shared across threads without an explicit strategy. Prefer one connection owned by the repository with locked access, or a documented per-thread pattern.

Goals:

- No race conditions.
- No alarms firing after deletion.
- No lost updates.
- No corrupted alarm state or SQLite file from unclean concurrent use.
- Scheduler wake after mutations.

Do not introduce complex concurrency frameworks unless necessary.

---

# 23. Testing Strategy

Testing should focus primarily on deterministic domain and persistence behavior.

The most important areas are:

```text
Alarm creation
Alarm updates
Alarm deletion
Enable / disable
Persistence round-trips
Recurrence
Next occurrence calculation
Past-time roll-forward
Timezone / DST handling
Snooze
Dismissal
Scheduler due detection and wake-on-mutation
Stopwatch transitions
TUI input validation (where practical without requiring full Textual launch for core tests)
```

Time-dependent behavior should be testable without requiring tests to actually sleep until a real alarm time.

Use injectable clocks:

```text
Production:
RealClock

Tests:
FakeClock
```

Example:

```text
Current time = 07:29:59
Advance clock
Current time = 07:30:00
Assert alarm fired
```

without waiting in real time.

---

# 24. Testing Boundaries

The system should be tested at multiple levels.

### Unit tests

Test:

- Alarm model.
- Recurrence.
- Next occurrence calculation (including strictly-after).
- Past-time roll-forward.
- Timezone / DST gap and fold behavior.
- Stopwatch calculations and invalid transitions.

### Repository / persistence tests

Use a temporary SQLite database file or in-memory SQLite URL dedicated to the test.

Cover at least:

- Creating an alarm persists it.
- Persisted alarms load after reopening the database.
- Updating an alarm persists the update.
- Deleting an alarm removes it from persistence.
- Enable/disable state persists.
- Recurrence configuration persists.
- Multiple alarms persist correctly.
- Completed one-time alarms do not become triggerable after restart.
- Snoozed `next_fire_at` survives reopen.

Never run persistence tests against the user’s real application database file.

### Service-level tests

Test:

- Alarm manager behavior.
- Scheduler behavior with FakeClock.
- Snooze/dismiss lifecycle.
- Wake/re-evaluate after mutation.
- Catch-up of already-due alarms.

### TUI / presentation tests

Where valuable, test:

- Screen-level behavior via Textual testing utilities, if used.
- That presentation calls services rather than embedding domain rules.

Core domain, repository, and scheduler tests must pass without launching the Textual application.

### Integration tests

Verify important end-to-end flows such as:

```text
Create alarm
    ↓
Persist to temp SQLite
    ↓
Reload repository
    ↓
Scheduler detects alarm
    ↓
Notification triggered
    ↓
User dismisses
    ↓
Alarm reaches expected final persisted state
```

---

# 25. Observability / Debugging

The application should make it possible to understand scheduler and persistence behavior during development.

Useful information may include:

```text
Database opened: ...
Loaded alarms: 3
Next alarm: 07:30 AM
Scheduler started
Alarm #1 triggered
Alarm #1 snoozed until 07:35 AM
Alarm #1 dismissed
Next occurrence: Tuesday 07:30 AM
```

Debug logging should be separate from normal user-facing TUI output where practical.

---

# 26. Configuration

The initial implementation should minimize configuration.

Reasonable configurable values may include:

- SQLite database file path.
- Default snooze duration.
- Timezone.
- Notification behavior.

However, configuration should only be introduced where it provides meaningful value.

Avoid creating a complex configuration system for a small local application.

Tests must be able to override the database path.

---

# 27. Design Principles

The implementation should follow these principles:

### Separation of concerns

Alarm logic should not know about Textual rendering or SQL.

### Persistence isolation

All SQLite access goes through the repository.

### Presentation isolation

All Textual usage stays in the TUI/presentation layer. Domain, scheduler, and repository must not import Textual.

### Testability

Time-dependent behavior should be deterministic in tests; persistence tests use temporary databases.

### Simplicity

Prefer straightforward Python, stdlib `sqlite3`, and Textual for presentation over unnecessary frameworks or ORMs.

### Explicit behavior

Important edge cases (past times, DST, restart, snooze persistence) should have defined behavior.

### Safe state transitions

Alarm lifecycle changes should be controlled, persisted where required, and predictable.

### Dependency isolation

Sound and Textual rendering should not be required for testing the core scheduler or repository.

### Correct time handling

Use timezone-aware datetimes for wall-clock scheduling and monotonic clocks for elapsed durations.

---

# 28. Important Tradeoffs

## SQLite vs external databases

SQLite is required because:

- The app is local and single-user.
- No separate database server is desired.
- Persistence must survive restarts.
- Stdlib `sqlite3` keeps dependencies minimal.

MySQL/PostgreSQL are explicitly out of scope.

---

## Interactive Textual session vs daemon

Persistence does not remove the need for a running scheduler.

The initial design prefers a long-running interactive Textual TUI over an OS daemon to keep the architecture small and debuggable.

---

## Polling vs scheduled waiting

A naive implementation could check every second:

```text
while running:
    check alarms
    sleep(1)
```

This is simple and acceptable initially if wake/shutdown are correct.

A better implementation may calculate the next relevant alarm and wait until it is due, while still supporting cancellation and newly added/updated alarms via an explicit wake event.

The final implementation should balance simplicity and correctness. Correct wake-on-mutation matters more than micro-optimizing sleep intervals.

---

## Threads vs event loop

Both approaches are possible.

The implementation should select the simplest approach that allows:

- Interactive Textual TUI.
- Background alarm scheduling.
- Safe repository access.
- Graceful shutdown.
- Deterministic testing without launching Textual for core logic.

Avoid introducing asynchronous complexity solely for architectural appearance.

---

## ORM vs raw SQL

Prefer raw SQL through `sqlite3` with a small repository API.

An ORM would add dependency and abstraction cost unjustified by a single-table local schema.

---

# 29. Implementation Order

Implementation should proceed incrementally.

### Phase 1 — Domain

```text
Alarm model
Recurrence
Alarm states
Next occurrence calculation
Past-time / DST rules
```

### Phase 2 — Persistence

```text
SQLite schema
Repository CRUD
Startup load / schema init
Shutdown close
```

### Phase 3 — Alarm management

```text
Create
List
Update
Delete
Enable
Disable
Immediate persistence of mutations
```

### Phase 4 — Time

```text
Current time
Timezone handling
Timezone-aware scheduling
```

### Phase 5 — Scheduler

```text
Due-alarm detection
Background execution
Wake-on-mutation
Catch-up on startup
Alarm lifecycle transitions
```

### Phase 6 — Notification

```text
Terminal notification
Dismiss
Snooze (persist next_fire_at)
Sound/bell
```

### Phase 7 — Stopwatch

```text
Start
Pause
Resume
Reset
Invalid transitions
```

### Phase 8 — Tests

Add and run deterministic tests across domain, scheduler, and temporary-database persistence behavior.

### Phase 9 — Textual TUI UX

Only after core functionality is stable:

```text
Textual screens / layouts
Colors / panels
Keyboard navigation
Ringing presentation
Animation
Live clock
Countdown
Improved prompts / forms
```

---

# 30. Definition of Done

The implementation is ready for final polish when:

- Core alarm behavior works.
- SQLite persistence works across restart.
- Multiple alarms work.
- Recurrence works.
- Custom weekdays work.
- Timezone behavior works.
- Snooze/dismiss works and snooze survives restart via `next_fire_at`.
- Completed one-time alarms stay completed after restart.
- Scheduler runs reliably in the interactive Textual session.
- Wake-on-mutation works.
- Stopwatch works.
- Invalid input is handled.
- Application shutdown is graceful and closes the database safely.
- Automated tests pass, including persistence tests on a temporary database.
- Core time-dependent behavior is deterministic in tests.
- No unnecessary architectural complexity remains.

Only after these conditions are satisfied should significant effort be spent on terminal animation and visual polish.

---

# 31. AI-Assisted Development

AI tools may be used throughout implementation.

The AI should be treated as an engineering assistant rather than an unquestioned source of truth.

The workflow should be:

```text
Requirements
     ↓
Design
     ↓
AI-assisted implementation
     ↓
Human review
     ↓
Tests
     ↓
Validation
     ↓
Iteration
```

The implementation should be reviewed against both:

```text
REQUIREMENTS.md
DESIGN.md
```

If AI-generated code conflicts with either document, the requirements and design take precedence.

AI-generated code should not be accepted solely because it compiles or passes a superficial happy-path test.

---

# 32. Design Evolution

This design is a starting point rather than an immutable architecture.

During implementation, if a simpler or more reliable approach is discovered, the implementation may deviate from this document.

Any meaningful architectural deviation should be documented so that the final design reflects the actual system.

The objective is not to follow the design mechanically.

The objective is to build a correct, maintainable, well-tested application using sound engineering judgment.
