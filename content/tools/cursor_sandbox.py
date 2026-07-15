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

import errno
import hashlib
import json
import os
import re
import shutil
import stat
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
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 30.0
_RUNTIME_CANDIDATES = ("docker", "podman")
_ALLOWED_NETWORKS = frozenset({"bridge", "default"})
_WORKER_CONTEXT_FILES = (
    ".dockerignore",
    "Dockerfile",
    "pyproject.toml",
    "uv.lock",
    "worker.py",
)

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
    network: str = "bridge"

    def __post_init__(self) -> None:
        if self.runtime not in _RUNTIME_CANDIDATES:
            allowed = ", ".join(_RUNTIME_CANDIDATES)
            raise ValueError(f"runtime must be one of: {allowed}")
        if not isinstance(self.image, str) or not self.image.strip():
            raise ValueError("image must be a non-empty string")
        if self.image.startswith("-"):
            raise ValueError("image must not begin with '-'")
        if self.network not in _ALLOWED_NETWORKS:
            allowed_networks = ", ".join(sorted(_ALLOWED_NETWORKS))
            raise ValueError(f"network must be one of: {allowed_networks}")
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


def _validate_cli_value(value: str, *, name: str) -> str:
    if not value or not value.strip():
        raise SandboxError(f"{name} must be a non-empty string")
    if value.startswith("-"):
        raise SandboxError(f"{name} must not begin with '-'")
    return value


def _validated_parent(path: Path) -> Path:
    """Resolve a request parent and reject direct symlinks or unsafe targets."""
    try:
        initial = path.lstat()
    except FileNotFoundError:
        initial = None
    if initial is not None:
        if stat.S_ISLNK(initial.st_mode):
            raise RequestDirectoryError("request parent must not be a symlink")
        if not stat.S_ISDIR(initial.st_mode):
            raise RequestDirectoryError("request parent must be a directory")

    lexical = path.absolute()
    resolved_before_create = path.resolve(strict=False)
    _reject_private_markers(str(lexical), str(resolved_before_create))
    resolved_before_create.mkdir(parents=True, exist_ok=True)

    try:
        final_stat = path.lstat()
    except FileNotFoundError as err:
        raise RequestDirectoryError("request parent disappeared during setup") from err
    if stat.S_ISLNK(final_stat.st_mode):
        raise RequestDirectoryError("request parent must not be a symlink")
    if not stat.S_ISDIR(final_stat.st_mode):
        raise RequestDirectoryError("request parent must be a directory")

    final = path.resolve(strict=True)
    if final != resolved_before_create:
        raise RequestDirectoryError("request parent changed while being prepared")
    _reject_private_markers(str(final))
    return final


def _walk_request_directory(directory: Path, request_root: Path) -> None:
    try:
        entries = list(os.scandir(directory))
    except OSError as err:
        raise RequestDirectoryError("request directory could not be inspected") from err
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as err:
            raise RequestDirectoryError(
                f"request entry could not be inspected: {entry.name}"
            ) from err
        relative = Path(entry.path).relative_to(request_root)
        _reject_private_markers(str(relative))
        if stat.S_ISLNK(info.st_mode):
            raise RequestDirectoryError(
                f"request directory contains a symlink: {relative}"
            )
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise RequestDirectoryError(
                    f"request directory contains a hard link: {relative}"
                )
        elif stat.S_ISDIR(info.st_mode):
            _walk_request_directory(Path(entry.path), request_root)
        else:
            raise RequestDirectoryError(
                f"request directory contains a non-regular entry: {relative}"
            )


def _ensure_isolated_request_dir(request_dir: Path, parent: Path) -> None:
    """Reject symlinks, hard links, special files, and path escapes."""
    try:
        request_stat = request_dir.lstat()
    except FileNotFoundError as err:
        raise RequestDirectoryError("request directory is missing") from err
    if stat.S_ISLNK(request_stat.st_mode):
        raise RequestDirectoryError("request directory must not be a symlink")
    if not stat.S_ISDIR(request_stat.st_mode):
        raise RequestDirectoryError("request path must be a directory")

    try:
        resolved = request_dir.resolve(strict=True)
        parent_resolved = parent.resolve(strict=True)
    except OSError as err:
        raise RequestDirectoryError("request paths could not be resolved") from err
    if resolved.parent != parent_resolved:
        raise RequestDirectoryError("request directory escapes its parent")
    _reject_private_markers(str(parent_resolved), str(resolved))
    _walk_request_directory(resolved, resolved)


def _write_request_file(request_dir: Path, payload: dict[str, object]) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RequestDirectoryError("host does not support O_NOFOLLOW")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(request_dir / "request.json", flags, 0o600)
    except OSError as err:
        raise RequestDirectoryError("request.json could not be created safely") from err
    with os.fdopen(descriptor, "w", encoding="utf-8") as request_file:
        json.dump(payload, request_file, sort_keys=True)


