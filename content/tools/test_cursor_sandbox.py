# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the host OCI sandbox adapter.

Every test injects a fake command runner. No Docker or Podman runtime, no
network, no Cursor key, and no model call is required. The fake runner records
the exact command and environment it was handed and simulates the worker by
writing a ``result.json`` into the mounted request directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cursor_sandbox  # noqa: E402
from pgrep.ai import model_backend  # type: ignore[import-not-found]  # noqa: E402


def _request(model_id: str = "gpt-5.6-sol-max") -> model_backend.ModelRequest:
    return model_backend.ModelRequest(
        request_id="req-1",
        role="generator",
        model=model_backend.ModelSpec(
            family="sol",
            model_id=model_id,
            reasoning_effort="high",
        ),
        system="Return JSON.",
        user="CORPUS CONTEXT: x",
        prompt_version="shadow-problem-v1",
        schema_version="pgrep-shadow-problem/v1",
        seed=7,
        corpus_chunk_ids=("chunk-1",),
        source_refs=("OpenStax, p. 1",),
    )


def _finished_body(model_id: str = "gpt-5.6-sol-max") -> dict[str, object]:
    return {
        "status": "finished",
        "model_id": model_id,
        "text": '{"ok": true}',
        "agent_id": "agent-1",
        "run_id": "run-1",
        "requested_model_id": model_id,
        "error_kind": None,
    }


def _mounts(command: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for index, arg in enumerate(command):
        if arg in ("-v", "--volume") and index + 1 < len(command):
            source, _, dest = command[index + 1].rpartition(":")
            pairs.append((source, dest))
    return pairs


class FakeRunner:
    """Records commands/environments and simulates the worker's file output."""

    def __init__(
        self,
        *,
        result_body: dict[str, object] | None = None,
        raw_result: str | None = None,
        returncode: int = 0,
        write_result: bool = True,
        raise_timeout: bool = False,
        stderr: str = "",
    ) -> None:
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self.requests: list[dict[str, object]] = []
        self._result_body = result_body
        self._raw_result = raw_result
        self._returncode = returncode
        self._write_result = write_result
        self._raise_timeout = raise_timeout
        self._stderr = stderr

    def run(self, command, *, env, timeout, cwd=None):  # noqa: ANN001
        self.commands.append(list(command))
        self.envs.append(dict(env))
        work = None
        for source, dest in _mounts(list(command)):
            if dest == "/work":
                work = Path(source)
        if work is not None:
            request_file = work / "request.json"
            if request_file.exists():
                self.requests.append(json.loads(request_file.read_text()))
        if self._raise_timeout:
            raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)
        if self._write_result and work is not None:
            target = work / "result.json"
            if self._raw_result is not None:
                target.write_text(self._raw_result, encoding="utf-8")
            else:
                target.write_text(
                    json.dumps(self._result_body or {}), encoding="utf-8"
                )
        return cursor_sandbox.CommandResult(
            returncode=self._returncode, stdout="", stderr=self._stderr
        )


def _sandbox(runner: FakeRunner, *, debug_retain: bool = False) -> object:
    return cursor_sandbox.CursorSandbox(
        cursor_sandbox.SandboxConfig(
            runtime="docker",
            image="pgrep-shadow-worker:test",
            debug_retain=debug_retain,
        ),
        runner=runner,
        api_key="secret",
    )


def test_missing_runtime_fails_before_request() -> None:
    with pytest.raises(RuntimeError, match="Docker or Podman"):
        cursor_sandbox.detect_runtime(which=lambda _: None)


def test_detect_runtime_prefers_docker_then_podman() -> None:
    assert (
        cursor_sandbox.detect_runtime(
            which=lambda name: "/usr/bin/docker" if name == "docker" else None
        )
        == "docker"
    )
    assert (
        cursor_sandbox.detect_runtime(
            which=lambda name: "/usr/bin/podman" if name == "podman" else None
        )
        == "podman"
    )


