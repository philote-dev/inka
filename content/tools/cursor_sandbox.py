# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Host-side OCI sandbox adapter for the isolated Cursor model worker.

The adapter runs the worker image (see ``tools/shadow_worker/``) inside a
disposable Docker or Podman container. It enforces the isolation the shadow
design requires:

- the only host mount is a freshly created, empty request directory bound to
  ``/work``; no repository, parent project, HOME, Docker socket, or extra
  credential is exposed;
- ``CURSOR_API_KEY`` is forwarded by name (``--env CURSOR_API_KEY``) and only
  ever lives in the sanitized subprocess environment, never in a command
  argument or in ``request.json``;
- the subprocess environment is reduced to the minimum the container CLI needs
  plus the forwarded key;
- symlinks, hard links, path escapes, and private training-data markers are
  rejected before any container spawns;
- every captured error is redacted before it is raised or persisted;
- request directories are always removed unless an explicit debug-retain option
  is set, and a retained directory must live under git-ignored ``content/run``
  or the OS temp tree.

The worker result is validated through
``model_backend.ModelResult.from_dict(expected=...)``, which binds the request
identity and the actual returned model identity. Missing runtime, image build
failure, timeout, process error, missing or malformed output, model mismatch,
and worker-declared failure are all distinguished as separate errors.

Tests inject a fake command runner, so no Docker, Podman, network, Cursor key,
or model call is required.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import model_backend  # type: ignore[import-not-found]  # noqa: E402

WORK_MOUNT = "/work"
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_BUILD_TIMEOUT_SECONDS = 1800.0
_RUNTIME_CANDIDATES = ("docker", "podman")

# Minimal host variables the container CLI itself needs. The API key is added
# separately and forwarded into the container by name. Nothing else from the
# ambient environment is exposed to the subprocess.
_HOST_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "DOCKER_HOST",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CONTEXT",
    "CONTAINER_HOST",
    "CONTAINERS_CONF",
    "CONTAINERS_STORAGE_CONF",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "SystemRoot",
    "USERPROFILE",
    "ComSpec",
    "windir",
)

# Keep this boundary-aware expression aligned with model_backend.py's hardened
# training-data firewall. In particular, "marigold" must not match "gold".
_PRIVATE_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"(?:gold|ets|gr9677|gr1777)(?=$|[-_/:\\])"
    r"|held[\s_-]*out(?=$|[\s_/:\\-])"
    r"|tier[\s_-]*3(?=$|[\s_/:\\-])"
    r")"
)

_AUTHORIZATION_RE = re.compile(
    r"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*)"
    r"(?:(?:bearer|basic|token)\s+)?[^\s;,]+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-=]+")
_API_KEY_RE = re.compile(r"(?i)(\bapi[-_ ]?key\s*[:=]\s*)[^\s;,]+")
_COMMON_SECRET_RE = re.compile(
    r"(?i)\b(?:cursor|crsr)_[A-Za-z0-9._-]{6,}\b|\bsk-[A-Za-z0-9._-]{6,}\b"
)


class SandboxError(RuntimeError):
    """Base class for every host sandbox failure."""


class RuntimeUnavailableError(SandboxError):
    """No supported container runtime is installed."""


class ImageBuildError(SandboxError):
    """The worker image failed to build."""


class SandboxTimeout(SandboxError):
    """The container did not finish within the configured timeout."""


class SandboxProcessError(SandboxError):
    """The container process failed and produced no result file."""


class SandboxOutputError(SandboxError):
    """The result file is missing or malformed."""


class WorkerFailure(SandboxError):
    """The worker ran and declared a non-finished status."""


class ModelMismatchError(SandboxError):
    """The returned model identity did not match the requested model."""


class RequestDirectoryError(SandboxError):
    """The request directory is unsafe (symlink, hard link, or escape)."""


class LeakageError(SandboxError):
    """A private training-data marker appeared in a request path or payload."""