def _read_result_file_nofollow(request_dir: Path) -> str:
    """Open result.json relative to a no-follow directory descriptor."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        raise RequestDirectoryError(
            "host must support O_NOFOLLOW and O_DIRECTORY for sandbox output"
        )
    directory_flags = os.O_RDONLY | nofollow | directory_flag
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        directory_descriptor = os.open(request_dir, directory_flags)
    except OSError as err:
        raise RequestDirectoryError(
            "request directory changed before result read"
        ) from err
    try:
        result_flags = os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0)
        result_flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            result_descriptor = os.open(
                "result.json",
                result_flags,
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            raise
        except OSError as err:
            if err.errno in (errno.ELOOP, errno.EMLINK):
                raise RequestDirectoryError(
                    "result.json must not be a symlink"
                ) from err
            raise SandboxOutputError("result.json could not be opened safely") from err

        try:
            result_stat = os.fstat(result_descriptor)
            if not stat.S_ISREG(result_stat.st_mode):
                raise RequestDirectoryError("result.json must be a regular file")
            if result_stat.st_nlink != 1:
                raise RequestDirectoryError("result.json must not be a hard link")
            with os.fdopen(result_descriptor, "r", encoding="utf-8") as result_file:
                result_descriptor = -1
                return result_file.read()
        finally:
            if result_descriptor >= 0:
                os.close(result_descriptor)
    finally:
        os.close(directory_descriptor)


def _default_worker_context() -> Path:
    return Path(__file__).resolve().parents[2] / "tools" / "shadow_worker"


def _default_parent() -> Path:
    return Path(tempfile.gettempdir()) / "pgrep-shadow-foundry"


def _validated_worker_context(context: Path | str | None) -> Path:
    expected_path = _default_worker_context()
    try:
        expected_stat = expected_path.lstat()
        expected = expected_path.resolve(strict=True)
    except OSError as err:
        raise ImageBuildError("worker build context is unavailable") from err
    if stat.S_ISLNK(expected_stat.st_mode) or not stat.S_ISDIR(expected_stat.st_mode):
        raise ImageBuildError("worker build context must be a real directory")

    if context is None:
        selected_path = expected_path
    else:
        rendered = os.fspath(context)
        if rendered.startswith("-"):
            raise ImageBuildError("worker build context must not begin with '-'")
        selected_path = Path(context)
    try:
        selected_stat = selected_path.lstat()
        selected = selected_path.resolve(strict=True)
    except OSError as err:
        raise ImageBuildError("worker build context is unavailable") from err
    if stat.S_ISLNK(selected_stat.st_mode):
        raise ImageBuildError("worker build context must not be a symlink")
    if selected != expected:
        raise ImageBuildError(f"worker build context must be exactly {expected}")

    for relative in _WORKER_CONTEXT_FILES:
        candidate = selected / relative
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError as err:
            raise ImageBuildError(
                f"worker build context is missing {relative}"
            ) from err
        if (
            stat.S_ISLNK(candidate_stat.st_mode)
            or not stat.S_ISREG(candidate_stat.st_mode)
            or candidate_stat.st_nlink != 1
        ):
            raise ImageBuildError(f"worker build context file is unsafe: {relative}")
    return selected


def _retain_location_ok(path: Path) -> bool:
    resolved = path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if resolved == temp_root or temp_root in resolved.parents:
        return True
    for ancestor in (resolved, *resolved.parents):
        if ancestor.name == "run" and ancestor.parent.name == "content":
            return True
    return False


def _container_name(request_dir: Path) -> str:
    digest = hashlib.sha256(str(request_dir).encode("utf-8")).hexdigest()[:24]
    return f"pgrep-shadow-{digest}"


def _remove_request_path(request_dir: Path) -> None:
    try:
        request_stat = request_dir.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(request_stat.st_mode) and not stat.S_ISLNK(request_stat.st_mode):
        shutil.rmtree(request_dir, ignore_errors=True)
    else:
        try:
            request_dir.unlink()
        except OSError:
            pass


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
        self._runner: CommandRunner = (
            runner if runner is not None else SubprocessRunner()
        )
        self._api_key = api_key

    def build_image(self, *, context: Path | str | None = None) -> str:
        """Build the worker image from a whitelisted build context."""
        context_dir = _validated_worker_context(context)
        command = [
            self._config.runtime,
            "build",
            "-t",
            self._config.image,
            "--",
            str(context_dir),
        ]
        try:
            completed = self._runner.run(
                command,
                env=self._build_subprocess_env(),
                timeout=self._config.build_timeout,
            )
        except subprocess.TimeoutExpired as err:
            raise ImageBuildError(
                f"worker image build timed out after {self._config.build_timeout} seconds"
            ) from err
        except Exception as err:
            raise ImageBuildError(
                self._redact_text(err or "worker image build failed")
            ) from err
        if completed.returncode != 0:
            raise ImageBuildError(
                self._redact_text(completed.stderr or "worker image build failed")
            )
        return self._config.image

    def list_models(
        self, *, parent: Path | str | None = None
    ) -> list[dict[str, object]]:
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
        parent_path = Path(parent) if parent is not None else _default_parent()
        parent_dir = _validated_parent(parent_path)
        if self._config.debug_retain and not _retain_location_ok(parent_dir):
            raise SandboxError(
                "debug retain requires a parent under content/run or the OS temp tree"
            )
        request_dir = Path(tempfile.mkdtemp(prefix="shadow-", dir=parent_dir))
        try:
            _ensure_isolated_request_dir(request_dir, parent_dir)
            request_dir = request_dir.resolve(strict=True)
            _write_request_file(request_dir, payload)
            _ensure_isolated_request_dir(request_dir, parent_dir)
            _reject_private_markers(json.dumps(payload, sort_keys=True))
            container_name = _validate_cli_value(
                _container_name(request_dir),
                name="container name",
            )
            completed = self._run_worker(
                request_dir=request_dir,
                container_name=container_name,
            )
            _ensure_isolated_request_dir(request_dir, parent_dir)
            return self._load_result(request_dir, completed)
        finally:
            if not self._config.debug_retain:
                _remove_request_path(request_dir)

    def _run_worker(
        self,
        *,
        request_dir: Path,
        container_name: str,
    ) -> CommandResult:
        command = self._run_command(request_dir, container_name)
        run_environment = self._run_subprocess_env()
        try:
            completed = self._runner.run(
                command,
                env=run_environment,
                timeout=self._config.timeout,
            )
        except BaseException as err:
            self._force_remove_container(container_name)
            if isinstance(err, subprocess.TimeoutExpired):
                raise SandboxTimeout(
                    f"worker timed out after {self._config.timeout} seconds"
                ) from err
            if isinstance(err, Exception):
                raise SandboxProcessError(
                    self._redact_text(err or "worker process failed")
                ) from err
            raise
        if completed.returncode != 0:
            self._force_remove_container(container_name)
        return completed

    def _force_remove_container(self, container_name: str) -> None:
        command = [
            self._config.runtime,
            "rm",
            "-f",
            "--",
            _validate_cli_value(container_name, name="container name"),
        ]
        try:
            self._runner.run(
                command,
                env=self._build_subprocess_env(),
                timeout=DEFAULT_CLEANUP_TIMEOUT_SECONDS,
            )
        except BaseException:
            # Preserve the primary timeout, interruption, or process failure.
            # The stable name lets an operator retry this exact cleanup command.
            pass

    def _run_command(
        self,
        request_dir: Path,
        container_name: str,
    ) -> list[str]:
        # Only the request directory is mounted, the key is forwarded by name,
        # and network stays on the bridge/default path so the container can
        # reach the Cursor API without host networking.
        command = [
            self._config.runtime,
            "run",
            "--rm",
            "--name",
            _validate_cli_value(container_name, name="container name"),
        ]
        if self._config.network == "bridge":
            command.extend(["--network", "bridge"])
        command.extend(
            [
                "--env",
                "CURSOR_API_KEY",
                "--volume",
                f"{request_dir}:{WORK_MOUNT}",
                "--workdir",
                WORK_MOUNT,
                "--",
                self._config.image,
            ]
        )
        return command

    def _load_result(
        self,
        request_dir: Path,
        completed: CommandResult,
    ) -> dict[str, object]:
        try:
            rendered = _read_result_file_nofollow(request_dir)
        except FileNotFoundError:
            if completed.returncode != 0:
                raise SandboxProcessError(
                    self._redact_text(
                        completed.stderr
                        or f"worker process exited with code {completed.returncode}"
                    )
                )
            raise SandboxOutputError("worker produced no result.json")
        except UnicodeError as err:
            raise SandboxOutputError("worker result.json is malformed") from err
        try:
            body = json.loads(rendered)
        except json.JSONDecodeError as err:
            raise SandboxOutputError("worker result.json is malformed") from err
        if not isinstance(body, dict):
            raise SandboxOutputError("worker result.json is not an object")
        if completed.returncode != 0 and body.get("status") == "finished":
            raise SandboxProcessError(
                self._redact_text(
                    completed.stderr
                    or f"worker process exited with code {completed.returncode}"
                )
            )
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

    def _build_subprocess_env(self) -> dict[str, str]:
        return {
            name: os.environ[name] for name in _HOST_ENV_ALLOWLIST if name in os.environ
        }

    def _run_subprocess_env(self) -> dict[str, str]:
        env = self._build_subprocess_env()
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
