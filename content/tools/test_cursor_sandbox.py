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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cursor_sandbox  # noqa: E402
from pgrep.ai import model_backend  # type: ignore[import-not-found]  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_ROOT = REPO_ROOT / "tools" / "shadow_worker"


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
        raw_result: str | bytes | None = None,
        returncode: int = 0,
        write_result: bool = True,
        raise_timeout: bool = False,
        raise_interrupt: bool = False,
        poison_result: str | None = None,
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
        self._raise_interrupt = raise_interrupt
        self._poison_result = poison_result
        self._stderr = stderr

    def run(self, command, *, env, timeout, cwd=None):  # noqa: ANN001
        self.commands.append(list(command))
        self.envs.append(dict(env))
        action = command[1] if len(command) > 1 else ""
        work = None
        for source, dest in _mounts(list(command)):
            if dest == "/work":
                work = Path(source)
        if work is not None:
            request_file = work / "request.json"
            if request_file.exists():
                self.requests.append(json.loads(request_file.read_text()))
        if action == "run" and self._raise_timeout:
            raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)
        if action == "run" and self._raise_interrupt:
            raise KeyboardInterrupt
        if action == "run" and self._write_result and work is not None:
            target = work / "result.json"
            if self._poison_result == "request-symlink":
                outside_dir = work.parent / "outside-request"
                outside_dir.mkdir()
                (outside_dir / "result.json").write_text(
                    json.dumps(self._result_body or {}), encoding="utf-8"
                )
                shutil.rmtree(work)
                work.symlink_to(outside_dir, target_is_directory=True)
            elif self._poison_result in ("symlink", "hardlink"):
                outside = work.parent / "outside-result.json"
                outside.write_text(
                    json.dumps(self._result_body or {}), encoding="utf-8"
                )
                if self._poison_result == "symlink":
                    target.symlink_to(outside)
                else:
                    os.link(outside, target)
            elif self._poison_result == "directory":
                target.mkdir()
            elif self._raw_result is not None:
                if isinstance(self._raw_result, bytes):
                    target.write_bytes(self._raw_result)
                else:
                    target.write_text(self._raw_result, encoding="utf-8")
            else:
                target.write_text(json.dumps(self._result_body or {}), encoding="utf-8")
        return cursor_sandbox.CommandResult(
            returncode=self._returncode, stdout="", stderr=self._stderr
        )


