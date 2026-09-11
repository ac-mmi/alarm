"""Domain-level errors for the alarm clock."""


class AlarmError(Exception):
    """Base class for domain errors."""


class InvalidAlarmTime(AlarmError):
    """Raised when an alarm time of day is invalid."""


class InvalidRecurrence(AlarmError):
    """Raised when recurrence configuration is invalid."""


class InvalidTimezone(AlarmError):
    """Raised when a timezone name is invalid."""


class InvalidAlarmState(AlarmError):
    """Raised when an invalid lifecycle transition is attempted."""


class AlarmNotFound(AlarmError):
    """Raised when an alarm ID does not exist in the repository."""


class RepositoryError(AlarmError):
    """Raised when a persistence operation fails."""


class InvalidStopwatchOperation(AlarmError):
    """Raised when a stopwatch lifecycle transition is invalid."""
