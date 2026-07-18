# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the per-run, privacy-safe generation safety contract."""

from __future__ import annotations

import json
import math
import multiprocessing
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from anki.pgrep.ai.batch_safety import (
    SAFETY_STATE_FILENAME,
    STOP_GENERATION_PATH,
    BatchCounters,
    BatchLimits,
    BatchState,
    BatchStatus,
    BatchStopped,
    BatchStopReason,
    CallPermit,
    GenerationManager,
)

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "PGREP_BATCH_MAX_CALLS": "12",
        "PGREP_BATCH_MAX_CONCURRENCY": "3",
        "PGREP_BATCH_MAX_RETRIES": "2",
        "PGREP_BATCH_MAX_MINUTES": "15",
    }
    env.update(overrides)
    return env


def _limits(
    *,
    max_calls: int = 12,
    max_concurrency: int = 3,
    max_retries: int = 2,
    max_minutes: int = 15,
) -> BatchLimits:
    return BatchLimits(max_calls, max_concurrency, max_retries, max_minutes)


@dataclass
class _Clock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


def _manager(
    run_dir: Path,
    *,
    limits: BatchLimits | None = None,
    clock: _Clock | None = None,
    lock_timeout_seconds: float | None = None,
) -> GenerationManager:
    manager_clock: Callable[[], datetime] = clock or (
        lambda: datetime.now(timezone.utc)
    )
    return GenerationManager(
        run_id="run-123",
        tool="generate-content-set",
        run_dir=run_dir,
        limits=limits or _limits(),
        stop_path=run_dir / "STOP_GENERATION",
        clock=manager_clock,
        lock_timeout_seconds=lock_timeout_seconds or 5.0,
        lock_poll_interval_seconds=0.005,
    )


def _read_state(path: Path) -> BatchState:
    return BatchState.from_dict(json.loads(path.read_text(encoding="utf8")))


def _initialize_once(
    run_dir: str,
    limits: BatchLimits,
    start: Any,
    results: Any,
) -> None:
    manager = GenerationManager(
        "run-123",
        "generate-content-set",
        run_dir,
        limits,
        stop_path=f"{run_dir}.stop",
    )
    start.wait()
    try:
        manager.initialize()
    except BatchStopped as exc:
        results.put(("stopped", exc.reason.value))
    else:
        results.put(("initialized", None))


def _reserve_once(
    run_dir: str,
    limits: BatchLimits,
    operation_id: str,
    start: Any,
    results: Any,
) -> None:
    manager = GenerationManager(
        "run-123",
        "generate-content-set",
        run_dir,
        limits,
        stop_path=f"{run_dir}.stop",
    )
    start.wait()
    try:
        manager.before_call(operation_id, 0)
    except BatchStopped as exc:
        results.put(("stopped", exc.reason.value))
    else:
        results.put(("reserved", None))


def _reserve_retry_once(
    run_dir: str,
    limits: BatchLimits,
    operation_id: str,
    results: Any,
) -> None:
    manager = GenerationManager(
        "run-123",
        "generate-content-set",
        run_dir,
        limits,
        stop_path=f"{run_dir}.stop",
    )
    try:
        permit = manager.before_call(operation_id, 1)
        manager.after_call(permit, ok=True)
    except BatchStopped as exc:
        results.put(("stopped", exc.reason.value))
    else:
        results.put(("reserved", None))


def _reserve_and_hold(
    run_dir: str,
    limits: BatchLimits,
    operation_id: str,
    start: Any,
    ready: Any,
    release: Any,
) -> None:
    manager = GenerationManager(
        "run-123",
        "generate-content-set",
        run_dir,
        limits,
        stop_path=f"{run_dir}.stop",
    )
    start.wait()
    manager.before_call(operation_id, 0)
    ready.put(operation_id)
    release.wait(15)


def _reserve_then_crash(
    run_dir: str,
    limits: BatchLimits,
    ready: Any,
) -> None:
    manager = GenerationManager(
        "run-123",
        "generate-content-set",
        run_dir,
        limits,
        stop_path=f"{run_dir}.stop",
    )
    manager.before_call("crashed-operation", 0)
    ready.set()
    os._exit(0)


