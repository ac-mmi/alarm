"""SQLite persistence for Alarm domain objects."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from alarm_clock.errors import AlarmNotFound, RepositoryError
from alarm_clock.models import (
    Alarm,
    AlarmState,
    AlarmTime,
    RecurrenceType,
    Weekday,
)

DEFAULT_DB_PATH = Path.home() / ".alarm-clock" / "alarms.db"


def default_db_path() -> Path:
    """Return the default application database path (~/.alarm-clock/alarms.db)."""
    return DEFAULT_DB_PATH


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise RepositoryError("Refusing to persist a naive datetime")
    return value.astimezone(timezone.utc).isoformat()


def _from_utc_iso(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_days(days: frozenset[Weekday]) -> Optional[str]:
    if not days:
        return None
    return json.dumps(sorted(day.value for day in days))


def _deserialize_days(raw: Optional[str]) -> frozenset[Weekday]:
    if not raw:
        return frozenset()
    values = json.loads(raw)
    return frozenset(Weekday(int(v)) for v in values)


class AlarmRepository:
    """SQLite-backed alarm store.

    Owns a single connection guarded by a lock so future scheduler/TUI
    threads can share access safely without sharing the connection casually.
    """

    def __init__(self, path: Optional[Union[str, Path]] = None) -> None:
        self._path = Path(path) if path is not None else default_db_path()
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self.open()

    @property
    def path(self) -> Path:
        return self._path

    def open(self) -> None:
        """Open (or reopen) the database and ensure the schema exists."""
        with self._lock:
            if self._conn is not None:
                return
            try:
                path_str = str(self._path)
                if path_str != ":memory:":
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(
                    path_str,
                    check_same_thread=False,
                    isolation_level=None,  # autocommit; we manage transactions
                )
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._initialize_schema()
            except sqlite3.Error as exc:
                self._conn = None
                raise RepositoryError(
                    f"Failed to open database at {self._path}: {exc}"
                ) from exc

    def _initialize_schema(self) -> None:
        assert self._conn is not None
        # CREATE TABLE IF NOT EXISTS is idempotent; avoid executescript,
        # which issues implicit commits that fight explicit transactions.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL,
                recurrence TEXT NOT NULL,
                days TEXT,
                timezone TEXT NOT NULL,
                state TEXT NOT NULL,
                next_fire_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                raise RepositoryError(
                    f"Failed to close database at {self._path}: {exc}"
                ) from exc
            finally:
                self._conn = None

    def __enter__(self) -> AlarmRepository:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RepositoryError("Repository is closed")
        return self._conn

    def create(self, alarm: Alarm) -> Alarm:
        """Insert a new alarm and return it with the assigned database ID.

        The incoming ``alarm.id`` is ignored; SQLite assigns the primary key.
        ``RINGING`` is persisted as ``SCHEDULED``.
        """
        created_at = alarm.created_at or datetime.now(timezone.utc)
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute("BEGIN")
                cursor = conn.execute(
                    """
                    INSERT INTO alarms (
                        hour, minute, label, enabled, recurrence, days,
                        timezone, state, next_fire_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alarm.time.hour,
                        alarm.time.minute,
                        alarm.label,
                        1 if alarm.enabled else 0,
                        alarm.recurrence.value,
                        _serialize_days(alarm.days),
                        alarm.timezone,
                        self._persist_state(alarm.state).value,
                        _to_utc_iso(alarm.next_fire_at)
                        if alarm.next_fire_at is not None
                        else None,
                        _to_utc_iso(created_at),
                    ),
                )
                new_id = int(cursor.lastrowid)
                conn.execute("COMMIT")
            except sqlite3.Error as exc:
                conn.execute("ROLLBACK")
                raise RepositoryError(f"Failed to create alarm: {exc}") from exc

        return self.get(new_id)

    def get(self, alarm_id: int) -> Alarm:
        """Load a single alarm by ID."""
        with self._lock:
            conn = self._require_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM alarms WHERE id = ?",
                    (alarm_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise RepositoryError(
                    f"Failed to get alarm #{alarm_id}: {exc}"
                ) from exc
        if row is None:
            raise AlarmNotFound(f"Alarm #{alarm_id} does not exist")
        return self._row_to_alarm(row)

    def list_alarms(self) -> List[Alarm]:
        """Return all alarms ordered by ID ascending."""
        with self._lock:
            conn = self._require_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM alarms ORDER BY id ASC"
                ).fetchall()
            except sqlite3.Error as exc:
                raise RepositoryError(f"Failed to list alarms: {exc}") from exc
        return [self._row_to_alarm(row) for row in rows]

    def update(self, alarm: Alarm) -> Alarm:
        """Persist changes to an existing alarm. Raises AlarmNotFound if missing."""
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute("BEGIN")
                cursor = conn.execute(
                    """
                    UPDATE alarms SET
                        hour = ?,
                        minute = ?,
                        label = ?,
                        enabled = ?,
                        recurrence = ?,
                        days = ?,
                        timezone = ?,
                        state = ?,
                        next_fire_at = ?
                    WHERE id = ?
                    """,
                    (
                        alarm.time.hour,
                        alarm.time.minute,
                        alarm.label,
                        1 if alarm.enabled else 0,
                        alarm.recurrence.value,
                        _serialize_days(alarm.days),
                        alarm.timezone,
                        self._persist_state(alarm.state).value,
                        _to_utc_iso(alarm.next_fire_at)
                        if alarm.next_fire_at is not None
                        else None,
                        alarm.id,
                    ),
                )
                if cursor.rowcount == 0:
                    conn.execute("ROLLBACK")
                    raise AlarmNotFound(f"Alarm #{alarm.id} does not exist")
                conn.execute("COMMIT")
            except AlarmNotFound:
                raise
            except sqlite3.Error as exc:
                conn.execute("ROLLBACK")
                raise RepositoryError(
                    f"Failed to update alarm #{alarm.id}: {exc}"
                ) from exc
        return self.get(alarm.id)

    def delete(self, alarm_id: int) -> None:
        """Delete an alarm by ID. Raises AlarmNotFound if missing."""
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute("BEGIN")
                cursor = conn.execute(
                    "DELETE FROM alarms WHERE id = ?",
                    (alarm_id,),
                )
                if cursor.rowcount == 0:
                    conn.execute("ROLLBACK")
                    raise AlarmNotFound(f"Alarm #{alarm_id} does not exist")
                conn.execute("COMMIT")
            except AlarmNotFound:
                raise
            except sqlite3.Error as exc:
                conn.execute("ROLLBACK")
                raise RepositoryError(
                    f"Failed to delete alarm #{alarm_id}: {exc}"
                ) from exc

    @staticmethod
    def _persist_state(state: AlarmState) -> AlarmState:
        # RINGING is runtime UI state; persist as SCHEDULED so restarts
        # reconstruct a non-UI state (catch-up uses next_fire_at).
        if state is AlarmState.RINGING:
            return AlarmState.SCHEDULED
        return state

    @staticmethod
    def _row_to_alarm(row: sqlite3.Row) -> Alarm:
        state = AlarmState(row["state"])
        if state is AlarmState.RINGING:
            state = AlarmState.SCHEDULED
        return Alarm(
            id=int(row["id"]),
            time=AlarmTime(int(row["hour"]), int(row["minute"])),
            label=row["label"] or "",
            enabled=bool(row["enabled"]),
            recurrence=RecurrenceType(row["recurrence"]),
            days=_deserialize_days(row["days"]),
            timezone=row["timezone"],
            state=state,
            next_fire_at=_from_utc_iso(row["next_fire_at"]),
            created_at=_from_utc_iso(row["created_at"]),
        )
