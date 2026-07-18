# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Per-run, cross-process safety contract for batch generation.

The serialized types are closed schemas: they contain limits, operational
identifiers, and counters, never generation payloads or account data.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Callable, Final, Iterator

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

SAFETY_STATE_FILENAME: Final = "safety.json"
STOP_GENERATION_PATH: Final = Path("content/run/STOP_GENERATION")
_ACTIVE_CALLS_DIRNAME: Final = ".safety-active"
_PERMIT_FILE_PREFIX: Final = "permit-"
_LOCK_TIMEOUT_SECONDS: Final = 5.0
_LOCK_POLL_INTERVAL_SECONDS: Final = 0.01

_LIMIT_ENV_VARS: Final = {
    "max_calls": "PGREP_BATCH_MAX_CALLS",
    "max_concurrency": "PGREP_BATCH_MAX_CONCURRENCY",
    "max_retries": "PGREP_BATCH_MAX_RETRIES",
    "max_minutes": "PGREP_BATCH_MAX_MINUTES",
}
_LIMIT_FIELDS: Final = frozenset(_LIMIT_ENV_VARS)
_POSITIVE_INTEGER_RE: Final = re.compile(r"[1-9][0-9]*", re.ASCII)
_IDENTIFIER_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", re.ASCII)
_RFC3339_RE: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})",
    re.ASCII,
)

_COUNTER_FIELDS: Final = frozenset(
    {
        "calls_started",
        "calls_completed",
        "calls_failed",
        "active_calls",
        "peak_concurrency",
        "retries",
    }
)
_STATE_FIELDS: Final = frozenset(
    {
        "run_id",
        "tool",
        "status",
        "limits",
        "counters",
        "started_at",
        "updated_at",
        "stop_reason",
    }
)
_PERMIT_FIELDS: Final = frozenset({"operation_id", "attempt"})


class _StateIOError(RuntimeError):
    """Internal marker for state and lock failures."""


def _require_exact_object(
    value: object, expected_fields: frozenset[str], *, name: str
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{name} must be a JSON object")
    if any(type(key) is not str for key in value):
        raise ValueError(f"{name} field names must be strings")

    fields = frozenset(value)
    missing = expected_fields - fields
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"{name} has missing fields: {names}")
    unknown = fields - expected_fields
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"{name} has unknown fields: {names}")
    return value