def _hold_state_lock(lock_path: str, ready: Any, release: Any) -> None:
    with open(lock_path, "a+b") as handle:
        if sys.platform == "win32":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        ready.set()
        release.wait(15)
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_states(
    run_dir: str,
    limits: BatchLimits,
    count: int,
    barrier: Any,
    done: Any,
    results: Any,
) -> None:
    manager = GenerationManager(
        "run-123",
        "generate-content-set",
        run_dir,
        limits,
        stop_path=f"{run_dir}.stop",
    )
    barrier.wait()
    try:
        for index in range(count):
            permit = manager.before_call(f"operation-{index}", 0)
            manager.after_call(permit, ok=True)
    except Exception as exc:
        results.put(repr(exc))
    else:
        results.put(None)
    finally:
        done.set()


def _read_states_atomically(
    state_path: str,
    barrier: Any,
    done: Any,
    results: Any,
) -> None:
    barrier.wait()
    reads = 0
    try:
        while not done.is_set() or reads == 0:
            BatchState.from_dict(
                json.loads(Path(state_path).read_text(encoding="utf8"))
            )
            reads += 1
    except Exception as exc:
        results.put((reads, repr(exc)))
    else:
        results.put((reads, None))


def _join_processes(processes: list[Any]) -> None:
    for process in processes:
        process.join(15)
        assert not process.is_alive()
        assert process.exitcode == 0


def test_limits_are_loaded_from_all_required_environment_variables() -> None:
    limits = BatchLimits.from_env(_env(PGREP_UNUSED_SETTING="ignored"))

    assert limits == BatchLimits(
        max_calls=12, max_concurrency=3, max_retries=2, max_minutes=15
    )


@pytest.mark.parametrize(
    "env, variable",
    [
        (
            {
                key: value
                for key, value in _env().items()
                if key != "PGREP_BATCH_MAX_CALLS"
            },
            "PGREP_BATCH_MAX_CALLS",
        ),
        (_env(PGREP_BATCH_MAX_CALLS=""), "PGREP_BATCH_MAX_CALLS"),
        (_env(PGREP_BATCH_MAX_CALLS=" 2"), "PGREP_BATCH_MAX_CALLS"),
        (_env(PGREP_BATCH_MAX_CONCURRENCY="1.5"), "PGREP_BATCH_MAX_CONCURRENCY"),
        (_env(PGREP_BATCH_MAX_RETRIES="0"), "PGREP_BATCH_MAX_RETRIES"),
        (_env(PGREP_BATCH_MAX_MINUTES="-1"), "PGREP_BATCH_MAX_MINUTES"),
    ],
)
def test_limits_reject_missing_or_non_positive_non_integer_values(
    env: dict[str, str], variable: str
) -> None:
    with pytest.raises(ValueError, match=variable):
        BatchLimits.from_env(env)


def test_public_stop_reasons_are_exact_and_typed() -> None:
    assert {reason.value for reason in BatchStopReason} == {
        "CALL_LIMIT",
        "CONCURRENCY_LIMIT",
        "RETRY_LIMIT",
        "DURATION_LIMIT",
        "KILL_SWITCH",
        "STATE_IO",
    }
    error = BatchStopped(BatchStopReason.CALL_LIMIT)
    assert error.reason is BatchStopReason.CALL_LIMIT
    assert "CALL_LIMIT" in str(error)