@dataclass(frozen=True)
class CommandResult:
    """The captured outcome of one runner invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Runs an explicit argument list and returns its captured result."""

    def run(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        cwd: str | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    """Default runner backed by ``subprocess.run`` with captured output."""

    def run(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        cwd: str | None = None,
    ) -> CommandResult:
        completed = subprocess.run(  # noqa: PLW1510
            list(command),
            env=dict(env),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


@dataclass(frozen=True)
class SandboxConfig:
    """Static configuration for one sandbox adapter."""

    runtime: str
    image: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    build_timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS
    debug_retain: bool = False

    def __post_init__(self) -> None:
        if self.runtime not in _RUNTIME_CANDIDATES:
            allowed = ", ".join(_RUNTIME_CANDIDATES)
            raise ValueError(f"runtime must be one of: {allowed}")
        if not isinstance(self.image, str) or not self.image.strip():
            raise ValueError("image must be a non-empty string")
        if self.timeout <= 0 or self.build_timeout <= 0:
            raise ValueError("timeouts must be positive")


def detect_runtime(
    *,
    which: Callable[[str], str | None] = shutil.which,
    candidates: Sequence[str] = _RUNTIME_CANDIDATES,
) -> str:
    """Return the first available container runtime, else raise.

    The message names Docker or Podman so callers can fail before any request
    directory or model call is created.
    """
    for name in candidates:
        if which(name):
            return name
    raise RuntimeUnavailableError(
        "no container runtime found; install Docker or Podman for sandboxed runs"
    )


def _redact(text: object, *sensitive_values: str) -> str:
    redacted = str(text or "")
    for value in sensitive_values:
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    redacted = _AUTHORIZATION_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _BEARER_RE.sub("Bearer [REDACTED]", redacted)
    redacted = _API_KEY_RE.sub(r"\1[REDACTED]", redacted)
    return _COMMON_SECRET_RE.sub("[REDACTED]", redacted)


def _reject_private_markers(*texts: str) -> None:
    for text in texts:
        if match := _PRIVATE_MARKER.search(text):
            raise LeakageError(
                f"private marker {match.group(0)!r} is not allowed in shadow input"
            )


def _ensure_isolated_request_dir(request_dir: Path, parent: Path) -> None:
    """Reject symlinks, hard links, and path escapes before spawning."""
    if request_dir.is_symlink():
        raise RequestDirectoryError("request directory must not be a symlink")
    resolved = request_dir.resolve()
    parent_resolved = parent.resolve()
    if resolved != parent_resolved and parent_resolved not in resolved.parents:
        raise RequestDirectoryError("request directory escapes its parent")
    for entry in request_dir.iterdir():
        if entry.is_symlink():
            raise RequestDirectoryError(
                f"request directory contains a symlink: {entry.name}"
            )
        stat = entry.lstat()
        if entry.is_file() and stat.st_nlink > 1:
            raise RequestDirectoryError(
                f"request directory contains a hard link: {entry.name}"
            )


def _default_worker_context() -> Path:
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        candidate = base / "tools" / "shadow_worker"
        if (candidate / "Dockerfile").is_file():
            return candidate
    return Path.cwd() / "tools" / "shadow_worker"


def _default_parent() -> Path:
    return Path(tempfile.gettempdir()) / "pgrep-shadow-foundry"


def _retain_location_ok(path: Path) -> bool:
    resolved = path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if resolved == temp_root or temp_root in resolved.parents:
        return True
    for ancestor in (resolved, *resolved.parents):
        if ancestor.name == "run" and ancestor.parent.name == "content":
            return True
    return False


class CursorSandbox:
    """Runs the Cursor worker image inside a disposable OCI container."""

    def __init__(
        self,
        config: SandboxConfig,
        *,
        runner: CommandRunner | None = None,
        api_key: str = "",
    ) -> None:
        self._config = config
        self._runner: CommandRunner = runner if runner is not None else SubprocessRunner()
        self._api_key = api_key

    def build_image(self, *, context: Path | str | None = None) -> str:
        """Build the worker image from a whitelisted build context."""
        context_dir = Path(context) if context is not None else _default_worker_context()
        if not (context_dir / "Dockerfile").is_file():
            raise ImageBuildError(
                f"worker Dockerfile not found under {context_dir}"
            )
        command = [
            self._config.runtime,
            "build",
            "-t",
            self._config.image,
            str(context_dir),
        ]
        completed = self._runner.run(
            command,
            env=self._subprocess_env(),
            timeout=self._config.build_timeout,
        )
        if completed.returncode != 0:
            raise ImageBuildError(
                self._redact_text(completed.stderr or "worker image build failed")
            )
        return self._config.image

    def list_models(self, *, parent: Path | str | None = None) -> list[dict[str, object]]:
        """Probe the account model catalog inside the sandbox."""
        body = self._execute({"action": "models"}, parent=parent)
        status = str(body.get("status") or "")
        if status != "finished":
            raise WorkerFailure(
                self._redact_text(str(body.get("text") or "model listing failed"))
            )
        models = body.get("models")
        if not isinstance(models, list):
            raise SandboxOutputError("model listing is missing the models array")
        return models

    def complete(
        self,
        request: model_backend.ModelRequest,
        *,
        parent: Path | str | None = None,
    ) -> model_backend.ModelResult:
        """Run one prompt request and return a validated model result."""
        if type(request) is not model_backend.ModelRequest:
            raise TypeError("request must be a ModelRequest")
        payload = {
            "action": "prompt",
            "model_id": request.model.model_id,
            "prompt": f"{request.system}\n\n{request.user}",
        }
        body = self._execute(payload, parent=parent)
        return self._to_result(body, request)

    def _execute(
        self,
        payload: dict[str, object],
        *,
        parent: Path | str | None,
    ) -> dict[str, object]:
        parent_dir = Path(parent) if parent is not None else _default_parent()
        if self._config.debug_retain and not _retain_location_ok(parent_dir):
            raise SandboxError(
                "debug retain requires a parent under content/run or the OS temp tree"
            )
        _reject_private_markers(str(parent_dir))
        parent_dir.mkdir(parents=True, exist_ok=True)
        request_dir = Path(tempfile.mkdtemp(prefix="shadow-", dir=parent_dir))
        try:
            (request_dir / "request.json").write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )
            _ensure_isolated_request_dir(request_dir, parent_dir)
            _reject_private_markers(str(request_dir), json.dumps(payload))
            command = self._run_command(request_dir)
            try:
                completed = self._runner.run(
                    command,
                    env=self._subprocess_env(),
                    timeout=self._config.timeout,
                )
            except subprocess.TimeoutExpired as err:
                raise SandboxTimeout(
                    f"worker timed out after {self._config.timeout} seconds"
                ) from err
            return self._load_result(request_dir, completed)
        finally:
            if not self._config.debug_retain:
                shutil.rmtree(request_dir, ignore_errors=True)

    def _run_command(self, request_dir: Path) -> list[str]:
        # Only the request directory is mounted, the key is forwarded by name,
        # and network stays on the default bridge so the container can reach the
        # Cursor API without host networking.
        return [
            self._config.runtime,
            "run",
            "--rm",
            "--network",
            "bridge",
            "--env",
            "CURSOR_API_KEY",
            "--volume",
            f"{request_dir}:{WORK_MOUNT}",
            "--workdir",
            WORK_MOUNT,
            self._config.image,
        ]

    def _load_result(
        self,
        request_dir: Path,
        completed: CommandResult,
    ) -> dict[str, object]:
        result_file = request_dir / "result.json"
        if not result_file.exists():
            if completed.returncode != 0:
                raise SandboxProcessError(
                    self._redact_text(
                        completed.stderr
                        or f"worker process exited with code {completed.returncode}"
                    )
                )
            raise SandboxOutputError("worker produced no result.json")
        try:
            body = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            raise SandboxOutputError("worker result.json is malformed") from err
        if not isinstance(body, dict):
            raise SandboxOutputError("worker result.json is not an object")
        return body

    def _to_result(
        self,
        body: dict[str, object],
        request: model_backend.ModelRequest,
    ) -> model_backend.ModelResult:
        status = str(body.get("status") or "")
        if body.get("error_kind") == "model_identity":
            raise ModelMismatchError(
                self._redact_text(str(body.get("text") or "model identity mismatch"))
            )
        if status != "finished":
            raise WorkerFailure(
                self._redact_text(
                    str(body.get("text") or f"worker declared status {status!r}")
                )
            )
        mapped = {
            "request_id": request.request_id,
            "model_id": str(body.get("model_id") or ""),
            "status": status,
            "text": str(body.get("text") or ""),
            "agent_id": str(body.get("agent_id") or ""),
            "run_id": str(body.get("run_id") or ""),
            "error": "",
        }
        try:
            return model_backend.ModelResult.from_dict(mapped, expected=request)
        except ValueError as err:
            message = str(err)
            if "model_id" in message:
                raise ModelMismatchError(message) from err
            raise SandboxOutputError(self._redact_text(message)) from err

    def _subprocess_env(self) -> dict[str, str]:
        env = {name: os.environ[name] for name in _HOST_ENV_ALLOWLIST if name in os.environ}
        key = self._api_key or os.environ.get("CURSOR_API_KEY", "")
        if not key:
            raise SandboxError("CURSOR_API_KEY is required for sandboxed model calls")
        env["CURSOR_API_KEY"] = key
        return env

    def _redact_text(self, text: object) -> str:
        return _redact(
            text,
            self._api_key,
            os.environ.get("CURSOR_API_KEY", ""),
        )