def _require_identifier(value: object, *, name: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(
            f"{name} must be a non-empty identifier of at most 128 characters"
        )
    return value


def _require_nonnegative_int(value: object, *, name: str) -> int:
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_positive_int(value: object, *, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_positive_float(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return converted


def _parse_timestamp(value: object, *, name: str) -> datetime:
    if type(value) is not str or _RFC3339_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be an RFC 3339 timestamp with an offset")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid RFC 3339 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{name} must include an offset")
    return parsed


def _format_timestamp(value: datetime, *, name: str) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must return an offset-aware datetime")
    return value.isoformat().replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _is_lock_contention(exc: OSError) -> bool:
    return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
        exc, "winerror", None
    ) in {33, 36}


class _FileLock:
    """One-byte advisory lock that works across local processes."""

    def __init__(self, path: Path, *, create: bool = True) -> None:
        self.path = path
        self._create = create
        self._handle: BinaryIO | None = None
        self._locked = False

    def acquire(self, timeout_seconds: float, poll_interval_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        self._open()
        while True:
            try:
                self._try_lock()
            except OSError as exc:
                if not _is_lock_contention(exc):
                    self._close()
                    raise _StateIOError(f"failed to lock {self.path}") from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._close()
                    raise _StateIOError(f"timed out locking {self.path}") from exc
                time.sleep(min(poll_interval_seconds, remaining))
            else:
                self._locked = True
                return

    def try_acquire(self) -> bool:
        self._open()
        try:
            self._try_lock()
        except OSError as exc:
            self._close()
            if _is_lock_contention(exc):
                return False
            raise _StateIOError(f"failed to probe lock {self.path}") from exc
        self._locked = True
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if self._locked:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise _StateIOError(f"failed to unlock {self.path}") from exc
        finally:
            self._locked = False
            self._close()

    def _open(self) -> None:
        try:
            if self._create:
                self._handle = open(self.path, "a+b", buffering=0)
            else:
                self._handle = open(self.path, "r+b", buffering=0)
            if sys.platform == "win32":
                self._handle.seek(0, os.SEEK_END)
                if self._handle.tell() == 0:
                    if not self._create:
                        raise OSError(errno.EINVAL, "lock file is empty")
                    self._handle.write(b"\0")
                self._handle.seek(0)
        except OSError as exc:
            self._close()
            raise _StateIOError(f"failed to open lock {self.path}") from exc

    def _try_lock(self) -> None:
        assert self._handle is not None
        if sys.platform == "win32":
            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


class BatchStatus(str, Enum):
    """Lifecycle state: tool failure is distinct from a safety stop."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class BatchStopReason(str, Enum):
    """Public reason a generation run was stopped."""

    CALL_LIMIT = "CALL_LIMIT"
    CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
    RETRY_LIMIT = "RETRY_LIMIT"
    DURATION_LIMIT = "DURATION_LIMIT"
    KILL_SWITCH = "KILL_SWITCH"
    STATE_IO = "STATE_IO"


@dataclass(frozen=True, slots=True)
class BatchLimits:
    """Mandatory positive limits for one generation run."""

    max_calls: int
    max_concurrency: int
    max_retries: int
    max_minutes: int

    def __post_init__(self) -> None:
        for field_name in _LIMIT_ENV_VARS:
            _require_positive_int(getattr(self, field_name), name=field_name)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_calls": self.max_calls,
            "max_concurrency": self.max_concurrency,
            "max_retries": self.max_retries,
            "max_minutes": self.max_minutes,
        }

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BatchLimits:
        """Parse all required limits from ``env``, ignoring unrelated entries."""

        source = os.environ if env is None else env
        parsed: dict[str, int] = {}
        for field_name, variable in _LIMIT_ENV_VARS.items():
            try:
                raw = source[variable]
            except KeyError as exc:
                raise ValueError(f"{variable} is required") from exc
            if type(raw) is not str or _POSITIVE_INTEGER_RE.fullmatch(raw) is None:
                raise ValueError(f"{variable} must be a positive integer")
            parsed[field_name] = int(raw)
        return cls(**parsed)

    @classmethod
    def from_dict(cls, value: object) -> BatchLimits:
        data = _require_exact_object(value, _LIMIT_FIELDS, name="batch limits")
        return cls(
            max_calls=_require_positive_int(data["max_calls"], name="max_calls"),
            max_concurrency=_require_positive_int(
                data["max_concurrency"], name="max_concurrency"
            ),
            max_retries=_require_positive_int(data["max_retries"], name="max_retries"),
            max_minutes=_require_positive_int(data["max_minutes"], name="max_minutes"),
        )


@dataclass(frozen=True, slots=True)
class BatchCounters:
    """Non-sensitive accounting for calls made by one run."""

    calls_started: int = 0
    calls_completed: int = 0
    calls_failed: int = 0
    active_calls: int = 0
    peak_concurrency: int = 0
    retries: int = 0

    def __post_init__(self) -> None:
        for field_name in _COUNTER_FIELDS:
            _require_nonnegative_int(getattr(self, field_name), name=field_name)

    def to_dict(self) -> dict[str, int]:
        return {
            "calls_started": self.calls_started,
            "calls_completed": self.calls_completed,
            "calls_failed": self.calls_failed,
            "active_calls": self.active_calls,
            "peak_concurrency": self.peak_concurrency,
            "retries": self.retries,
        }

    @classmethod
    def from_dict(cls, value: object) -> BatchCounters:
        data = _require_exact_object(value, _COUNTER_FIELDS, name="batch counters")
        return cls(
            calls_started=_require_nonnegative_int(
                data["calls_started"], name="calls_started"
            ),
            calls_completed=_require_nonnegative_int(
                data["calls_completed"], name="calls_completed"
            ),
            calls_failed=_require_nonnegative_int(
                data["calls_failed"], name="calls_failed"
            ),
            active_calls=_require_nonnegative_int(
                data["active_calls"], name="active_calls"
            ),
            peak_concurrency=_require_nonnegative_int(
                data["peak_concurrency"], name="peak_concurrency"
            ),
            retries=_require_nonnegative_int(data["retries"], name="retries"),
        )


@dataclass(frozen=True, slots=True)
class BatchState:
    """Strict, privacy-safe state persisted for one generation run."""

    run_id: str
    tool: str
    status: BatchStatus
    limits: BatchLimits
    counters: BatchCounters
    started_at: str
    updated_at: str
    stop_reason: BatchStopReason | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.run_id, name="run_id")
        _require_identifier(self.tool, name="tool")
        if type(self.status) is not BatchStatus:
            raise ValueError("status must be a BatchStatus")
        if type(self.limits) is not BatchLimits:
            raise ValueError("limits must be BatchLimits")
        if type(self.counters) is not BatchCounters:
            raise ValueError("counters must be BatchCounters")

        accounted = (
            self.counters.calls_completed
            + self.counters.calls_failed
            + self.counters.active_calls
        )
        if accounted != self.counters.calls_started:
            raise ValueError(
                "calls_completed + calls_failed + active_calls must equal calls_started"
            )
        if self.counters.peak_concurrency < self.counters.active_calls:
            raise ValueError("peak_concurrency must be at least active_calls")
        if self.counters.calls_started > self.limits.max_calls:
            raise ValueError("calls_started must not exceed limits.max_calls")
        if self.counters.retries > self.limits.max_retries:
            raise ValueError("retries must not exceed limits.max_retries")

        started = _parse_timestamp(self.started_at, name="started_at")
        updated = _parse_timestamp(self.updated_at, name="updated_at")
        if updated < started:
            raise ValueError("updated_at must not precede started_at")

        if self.status is BatchStatus.STOPPED:
            if type(self.stop_reason) is not BatchStopReason:
                raise ValueError("a stopped state requires a typed stop_reason")
        elif self.stop_reason is not None:
            raise ValueError("stop_reason is only valid for a stopped state")

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "tool": self.tool,
            "status": self.status.value,
            "limits": self.limits.to_dict(),
            "counters": self.counters.to_dict(),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "stop_reason": (
                self.stop_reason.value if self.stop_reason is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> BatchState:
        data = _require_exact_object(value, _STATE_FIELDS, name="batch state")
        status_value = data["status"]
        if type(status_value) is not str:
            raise ValueError("status must be a string")
        try:
            status = BatchStatus(status_value)
        except ValueError as exc:
            raise ValueError("status is not a recognized BatchStatus") from exc

        reason_value = data["stop_reason"]
        if reason_value is None:
            stop_reason = None
        elif type(reason_value) is str:
            try:
                stop_reason = BatchStopReason(reason_value)
            except ValueError as exc:
                raise ValueError(
                    "stop_reason is not a recognized BatchStopReason"
                ) from exc
        else:
            raise ValueError("stop_reason must be a string or null")

        return cls(
            run_id=_require_identifier(data["run_id"], name="run_id"),
            tool=_require_identifier(data["tool"], name="tool"),
            status=status,
            limits=BatchLimits.from_dict(data["limits"]),
            counters=BatchCounters.from_dict(data["counters"]),
            started_at=_require_timestamp_string(data["started_at"], name="started_at"),
            updated_at=_require_timestamp_string(data["updated_at"], name="updated_at"),
            stop_reason=stop_reason,
        )


def _require_timestamp_string(value: object, *, name: str) -> str:
    _parse_timestamp(value, name=name)
    assert type(value) is str
    return value


@dataclass(frozen=True, slots=True)
class CallPermit:
    """Minimal metadata connecting ``before_call`` to ``after_call``."""

    operation_id: str
    attempt: int

    def __post_init__(self) -> None:
        _require_identifier(self.operation_id, name="operation_id")
        _require_nonnegative_int(self.attempt, name="attempt")

    def to_dict(self) -> dict[str, object]:
        return {"operation_id": self.operation_id, "attempt": self.attempt}

    @classmethod
    def from_dict(cls, value: object) -> CallPermit:
        data = _require_exact_object(value, _PERMIT_FIELDS, name="call permit")
        return cls(
            operation_id=_require_identifier(data["operation_id"], name="operation_id"),
            attempt=_require_nonnegative_int(data["attempt"], name="attempt"),
        )


class BatchStopped(RuntimeError):
    """Raised when a run is denied further generation calls."""

    reason: BatchStopReason

    def __init__(self, reason: BatchStopReason) -> None:
        if type(reason) is not BatchStopReason:
            raise ValueError("reason must be a BatchStopReason")
        self.reason = reason
        super().__init__(f"generation batch stopped: {reason.value}")


class GenerationManager:
    """Cross-process admission and accounting for one generation run."""

    def __init__(
        self,
        run_id: str,
        tool: str,
        run_dir: str | os.PathLike[str],
        limits: BatchLimits,
        *,
        stop_path: str | os.PathLike[str] = STOP_GENERATION_PATH,
        clock: Callable[[], datetime] = _utc_now,
        lock_timeout_seconds: float = _LOCK_TIMEOUT_SECONDS,
        lock_poll_interval_seconds: float = _LOCK_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.run_id = _require_identifier(run_id, name="run_id")
        self.tool = _require_identifier(tool, name="tool")
        if type(limits) is not BatchLimits:
            raise ValueError("limits must be BatchLimits")
        self.limits = limits
        self.run_dir = Path(run_dir)
        self.state_path = self.run_dir / SAFETY_STATE_FILENAME
        self.lock_path = self.run_dir / f"{SAFETY_STATE_FILENAME}.lock"
        self.stop_path = Path(stop_path)
        self._active_calls_dir = self.run_dir / _ACTIVE_CALLS_DIRNAME
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._clock = clock
        self._lock_timeout_seconds = _require_positive_float(
            lock_timeout_seconds, name="lock_timeout_seconds"
        )
        self._lock_poll_interval_seconds = _require_positive_float(
            lock_poll_interval_seconds, name="lock_poll_interval_seconds"
        )
        self._permit_locks: dict[tuple[str, int], _FileLock] = {}

    @classmethod
    def attach(
        cls,
        run_dir: str | os.PathLike[str],
        *,
        stop_path: str | os.PathLike[str] = STOP_GENERATION_PATH,
        clock: Callable[[], datetime] = _utc_now,
        lock_timeout_seconds: float = _LOCK_TIMEOUT_SECONDS,
        lock_poll_interval_seconds: float = _LOCK_POLL_INTERVAL_SECONDS,
    ) -> GenerationManager:
        """Load an existing RUNNING run without creating or changing its state."""

        resolved_run_dir = Path(run_dir)
        state_path = resolved_run_dir / SAFETY_STATE_FILENAME
        lock_path = resolved_run_dir / f"{SAFETY_STATE_FILENAME}.lock"
        timeout = _require_positive_float(
            lock_timeout_seconds,
            name="lock_timeout_seconds",
        )
        poll_interval = _require_positive_float(
            lock_poll_interval_seconds,
            name="lock_poll_interval_seconds",
        )
        lock = _FileLock(lock_path, create=False)
        try:
            lock.acquire(timeout, poll_interval)
            try:
                with state_path.open(encoding="utf8") as handle:
                    encoded = json.load(handle, object_pairs_hook=_strict_json_object)
                state = BatchState.from_dict(encoded)
                if state.status is not BatchStatus.RUNNING:
                    raise BatchStopped(BatchStopReason.STATE_IO)
                manager = cls(
                    run_id=state.run_id,
                    tool=state.tool,
                    run_dir=resolved_run_dir,
                    limits=state.limits,
                    stop_path=stop_path,
                    clock=clock,
                    lock_timeout_seconds=timeout,
                    lock_poll_interval_seconds=poll_interval,
                )
                if len(manager._permit_markers_locked()) != state.counters.active_calls:
                    manager._stop_locked(state, BatchStopReason.STATE_IO)
                if manager._has_stale_permit_locked():
                    manager._stop_locked(state, BatchStopReason.STATE_IO)
                return manager
            finally:
                lock.release()
        except BatchStopped:
            raise
        except (OSError, UnicodeError, ValueError, _StateIOError) as exc:
            raise BatchStopped(BatchStopReason.STATE_IO) from exc

    def initialize(self) -> BatchState:
        """Create a new RUNNING state without overwriting an existing run."""

        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            with self._state_lock():
                if os.path.lexists(self.state_path):
                    raise BatchStopped(BatchStopReason.STATE_IO)
                self._active_calls_dir.mkdir(exist_ok=True)
                if any(self._active_calls_dir.iterdir()):
                    raise BatchStopped(BatchStopReason.STATE_IO)
                timestamp = self._timestamp()
                state = BatchState(
                    run_id=self.run_id,
                    tool=self.tool,
                    status=BatchStatus.RUNNING,
                    limits=self.limits,
                    counters=BatchCounters(),
                    started_at=timestamp,
                    updated_at=timestamp,
                )
                self._write_state_locked(state)
                return state
        except BatchStopped:
            raise
        except (OSError, UnicodeError, ValueError, _StateIOError) as exc:
            raise BatchStopped(BatchStopReason.STATE_IO) from exc

    def before_call(self, operation_id: str, attempt: int) -> CallPermit:
        """Reserve one provider call after checking all safety limits."""

        operation_id = _require_identifier(operation_id, name="operation_id")
        attempt = _require_nonnegative_int(attempt, name="attempt")
        permit = CallPermit(operation_id, attempt)
        try:
            with self._state_lock():
                return self._before_call_locked(permit)
        except BatchStopped:
            raise
        except (OSError, UnicodeError, ValueError, _StateIOError) as exc:
            raise BatchStopped(BatchStopReason.STATE_IO) from exc

    def _before_call_locked(self, permit: CallPermit) -> CallPermit:
        state = self._read_running_state_locked()
        if os.path.lexists(self.stop_path):
            self._stop_locked(state, BatchStopReason.KILL_SWITCH)

        now = self._now()
        self._enforce_admission_limits_locked(state, permit.attempt, now)
        return self._reserve_call_locked(state, permit, now)

    def _enforce_admission_limits_locked(
        self, state: BatchState, attempt: int, now: datetime
    ) -> None:
        started = _parse_timestamp(state.started_at, name="started_at")
        if now < started:
            raise _StateIOError("clock precedes batch start")
        if (now - started).total_seconds() >= state.limits.max_minutes * 60:
            self._stop_locked(state, BatchStopReason.DURATION_LIMIT, now=now)
        if attempt > state.limits.max_retries:
            self._stop_locked(state, BatchStopReason.RETRY_LIMIT, now=now)
        if attempt > 0 and state.counters.retries >= state.limits.max_retries:
            self._stop_locked(state, BatchStopReason.RETRY_LIMIT, now=now)
        if state.counters.calls_started >= state.limits.max_calls:
            self._stop_locked(state, BatchStopReason.CALL_LIMIT, now=now)
        if state.counters.active_calls >= state.limits.max_concurrency:
            if self._has_stale_permit_locked():
                self._stop_locked(state, BatchStopReason.STATE_IO, now=now)
            self._stop_locked(state, BatchStopReason.CONCURRENCY_LIMIT, now=now)

    def _reserve_call_locked(
        self, state: BatchState, permit: CallPermit, now: datetime
    ) -> CallPermit:
        permit_lock = self._create_permit_marker_locked(permit)
        counters = replace(
            state.counters,
            calls_started=state.counters.calls_started + 1,
            active_calls=state.counters.active_calls + 1,
            peak_concurrency=max(
                state.counters.peak_concurrency,
                state.counters.active_calls + 1,
            ),
            retries=state.counters.retries + (1 if permit.attempt > 0 else 0),
        )
        updated = replace(
            state,
            counters=counters,
            updated_at=_format_timestamp(now, name="clock"),
        )
        try:
            self._write_state_locked(updated)
        except _StateIOError:
            self._release_permit_marker(permit_lock)
            raise
        self._permit_locks[self._permit_key(permit)] = permit_lock
        return permit

    def after_call(self, permit: CallPermit, *, ok: bool) -> None:
        """Record the terminal outcome for a previously issued permit."""

        if type(permit) is not CallPermit:
            raise ValueError("permit must be a CallPermit")
        if type(ok) is not bool:
            raise ValueError("ok must be a bool")

        try:
            with self._state_lock():
                state = self._read_running_state_locked()
                permit_lock = self._permit_locks.get(self._permit_key(permit))
                if permit_lock is None or state.counters.active_calls == 0:
                    self._stop_locked(state, BatchStopReason.STATE_IO)
                expected_path = self._permit_marker_path(permit)
                if permit_lock.path != expected_path or not expected_path.is_file():
                    self._stop_locked(state, BatchStopReason.STATE_IO)

                self._release_permit_marker(permit_lock)
                self._permit_locks.pop(self._permit_key(permit), None)
                counters = replace(
                    state.counters,
                    calls_completed=state.counters.calls_completed + int(ok),
                    calls_failed=state.counters.calls_failed + int(not ok),
                    active_calls=state.counters.active_calls - 1,
                )
                updated = replace(
                    state,
                    counters=counters,
                    updated_at=self._timestamp(),
                )
                self._write_state_locked(updated)
        except BatchStopped:
            raise
        except (OSError, UnicodeError, ValueError, _StateIOError) as exc:
            raise BatchStopped(BatchStopReason.STATE_IO) from exc

    def mark_completed(self) -> BatchState:
        """Atomically complete a RUNNING run with no calls in flight."""

        return self._mark_terminal(BatchStatus.COMPLETED)

    def mark_failed(self) -> BatchState:
        """Atomically fail a RUNNING run with no calls in flight."""

        return self._mark_terminal(BatchStatus.FAILED)

    def _mark_terminal(self, status: BatchStatus) -> BatchState:
        try:
            with self._state_lock():
                state = self._read_running_state_locked()
                if state.counters.active_calls != 0:
                    if self._has_stale_permit_locked():
                        self._stop_locked(state, BatchStopReason.STATE_IO)
                    raise BatchStopped(BatchStopReason.STATE_IO)
                terminal = replace(
                    state,
                    status=status,
                    updated_at=self._timestamp(),
                )
                self._write_state_locked(terminal)
                return terminal
        except BatchStopped:
            raise
        except (OSError, UnicodeError, ValueError, _StateIOError) as exc:
            raise BatchStopped(BatchStopReason.STATE_IO) from exc

    @contextmanager
    def _state_lock(self) -> Iterator[None]:
        lock = _FileLock(self.lock_path)
        lock.acquire(self._lock_timeout_seconds, self._lock_poll_interval_seconds)
        try:
            yield
        finally:
            lock.release()

    def _read_running_state_locked(self) -> BatchState:
        state = self._read_state_locked()
        if (
            state.run_id != self.run_id
            or state.tool != self.tool
            or state.limits != self.limits
            or state.status is not BatchStatus.RUNNING
        ):
            raise BatchStopped(BatchStopReason.STATE_IO)
        markers = self._permit_markers_locked()
        if len(markers) != state.counters.active_calls:
            self._stop_locked(state, BatchStopReason.STATE_IO)
        return state

    def _read_state_locked(self) -> BatchState:
        try:
            with self.state_path.open(encoding="utf8") as handle:
                encoded = json.load(handle, object_pairs_hook=_strict_json_object)
            return BatchState.from_dict(encoded)
        except (OSError, UnicodeError, ValueError) as exc:
            raise _StateIOError(f"failed to read {self.state_path}") from exc

    def _write_state_locked(self, state: BatchState) -> None:
        temporary_path: Path | None = None
        descriptor = -1
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.run_dir,
                prefix=f".{SAFETY_STATE_FILENAME}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf8", newline="\n") as handle:
                descriptor = -1
                json.dump(
                    state.to_dict(),
                    handle,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.state_path)
            temporary_path = None
            self._fsync_run_directory()
        except (OSError, TypeError, ValueError) as exc:
            raise _StateIOError(f"failed to write {self.state_path}") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _fsync_run_directory(self) -> None:
        if sys.platform == "win32":
            return
        descriptor = os.open(self.run_dir, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _stop_locked(
        self,
        state: BatchState,
        reason: BatchStopReason,
        *,
        now: datetime | None = None,
    ) -> None:
        stopped = replace(
            state,
            status=BatchStatus.STOPPED,
            updated_at=_format_timestamp(now, name="clock")
            if now is not None
            else self._timestamp(),
            stop_reason=reason,
        )
        self._write_state_locked(stopped)
        raise BatchStopped(reason)

    def _permit_key(self, permit: CallPermit) -> tuple[str, int]:
        return (permit.operation_id, permit.attempt)

    def _permit_marker_path(self, permit: CallPermit) -> Path:
        identity = f"{permit.operation_id}\0{permit.attempt}".encode()
        digest = hashlib.sha256(identity).hexdigest()
        return self._active_calls_dir / f"{_PERMIT_FILE_PREFIX}{digest}.lock"

    def _create_permit_marker_locked(self, permit: CallPermit) -> _FileLock:
        key = self._permit_key(permit)
        marker_path = self._permit_marker_path(permit)
        if key in self._permit_locks:
            raise _StateIOError("permit is already active")
        descriptor = -1
        try:
            descriptor = os.open(
                marker_path,
                os.O_CREAT | os.O_EXCL | os.O_RDWR,
                0o600,
            )
        except OSError as exc:
            raise _StateIOError("failed to create active-call marker") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        permit_lock = _FileLock(marker_path)
        try:
            permit_lock.acquire(
                self._lock_timeout_seconds, self._lock_poll_interval_seconds
            )
        except _StateIOError:
            marker_path.unlink(missing_ok=True)
            raise
        return permit_lock

    def _release_permit_marker(self, permit_lock: _FileLock) -> None:
        permit_lock.release()
        try:
            permit_lock.path.unlink()
        except OSError as exc:
            raise _StateIOError("failed to remove active-call marker") from exc

    def _permit_markers_locked(self) -> list[Path]:
        try:
            entries = list(self._active_calls_dir.iterdir())
        except OSError as exc:
            raise _StateIOError("failed to inspect active-call markers") from exc
        if any(
            not entry.is_file()
            or not entry.name.startswith(_PERMIT_FILE_PREFIX)
            or entry.suffix != ".lock"
            for entry in entries
        ):
            raise _StateIOError("active-call marker directory is corrupt")
        return sorted(entries)

    def _has_stale_permit_locked(self) -> bool:
        for marker_path in self._permit_markers_locked():
            marker_lock = _FileLock(marker_path)
            if marker_lock.try_acquire():
                marker_lock.release()
                return True
        return False

    def _now(self) -> datetime:
        try:
            value = self._clock()
            _format_timestamp(value, name="clock")
            return value
        except (TypeError, ValueError) as exc:
            raise _StateIOError("clock failed") from exc

    def _timestamp(self) -> str:
        return _format_timestamp(self._now(), name="clock")
