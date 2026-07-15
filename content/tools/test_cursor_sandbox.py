# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the host Docker sandbox adapter.

Every test injects a fake command runner. No Docker daemon, network, Cursor
key, or model call is required. The fake runner records the exact command and
environment it was handed and simulates the worker by writing a
``result.json`` into the mounted request directory.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cursor_sandbox  # noqa: E402
from pgrep.ai import model_backend  # type: ignore[import-not-found]  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_ROOT = REPO_ROOT / "tools" / "shadow_worker"
IMAGE_DIGEST = "sha256:" + ("a" * 64)
_TEST_ENDPOINT = None


@pytest.fixture(autouse=True)
def _verified_local_runtime(monkeypatch: pytest.MonkeyPatch):
    """Give adapter tests a real local Unix socket and fake command runner."""
    global _TEST_ENDPOINT
    if not hasattr(cursor_sandbox, "LocalRuntime"):
        yield
        return

    runtime_root = Path(tempfile.mkdtemp(prefix="cs-", dir="/tmp"))
    socket_path = runtime_root / "docker.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    original_candidates = cursor_sandbox._local_socket_candidates

    def local_candidates(runtime, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if args or kwargs:
            return original_candidates(runtime, *args, **kwargs)
        return (socket_path,)

    monkeypatch.setattr(
        cursor_sandbox,
        "_local_socket_candidates",
        local_candidates,
    )
    _TEST_ENDPOINT = cursor_sandbox.discover_local_runtime(
        "docker",
        which=lambda _runtime: sys.executable,
        socket_candidates=lambda _runtime: (socket_path,),
    )
    try:
        yield
    finally:
        _TEST_ENDPOINT = None
        listener.close()
        socket_path.unlink(missing_ok=True)
        shutil.rmtree(runtime_root)


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

    def __init__(  # noqa: PLR0913
        self,
        *,
        result_body: dict[str, object] | None = None,
        raw_result: str | bytes | None = None,
        returncode: int = 0,
        write_result: bool = True,
        raise_timeout: bool = False,
        raise_interrupt: bool = False,
        poison_result: str | None = None,
        probe_mode: str = "success",
        probe_modes: list[str] | None = None,
        probe_returncode: int = 0,
        image_digests: list[str] | None = None,
        cleanup_rm_returncode: int = 0,
        cleanup_rm_exception: bool = False,
        cleanup_inspect: str = "absent",
        cleanup_inspects: list[str] | None = None,
        output_mutator: Callable[[Path], None] | None = None,
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
        self._probe_modes = probe_modes or [probe_mode]
        self._probe_mode_index = 0
        self._probe_returncode = probe_returncode
        self._image_digests = image_digests or [IMAGE_DIGEST]
        self._image_digest_index = 0
        self._cleanup_rm_returncode = cleanup_rm_returncode
        self._cleanup_rm_exception = cleanup_rm_exception
        self._cleanup_inspects = cleanup_inspects or [cleanup_inspect]
        self._cleanup_inspect_index = 0
        self._output_mutator = output_mutator
        self._stderr = stderr

    def run(self, command, *, env, timeout, cwd=None):  # noqa: ANN001
        self.commands.append(list(command))
        self.envs.append(dict(env))
        action = command[1] if len(command) > 1 else ""
        if action == "image" and command[2] == "inspect":
            index = min(self._image_digest_index, len(self._image_digests) - 1)
            digest = self._image_digests[index]
            self._image_digest_index += 1
            return cursor_sandbox.CommandResult(0, stdout=digest + "\n")
        if action == "rm":
            if self._cleanup_rm_exception:
                raise OSError("remove failed")
            return cursor_sandbox.CommandResult(
                self._cleanup_rm_returncode,
                stderr="remove failed" if self._cleanup_rm_returncode else "",
            )
        if action == "container" and command[2] == "inspect":
            index = min(
                self._cleanup_inspect_index,
                len(self._cleanup_inspects) - 1,
            )
            cleanup_inspect = self._cleanup_inspects[index]
            self._cleanup_inspect_index += 1
            if cleanup_inspect == "absent":
                return cursor_sandbox.CommandResult(
                    1,
                    stderr=f"Error: No such object: {command[-1]}",
                )
            if cleanup_inspect == "present":
                return cursor_sandbox.CommandResult(0, stdout="container-id\n")
            if cleanup_inspect == "ambiguous":
                return cursor_sandbox.CommandResult(
                    1,
                    stdout="container-id\n",
                    stderr=f"Error: No such object: {command[-1]}",
                )
            if cleanup_inspect == "exception":
                raise OSError("inspect failed")
            return cursor_sandbox.CommandResult(
                1,
                stderr="Cannot connect to the container endpoint",
            )

        work = None
        for source, dest in _mounts(list(command)):
            if dest == "/work":
                work = Path(source)
        is_probe = action == "run" and "--entrypoint" in command
        if is_probe:
            index = min(self._probe_mode_index, len(self._probe_modes) - 1)
            probe_mode = self._probe_modes[index]
            self._probe_mode_index += 1
            if self._probe_returncode:
                return cursor_sandbox.CommandResult(
                    self._probe_returncode,
                    stderr="probe failed",
                )
            if work is not None and probe_mode == "request-symlink":
                outside_dir = work.parent / "probe-outside"
                outside_dir.mkdir()
                (outside_dir / ".mount-probe-input").write_bytes(b"outside-input")
                (outside_dir / ".mount-probe-output").write_bytes(b"outside-output")
                shutil.rmtree(work)
                work.symlink_to(outside_dir, target_is_directory=True)
                return cursor_sandbox.CommandResult(0)
            if work is not None and probe_mode != "missing":
                nonce = (work / ".mount-probe-input").read_bytes()
                if probe_mode == "wrong":
                    nonce = b"wrong-nonce"
                (work / ".mount-probe-output").write_bytes(nonce)
            return cursor_sandbox.CommandResult(0)

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
            if self._output_mutator is not None:
                self._output_mutator(work)
        return cursor_sandbox.CommandResult(
            returncode=self._returncode, stdout="", stderr=self._stderr
        )


def _sandbox(
    runner: FakeRunner,
    *,
    debug_retain: bool = False,
    network: str = "bridge",
    api_key: str = "secret",
    endpoint_resolver=None,  # noqa: ANN001
) -> cursor_sandbox.CursorSandbox:
    config_kwargs: dict[str, object] = {
        "runtime": "docker",
        "image": "pgrep-shadow-worker:test",
        "debug_retain": debug_retain,
    }
    if network != "bridge":
        config_kwargs["network"] = network
    sandbox_kwargs: dict[str, object] = {"runner": runner, "api_key": api_key}
    resolver = endpoint_resolver
    if resolver is None and _TEST_ENDPOINT is not None:

        def resolve_test_endpoint(_runtime: str):
            return _TEST_ENDPOINT

        resolver = resolve_test_endpoint
    if resolver is not None:
        sandbox_kwargs["endpoint_resolver"] = resolver
    return cursor_sandbox.CursorSandbox(
        cursor_sandbox.SandboxConfig(**config_kwargs),
        **sandbox_kwargs,
    )


def _action_commands(runner: FakeRunner, action: str) -> list[list[str]]:
    return [
        command
        for command in runner.commands
        if len(command) > 1 and command[1] == action
    ]


def _probe_commands(runner: FakeRunner) -> list[list[str]]:
    return [
        command
        for command in _action_commands(runner, "run")
        if "--entrypoint" in command
    ]


def _worker_commands(runner: FakeRunner) -> list[list[str]]:
    return [
        command
        for command in _action_commands(runner, "run")
        if "--entrypoint" not in command
    ]


def _env_for(runner: FakeRunner, command: list[str]) -> dict[str, str]:
    return runner.envs[runner.commands.index(command)]


def test_missing_runtime_fails_before_request() -> None:
    with pytest.raises(RuntimeError, match="Docker"):
        cursor_sandbox.detect_runtime(which=lambda _: None)


def test_detect_runtime_checks_only_docker() -> None:
    checked: list[str] = []

    def which(name: str) -> str | None:
        checked.append(name)
        return "/usr/bin/docker" if name == "docker" else "/usr/bin/other"

    assert cursor_sandbox.detect_runtime(which=which) == "docker"
    assert checked == ["docker"]


def test_config_rejects_non_docker_runtime() -> None:
    with pytest.raises(ValueError, match="Docker"):
        cursor_sandbox.SandboxConfig(
            runtime="other-runtime",
            image="pgrep-shadow-worker:test",
        )


@pytest.mark.parametrize(
    "candidate",
    [
        "ssh://host/run/docker.sock",
        "tcp://127.0.0.1:2375",
        "npipe:////./pipe/docker_engine",
        "unix:///tmp/remote-docker.sock",
    ],
)
def test_discovery_rejects_remote_endpoint_candidates(candidate: str) -> None:
    with pytest.raises(cursor_sandbox.RuntimeEndpointError):
        cursor_sandbox.discover_local_runtime(
            "docker",
            which=lambda _runtime: sys.executable,
            socket_candidates=lambda _runtime: (candidate,),
        )


def test_docker_desktop_user_socket_is_an_allowed_local_candidate(
    tmp_path: Path,
) -> None:
    candidates = cursor_sandbox._local_socket_candidates(
        "docker",
        platform="darwin",
        uid=os.getuid(),
        home=tmp_path,
    )
    assert tmp_path / ".docker" / "run" / "docker.sock" in candidates


def test_prompt_mounts_only_request_directory(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    sandbox = _sandbox(runner)
    sandbox.complete(_request(), parent=tmp_path)
    command = _worker_commands(runner)[-1]
    assert command[1:3] == ["run", "--rm"]
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
    command = _worker_commands(runner)[-1]
    name = command[command.index("--name") + 1]
    source = Path(_mounts(command)[0][0])
    assert name == cursor_sandbox._container_name(source)
    assert not name.startswith("-")
    assert command[command.index("--") + 1] == IMAGE_DIGEST


def test_container_names_are_deterministic_and_unique(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    sandbox = _sandbox(runner)
    sandbox.complete(_request(), parent=tmp_path)
    sandbox.complete(_request(), parent=tmp_path)
    run_commands = _worker_commands(runner)
    names = [command[command.index("--name") + 1] for command in run_commands]
    sources = [Path(_mounts(command)[0][0]) for command in run_commands]
    assert names == [cursor_sandbox._container_name(source) for source in sources]
    assert len(set(names)) == 2


def test_api_key_is_forwarded_by_environment_not_arguments(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    command = _worker_commands(runner)[-1]
    assert "--env" in command
    assert command[command.index("--env") + 1] == "CURSOR_API_KEY"
    assert "secret" not in " ".join(command)
    assert _env_for(runner, command)["CURSOR_API_KEY"] == "secret"


def test_missing_api_key_fails_before_runtime_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.SandboxError, match="CURSOR_API_KEY"):
        _sandbox(runner, api_key="").complete(_request(), parent=tmp_path)
    assert len(_probe_commands(runner)) == 1
    assert _worker_commands(runner) == []
    assert all("CURSOR_API_KEY" not in env for env in runner.envs)


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
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote-context")
    monkeypatch.setenv("CONTAINER_HOST", "tcp://remote:1234")
    monkeypatch.setenv("HOME", "/host/home")
    monkeypatch.setenv("DOCKER_CONFIG", "/host/docker-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/host/xdg-config")
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    command = _worker_commands(runner)[-1]
    env = _env_for(runner, command)
    assert env["CURSOR_API_KEY"] == "secret"
    assert env["DOCKER_HOST"].startswith("unix://")
    assert set(env) == {"CURSOR_API_KEY", "DOCKER_HOST"}


def test_mount_probe_is_keyless_two_way_and_precedes_worker(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    probe = _probe_commands(runner)
    worker = _worker_commands(runner)
    assert len(probe) == 1
    assert len(worker) == 1
    assert runner.commands.index(probe[0]) < runner.commands.index(worker[0])
    assert probe[0][probe[0].index("--entrypoint") + 1] == "/bin/sh"
    assert probe[0][probe[0].index("--network") + 1] == "none"
    assert probe[0][probe[0].index("--user") + 1] == (f"{os.getuid()}:{os.getgid()}")
    assert len(_mounts(probe[0])) == 1
    assert "CURSOR_API_KEY" not in _env_for(runner, probe[0])
    assert _env_for(runner, worker[0])["CURSOR_API_KEY"] == "secret"


@pytest.mark.parametrize("mode", ["wrong", "missing"])
def test_mount_probe_rejects_wrong_or_missing_nonce(
    tmp_path: Path,
    mode: str,
) -> None:
    runner = FakeRunner(result_body=_finished_body(), probe_mode=mode)
    with pytest.raises(cursor_sandbox.MountProbeError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert len(_probe_commands(runner)) == 1
    assert _worker_commands(runner) == []


def test_mount_probe_rejects_process_failure(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body(), probe_returncode=7)
    with pytest.raises(cursor_sandbox.MountProbeError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert _worker_commands(runner) == []


def test_mount_probe_cleanup_never_follows_replaced_request_path(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        probe_mode="request-symlink",
    )
    with pytest.raises(cursor_sandbox.SandboxError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    outside = tmp_path / "probe-outside"
    assert (outside / ".mount-probe-input").read_bytes() == b"outside-input"
    assert (outside / ".mount-probe-output").read_bytes() == b"outside-output"


def test_each_request_directory_runs_its_own_mount_probe(tmp_path: Path) -> None:
    first_parent = tmp_path / "first"
    second_parent = tmp_path / "second"
    first_parent.mkdir()
    second_parent.mkdir()
    runner = FakeRunner(result_body=_finished_body())
    sandbox = _sandbox(runner)
    sandbox.complete(_request(), parent=first_parent)
    sandbox.complete(_request(), parent=second_parent)
    probes = _probe_commands(runner)
    assert len(probes) == 2
    assert Path(_mounts(probes[0])[0][0]).parent == first_parent
    assert Path(_mounts(probes[1])[0][0]).parent == second_parent


def test_prior_mount_proof_cannot_bypass_later_failure(tmp_path: Path) -> None:
    first_parent = tmp_path / "first"
    second_parent = tmp_path / "second"
    first_parent.mkdir()
    second_parent.mkdir()
    runner = FakeRunner(
        result_body=_finished_body(),
        probe_modes=["success", "wrong"],
    )
    sandbox = _sandbox(runner)
    sandbox.complete(_request(), parent=first_parent)
    with pytest.raises(cursor_sandbox.MountProbeError):
        sandbox.complete(_request(), parent=second_parent)
    assert len(_probe_commands(runner)) == 2
    assert len(_worker_commands(runner)) == 1


def test_worker_runs_as_host_uid_and_gid(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    worker = _worker_commands(runner)[-1]
    assert worker[worker.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"


def test_probe_and_worker_use_portable_docker_hardening(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    for command in (*_probe_commands(runner), *_worker_commands(runner)):
        assert "--read-only" in command
        assert command[command.index("--cap-drop") + 1] == "ALL"
        assert command[command.index("--security-opt") + 1] == "no-new-privileges=true"
        assert command[command.index("--pids-limit") + 1] == "128"
        assert command[command.index("--memory") + 1] == "1g"
        assert command[command.index("--cpus") + 1] == "2"
        assert command[command.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,size=64m"
        assert command[command.index("--user") + 1] == (f"{os.getuid()}:{os.getgid()}")
        assert "--privileged" not in command
        assert command[command.index("--network") + 1] != "host"
        assert len(_mounts(command)) == 1
        assert "/var/run/docker.sock" not in " ".join(command)


def test_run_network_allows_egress_without_host_network_or_sensitive_mounts(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    command = _worker_commands(runner)[-1]
    assert command[command.index("--network") + 1] == "bridge"
    assert len(_mounts(command)) == 1
    mount_source, mount_dest = _mounts(command)[0]
    assert mount_dest == "/work"
    assert Path(mount_source).parent == tmp_path
    joined = " ".join(command)
    assert "/var/run/docker.sock" not in joined
    assert Path(mount_source).resolve() not in {
        Path.home().resolve(),
        REPO_ROOT.resolve(),
        tmp_path.resolve(),
    }


def test_default_network_uses_runtime_default_egress(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner, network="default").complete(_request(), parent=tmp_path)
    command = _worker_commands(runner)[-1]
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


def test_request_cleanup_error_is_not_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove(_path: Path) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(cursor_sandbox, "_rmtree", fail_remove, raising=False)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.RequestCleanupError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_request_cleanup_wraps_non_os_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove(_path: Path) -> None:
        raise RuntimeError("unexpected cleanup failure")

    monkeypatch.setattr(cursor_sandbox, "_rmtree", fail_remove)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.RequestCleanupError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_request_cleanup_verifies_path_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cursor_sandbox, "_rmtree", lambda _path: None, raising=False)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.RequestCleanupError, match="still exists"):
        _sandbox(runner).complete(_request(), parent=tmp_path)


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


def test_debug_retain_rejects_unrelated_content_run_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_temp = tmp_path / "different-temp"
    fake_temp.mkdir()
    monkeypatch.setattr(cursor_sandbox.tempfile, "gettempdir", lambda: str(fake_temp))
    parent = tmp_path / "unrelated" / "content" / "run" / "shadow"
    parent.mkdir(parents=True)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.SandboxError, match="retention"):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=parent)
    assert runner.commands == []


def test_debug_retain_allows_exact_repo_content_run_root() -> None:
    allowed = REPO_ROOT / "content" / "run" / "shadow-foundry"
    assert cursor_sandbox._retain_location_ok(allowed)


def test_debug_retain_refuses_poisoned_path_escape(tmp_path: Path) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        poison_result="request-symlink",
    )
    with pytest.raises(cursor_sandbox.RequestRetentionError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not any(path.is_symlink() for path in tmp_path.iterdir())


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_debug_retain_removes_link_poison(
    tmp_path: Path,
    kind: str,
) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        poison_result=kind,
    )
    with pytest.raises(cursor_sandbox.RequestRetentionError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_removes_special_file_poison(tmp_path: Path) -> None:
    def add_fifo(work: Path) -> None:
        os.mkfifo(work / "special.fifo")

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_fifo,
    )
    with pytest.raises(cursor_sandbox.RequestRetentionError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_removes_oversized_file_poison(tmp_path: Path) -> None:
    def add_oversized_file(work: Path) -> None:
        with (work / "oversized.bin").open("wb") as output:
            output.truncate(cursor_sandbox.MAX_FILE_BYTES + 1)

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_oversized_file,
    )
    with pytest.raises(cursor_sandbox.RequestRetentionError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_removes_deep_tree_poison(tmp_path: Path) -> None:
    def add_deep_tree(work: Path) -> None:
        current = work
        for index in range(cursor_sandbox.MAX_REQUEST_DEPTH + 1):
            current /= f"depth-{index}"
            current.mkdir()

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_deep_tree,
    )
    with pytest.raises(cursor_sandbox.RequestRetentionError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_removes_unreadable_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def add_unreadable_file(work: Path) -> None:
        (work / "unreadable.bin").write_bytes(b"x")

    def reject_unreadable(path: Path, _info) -> None:  # noqa: ANN001
        if path.name == "unreadable.bin":
            raise cursor_sandbox.RequestDirectoryError("unreadable content")

    monkeypatch.setattr(
        cursor_sandbox,
        "_verify_regular_file_readable",
        reject_unreadable,
        raising=False,
    )
    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_unreadable_file,
    )
    with pytest.raises(cursor_sandbox.RequestRetentionError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


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


def test_rejects_too_many_output_entries(tmp_path: Path) -> None:
    def add_entries(work: Path) -> None:
        for index in range(cursor_sandbox.MAX_REQUEST_ENTRIES):
            (work / f"extra-{index}.txt").write_text("", encoding="utf-8")

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_entries,
    )
    with pytest.raises(cursor_sandbox.SandboxLimitError, match="entries"):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_rejects_deep_output_tree(tmp_path: Path) -> None:
    def add_deep_tree(work: Path) -> None:
        current = work
        for index in range(cursor_sandbox.MAX_REQUEST_DEPTH + 1):
            current /= f"depth-{index}"
            current.mkdir()

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_deep_tree,
    )
    with pytest.raises(cursor_sandbox.SandboxLimitError, match="depth"):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_rejects_sparse_oversized_result_before_reading(tmp_path: Path) -> None:
    def enlarge_result(work: Path) -> None:
        with (work / "result.json").open("r+b") as result:
            result.truncate(cursor_sandbox.MAX_RESULT_JSON_BYTES + 1)

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=enlarge_result,
    )
    with pytest.raises(cursor_sandbox.SandboxLimitError, match="result.json"):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_rejects_oversized_auxiliary_file(tmp_path: Path) -> None:
    def add_oversized_file(work: Path) -> None:
        with (work / "oversized.bin").open("wb") as output:
            output.truncate(cursor_sandbox.MAX_FILE_BYTES + 1)

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_oversized_file,
    )
    with pytest.raises(cursor_sandbox.SandboxLimitError, match="file"):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_rejects_excessive_total_output_size(tmp_path: Path) -> None:
    def add_large_files(work: Path) -> None:
        remaining = cursor_sandbox.MAX_TOTAL_BYTES + 1
        index = 0
        while remaining:
            size = min(cursor_sandbox.MAX_FILE_BYTES, remaining)
            with (work / f"large-{index}.bin").open("wb") as output:
                output.truncate(size)
            remaining -= size
            index += 1

    runner = FakeRunner(
        result_body=_finished_body(),
        output_mutator=add_large_files,
    )
    with pytest.raises(cursor_sandbox.SandboxLimitError, match="total"):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_descriptor_relative_open_unsupported_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = cursor_sandbox.os.open

    def unsupported_open(path, flags, mode=0o777, *, dir_fd=None):  # noqa: ANN001
        if dir_fd is not None:
            raise NotImplementedError("dir_fd unsupported")
        return real_open(path, flags, mode)

    monkeypatch.setattr(cursor_sandbox.os, "open", unsupported_open)
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.DescriptorOpenError):
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
    run_command = _worker_commands(runner)[-1]
    name = run_command[run_command.index("--name") + 1]
    cleanup_command = [
        command for command in _action_commands(runner, "rm") if command[-1] == name
    ][-1]
    inspect_command = [
        command
        for command in _action_commands(runner, "container")
        if command[-1] == name
    ][-1]
    assert cleanup_command[1:] == ["rm", "-f", "--", name]
    assert inspect_command[1:3] == ["container", "inspect"]
    assert "CURSOR_API_KEY" in _env_for(runner, run_command)
    assert "CURSOR_API_KEY" not in _env_for(runner, cleanup_command)
    assert "CURSOR_API_KEY" not in _env_for(runner, inspect_command)
    assert list(tmp_path.iterdir()) == []


def test_interrupt_force_removes_named_container(tmp_path: Path) -> None:
    runner = FakeRunner(raise_interrupt=True)
    with pytest.raises(KeyboardInterrupt):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    run_command = _worker_commands(runner)[-1]
    name = run_command[run_command.index("--name") + 1]
    cleanup_command = [
        command for command in _action_commands(runner, "rm") if command[-1] == name
    ][-1]
    assert cleanup_command[1:] == ["rm", "-f", "--", name]
    assert "CURSOR_API_KEY" not in _env_for(runner, cleanup_command)


def test_killed_cli_force_removes_named_container(tmp_path: Path) -> None:
    runner = FakeRunner(returncode=-9, write_result=False)
    with pytest.raises(cursor_sandbox.SandboxProcessError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    run_command = _worker_commands(runner)[-1]
    name = run_command[run_command.index("--name") + 1]
    cleanup_command = [
        command for command in _action_commands(runner, "rm") if command[-1] == name
    ][-1]
    assert cleanup_command[1:] == ["rm", "-f", "--", name]


def test_success_removes_and_proves_worker_container_absent(tmp_path: Path) -> None:
    runner = FakeRunner(result_body=_finished_body())
    _sandbox(runner).complete(_request(), parent=tmp_path)
    worker = _worker_commands(runner)[-1]
    name = worker[worker.index("--name") + 1]
    assert any(command[1:] == ["rm", "-f", "--", name] for command in runner.commands)
    assert any(
        command[1:3] == ["container", "inspect"] and command[-1] == name
        for command in runner.commands
    )


@pytest.mark.parametrize("inspect_state", ["present", "uncertain", "ambiguous"])
def test_cleanup_requires_proof_container_is_absent(
    tmp_path: Path,
    inspect_state: str,
) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        cleanup_inspect=inspect_state,
    )
    with pytest.raises(cursor_sandbox.SecurityCleanupError):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_docker_auto_removal_accepts_rm_nonzero_when_inspect_proves_absence(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        cleanup_rm_returncode=1,
        cleanup_inspect="absent",
    )
    result = _sandbox(runner).complete(_request(), parent=tmp_path)
    assert result.status == "finished"


def test_debug_retain_timeout_removes_request_path(tmp_path: Path) -> None:
    runner = FakeRunner(raise_timeout=True)
    with pytest.raises(cursor_sandbox.SandboxTimeout):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_accepts_verified_docker_auto_removal(tmp_path: Path) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        cleanup_rm_returncode=1,
        cleanup_inspect="absent",
    )
    result = _sandbox(runner, debug_retain=True).complete(
        _request(),
        parent=tmp_path,
    )
    assert result.status == "finished"
    assert len(list(tmp_path.glob("shadow-*"))) == 1


def test_debug_retain_rm_exception_removes_request_path(tmp_path: Path) -> None:
    runner = FakeRunner(
        cleanup_rm_exception=True,
        cleanup_inspect="absent",
    )
    with pytest.raises(cursor_sandbox.SecurityCleanupError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_inspect_exception_removes_request_path(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(cleanup_inspect="exception")
    with pytest.raises(cursor_sandbox.SecurityCleanupError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_present_container_removes_request_path(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(cleanup_inspect="present")
    with pytest.raises(cursor_sandbox.SecurityCleanupError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert not list(tmp_path.glob("shadow-*"))


def test_debug_retain_later_present_container_overrides_prior_absence(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        result_body=_finished_body(),
        cleanup_rm_returncode=1,
        cleanup_inspects=["absent", "present"],
    )
    with pytest.raises(cursor_sandbox.SecurityCleanupError):
        _sandbox(runner, debug_retain=True).complete(_request(), parent=tmp_path)
    assert len(_worker_commands(runner)) == 1
    assert len(_action_commands(runner, "container")) == 2
    assert not list(tmp_path.glob("shadow-*"))


def test_verified_auto_removal_preserves_worker_failure_semantics(
    tmp_path: Path,
) -> None:
    body = _finished_body()
    body["status"] = "error"
    body["error_kind"] = "run"
    runner = FakeRunner(
        result_body=body,
        returncode=2,
        cleanup_rm_returncode=1,
        cleanup_inspect="absent",
    )
    with pytest.raises(cursor_sandbox.WorkerFailure):
        _sandbox(runner).complete(_request(), parent=tmp_path)


def test_cleanup_failure_overrides_primary_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(
        raise_timeout=True,
        cleanup_inspects=["absent", "uncertain"],
    )
    with pytest.raises(cursor_sandbox.SecurityCleanupError) as info:
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert isinstance(info.value.__cause__, subprocess.TimeoutExpired)


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
    swapped = False
    outside = tmp_path / f"race-{kind}.json"
    outside.write_text(json.dumps(_finished_body()), encoding="utf-8")

    def check_then_swap(request_dir: Path, parent: Path) -> None:
        nonlocal checks, swapped
        original_check(request_dir, parent)
        checks += 1
        result = request_dir / "result.json"
        if result.exists() and not swapped:
            result.unlink()
            if kind == "symlink":
                result.symlink_to(outside)
            else:
                os.link(outside, result)
            swapped = True

    monkeypatch.setattr(
        cursor_sandbox,
        "_ensure_isolated_request_dir",
        check_then_swap,
    )
    runner = FakeRunner(result_body=_finished_body())
    with pytest.raises(cursor_sandbox.RequestDirectoryError):
        _sandbox(runner).complete(_request(), parent=tmp_path)
    assert swapped


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


def test_probe_models_returns_actual_sdk_version(tmp_path: Path) -> None:
    body = {
        "status": "finished",
        "models": [
            {
                "id": "gpt-5.6-sol-max",
                "parameters": [],
                "variants": [],
            }
        ],
        "sdk_version": "0.1.9",
        "text": "",
        "agent_id": "",
        "run_id": "",
        "model_id": "",
        "error_kind": None,
    }
    runner = FakeRunner(result_body=body)
    assert _sandbox(runner).probe_models(parent=tmp_path) == {
        "models": body["models"],
        "sdk_version": "0.1.9",
    }


def test_config_accepts_explicit_local_socket() -> None:
    config = cursor_sandbox.SandboxConfig(
        runtime="docker",
        image="pgrep-shadow-worker:test",
        socket="/var/run/docker.sock",
    )
    assert config.socket == "/var/run/docker.sock"


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
    assert command[1] == "build"
    assert "-t" in command
    assert command[command.index("-t") + 1] == "pgrep-shadow-worker:test"
    assert command[-2:] == ["--", str(WORKER_ROOT.resolve())]


def test_build_image_does_not_require_or_receive_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "ambient-secret")
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    monkeypatch.setenv("HOME", "/host/home")
    monkeypatch.setenv("DOCKER_CONFIG", "/host/config")
    runner = FakeRunner()
    _sandbox(runner, api_key="").build_image(context=WORKER_ROOT)
    assert set(runner.envs[-1]) == {"DOCKER_HOST"}
    assert runner.envs[-1]["DOCKER_HOST"].startswith("unix://")


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
    assert _worker_commands(runner) == []


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


def test_approved_docs_state_first_runner_is_docker_only() -> None:
    plan = (
        REPO_ROOT / "docs_pgrep" / "plan" / "multi-model-shadow-runner-plan.md"
    ).read_text(encoding="utf-8")
    design = (
        REPO_ROOT / "docs_pgrep" / "plan" / "shadow-foundry-calibration-design.md"
    ).read_text(encoding="utf-8")
    assert "Docker-only" in plan
    assert "Docker-only" in design