def test_prompt_mounts_only_request_directory(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    sandbox = _sandbox(runner)
    sandbox.complete(_request(), parent=tmp_path)
    command = runner.commands[-1]
    assert command[:3] == ["docker", "run", "--rm"]
    mounts = _mounts(command)
    assert len(mounts) == 1
    source, dest = mounts[0]
    assert dest == "/work"
    assert Path(source).parent == tmp_path
    assert "/var/run/docker.sock" not in " ".join(command)
    assert "secret" not in " ".join(command)


def test_api_key_is_forwarded_by_environment_not_arguments(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    command = runner.commands[-1]
    assert "--env" in command
    assert command[command.index("--env") + 1] == "CURSOR_API_KEY"
    assert "secret" not in " ".join(command)
    assert runner.envs[-1]["CURSOR_API_KEY"] == "secret"


def test_request_json_holds_only_worker_protocol_fields(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    payload = runner.requests[-1]
    assert set(payload) == {"action", "model_id", "prompt"}
    assert payload["action"] == "prompt"
    assert payload["model_id"] == "gpt-5.6-sol-max"
    assert "secret" not in json.dumps(payload)


def test_subprocess_environment_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_LEAK", "leak-value")
    monkeypatch.setenv("PATH", "/usr/bin")
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    env = runner.envs[-1]
    assert env["CURSOR_API_KEY"] == "secret"
    assert env.get("PATH") == "/usr/bin"
    assert "SECRET_LEAK" not in env


def test_complete_returns_validated_result(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    result = _sandbox(runner).complete(_request(), parent=tmp_path)
    assert isinstance(result, model_backend.ModelResult)
    assert result.request_id == "req-1"
    assert result.model_id == "gpt-5.6-sol-max"
    assert result.status == "finished"
    assert result.text == '{"ok": true}'
    assert result.agent_id == "agent-1"
    assert result.run_id == "run-1"


def test_request_directory_is_cleaned_on_success(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_request_directory_is_cleaned_on_failure(tmp_path: Path) -> None:
    runner = FakeRunner(returncode=1, write_result=False, stderr="boom")
    with pytest.raises(cursor_sandbox.SandboxProcessError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_debug_retain_keeps_directory_under_content_run(tmp_path: Path) -> None:
    parent = tmp_path / "content" / "run" / "shadow-foundry"
    parent.mkdir(parents=True)
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner, debug_retain=True).complete(_request(), parent=parent)
    kept = list(parent.iterdir())
    assert len(kept) == 1
    assert (kept[0] / "request.json").exists()


def test_debug_retain_rejects_disallowed_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point the temp root elsewhere so the parent counts as neither OS temp nor
    # content/run.
    fake_temp = tmp_path / "elsewhere-temp"
    fake_temp.mkdir()
    monkeypatch.setattr(cursor_sandbox.tempfile, "gettempdir", lambda: str(fake_temp))
    parent = tmp_path / "not-allowed"
    parent.mkdir()
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.SandboxError, match="content/run"):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=parent)
    assert runner.commands == []


def test_nonzero_exit_without_output_is_process_error(tmp_path: Path) -> None:
    runner = FakeRunner(returncode=2, write_result=False, stderr="crash secret")
    with pytest.raises(cursor_sandbox.SandboxProcessError) as info:
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert "secret" not in str(info.value)


def test_missing_result_is_output_error(tmp_path: Path) -> None:
    runner = FakeRunner(returncode=0, write_result=False)
    with pytest.raises(cursor_sandbox.SandboxOutputError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_malformed_result_is_output_error(tmp_path: Path) -> None:
    runner = FakeRunner(raw_result="{ not json")
    with pytest.raises(cursor_sandbox.SandboxOutputError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_worker_declared_failure_raises_and_redacts(tmp_path: Path) -> None:
    body = _finished_body()
    body["status"] = "error"
    body["error_kind"] = "run"
    body["text"] = "boom api_key=secret"
    runner = FakeRunner(result_body=body)
    with pytest.raises(cursor_sandbox.WorkerFailure) as info:
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert "secret" not in str(info.value)


def test_model_mismatch_is_distinguished(tmp_path: Path) -> None:
    body = _finished_body(model_id="different-model")
    body["status"] = "error"
    body["error_kind"] = "model_identity"
    body["requested_model_id"] = "gpt-5.6-sol-max"
    runner = FakeRunner(result_body=body)
    with pytest.raises(cursor_sandbox.ModelMismatchError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_finished_but_wrong_model_is_mismatch(tmp_path: Path) -> None:
    body = _finished_body(model_id="sneaky-substitute")
    runner = FakeRunner(result_body=body)
    with pytest.raises(cursor_sandbox.ModelMismatchError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_timeout_is_distinguished_and_cleans(tmp_path: Path) -> None:
    runner = FakeRunner(raise_timeout=True)
    with pytest.raises(cursor_sandbox.SandboxTimeout):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_private_marker_in_parent_rejected_before_subprocess(tmp_path: Path) -> None:
    parent = tmp_path / "gr9677"
    parent.mkdir()
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.LeakageError):
        _sandbox(runner).complete(_request(), parent=parent)
    assert runner.commands == []


def test_symlink_entry_in_request_directory_rejected(tmp_path: Path) -> None:
    request_dir = tmp_path / "req"
    request_dir.mkdir()
    (request_dir / "request.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (request_dir / "link.json").symlink_to(outside)
    with pytest.raises(cursor_sandbox.RequestDirectoryError, match="symlink"):
        cursor_sandbox._ensure_isolated_request_dir(request_dir, tmp_path)


def test_hard_link_in_request_directory_rejected(tmp_path: Path) -> None:
    request_dir = tmp_path / "req"
    request_dir.mkdir()
    original = request_dir / "request.json"
    original.write_text("{}", encoding="utf-8")
    os.link(original, request_dir / "hard.json")
    with pytest.raises(cursor_sandbox.RequestDirectoryError, match="hard link"):
        cursor_sandbox._ensure_isolated_request_dir(request_dir, tmp_path)


def test_symlinked_request_directory_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(cursor_sandbox.RequestDirectoryError):
        cursor_sandbox._ensure_isolated_request_dir(link, tmp_path)


def test_list_models_returns_catalog(tmp_path: Path) -> None:
    body = {
        "status": "finished",
        "models": [
            {"id": "claude-opus-4-8-thinking-high-fast"},
            {"id": "cursor-grok-4.5-high-fast"},
            {"id": "gpt-5.6-sol-max"},
        ],
        "text": "",
        "agent_id": "",
        "run_id": "",
        "model_id": "",
        "error_kind": None,
    }
    runner = FakeRunner(result_body=body)
    models = _sandbox(runner).list_models(parent=tmp_path)
    assert [m["id"] for m in models] == [
        "claude-opus-4-8-thinking-high-fast",
        "cursor-grok-4.5-high-fast",
        "gpt-5.6-sol-max",
    ]
    assert runner.requests[-1] == {"action": "models"}


def test_list_models_startup_failure_raises(tmp_path: Path) -> None:
    body = {
        "status": "startup_error",
        "models": [],
        "text": "authentication failed secret",
        "error_kind": "startup",
    }
    runner = FakeRunner(result_body=body)
    with pytest.raises(cursor_sandbox.WorkerFailure) as info:
        _sandbox(runner).list_models(parent=tmp_path)
    assert "secret" not in str(info.value)


def test_build_image_constructs_build_command(tmp_path: Path) -> None:
    context = tmp_path / "shadow_worker"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    runner = FakeRunner()
    sandbox = _sandbox(runner)
    sandbox.build_image(context=context)
    command = runner.commands[-1]
    assert command[:2] == ["docker", "build"]
    assert "-t" in command
    assert command[command.index("-t") + 1] == "pgrep-shadow-worker:test"
    assert str(context) in command


def test_build_image_failure_raises_image_build_error(tmp_path: Path) -> None:
    context = tmp_path / "shadow_worker"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    runner = FakeRunner(returncode=1, stderr="build failed secret")
    with pytest.raises(cursor_sandbox.ImageBuildError) as info:
        _sandbox(runner).build_image(context=context)
    assert "secret" not in str(info.value)


def test_build_image_missing_dockerfile_raises(tmp_path: Path) -> None:
    context = tmp_path / "empty"
    context.mkdir()
    runner = FakeRunner()
    with pytest.raises(cursor_sandbox.ImageBuildError):
        _sandbox(runner).build_image(context=context)
    assert runner.commands == []


def test_default_worker_context_has_pinned_dockerfile() -> None:
    context = cursor_sandbox._default_worker_context()
    dockerfile = (context / "Dockerfile").read_text(encoding="utf-8")
    assert "ENTRYPOINT" in dockerfile
    assert "@sha256:" in dockerfile