def _sandbox(
    runner: FakeRunner,
    *,
    debug_retain: bool = False,
    network: str = "bridge",
    api_key: str = "secret",
) -> cursor_sandbox.CursorSandbox:
    config_kwargs: dict[str, object] = {
        "runtime": "docker",
        "image": "pgrep-shadow-worker:test",
        "debug_retain": debug_retain,
    }
    if network != "bridge":
        config_kwargs["network"] = network
    return cursor_sandbox.CursorSandbox(
        cursor_sandbox.SandboxConfig(**config_kwargs),
        runner=runner,
        api_key=api_key,
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


def test_run_uses_named_container_and_option_terminator(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    command = runner.commands[-1]
    name = command[command.index("--name") + 1]
    source = Path(_mounts(command)[0][0])
    assert name == cursor_sandbox._container_name(source)
    assert not name.startswith("-")
    assert command[command.index("--") + 1] == "pgrep-shadow-worker:test"


def test_container_names_are_deterministic_and_unique(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    sandbox = _sandbox(runner)
    sandbox.complete(_request(), parent=tmp_path)
    sandbox.complete(_request(), parent=tmp_path)
    run_commands = [command for command in runner.commands if command[1] == "run"]
    names = [command[command.index("--name") + 1] for command in run_commands]
    sources = [Path(_mounts(command)[0][0]) for command in run_commands]
    assert names == [cursor_sandbox._container_name(source) for source in sources]
    assert len(set(names)) == 2


def test_api_key_is_forwarded_by_environment_not_arguments(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    command = runner.commands[-1]
    assert "--env" in command
    assert command[command.index("--env") + 1] == "CURSOR_API_KEY"
    assert "secret" not in " ".join(command)
    assert runner.envs[-1]["CURSOR_API_KEY"] == "secret"


def test_missing_api_key_fails_before_runtime_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.SandboxError, match="CURSOR_API_KEY"):
        _sandbox(runner, api_key="").complete(_request(), parent=tmp_path)
    assert runner.commands == []


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


def test_run_network_allows_egress_without_host_network_or_sensitive_mounts(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    command = runner.commands[-1]
    assert command[command.index("--network") + 1] == "bridge"
    assert len(_mounts(command)) == 1
    mount_source, mount_dest = _mounts(command)[0]
    assert mount_dest == "/work"
    assert Path(mount_source).parent == tmp_path
    joined = " ".join(command)
    assert "/var/run/docker.sock" not in joined
    assert str(Path.home()) not in joined
    assert str(REPO_ROOT) not in joined


def test_default_network_uses_runtime_default_egress(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner, network="default").complete(_request(), parent=tmp_path)
    command = runner.commands[-1]
    assert "--network" not in command


@pytest.mark.parametrize("network", ["host", "none"])
def test_network_rejects_host_and_none(network: str) -> None:
    with pytest.raises(ValueError, match="network"):
        cursor_sandbox.SandboxConfig(
            runtime="docker",
            image="pgrep-shadow-worker:test",
            network=network,
        )


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


def test_non_utf8_result_is_output_error(tmp_path: Path) -> None:
    runner = FakeRunner(raw_result=b"\xff\xfe")
    with pytest.raises(cursor_sandbox.SandboxOutputError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_worker_declared_failure_raises_and_redacts(tmp_path: Path) -> None:
    body = _finished_body()
    body["status"] = "error"
    body["error_kind"] = "run"
    body["text"] = "boom api_key=secret"
    runner = FakeRunner(result_body=body, returncode=2)
    with pytest.raises(cursor_sandbox.WorkerFailure) as info:
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert "secret" not in str(info.value)


def test_nonzero_exit_with_finished_result_is_process_error(tmp_path: Path) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        returncode=2,
        stderr="unexpected worker exit",
    )
    with pytest.raises(cursor_sandbox.SandboxProcessError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


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


def test_timeout_force_removes_named_container_and_cleans(tmp_path: Path) -> None:
    runner = FakeRunner(raise_timeout=True)
    with pytest.raises(cursor_sandbox.SandboxTimeout):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    run_command, cleanup_command = runner.commands
    name = run_command[run_command.index("--name") + 1]
    assert cleanup_command == ["docker", "rm", "-f", "--", name]
    assert "CURSOR_API_KEY" in runner.envs[0]
    assert "CURSOR_API_KEY" not in runner.envs[1]
    assert list(tmp_path.iterdir()) == []


def test_interrupt_force_removes_named_container(tmp_path: Path) -> None:
    runner = FakeRunner(raise_interrupt=True)
    with pytest.raises(KeyboardInterrupt):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    run_command, cleanup_command = runner.commands
    name = run_command[run_command.index("--name") + 1]
    assert cleanup_command == ["docker", "rm", "-f", "--", name]
    assert "CURSOR_API_KEY" not in runner.envs[1]


def test_killed_cli_force_removes_named_container(tmp_path: Path) -> None:
    runner = FakeRunner(returncode=-9, write_result=False)
    with pytest.raises(cursor_sandbox.SandboxProcessError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    run_command, cleanup_command = runner.commands
    name = run_command[run_command.index("--name") + 1]
    assert cleanup_command == ["docker", "rm", "-f", "--", name]


def test_private_marker_in_parent_rejected_before_subprocess(tmp_path: Path) -> None:
    parent = tmp_path / "gr9677"
    parent.mkdir()
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.LeakageError):
        _sandbox(runner).complete(_request(), parent=parent)
    assert runner.commands == []


def test_symlink_parent_rejected_before_subprocess(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.RequestDirectoryError, match="parent"):
        _sandbox(runner).complete(_request(), parent=linked_parent)
    assert runner.commands == []


def test_resolved_parent_private_marker_rejected_before_subprocess(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "gr9677"
    resolved_parent = private_root / "requests"
    resolved_parent.mkdir(parents=True)
    alias = tmp_path / "public-alias"
    alias.symlink_to(private_root, target_is_directory=True)
    lexical_parent = alias / "requests"
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.LeakageError):
        _sandbox(runner).complete(_request(), parent=lexical_parent)
    assert runner.commands == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_complete_rejects_poisoned_request_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    real_mkdtemp = cursor_sandbox.tempfile.mkdtemp
    outside = tmp_path / f"outside-{kind}.json"
    outside.write_text("{}", encoding="utf-8")

    def poisoned_mkdtemp(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        request_dir = Path(real_mkdtemp(*args, **kwargs))
        poison = request_dir / "poison.json"
        if kind == "symlink":
            poison.symlink_to(outside)
        else:
            os.link(outside, poison)
        return str(request_dir)

    monkeypatch.setattr(cursor_sandbox.tempfile, "mkdtemp", poisoned_mkdtemp)
    runner = FakeRunner(result_body=_finished_body())
    expected = "symlink" if kind == "symlink" else "hard link"
    with pytest.raises(cursor_sandbox.RequestDirectoryError, match=expected):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert runner.commands == []


@pytest.mark.parametrize(
    "kind",
    ["symlink", "hardlink", "request-symlink", "directory"],
)
def test_complete_revalidates_poisoned_result_after_run(
    tmp_path: Path,
    kind: str,
) -> None:
    runner = FakeRunner(result_body=_finished_body(), poison_result=kind)
    with pytest.raises(cursor_sandbox.RequestDirectoryError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert any(command[1] == "run" for command in runner.commands)


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_complete_safe_open_rejects_result_swapped_after_postcheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    original_check = cursor_sandbox._ensure_isolated_request_dir
    checks = 0
    outside = tmp_path / f"race-{kind}.json"
    outside.write_text(json.dumps(_finished_body()), encoding="utf-8")

    def check_then_swap(request_dir: Path, parent: Path) -> None:
        nonlocal checks
        original_check(request_dir, parent)
        checks += 1
        if checks == 3:
            result = request_dir / "result.json"
            result.unlink()
            if kind == "symlink":
                result.symlink_to(outside)
            else:
                os.link(outside, result)

    monkeypatch.setattr(
        cursor_sandbox,
        "_ensure_isolated_request_dir",
        check_then_swap,
    )
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.RequestDirectoryError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert checks == 3


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
    del tmp_path
    runner = FakeRunner()
    sandbox = _sandbox(runner)
    sandbox.build_image(context=WORKER_ROOT)
    command = runner.commands[-1]
    assert command[:2] == ["docker", "build"]
    assert "-t" in command
    assert command[command.index("-t") + 1] == "pgrep-shadow-worker:test"
    assert command[-2:] == ["--", str(WORKER_ROOT.resolve())]


def test_build_image_does_not_require_or_receive_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "ambient-secret")
    runner = FakeRunner()
    _sandbox(runner, api_key="").build_image(context=WORKER_ROOT)
    assert "CURSOR_API_KEY" not in runner.envs[-1]


def test_build_image_failure_raises_image_build_error() -> None:
    runner = FakeRunner(returncode=1, stderr="build failed secret")
    with pytest.raises(cursor_sandbox.ImageBuildError) as info:
        _sandbox(runner).build_image(context=WORKER_ROOT)
    assert "secret" not in str(info.value)


def test_build_image_rejects_non_worker_context(tmp_path: Path) -> None:
    context = tmp_path / "other-context"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    runner = FakeRunner()
    with pytest.raises(cursor_sandbox.ImageBuildError, match="exact"):
        _sandbox(runner).build_image(context=context)
    assert runner.commands == []


def test_build_image_rejects_flag_like_context() -> None:
    runner = FakeRunner()
    with pytest.raises(cursor_sandbox.ImageBuildError, match="begin"):
        _sandbox(runner).build_image(context="-malicious")
    assert runner.commands == []


def test_config_rejects_flag_like_image() -> None:
    with pytest.raises(ValueError, match="begin"):
        cursor_sandbox.SandboxConfig(
            runtime="docker",
            image="--privileged",
        )


def test_complete_rejects_flag_like_container_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cursor_sandbox,
        "_container_name",
        lambda _request_dir: "--escape",
        raising=False,
    )
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.SandboxError, match="container"):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert runner.commands == []


def test_default_worker_context_has_pinned_dockerfile() -> None:
    context = cursor_sandbox._default_worker_context()
    dockerfile = (context / "Dockerfile").read_text(encoding="utf-8")
    assert "ENTRYPOINT" in dockerfile
    assert "@sha256:" in dockerfile


def test_worker_context_cannot_be_rebased_by_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attacker_context = tmp_path / "tools" / "shadow_worker"
    attacker_context.mkdir(parents=True)
    (attacker_context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert cursor_sandbox._default_worker_context().resolve() == WORKER_ROOT.resolve()
