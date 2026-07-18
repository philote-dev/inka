# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Operator controls for privacy-safe generation batch state."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import _ai_path

_ai_path.add_ai_core()

from pgrep.ai.batch_safety import (  # type: ignore[import-not-found]  # noqa: E402
    SAFETY_STATE_FILENAME,
    STOP_GENERATION_PATH,
    BatchLimits,
    BatchState,
    BatchStatus,
    GenerationManager,
)

DEFAULT_RUN_ROOT: Final = Path("content/run")
DEFAULT_WATCH_INTERVAL_SECONDS: Final = 30.0
STOPPED_EXIT_STATUS: Final = 3

Clock = Callable[[], datetime]
Output = Callable[[str], None]
Sleeper = Callable[[float], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _print_line(line: str) -> None:
    print(line, flush=True)


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _parse_timestamp(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.utcoffset() is None:
        raise ValueError("batch timestamp must include an offset")
    return parsed


def _now(clock: Clock) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("clock must return an offset-aware datetime")
    return value


def _state_path(run_dir: str | os.PathLike[str]) -> Path:
    path = Path(run_dir)
    return path if path.name == SAFETY_STATE_FILENAME else path / SAFETY_STATE_FILENAME


def _read_state(path: Path) -> BatchState:
    try:
        encoded = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read batch state at {path}") from error
    return BatchState.from_dict(encoded)


def _resolve_state_path(
    run_dir: str | os.PathLike[str] | None,
    *,
    search_root: str | os.PathLike[str],
) -> Path:
    if run_dir is not None:
        path = _state_path(run_dir)
        if not path.is_file():
            raise FileNotFoundError(f"batch state not found: {path}")
        return path

    root = Path(search_root)
    candidates: list[tuple[int, str, Path]] = []
    if root.is_dir():
        for path in root.rglob(SAFETY_STATE_FILENAME):
            if path.is_file() and not path.is_symlink():
                stat = path.stat()
                candidates.append((stat.st_mtime_ns, str(path), path))
    if not candidates:
        raise FileNotFoundError(f"no {SAFETY_STATE_FILENAME} found under {root}")
    return max(candidates)[2]


def format_status(state: BatchState, *, now: datetime) -> str:
    """Render the stable, non-sensitive one-line operator status."""

    started = _parse_timestamp(state.started_at)
    if now.utcoffset() is None:
        raise ValueError("status time must include an offset")
    elapsed_at = (
        now
        if state.status is BatchStatus.RUNNING
        else _parse_timestamp(state.updated_at)
    )
    elapsed_seconds = (elapsed_at - started).total_seconds()
    if elapsed_seconds < 0:
        raise ValueError("status clock precedes batch start")
    elapsed_minutes = elapsed_seconds / 60
    stop_reason = state.stop_reason.value if state.stop_reason is not None else "-"
    return (
        f"run={state.run_id} tool={state.tool} "
        f"calls={state.counters.calls_started}/{state.limits.max_calls} "
        f"active={state.counters.active_calls}/{state.limits.max_concurrency} "
        f"retries={state.counters.retries}/{state.limits.max_retries} "
        f"elapsed={elapsed_minutes:.1f}m/{state.limits.max_minutes}m "
        f"state={state.status.value} stop_reason={stop_reason}"
    )


def preflight(
    *,
    tool: str,
    run_id: str,
    run_dir: str | os.PathLike[str],
    env: Mapping[str, str] | None = None,
    clock: Clock = _utc_now,
    stop_path: str | os.PathLike[str] = STOP_GENERATION_PATH,
    output: Output = _print_line,
) -> BatchState:
    """Validate mandatory limits, initialize one run, and print its status."""

    limits = BatchLimits.from_env(env)
    manager = GenerationManager(
        run_id=run_id,
        tool=tool,
        run_dir=run_dir,
        limits=limits,
        stop_path=stop_path,
        clock=clock,
    )
    state = manager.initialize()
    output(format_status(state, now=_now(clock)))
    return state


def status(
    run_dir: str | os.PathLike[str] | None = None,
    *,
    search_root: str | os.PathLike[str] = DEFAULT_RUN_ROOT,
    clock: Clock = _utc_now,
    output: Output = _print_line,
) -> BatchState:
    """Print one explicit run, or the latest state beneath ``content/run``."""

    state_path = _resolve_state_path(run_dir, search_root=search_root)
    state = _read_state(state_path)
    output(format_status(state, now=_now(clock)))
    return state


def _validate_interval(interval: float) -> float:
    if isinstance(interval, bool) or not isinstance(interval, (int, float)):
        raise ValueError("watch interval must be a positive finite number")
    converted = float(interval)
    if not math.isfinite(converted) or converted <= 0:
        raise ValueError("watch interval must be a positive finite number")
    return converted


def watch(
    run_dir: str | os.PathLike[str],
    *,
    interval: float = DEFAULT_WATCH_INTERVAL_SECONDS,
    sleep: Sleeper = time.sleep,
    clock: Clock = _utc_now,
    output: Output = _print_line,
) -> BatchState:
    """Print immediately, at each cadence, and once when the run is terminal."""

    cadence = _validate_interval(interval)
    state_path = _resolve_state_path(run_dir, search_root=DEFAULT_RUN_ROOT)
    while True:
        state = _read_state(state_path)
        output(format_status(state, now=_now(clock)))
        if state.status is not BatchStatus.RUNNING:
            return state
        sleep(cadence)


def _sync_directory(path: Path) -> None:
    if sys.platform == "win32":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_final_state(state_path: Path, artifact_dir: Path) -> None:
    if not artifact_dir.exists():
        return
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ValueError(f"artifact directory is unsafe: {artifact_dir}")

    destination = artifact_dir / SAFETY_STATE_FILENAME
    payload = state_path.read_bytes()
    if destination.exists():
        if destination.is_file() and not destination.is_symlink():
            if destination.read_bytes() == payload:
                return
        raise ValueError(f"artifact state already exists: {destination}")

    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=artifact_dir,
            prefix=f".{SAFETY_STATE_FILENAME}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        temporary = None
        _sync_directory(artifact_dir)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def finish(
    run_dir: str | os.PathLike[str],
    *,
    result: str,
    artifact_dir: str | os.PathLike[str] | None = None,
    clock: Clock = _utc_now,
    stop_path: str | os.PathLike[str] = STOP_GENERATION_PATH,
    output: Output = _print_line,
) -> BatchState:
    """Finalize a RUNNING run without ever changing a stopped run."""

    if result not in {"completed", "failed"}:
        raise ValueError("result must be completed or failed")

    state_path = _resolve_state_path(run_dir, search_root=DEFAULT_RUN_ROOT)
    state = _read_state(state_path)
    desired = BatchStatus.COMPLETED if result == "completed" else BatchStatus.FAILED
    if state.status is BatchStatus.RUNNING:
        manager = GenerationManager.attach(
            state_path.parent,
            stop_path=stop_path,
            clock=clock,
        )
        state = (
            manager.mark_completed()
            if desired is BatchStatus.COMPLETED
            else manager.mark_failed()
        )
    elif state.status is BatchStatus.STOPPED:
        pass
    elif state.status is not desired:
        raise ValueError(
            f"cannot change terminal batch state {state.status.value} to {desired.value}"
        )

    if artifact_dir is not None:
        _copy_final_state(state_path, Path(artifact_dir))
    output(format_status(state, now=_now(clock)))
    return state


def stop(
    *,
    stop_path: str | os.PathLike[str] = STOP_GENERATION_PATH,
    output: Output = _print_line,
) -> Path:
    """Atomically and idempotently create the global generation stop file."""

    path = Path(stop_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
        descriptor = -1
        _sync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    output(f"stop_file={path}")
    return path


def resume(
    *,
    stop_path: str | os.PathLike[str] = STOP_GENERATION_PATH,
    output: Output = _print_line,
) -> Path:
    """Idempotently remove only the global stop file."""

    path = Path(stop_path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    else:
        _sync_directory(path.parent)
    output(f"stop_file_removed={path}")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and control generation batch safety."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--tool", required=True)
    preflight_parser.add_argument("--run-id", required=True)
    preflight_parser.add_argument("--run-dir", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--run-dir")

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--run-dir", required=True)
    watch_parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_WATCH_INTERVAL_SECONDS,
    )

    finish_parser = subparsers.add_parser("finish")
    finish_parser.add_argument("--run-dir", required=True)
    finish_parser.add_argument("--result", choices=("completed", "failed"), required=True)
    finish_parser.add_argument("--artifact-dir")

    subparsers.add_parser("stop")
    subparsers.add_parser("resume")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "preflight":
            preflight(tool=args.tool, run_id=args.run_id, run_dir=args.run_dir)
        elif args.command == "status":
            status(args.run_dir)
        elif args.command == "watch":
            watch(args.run_dir, interval=args.interval)
        elif args.command == "finish":
            state = finish(
                args.run_dir,
                result=args.result,
                artifact_dir=args.artifact_dir,
            )
            if state.status is BatchStatus.STOPPED:
                return STOPPED_EXIT_STATUS
        elif args.command == "stop":
            stop()
        elif args.command == "resume":
            resume()
        else:
            parser.error(f"unknown command: {args.command}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