def test_state_round_trip_is_json_safe_and_closed_to_unknown_data() -> None:
    limits = _limits()
    state = BatchState(
        run_id="run-123",
        tool="generate-content-set",
        status=BatchStatus.RUNNING,
        limits=limits,
        counters=BatchCounters(
            calls_started=4,
            calls_completed=2,
            calls_failed=1,
            active_calls=1,
            peak_concurrency=2,
            retries=1,
        ),
        started_at="2026-07-16T22:55:00Z",
        updated_at="2026-07-16T22:56:00Z",
    )

    encoded = state.to_dict()
    assert encoded == {
        "run_id": "run-123",
        "tool": "generate-content-set",
        "status": "RUNNING",
        "limits": {
            "max_calls": 12,
            "max_concurrency": 3,
            "max_retries": 2,
            "max_minutes": 15,
        },
        "counters": {
            "calls_started": 4,
            "calls_completed": 2,
            "calls_failed": 1,
            "active_calls": 1,
            "peak_concurrency": 2,
            "retries": 1,
        },
        "started_at": "2026-07-16T22:55:00Z",
        "updated_at": "2026-07-16T22:56:00Z",
        "stop_reason": None,
    }
    assert BatchState.from_dict(encoded) == state

    with pytest.raises(ValueError, match="unknown"):
        BatchState.from_dict({**encoded, "prompt": "never serialize prompts"})
    with pytest.raises(ValueError, match="missing"):
        BatchState.from_dict(
            {key: value for key, value in encoded.items() if key != "tool"}
        )
    with pytest.raises(ValueError, match="finite"):
        BatchState.from_dict(
            {
                **encoded,
                "counters": {
                    **state.counters.to_dict(),
                    "calls_started": math.inf,
                },
            }
        )


def test_stopped_state_requires_typed_stop_reason() -> None:
    with pytest.raises(ValueError, match="stop_reason"):
        BatchState(
            run_id="run-123",
            tool="generate-content-set",
            status=BatchStatus.STOPPED,
            limits=_limits(),
            counters=BatchCounters(),
            started_at="2026-07-16T22:55:00Z",
            updated_at="2026-07-16T22:56:00Z",
        )

    state = BatchState(
        run_id="run-123",
        tool="generate-content-set",
        status=BatchStatus.STOPPED,
        limits=_limits(),
        counters=BatchCounters(),
        started_at="2026-07-16T22:55:00Z",
        updated_at="2026-07-16T22:56:00Z",
        stop_reason=BatchStopReason.KILL_SWITCH,
    )
    assert state.to_dict()["stop_reason"] == "KILL_SWITCH"


def test_permit_is_minimal_and_rejects_private_payload_fields() -> None:
    permit = CallPermit(operation_id="operation-8", attempt=2)

    assert permit.to_dict() == {"operation_id": "operation-8", "attempt": 2}
    assert CallPermit.from_dict(permit.to_dict()) == permit
    with pytest.raises(ValueError, match="unknown"):
        CallPermit.from_dict(
            {"operation_id": "operation-8", "attempt": 2, "model": "private"}
        )


def test_manager_uses_run_local_state_and_global_or_explicit_stop_path(
    tmp_path: Path,
) -> None:
    manager = GenerationManager(
        run_id="run-123",
        tool="generate-content-set",
        run_dir=tmp_path,
        limits=BatchLimits(12, 3, 2, 15),
    )
    override = tmp_path / "test-stop"
    overridden_manager = GenerationManager(
        run_id="run-123",
        tool="generate-content-set",
        run_dir=tmp_path,
        limits=BatchLimits(12, 3, 2, 15),
        stop_path=override,
    )

    assert manager.state_path == tmp_path / SAFETY_STATE_FILENAME
    assert manager.lock_path == tmp_path / f"{SAFETY_STATE_FILENAME}.lock"
    assert manager.stop_path == STOP_GENERATION_PATH
    assert overridden_manager.stop_path == override
    assert not manager.state_path.exists()
    assert not manager.lock_path.exists()


def test_limits_have_strict_json_serialization() -> None:
    limits = _limits()

    assert limits.to_dict() == {
        "max_calls": 12,
        "max_concurrency": 3,
        "max_retries": 2,
        "max_minutes": 15,
    }
    assert BatchLimits.from_dict(limits.to_dict()) == limits
    with pytest.raises(ValueError, match="unknown"):
        BatchLimits.from_dict({**limits.to_dict(), "model": "never persist"})


