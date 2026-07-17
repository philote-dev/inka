# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the generation batch operator surface."""

from __future__ import annotations

import json
import multiprocessing
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import batch_manager  # noqa: E402
from pgrep.ai.batch_safety import (  # type: ignore[import-not-found]  # noqa: E402
    SAFETY_STATE_FILENAME,
    BatchLimits,
    BatchState,
    BatchStatus,
    BatchStopped,
    BatchStopReason,
    GenerationManager,
)


LIMIT_ENV = {
    "PGREP_BATCH_MAX_CALLS": "12",
    "PGREP_BATCH_MAX_CONCURRENCY": "3",
    "PGREP_BATCH_MAX_RETRIES": "2",
    "PGREP_BATCH_MAX_MINUTES": "15",
}
START = datetime(2026, 7, 16, 22, 55, tzinfo=timezone.utc)


@dataclass
class _Clock:
    current: datetime = START

    def __call__(self) -> datetime:
        return self.current


def _manager(
    run_dir: Path,
    *,
    run_id: str = "run-operator-1",
    tool: str = "shadow-foundry",
    clock: _Clock | None = None,
    stop_path: Path | None = None,
) -> GenerationManager:
    return GenerationManager(
        run_id=run_id,
        tool=tool,
        run_dir=run_dir,
        limits=BatchLimits.from_env(LIMIT_ENV),
        stop_path=stop_path or run_dir.parent / "STOP_GENERATION",
        clock=clock or _Clock(),
    )


def _state(run_dir: Path) -> BatchState:
    return BatchState.from_dict(
        json.loads((run_dir / SAFETY_STATE_FILENAME).read_text(encoding="utf-8"))
    )


def _reserve_then_crash(run_dir: str) -> None:
    path = Path(run_dir)
    manager = GenerationManager(
        run_id="run-operator-1",
        tool="shadow-foundry",
        run_dir=path,
        limits=BatchLimits.from_env(LIMIT_ENV),
        stop_path=path.parent / "STOP_GENERATION",
    )
    manager.before_call("crashed-operation", 0)
    os._exit(0)


def _recipe(justfile: str, name: str) -> str:
    lines = justfile.splitlines()
    for index, line in enumerate(lines):
        prefix = line.split(":", 1)[0]
        if not line.startswith((" ", "\t")) and prefix.split(" ", 1)[0] == name:
            body: list[str] = []
            for candidate in lines[index + 1 :]:
                if candidate and not candidate.startswith((" ", "\t")):
                    break
                body.append(candidate)
            return "\n".join(body)
    raise AssertionError(f"recipe not found: {name}")


def _just_env(tmp_path: Path, *, limits: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PGREP_BATCH_SAFETY_ENV_FILE"] = str(
        tmp_path / "isolated-batch-safety.env"
    )
    for variable in LIMIT_ENV:
        env.pop(variable, None)
    if limits:
        env.update(LIMIT_ENV)
    return env