@pytest.mark.parametrize(
    "counters, match",
    [
        (BatchCounters(calls_started=1), "completed.*failed.*active"),
        (
            BatchCounters(calls_started=1, active_calls=1, peak_concurrency=0),
            "peak",
        ),
        (
            BatchCounters(
                calls_started=13,
                calls_completed=13,
                peak_concurrency=1,
            ),
            "max_calls",
        ),
        (
            BatchCounters(
                calls_started=3,
                calls_completed=3,
                peak_concurrency=1,
                retries=3,
            ),
            "max_retries",
        ),
    ],
)
def test_state_rejects_impossible_counter_combinations(
    counters: BatchCounters, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        BatchState(
            run_id="run-123",
            tool="generate-content-set",
            status=BatchStatus.RUNNING,
            limits=_limits(),
            counters=counters,
            started_at="2026-07-16T22:55:00Z",
            updated_at="2026-07-16T22:56:00Z",
        )


def test_initialize_is_explicit_atomic_and_refuses_existing_state(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "new-run"
    clock = _Clock(datetime(2026, 7, 16, 22, 55, tzinfo=timezone.utc))
    manager = _manager(run_dir, clock=clock)

    assert not run_dir.exists()
    state = manager.initialize()

    assert state == _read_state(manager.state_path)
    assert state.status is BatchStatus.RUNNING
    assert state.counters == BatchCounters()
    assert state.limits == _limits()
    assert state.started_at == "2026-07-16T22:55:00Z"
    assert state.updated_at == state.started_at

    original = manager.state_path.read_bytes()
    with pytest.raises(BatchStopped) as error:
        manager.initialize()
    assert error.value.reason is BatchStopReason.STATE_IO
    assert manager.state_path.read_bytes() == original


def test_attach_recovers_running_identity_without_mutating_state(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "existing-run"
    clock = _Clock(datetime(2026, 7, 16, 22, 55, tzinfo=timezone.utc))
    initialized = _manager(run_dir, clock=clock)
    initialized.initialize()
    original = initialized.state_path.read_bytes()

    attached = GenerationManager.attach(
        run_dir,
        stop_path=initialized.stop_path,
        clock=clock,
    )

    assert attached.run_id == initialized.run_id
    assert attached.tool == initialized.tool
    assert attached.limits == initialized.limits
    assert attached.run_dir == initialized.run_dir
    assert attached.state_path.read_bytes() == original

    permit = attached.before_call("attached-operation", 0)
    attached.after_call(permit, ok=True)
    assert _read_state(attached.state_path).counters.calls_completed == 1


def test_attach_fails_closed_without_initializing_overwriting_or_resuming(
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "missing-run"
    missing_dir.mkdir()
    with pytest.raises(BatchStopped) as missing_error:
        GenerationManager.attach(missing_dir)
    assert missing_error.value.reason is BatchStopReason.STATE_IO
    assert not (missing_dir / SAFETY_STATE_FILENAME).exists()
    assert not (missing_dir / f"{SAFETY_STATE_FILENAME}.lock").exists()
    assert not (missing_dir / ".safety-active").exists()

    corrupt = _manager(tmp_path / "corrupt-run")
    corrupt.initialize()
    corrupt.state_path.write_text("{", encoding="utf8")
    corrupt_bytes = corrupt.state_path.read_bytes()
    with pytest.raises(BatchStopped) as corrupt_error:
        GenerationManager.attach(corrupt.run_dir)
    assert corrupt_error.value.reason is BatchStopReason.STATE_IO
    assert corrupt.state_path.read_bytes() == corrupt_bytes

    completed = _manager(tmp_path / "completed-run")
    completed.initialize()
    completed.mark_completed()
    completed_bytes = completed.state_path.read_bytes()
    with pytest.raises(BatchStopped) as completed_error:
        GenerationManager.attach(completed.run_dir)
    assert completed_error.value.reason is BatchStopReason.STATE_IO
    assert completed.state_path.read_bytes() == completed_bytes


def test_attach_loads_state_under_the_adjacent_lock(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    manager = _manager(tmp_path)
    manager.initialize()
    original = manager.state_path.read_bytes()
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_state_lock,
        args=(str(manager.lock_path), ready, release),
    )
    holder.start()
    assert ready.wait(15)

    try:
        with pytest.raises(BatchStopped) as error:
            GenerationManager.attach(
                tmp_path,
                lock_timeout_seconds=0.05,
                lock_poll_interval_seconds=0.005,
            )
        assert error.value.reason is BatchStopReason.STATE_IO
        assert manager.state_path.read_bytes() == original
    finally:
        release.set()
        _join_processes([holder])


def test_concurrent_initializers_create_exactly_one_state(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    run_dir = tmp_path / "concurrent-init"
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_initialize_once,
            args=(str(run_dir), _limits(), start, results),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    _join_processes(processes)

    assert sorted(outcomes) == [
        ("initialized", None),
        ("stopped", "STATE_IO"),
    ]
    assert _read_state(run_dir / SAFETY_STATE_FILENAME).status is BatchStatus.RUNNING


def test_before_and_after_call_account_for_each_outcome(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.initialize()

    successful = manager.before_call("operation-1", 0)
    assert successful == CallPermit("operation-1", 0)
    assert _read_state(manager.state_path).counters == BatchCounters(
        calls_started=1,
        active_calls=1,
        peak_concurrency=1,
    )
    manager.after_call(successful, ok=True)

    failed = manager.before_call("operation-2", 1)
    manager.after_call(failed, ok=False)

    assert _read_state(manager.state_path).counters == BatchCounters(
        calls_started=2,
        calls_completed=1,
        calls_failed=1,
        peak_concurrency=1,
        retries=1,
    )


def test_after_call_validates_arguments_before_mutating_state(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.initialize()
    permit = manager.before_call("operation-1", 0)

    with pytest.raises(ValueError, match="permit"):
        manager.after_call(object(), ok=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bool"):
        manager.after_call(permit, ok=1)  # type: ignore[arg-type]

    assert _read_state(manager.state_path).counters.active_calls == 1
    manager.after_call(permit, ok=True)
    with pytest.raises(BatchStopped) as error:
        manager.after_call(permit, ok=True)
    assert error.value.reason is BatchStopReason.STATE_IO


def test_call_limit_stops_and_persists_reason(tmp_path: Path) -> None:
    manager = _manager(tmp_path, limits=_limits(max_calls=1))
    manager.initialize()
    permit = manager.before_call("operation-1", 0)
    manager.after_call(permit, ok=True)

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-2", 0)

    assert error.value.reason is BatchStopReason.CALL_LIMIT
    state = _read_state(manager.state_path)
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.CALL_LIMIT
    assert state.counters.calls_started == 1


def test_concurrency_limit_stops_without_overbooking(tmp_path: Path) -> None:
    manager = _manager(tmp_path, limits=_limits(max_concurrency=1))
    manager.initialize()
    manager.before_call("operation-1", 0)

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-2", 0)

    assert error.value.reason is BatchStopReason.CONCURRENCY_LIMIT
    state = _read_state(manager.state_path)
    assert state.status is BatchStatus.STOPPED
    assert state.counters.active_calls == 1
    assert state.counters.peak_concurrency == 1


def test_retry_limit_is_cumulative_across_operations(tmp_path: Path) -> None:
    manager = _manager(tmp_path, limits=_limits(max_retries=2))
    manager.initialize()
    for operation_id in ("operation-1", "operation-2"):
        permit = manager.before_call(operation_id, 1)
        manager.after_call(permit, ok=False)

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-3", 1)

    assert error.value.reason is BatchStopReason.RETRY_LIMIT
    state = _read_state(manager.state_path)
    assert state.stop_reason is BatchStopReason.RETRY_LIMIT
    assert state.counters.retries == 2
    assert state.counters.calls_started == 2


def test_retry_attempt_sanity_stops_before_admission(tmp_path: Path) -> None:
    manager = _manager(tmp_path, limits=_limits(max_retries=2))
    manager.initialize()

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-1", 3)

    assert error.value.reason is BatchStopReason.RETRY_LIMIT
    state = _read_state(manager.state_path)
    assert state.stop_reason is BatchStopReason.RETRY_LIMIT
    assert state.counters == BatchCounters()


def test_duration_limit_stops_at_exact_boundary_without_sleep(
    tmp_path: Path,
) -> None:
    clock = _Clock(datetime(2026, 7, 16, 22, 55, tzinfo=timezone.utc))
    manager = _manager(tmp_path, limits=_limits(max_minutes=1), clock=clock)
    manager.initialize()
    clock.current += timedelta(minutes=1)

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-1", 0)

    assert error.value.reason is BatchStopReason.DURATION_LIMIT
    assert _read_state(manager.state_path).stop_reason is BatchStopReason.DURATION_LIMIT


def test_kill_switch_stops_before_reserving_a_call(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.initialize()
    manager.stop_path.touch()

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-1", 0)

    assert error.value.reason is BatchStopReason.KILL_SWITCH
    state = _read_state(manager.state_path)
    assert state.stop_reason is BatchStopReason.KILL_SWITCH
    assert state.counters == BatchCounters()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink semantics are Unix-only")
def test_dangling_kill_switch_symlink_stops_before_reserving_a_call(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager.initialize()
    manager.stop_path.symlink_to(tmp_path / "missing-stop-target")
    assert os.path.lexists(manager.stop_path)
    assert not manager.stop_path.exists()

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-1", 0)

    assert error.value.reason is BatchStopReason.KILL_SWITCH
    state = _read_state(manager.state_path)
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.KILL_SWITCH
    assert state.counters == BatchCounters()


def test_missing_corrupt_and_non_running_state_fail_closed(tmp_path: Path) -> None:
    missing = _manager(tmp_path / "missing")
    with pytest.raises(BatchStopped) as error:
        missing.before_call("operation-1", 0)
    assert error.value.reason is BatchStopReason.STATE_IO

    corrupt = _manager(tmp_path / "corrupt")
    corrupt.initialize()
    corrupt.state_path.write_text("{", encoding="utf8")
    with pytest.raises(BatchStopped) as error:
        corrupt.before_call("operation-1", 0)
    assert error.value.reason is BatchStopReason.STATE_IO

    impossible = _manager(tmp_path / "impossible")
    impossible.initialize()
    encoded = _read_state(impossible.state_path).to_dict()
    counters = encoded["counters"]
    assert isinstance(counters, dict)
    counters["calls_started"] = 1
    impossible.state_path.write_text(json.dumps(encoded), encoding="utf8")
    with pytest.raises(BatchStopped) as error:
        impossible.before_call("operation-1", 0)
    assert error.value.reason is BatchStopReason.STATE_IO

    completed = _manager(tmp_path / "completed")
    completed.initialize()
    completed.mark_completed()
    with pytest.raises(BatchStopped) as error:
        completed.before_call("operation-1", 0)
    assert error.value.reason is BatchStopReason.STATE_IO


def test_mark_completed_requires_no_active_calls_and_cannot_resume(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path / "active")
    manager.initialize()
    permit = manager.before_call("operation-1", 0)

    with pytest.raises(BatchStopped) as error:
        manager.mark_completed()
    assert error.value.reason is BatchStopReason.STATE_IO
    assert _read_state(manager.state_path).status is BatchStatus.RUNNING

    manager.after_call(permit, ok=True)
    completed = manager.mark_completed()
    assert completed.status is BatchStatus.COMPLETED
    assert _read_state(manager.state_path) == completed
    with pytest.raises(BatchStopped) as error:
        manager.mark_completed()
    assert error.value.reason is BatchStopReason.STATE_IO

    stopped = _manager(tmp_path / "stopped")
    stopped.initialize()
    stopped.stop_path.touch()
    with pytest.raises(BatchStopped):
        stopped.before_call("operation-1", 0)
    with pytest.raises(BatchStopped) as error:
        stopped.mark_completed()
    assert error.value.reason is BatchStopReason.STATE_IO
    assert _read_state(stopped.state_path).status is BatchStatus.STOPPED


def test_lock_acquisition_timeout_fails_closed(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    manager = _manager(tmp_path, lock_timeout_seconds=0.05)
    manager.initialize()
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_state_lock,
        args=(str(manager.lock_path), ready, release),
    )
    holder.start()
    assert ready.wait(15)

    try:
        with pytest.raises(BatchStopped) as error:
            manager.before_call("operation-1", 0)
        assert error.value.reason is BatchStopReason.STATE_IO
    finally:
        release.set()
        _join_processes([holder])


def test_processes_cannot_reserve_more_than_max_calls(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    limits = _limits(max_calls=3, max_concurrency=4)
    manager = _manager(tmp_path, limits=limits)
    manager.initialize()
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_reserve_once,
            args=(str(tmp_path), limits, f"operation-{index}", start, results),
        )
        for index in range(4)
    ]

    for process in processes:
        process.start()
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    _join_processes(processes)

    assert [outcome[0] for outcome in outcomes].count("reserved") == 3
    assert outcomes.count(("stopped", "CALL_LIMIT")) == 1
    state = _read_state(manager.state_path)
    assert state.counters.calls_started == 3
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.CALL_LIMIT


def test_processes_share_one_cumulative_retry_ceiling(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    limits = _limits(max_calls=4, max_concurrency=1, max_retries=2)
    manager = _manager(tmp_path, limits=limits)
    manager.initialize()
    results = context.Queue()
    outcomes = []

    for index in range(3):
        process = context.Process(
            target=_reserve_retry_once,
            args=(str(tmp_path), limits, f"retry-operation-{index}", results),
        )
        process.start()
        _join_processes([process])
        outcomes.append(results.get(timeout=15))

    assert outcomes == [
        ("reserved", None),
        ("reserved", None),
        ("stopped", "RETRY_LIMIT"),
    ]
    state = _read_state(manager.state_path)
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.RETRY_LIMIT
    assert state.counters.retries == limits.max_retries
    assert state.counters.calls_started == limits.max_retries


def test_processes_cannot_exceed_max_concurrency(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    limits = _limits(max_calls=3, max_concurrency=2)
    manager = _manager(tmp_path, limits=limits)
    manager.initialize()
    start = context.Event()
    ready = context.Queue()
    release = context.Event()
    holders = [
        context.Process(
            target=_reserve_and_hold,
            args=(
                str(tmp_path),
                limits,
                f"operation-{index}",
                start,
                ready,
                release,
            ),
        )
        for index in range(2)
    ]

    for process in holders:
        process.start()
    start.set()
    assert {ready.get(timeout=15) for _ in holders} == {
        "operation-0",
        "operation-1",
    }
    try:
        with pytest.raises(BatchStopped) as error:
            manager.before_call("operation-2", 0)
        assert error.value.reason is BatchStopReason.CONCURRENCY_LIMIT
    finally:
        release.set()
        _join_processes(holders)

    state = _read_state(manager.state_path)
    assert state.counters.calls_started == 2
    assert state.counters.active_calls == 2
    assert state.counters.peak_concurrency == 2


def test_crashed_worker_leaves_fail_safe_active_slot(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    limits = _limits(max_calls=2, max_concurrency=1)
    manager = _manager(tmp_path, limits=limits)
    manager.initialize()
    ready = context.Event()
    worker = context.Process(
        target=_reserve_then_crash,
        args=(str(tmp_path), limits, ready),
    )
    worker.start()
    assert ready.wait(15)
    worker.join(15)
    assert worker.exitcode == 0

    with pytest.raises(BatchStopped) as error:
        manager.before_call("operation-after-crash", 0)

    assert error.value.reason is BatchStopReason.STATE_IO
    state = _read_state(manager.state_path)
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.STATE_IO
    assert state.counters.active_calls == 1


def test_attach_persists_state_io_for_crashed_active_permit(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    limits = _limits(max_calls=2, max_concurrency=2)
    manager = _manager(tmp_path, limits=limits)
    manager.initialize()
    ready = context.Event()
    worker = context.Process(
        target=_reserve_then_crash,
        args=(str(tmp_path), limits, ready),
    )
    worker.start()
    assert ready.wait(15)
    worker.join(15)
    assert worker.exitcode == 0

    with pytest.raises(BatchStopped) as error:
        GenerationManager.attach(tmp_path, stop_path=manager.stop_path)

    assert error.value.reason is BatchStopReason.STATE_IO
    state = _read_state(manager.state_path)
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.STATE_IO
    assert state.counters.active_calls == 1


def test_terminal_marking_persists_state_io_for_crashed_active_permit(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    limits = _limits(max_calls=2, max_concurrency=2)
    manager = _manager(tmp_path, limits=limits)
    manager.initialize()
    ready = context.Event()
    worker = context.Process(
        target=_reserve_then_crash,
        args=(str(tmp_path), limits, ready),
    )
    worker.start()
    assert ready.wait(15)
    worker.join(15)
    assert worker.exitcode == 0

    with pytest.raises(BatchStopped) as error:
        manager.mark_completed()

    assert error.value.reason is BatchStopReason.STATE_IO
    state = _read_state(manager.state_path)
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.STATE_IO
    assert state.counters.active_calls == 1


def test_atomic_state_writes_remain_strictly_readable(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    limits = _limits(max_calls=40, max_concurrency=1)
    manager = _manager(tmp_path, limits=limits)
    manager.initialize()
    barrier = context.Barrier(2)
    done = context.Event()
    writer_results = context.Queue()
    reader_results = context.Queue()
    writer = context.Process(
        target=_write_states,
        args=(str(tmp_path), limits, 40, barrier, done, writer_results),
    )
    reader = context.Process(
        target=_read_states_atomically,
        args=(str(manager.state_path), barrier, done, reader_results),
    )

    writer.start()
    reader.start()
    _join_processes([writer, reader])

    assert writer_results.get(timeout=15) is None
    reads, error = reader_results.get(timeout=15)
    assert reads > 0
    assert error is None
    state = _read_state(manager.state_path)
    assert state.counters.calls_started == 40
    assert state.counters.calls_completed == 40


def test_failed_state_is_terminal_without_a_stop_reason() -> None:
    """FAILED records tool failure, not a safety stop."""

    state = BatchState(
        run_id="run-123",
        tool="generate-content-set",
        status=BatchStatus.FAILED,
        limits=_limits(),
        counters=BatchCounters(),
        started_at="2026-07-16T22:55:00Z",
        updated_at="2026-07-16T22:56:00Z",
    )

    assert BatchState.from_dict(state.to_dict()) == state
    assert state.to_dict()["stop_reason"] is None
    with pytest.raises(ValueError, match="stop_reason"):
        BatchState(
            run_id=state.run_id,
            tool=state.tool,
            status=BatchStatus.FAILED,
            limits=state.limits,
            counters=state.counters,
            started_at=state.started_at,
            updated_at=state.updated_at,
            stop_reason=BatchStopReason.STATE_IO,
        )


def test_mark_failed_requires_no_active_calls_and_never_resumes_terminal_state(
    tmp_path: Path,
) -> None:
    """Neither active nor already-terminal runs may become FAILED."""

    manager = _manager(tmp_path / "failed")
    manager.initialize()
    permit = manager.before_call("operation-1", 0)

    with pytest.raises(BatchStopped) as active_error:
        manager.mark_failed()
    assert active_error.value.reason is BatchStopReason.STATE_IO
    assert _read_state(manager.state_path).status is BatchStatus.RUNNING

    manager.after_call(permit, ok=False)
    failed = manager.mark_failed()
    assert failed.status is BatchStatus.FAILED
    assert failed.stop_reason is None
    assert _read_state(manager.state_path) == failed
    with pytest.raises(BatchStopped) as repeated_error:
        manager.mark_failed()
    assert repeated_error.value.reason is BatchStopReason.STATE_IO
    with pytest.raises(BatchStopped) as completed_error:
        manager.mark_completed()
    assert completed_error.value.reason is BatchStopReason.STATE_IO
    assert _read_state(manager.state_path) == failed

    stopped = _manager(tmp_path / "stopped-failure")
    stopped.initialize()
    stopped.stop_path.touch()
    with pytest.raises(BatchStopped):
        stopped.before_call("operation-1", 0)
    original = stopped.state_path.read_bytes()
    with pytest.raises(BatchStopped) as stopped_error:
        stopped.mark_failed()
    assert stopped_error.value.reason is BatchStopReason.STATE_IO
    assert stopped.state_path.read_bytes() == original