def _run_just(
    args: list[str],
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["just", "ninja=true", *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _failed_foundry_run(output: str) -> Path:
    matches = re.findall(
        r"run=([^ ]+) tool=foundry .* state=FAILED stop_reason=-",
        output,
    )
    assert matches, output
    return (
        REPO_ROOT
        / "content"
        / "run"
        / ".batch-safety"
        / "foundry"
        / matches[-1]
    )


def _protected_recipe_sandbox(tmp_path: Path, *, tool_status: int) -> Path:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    recipe = (
        "[private]\n"
        "[unix]\n"
        "[positional-arguments]\n"
        "_generation-protected tool *args:\n"
        f"{_recipe(justfile, '_generation-protected')}\n"
    )
    (tmp_path / "justfile").write_text(recipe, encoding="utf-8")

    python = tmp_path / "out" / "pyenv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        f"""#!/usr/bin/env python3
import signal
import sys
import time

args = sys.argv[1:]
if args and args[0].endswith("batch_manager.py"):
    command = args[1]
    if command == "preflight":
        print("PREFLIGHT_OK", flush=True)
    elif command == "watch":
        signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
        while True:
            time.sleep(1)
    elif command == "finish":
        print("FINISH_FAILED", file=sys.stderr, flush=True)
        sys.exit(7)
    elif command == "status":
        print("TERMINAL_STATUS", flush=True)
else:
    sys.exit({tool_status})
""",
        encoding="utf-8",
    )
    python.chmod(0o700)
    return tmp_path / "justfile"


def test_preflight_requires_all_positive_limits_before_creating_state(
    tmp_path: Path,
) -> None:
    invalid_environments = [
        {
            key: value
            for key, value in LIMIT_ENV.items()
            if key != "PGREP_BATCH_MAX_CALLS"
        },
        {**LIMIT_ENV, "PGREP_BATCH_MAX_CALLS": "0"},
        {**LIMIT_ENV, "PGREP_BATCH_MAX_CONCURRENCY": "-1"},
        {**LIMIT_ENV, "PGREP_BATCH_MAX_RETRIES": "1.5"},
        {**LIMIT_ENV, "PGREP_BATCH_MAX_MINUTES": "unbounded"},
    ]

    for index, env in enumerate(invalid_environments):
        run_dir = tmp_path / f"invalid-{index}"
        with pytest.raises(ValueError, match="PGREP_BATCH_"):
            batch_manager.preflight(
                tool="shadow-foundry",
                run_id="run-invalid",
                run_dir=run_dir,
                env=env,
                clock=_Clock(),
                stop_path=tmp_path / "STOP_GENERATION",
                output=lambda _line: None,
            )
        assert not run_dir.exists()


def test_preflight_initializes_and_prints_stable_initial_status(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "safety"
    lines: list[str] = []

    state = batch_manager.preflight(
        tool="shadow-foundry",
        run_id="run-operator-1",
        run_dir=run_dir,
        env=LIMIT_ENV,
        clock=_Clock(),
        stop_path=tmp_path / "STOP_GENERATION",
        output=lines.append,
    )

    assert state.status is BatchStatus.RUNNING
    assert lines == [
        "run=run-operator-1 tool=shadow-foundry calls=0/12 active=0/3 "
        "retries=0/2 elapsed=0.0m/15m state=RUNNING stop_reason=-"
    ]
    serialized = (run_dir / SAFETY_STATE_FILENAME).read_text(encoding="utf-8")
    for private_name in (
        "prompt",
        "response",
        "model",
        "source",
        "credential",
        "api_key",
    ):
        assert private_name not in serialized.lower()


def test_status_uses_explicit_run_or_latest_state_under_content_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "content" / "run"
    clock = _Clock()
    old = _manager(root / "old", run_id="run-old", clock=clock)
    old.initialize()
    clock.current += timedelta(minutes=2)
    new = _manager(root / "new", run_id="run-new", clock=clock)
    new.initialize()
    os.utime(old.state_path, ns=(1, 1))
    os.utime(new.state_path, ns=(2, 2))

    latest_lines: list[str] = []
    latest = batch_manager.status(
        search_root=root,
        clock=clock,
        output=latest_lines.append,
    )
    explicit_lines: list[str] = []
    explicit = batch_manager.status(
        old.run_dir,
        search_root=root,
        clock=clock,
        output=explicit_lines.append,
    )

    assert latest.run_id == "run-new"
    assert latest_lines == [
        "run=run-new tool=shadow-foundry calls=0/12 active=0/3 "
        "retries=0/2 elapsed=0.0m/15m state=RUNNING stop_reason=-"
    ]
    assert explicit.run_id == "run-old"
    assert explicit_lines == [
        "run=run-old tool=shadow-foundry calls=0/12 active=0/3 "
        "retries=0/2 elapsed=2.0m/15m state=RUNNING stop_reason=-"
    ]


def test_status_freezes_terminal_elapsed_but_running_uses_current_time(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    completed_manager = _manager(tmp_path / "completed-elapsed", clock=clock)
    completed_manager.initialize()
    clock.current += timedelta(minutes=2)
    completed = completed_manager.mark_completed()

    running_manager = _manager(
        tmp_path / "running-elapsed",
        run_id="run-running-elapsed",
        clock=clock,
    )
    running = running_manager.initialize()
    much_later = START + timedelta(minutes=30)

    assert "elapsed=2.0m/15m" in batch_manager.format_status(
        completed,
        now=much_later,
    )
    assert "elapsed=28.0m/15m" in batch_manager.format_status(
        running,
        now=much_later,
    )


def test_watch_prints_initial_cadence_and_terminal_state_once(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    manager = _manager(tmp_path / "watch", clock=clock)
    manager.initialize()
    sleeps: list[float] = []
    lines: list[str] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.current += timedelta(seconds=seconds)
        if len(sleeps) == 2:
            manager.mark_completed()

    terminal = batch_manager.watch(
        manager.run_dir,
        interval=30.0,
        sleep=sleep,
        clock=clock,
        output=lines.append,
    )

    assert terminal.status is BatchStatus.COMPLETED
    assert sleeps == [30.0, 30.0]
    assert [line.split(" state=", 1)[1].split(" ", 1)[0] for line in lines] == [
        "RUNNING",
        "RUNNING",
        "COMPLETED",
    ]
    assert ["0.0m/15m", "0.5m/15m", "1.0m/15m"] == [
        line.split(" elapsed=", 1)[1].split(" state=", 1)[0]
        for line in lines
    ]
    assert sum("state=COMPLETED" in line for line in lines) == 1


def test_watch_rejects_nonpositive_or_nonfinite_interval(tmp_path: Path) -> None:
    manager = _manager(tmp_path / "watch")
    manager.initialize()

    for interval in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="interval"):
            batch_manager.watch(
                manager.run_dir,
                interval=interval,
                sleep=lambda _seconds: None,
                output=lambda _line: None,
            )


def test_stop_and_resume_are_atomic_idempotent_and_secret_free(
    tmp_path: Path,
) -> None:
    stop_path = tmp_path / "content" / "run" / "STOP_GENERATION"
    lines: list[str] = []

    assert batch_manager.stop(stop_path=stop_path, output=lines.append) == stop_path
    first_stat = stop_path.stat()
    assert stop_path.read_bytes() == b""
    assert batch_manager.stop(stop_path=stop_path, output=lines.append) == stop_path
    assert stop_path.stat().st_ino == first_stat.st_ino
    assert lines == [f"stop_file={stop_path}", f"stop_file={stop_path}"]

    assert batch_manager.resume(stop_path=stop_path, output=lines.append) == stop_path
    assert not stop_path.exists()
    assert batch_manager.resume(stop_path=stop_path, output=lines.append) == stop_path
    assert not stop_path.exists()
    assert lines[-2:] == [
        f"stop_file_removed={stop_path}",
        f"stop_file_removed={stop_path}",
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="symlink semantics are Unix-only")
def test_stop_and_resume_preserve_then_remove_dangling_stop_symlink(
    tmp_path: Path,
) -> None:
    stop_path = tmp_path / "content" / "run" / "STOP_GENERATION"
    stop_path.parent.mkdir(parents=True)
    target = tmp_path / "missing-stop-target"
    stop_path.symlink_to(target)
    assert os.path.lexists(stop_path)
    assert not stop_path.exists()
    lines: list[str] = []

    batch_manager.stop(stop_path=stop_path, output=lines.append)

    assert stop_path.is_symlink()
    assert Path(os.readlink(stop_path)) == target
    assert lines == [f"stop_file={stop_path}"]

    batch_manager.resume(stop_path=stop_path, output=lines.append)

    assert not os.path.lexists(stop_path)
    assert lines[-1] == f"stop_file_removed={stop_path}"


def test_resume_and_finish_never_resume_a_stopped_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "stopped"
    stop_path = tmp_path / "STOP_GENERATION"
    manager = _manager(run_dir, stop_path=stop_path)
    manager.initialize()
    stop_path.touch()
    with pytest.raises(BatchStopped) as raised:
        manager.before_call("operation-1", 0)
    assert raised.value.reason is BatchStopReason.KILL_SWITCH
    stopped = manager.state_path.read_bytes()

    batch_manager.resume(stop_path=stop_path, output=lambda _line: None)
    lines: list[str] = []
    state = batch_manager.finish(
        run_dir,
        result="completed",
        stop_path=stop_path,
        clock=_Clock(START + timedelta(minutes=1)),
        output=lines.append,
    )

    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.KILL_SWITCH
    assert manager.state_path.read_bytes() == stopped
    assert "state=STOPPED stop_reason=KILL_SWITCH" in lines[0]
    with pytest.raises(BatchStopped):
        GenerationManager.attach(run_dir, stop_path=stop_path)


def test_cli_finish_returns_nonzero_for_stopped_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "stopped-cli"
    stop_path = tmp_path / "STOP_GENERATION"
    manager = _manager(run_dir, stop_path=stop_path)
    manager.initialize()
    stop_path.touch()
    with pytest.raises(BatchStopped):
        manager.before_call("operation-1", 0)

    exit_code = batch_manager.main(
        ["finish", "--run-dir", str(run_dir), "--result", "completed"]
    )

    assert exit_code != 0
    assert _state(run_dir).status is BatchStatus.STOPPED
    assert "state=STOPPED" in capsys.readouterr().out


def test_cli_finish_after_worker_crash_persists_stopped_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = multiprocessing.get_context("spawn")
    run_dir = tmp_path / "crashed-cli"
    manager = _manager(run_dir, clock=_Clock(datetime.now(timezone.utc)))
    manager.initialize()
    worker = context.Process(target=_reserve_then_crash, args=(str(run_dir),))
    worker.start()
    worker.join(15)
    assert not worker.is_alive()
    assert worker.exitcode == 0
    assert _state(run_dir).status is BatchStatus.RUNNING

    exit_code = batch_manager.main(
        ["finish", "--run-dir", str(run_dir), "--result", "completed"]
    )

    assert exit_code != 0
    state = _state(run_dir)
    assert state.status is BatchStatus.STOPPED
    assert state.stop_reason is BatchStopReason.STATE_IO
    assert "STATE_IO" in capsys.readouterr().err


def test_finish_completed_copies_only_final_state_after_publication(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    manager = _manager(tmp_path / "sidecar", clock=clock)
    manager.initialize()
    unpublished = tmp_path / "artifact"

    state = batch_manager.finish(
        manager.run_dir,
        result="completed",
        artifact_dir=unpublished,
        clock=clock,
        stop_path=manager.stop_path,
        output=lambda _line: None,
    )
    assert state.status is BatchStatus.COMPLETED
    assert not unpublished.exists()

    unpublished.mkdir()
    (unpublished / "_SUCCESS").write_text("ok\n", encoding="utf-8")
    lines: list[str] = []
    repeated = batch_manager.finish(
        manager.run_dir,
        result="completed",
        artifact_dir=unpublished,
        clock=clock,
        stop_path=manager.stop_path,
        output=lines.append,
    )

    assert repeated == state
    assert {path.name for path in unpublished.iterdir()} == {
        "_SUCCESS",
        SAFETY_STATE_FILENAME,
    }
    assert (unpublished / SAFETY_STATE_FILENAME).read_bytes() == (
        manager.state_path.read_bytes()
    )
    assert manager.lock_path.is_file()
    assert (manager.run_dir / ".safety-active").is_dir()
    assert lines and "state=COMPLETED stop_reason=-" in lines[0]


def test_finish_failed_is_terminal_without_stop_reason_or_success_marker(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    manager = _manager(tmp_path / "failed", clock=clock)
    manager.initialize()
    artifact = tmp_path / "failed-artifact"
    artifact.mkdir()
    (artifact / "_FAILED").write_text("failed\n", encoding="utf-8")

    state = batch_manager.finish(
        manager.run_dir,
        result="failed",
        artifact_dir=artifact,
        clock=clock,
        stop_path=manager.stop_path,
        output=lambda _line: None,
    )

    assert state.status is BatchStatus.FAILED
    assert state.stop_reason is None
    assert _state(manager.run_dir) == state
    assert not (artifact / "_SUCCESS").exists()
    assert (artifact / "_FAILED").read_text(encoding="utf-8") == "failed\n"
    assert (artifact / SAFETY_STATE_FILENAME).is_file()
    with pytest.raises(BatchStopped):
        GenerationManager.attach(manager.run_dir, stop_path=manager.stop_path)


def test_cli_preflight_refuses_missing_limits_without_creating_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for variable in LIMIT_ENV:
        monkeypatch.delenv(variable, raising=False)
    run_dir = tmp_path / "run"

    exit_code = batch_manager.main(
        [
            "preflight",
            "--tool",
            "shadow-foundry",
            "--run-id",
            "run-cli",
            "--run-dir",
            str(run_dir),
        ]
    )

    assert exit_code == 2
    assert "PGREP_BATCH_MAX_CALLS is required" in capsys.readouterr().err
    assert not run_dir.exists()


def test_justfile_exposes_operator_recipes_and_scopes_protection() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")

    assert "generation-status *args:" in justfile
    assert "generation-stop:" in justfile
    assert "generation-resume:" in justfile
    assert "content/tools/batch_manager.py status" in _recipe(
        justfile, "generation-status"
    )
    assert "content/tools/batch_manager.py stop" in _recipe(
        justfile, "generation-stop"
    )
    assert "content/tools/batch_manager.py resume" in _recipe(
        justfile, "generation-resume"
    )

    protected = {
        "shadow-foundry": "shadow-foundry",
        "foundry": "foundry",
        "gen-decompositions": "generate-decompositions",
        "audit-bundle-ai": "audit-bundle-ai",
    }
    for recipe, tool in protected.items():
        assert f"just _generation-protected {tool}" in _recipe(justfile, recipe)

    helper = _recipe(justfile, "_generation-protected")
    assert (
        'safety_env_file="${PGREP_BATCH_SAFETY_ENV_FILE:-'
        'content/run/batch-safety.env}"'
    ) in helper
    assert '. "$safety_env_file"' in helper
    assert "date -u +%Y%m%dT%H%M%SZ" in helper
    assert "PGREP_BATCH_RUN_DIR" in helper
    assert "batch_manager.py preflight" in helper
    assert "batch_manager.py watch" in helper
    assert "batch_manager.py finish" in helper
    assert helper.index("batch_manager.py preflight") < helper.index(
        '"${command[@]}"'
    )
    for variable in LIMIT_ENV:
        assert variable not in helper

    unprotected = (
        "foundry-dry",
        "shadow-smoke",
        "shadow-models",
        "shadow-worker-build",
        "calibration-ruler",
        "eval-verifier",
        "dev",
    )
    for recipe in unprotected:
        body = _recipe(justfile, recipe)
        assert "_generation-protected" not in body
        assert "PGREP_BATCH_RUN_DIR" not in body


def test_foundry_offline_paths_and_other_offline_recipes_are_unchanged() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    foundry = _recipe(justfile, "foundry")

    assert "--dry-run|--self-check" in foundry
    assert 'out/pyenv/bin/python content/tools/foundry.py "$@"' in foundry
    assert "just _generation-protected foundry" in foundry
    assert _recipe(justfile, "foundry-dry").strip().endswith(
        "out/pyenv/bin/python content/tools/foundry.py --self-check {{ args }}"
    )
    assert _recipe(justfile, "shadow-smoke").strip().endswith(
        "out/pyenv/bin/python content/tools/shadow_foundry.py --self-check"
    )
    assert _recipe(justfile, "shadow-models").strip().endswith(
        "out/pyenv/bin/python content/tools/shadow_foundry.py --probe-models {{ args }}"
    )


def test_recipe_sidecars_do_not_precreate_atomic_publication_directories() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    helper = _recipe(justfile, "_generation-protected")

    assert 'content/run/.batch-safety/shadow-foundry/${run_id}' in helper
    assert 'content/run/shadow-foundry/${run_id}' in helper
    assert 'content/run/.batch-safety/foundry/${run_id}' in helper
    assert '${output_root}/.runs/${run_id}' in helper
    assert (
        'shadow_foundry.py --shadow "$@" --run "$run_id"' in helper
    ), "operator run ID must override any caller-supplied --run"
    assert 'mkdir -p "$artifact_dir"' not in helper
    assert "decompositions.json" not in helper
    assert "audit_report.json" not in helper


@pytest.mark.parametrize(
    ("recipe", "argument_name"),
    [
        ("foundry", "--topic"),
        ("gen-decompositions", "--ids"),
        ("audit-bundle-ai", "--ids"),
        ("shadow-foundry", "--topic"),
    ],
)
def test_protected_recipes_do_not_evaluate_literal_arguments_before_preflight(
    tmp_path: Path,
    recipe: str,
    argument_name: str,
) -> None:
    sentinel = tmp_path / f"{recipe}-must-not-exist"
    literal = f"literal$(touch {sentinel})"

    result = _run_just(
        [recipe, argument_name, literal],
        env=_just_env(tmp_path, limits=False),
    )

    assert result.returncode == 2
    assert "PGREP_BATCH_MAX_CALLS is required" in result.stderr
    assert not sentinel.exists()


def test_generation_status_forwards_literal_run_directory_without_evaluation(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "status-must-not-exist"
    literal = f"missing$(touch {sentinel})"

    result = _run_just(
        ["generation-status", "--run-dir", literal],
        env=_just_env(tmp_path, limits=False),
    )

    assert result.returncode == 2
    assert "batch state not found" in result.stderr
    assert not sentinel.exists()


def test_offline_foundry_preserves_arguments_with_spaces_without_protection(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "offline output with spaces"
    topic = "classical mechanics with spaces"

    result = _run_just(
        [
            "foundry",
            "--dry-run",
            "--topic",
            topic,
            "--out",
            str(output_root),
            "--run",
            "offline-boundaries",
            "--n",
            "3",
        ],
        env=_just_env(tmp_path, limits=False),
    )

    assert result.returncode == 0, result.stderr
    run_dir = output_root / "offline-boundaries"
    assert (run_dir / "_SUCCESS").is_file()
    candidates: list[dict[str, object]] = []
    for name in ("accepted.json", "rejected.json", "escalated.json"):
        candidates.extend(json.loads((run_dir / name).read_text(encoding="utf-8")))
    assert candidates
    assert {candidate["topic"] for candidate in candidates} == {topic}
    assert "PGREP_BATCH_MAX_CALLS is required" not in result.stderr


def test_deterministic_audit_recipe_bypasses_generation_limits_offline(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle with spaces.json"
    output = tmp_path / "audit output with spaces"
    bundle.write_text(json.dumps({"problems": []}), encoding="utf-8")

    result = _run_just(
        [
            "audit-bundle-ai",
            "--only",
            "decomposition_leak",
            "citation",
            "--bundle",
            str(bundle),
            "--out",
            str(output),
            "--index",
            str(tmp_path / "missing corpus.db"),
        ],
        env=_just_env(tmp_path, limits=False),
    )

    assert result.returncode == 0, result.stderr
    assert (output / "audit_report.json").is_file()
    assert (output / "audit_summary.md").is_file()
    assert not list(output.rglob(SAFETY_STATE_FILENAME))
    assert "PGREP_BATCH_MAX_CALLS is required" not in result.stderr


def test_llm_audit_recipe_refuses_before_tool_without_generation_limits(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle.json"
    output = tmp_path / "audit"
    bundle.write_text(json.dumps({"problems": []}), encoding="utf-8")

    result = _run_just(
        [
            "audit-bundle-ai",
            "--only",
            "answer_key",
            "--bundle",
            str(bundle),
            "--out",
            str(output),
        ],
        env=_just_env(tmp_path, limits=False),
    )

    assert result.returncode == 2
    assert "PGREP_BATCH_MAX_CALLS is required" in result.stderr
    assert not (output / "audit_report.json").exists()


def test_audit_recipe_rejects_internal_classifier_argument(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.json"
    output = tmp_path / "audit"
    bundle.write_text(json.dumps({"problems": []}), encoding="utf-8")

    result = _run_just(
        [
            "audit-bundle-ai",
            "--classify-safety",
            "--only",
            "decomposition_leak",
            "citation",
            "--bundle",
            str(bundle),
            "--out",
            str(output),
        ],
        env=_just_env(tmp_path, limits=False),
    )

    assert result.returncode == 2
    assert "classify-safety" in result.stderr
    assert not (output / "audit_report.json").exists()
    assert not (output / "audit_summary.md").exists()


def test_protected_recipe_loads_explicit_safety_env_override(
    tmp_path: Path,
) -> None:
    safety_env = tmp_path / "limits with spaces.env"
    safety_env.write_text(
        "".join(f"{key}={value}\n" for key, value in LIMIT_ENV.items()),
        encoding="utf-8",
    )
    env = _just_env(tmp_path, limits=False)
    env["PGREP_BATCH_SAFETY_ENV_FILE"] = str(safety_env)

    result = _run_just(
        [
            "foundry",
            "--topic",
            "offline override proof",
            "--out",
            str(tmp_path / "foundry output"),
        ],
        env=env,
    )

    assert result.returncode == 2
    assert "online generation is not available yet" in result.stderr
    assert "PGREP_BATCH_MAX_CALLS is required" not in result.stderr


def test_protected_foundry_preserves_exit_and_records_failed_state(
    tmp_path: Path,
) -> None:
    result = _run_just(
        [
            "foundry",
            "--topic",
            "future online topic with spaces",
            "--out",
            str(tmp_path / "future output with spaces"),
        ],
        env=_just_env(tmp_path, limits=True),
    )

    assert result.returncode == 2
    assert "online generation is not available yet" in result.stderr
    run_dir = _failed_foundry_run(result.stdout + result.stderr)
    state = _state(run_dir)
    assert state.status is BatchStatus.FAILED
    assert state.stop_reason is None


@pytest.mark.parametrize(
    ("tool_status", "expected_status"),
    [(0, 7), (9, 9)],
)
def test_protected_recipe_exit_requires_successful_safety_finalization(
    tmp_path: Path,
    tool_status: int,
    expected_status: int,
) -> None:
    justfile = _protected_recipe_sandbox(tmp_path, tool_status=tool_status)

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(justfile),
            "_generation-protected",
            "audit-bundle-ai",
        ],
        cwd=tmp_path,
        env=_just_env(tmp_path, limits=True),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == expected_status
    assert "FINISH_FAILED" in result.stderr
    assert "TERMINAL_STATUS" in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="protected recipes are Unix-only")
def test_protected_recipe_reaps_its_watcher_process_group(tmp_path: Path) -> None:
    process = subprocess.Popen(
        [
            "just",
            "ninja=true",
            "foundry",
            "--topic",
            "watcher cleanup",
            "--out",
            str(tmp_path / "watcher output"),
        ],
        cwd=REPO_ROOT,
        env=_just_env(tmp_path, limits=True),
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        pytest.fail(f"protected recipe hung\nstdout:\n{stdout}\nstderr:\n{stderr}")

    assert process.returncode == 2
    _failed_foundry_run(stdout + stderr)
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        pass
    else:
        os.killpg(process.pid, signal.SIGTERM)
        pytest.fail(f"protected recipe leaked process group {process.pid}")


def test_all_changed_variadic_recipes_use_positional_argument_forwarding() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    recipes = (
        "generation-status",
        "_generation-protected",
        "gen-decompositions",
        "audit-bundle-ai",
        "foundry",
        "shadow-foundry",
    )

    for recipe in recipes:
        assert f"[positional-arguments]\n{recipe}" in justfile
        body = _recipe(justfile, recipe)
        assert "{{ args }}" not in body
        assert '"$@"' in body
