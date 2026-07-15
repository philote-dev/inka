# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Host-side Docker sandbox adapter for the isolated Cursor model worker.

The adapter runs the worker image (see ``tools/shadow_worker/``) inside a
disposable local Docker container. It enforces the isolation the shadow design
requires:

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

Tests inject a fake command runner, so no Docker daemon, network, Cursor key,
or model call is required.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

try:
    import pwd
except ImportError:  # pragma: no cover - OCI runtimes are Unix-only here.
    pwd = None  # type: ignore[assignment]

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import model_backend  # type: ignore[import-not-found]  # noqa: E402

WORK_MOUNT = "/work"
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_BUILD_TIMEOUT_SECONDS = 1800.0
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 30.0
MAX_REQUEST_ENTRIES = 128
MAX_REQUEST_DEPTH = 4
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_RESULT_JSON_BYTES = 512 * 1024
MAX_PROBE_BYTES = 256
_ALLOWED_NETWORKS = frozenset({"bridge", "default"})
_WORKER_CONTEXT_FILES = (
    ".dockerignore",
    "Dockerfile",
    "pyproject.toml",
    "uv.lock",
    "worker.py",
)
_DOCKER_HARDENING_OPTIONS = (
    "--read-only",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges=true",
    "--pids-limit",
    "128",
    "--memory",
    "1g",
    "--cpus",
    "2",
    "--tmpfs",
    "/tmp:rw,noexec,nosuid,size=64m",
)

_IMAGE_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_REMOTE_ENDPOINT_RE = re.compile(r"(?i)^(?:ssh|tcp|http|https|npipe|unix)://")
_ABSENT_CONTAINER_MARKERS = (
    "no such object",
    "no such container",
    "does not exist",
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


class SandboxSecurityError(SandboxError):
    """A sandbox identity, isolation, path, limit, or cleanup failure."""


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


class ModelMismatchError(SandboxSecurityError):
    """The returned model identity did not match the requested model."""


class RequestDirectoryError(SandboxSecurityError):
    """The request directory is unsafe (symlink, hard link, or escape)."""


class LeakageError(SandboxSecurityError):
    """A private training-data marker appeared in a request path or payload."""


class RuntimeEndpointError(SandboxSecurityError):
    """The runtime endpoint is not a verified local Unix socket."""


class MountProbeError(SandboxSecurityError):
    """The keyless two-way mount probe failed."""


class SecurityCleanupError(SandboxSecurityError):
    """A named container could not be proven absent."""


class RequestCleanupError(SandboxSecurityError):
    """A request path could not be proven removed."""


class RequestRetentionError(RequestCleanupError):
    """An unsafe request path was removed instead of debug-retained."""


class SandboxLimitError(SandboxSecurityError):
    """Container output exceeded a strict filesystem bound."""


class DescriptorOpenError(SandboxSecurityError):
    """The host cannot safely open files relative to a directory descriptor."""


@dataclass(frozen=True)
class CommandResult:
    """The captured outcome of one runner invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class LocalRuntime:
    """A verified executable and local Unix socket with stable identities."""

    kind: str
    binary: Path
    socket: Path
    binary_identity: str
    socket_identity: str


@dataclass
class _LifecycleState:
    """Tracks whether every started container is proven absent."""

    absence_proven: bool = True
    retention_forbidden: bool = False

    def container_starting(self) -> None:
        self.absence_proven = False

    def prove_absence(self) -> None:
        self.absence_proven = True

    def forbid_retention(self) -> None:
        self.retention_forbidden = True

    @property
    def can_retain(self) -> bool:
        return self.absence_proven and not self.retention_forbidden


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
    socket: str | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    build_timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS
    debug_retain: bool = False
    network: str = "bridge"

    def __post_init__(self) -> None:
        if self.runtime != "docker":
            raise ValueError("runtime must be Docker")
        if not isinstance(self.image, str) or not self.image.strip():
            raise ValueError("image must be a non-empty string")
        if self.image.startswith("-"):
            raise ValueError("image must not begin with '-'")
        if self.socket is not None:
            if (
                not isinstance(self.socket, str)
                or not self.socket.strip()
                or not Path(self.socket).is_absolute()
                or _REMOTE_ENDPOINT_RE.match(self.socket)
            ):
                raise ValueError("socket must be an absolute local path")
        if self.network not in _ALLOWED_NETWORKS:
            allowed_networks = ", ".join(sorted(_ALLOWED_NETWORKS))
            raise ValueError(f"network must be one of: {allowed_networks}")
        if self.timeout <= 0 or self.build_timeout <= 0:
            raise ValueError("timeouts must be positive")


def detect_runtime(
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """Return Docker when installed, else raise.

    Docker-only discovery lets callers fail before any request directory or
    model call is created.
    """
    if which("docker"):
        return "docker"
    raise RuntimeUnavailableError(
        "Docker was not found; install local Docker for sandboxed runs"
    )


def _account_home(uid: int) -> Path:
    if pwd is None:
        raise RuntimeEndpointError("local Unix runtime discovery is unsupported")
    try:
        return Path(pwd.getpwuid(uid).pw_dir)
    except (KeyError, OSError) as err:
        raise RuntimeEndpointError("could not resolve the local account home") from err


def _local_socket_candidates(
    runtime: str,
    *,
    platform: str = sys.platform,
    uid: int | None = None,
    home: Path | None = None,
) -> tuple[Path, ...]:
    """Return only structurally local sockets supported by this host."""
    if uid is None:
        if not hasattr(os, "getuid"):
            return ()
        uid = os.getuid()
    if home is None:
        home = _account_home(uid)

    if runtime != "docker":
        return ()
    if platform == "darwin":
        return (
            home / ".docker" / "run" / "docker.sock",
            Path("/var/run/docker.sock"),
        )
    if platform.startswith("linux"):
        return (
            Path("/var/run/docker.sock"),
            Path("/run/docker.sock"),
            Path(f"/run/user/{uid}/docker.sock"),
        )
    return ()


def _normalize_socket_candidate(runtime: str, candidate: Path | str) -> Path:
    rendered = os.fspath(candidate)
    if not isinstance(rendered, str):
        raise RuntimeEndpointError("runtime socket path must be text")
    if _REMOTE_ENDPOINT_RE.match(rendered) or not Path(rendered).is_absolute():
        raise RuntimeEndpointError(
            f"{runtime} endpoint must be an absolute local Unix socket path"
        )
    return Path(rendered)


def _path_identity(path: Path, info: os.stat_result) -> str:
    return f"{path}:{info.st_dev}:{info.st_ino}:{info.st_mtime_ns}:{info.st_size}"


def _verified_local_runtime(
    runtime: str,
    binary: Path | str,
    socket_path: Path | str,
    *,
    allowed_sockets: Sequence[Path | str],
) -> LocalRuntime:
    if runtime != "docker":
        raise RuntimeEndpointError("only Docker is supported")
    if not hasattr(os, "getuid"):
        raise RuntimeEndpointError("local Unix runtime endpoints are required")
    uid = os.getuid()

    try:
        binary_path = Path(binary).resolve(strict=True)
        binary_info = binary_path.stat()
    except OSError as err:
        raise RuntimeEndpointError("runtime binary is unavailable") from err
    if (
        not stat.S_ISREG(binary_info.st_mode)
        or not os.access(binary_path, os.X_OK)
        or binary_info.st_uid not in (0, uid)
    ):
        raise RuntimeEndpointError("runtime binary is not a trusted executable")

    selected = _normalize_socket_candidate(runtime, socket_path)
    try:
        selected_lstat = selected.lstat()
        resolved_socket = selected.resolve(strict=True)
        socket_info = resolved_socket.stat()
    except OSError as err:
        raise RuntimeEndpointError("local runtime socket is unavailable") from err
    if stat.S_ISLNK(selected_lstat.st_mode):
        raise RuntimeEndpointError("runtime socket must not be a symlink")
    if not stat.S_ISSOCK(socket_info.st_mode) or socket_info.st_uid not in (0, uid):
        raise RuntimeEndpointError("runtime endpoint is not a trusted Unix socket")

    allowed_resolved: set[Path] = set()
    for candidate in allowed_sockets:
        normalized = _normalize_socket_candidate(runtime, candidate)
        try:
            allowed_resolved.add(normalized.resolve(strict=True))
        except OSError:
            continue
    if resolved_socket not in allowed_resolved:
        raise RuntimeEndpointError("runtime socket is outside the local allowlist")

    return LocalRuntime(
        kind=runtime,
        binary=binary_path,
        socket=resolved_socket,
        binary_identity=_path_identity(binary_path, binary_info),
        socket_identity=_path_identity(resolved_socket, socket_info),
    )


def discover_local_runtime(
    runtime: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    socket_candidates: Callable[[str], Sequence[Path | str]] | None = None,
) -> LocalRuntime:
    """Discover a verified runtime binary and allowlisted local Unix socket."""
    binary = which(runtime)
    if not binary:
        raise RuntimeUnavailableError(
            f"{runtime} executable was not found on this host"
        )
    candidates = tuple((socket_candidates or _local_socket_candidates)(runtime))
    if not candidates:
        raise RuntimeEndpointError(
            f"no verified local Unix socket is supported for {runtime}"
        )
    errors: list[BaseException] = []
    for candidate in candidates:
        try:
            return _verified_local_runtime(
                runtime,
                binary,
                candidate,
                allowed_sockets=candidates,
            )
        except RuntimeEndpointError as err:
            errors.append(err)
    raise RuntimeEndpointError(
        f"no verified local Unix socket is available for {runtime}"
    ) from errors[-1]


def _revalidate_local_runtime(endpoint: LocalRuntime) -> LocalRuntime:
    refreshed = _verified_local_runtime(
        endpoint.kind,
        endpoint.binary,
        endpoint.socket,
        allowed_sockets=_local_socket_candidates(endpoint.kind),
    )
    if (
        refreshed.binary_identity != endpoint.binary_identity
        or refreshed.socket_identity != endpoint.socket_identity
    ):
        raise RuntimeEndpointError("runtime binary or socket identity changed")
    return refreshed


def _endpoint_environment(endpoint: LocalRuntime) -> dict[str, str]:
    if endpoint.kind != "docker":
        raise RuntimeEndpointError("only Docker is supported")
    value = f"unix://{endpoint.socket}"
    return {"DOCKER_HOST": value}


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


@dataclass
class _DirectoryUsage:
    entries: int = 0
    total_bytes: int = 0


def _verify_regular_file_readable(
    path: Path,
    expected: os.stat_result,
) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise DescriptorOpenError("host does not support O_NOFOLLOW")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except (TypeError, NotImplementedError, ValueError) as err:
        raise DescriptorOpenError("safe retention read is unsupported") from err
    except OSError as err:
        raise RequestDirectoryError(
            f"request content is unreadable: {path.name}"
        ) from err
    try:
        actual = os.fstat(descriptor)
        if (
            not stat.S_ISREG(actual.st_mode)
            or actual.st_nlink != 1
            or actual.st_dev != expected.st_dev
            or actual.st_ino != expected.st_ino
            or actual.st_size != expected.st_size
        ):
            raise RequestDirectoryError(
                f"request content changed during retention validation: {path.name}"
            )
        if actual.st_size:
            os.read(descriptor, 1)
    except OSError as err:
        raise RequestDirectoryError(
            f"request content is unreadable: {path.name}"
        ) from err
    finally:
        os.close(descriptor)


def _walk_request_directory(
    directory: Path,
    request_root: Path,
    usage: _DirectoryUsage,
    *,
    depth: int,
    require_readable: bool,
) -> None:
    try:
        iterator = os.scandir(directory)
    except OSError as err:
        raise RequestDirectoryError("request directory could not be inspected") from err
    with iterator:
        for entry in iterator:
            usage.entries += 1
            if usage.entries > MAX_REQUEST_ENTRIES:
                raise SandboxLimitError(
                    f"request directory exceeds {MAX_REQUEST_ENTRIES} entries"
                )
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
                if info.st_size > MAX_FILE_BYTES:
                    raise SandboxLimitError(
                        f"request file exceeds {MAX_FILE_BYTES} bytes: {relative}"
                    )
                usage.total_bytes += info.st_size
                if usage.total_bytes > MAX_TOTAL_BYTES:
                    raise SandboxLimitError(
                        f"request directory total exceeds {MAX_TOTAL_BYTES} bytes"
                    )
                if require_readable:
                    _verify_regular_file_readable(Path(entry.path), info)
            elif stat.S_ISDIR(info.st_mode):
                if depth >= MAX_REQUEST_DEPTH:
                    raise SandboxLimitError(
                        f"request directory exceeds depth {MAX_REQUEST_DEPTH}"
                    )
                _walk_request_directory(
                    Path(entry.path),
                    request_root,
                    usage,
                    depth=depth + 1,
                    require_readable=require_readable,
                )
            else:
                raise RequestDirectoryError(
                    f"request directory contains a non-regular entry: {relative}"
                )


def _ensure_isolated_request_dir(
    request_dir: Path,
    parent: Path,
    *,
    require_readable: bool = False,
) -> None:
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
    _walk_request_directory(
        resolved,
        resolved,
        _DirectoryUsage(),
        depth=0,
        require_readable=require_readable,
    )


def _write_named_file_nofollow(
    request_dir: Path,
    filename: str,
    content: bytes,
) -> None:
    if not filename or "/" in filename or filename in (".", ".."):
        raise RequestDirectoryError("unsafe internal request filename")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise DescriptorOpenError("host does not support O_NOFOLLOW")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(request_dir / filename, flags, 0o600)
    except (TypeError, NotImplementedError, ValueError) as err:
        raise DescriptorOpenError("safe file creation is unsupported") from err
    except OSError as err:
        raise RequestDirectoryError(f"{filename} could not be created safely") from err
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)


def _write_request_file(request_dir: Path, payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, sort_keys=True).encode("utf-8")
    _write_named_file_nofollow(request_dir, "request.json", rendered)


def _unlink_named_file_nofollow(request_dir: Path, filename: str) -> None:
    if not filename or "/" in filename or filename in (".", ".."):
        raise RequestCleanupError("unsafe internal cleanup filename")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        raise DescriptorOpenError(
            "host must support O_NOFOLLOW and O_DIRECTORY for cleanup"
        )
    flags = os.O_RDONLY | nofollow | directory_flag
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        directory_descriptor = os.open(request_dir, flags)
    except (TypeError, NotImplementedError, ValueError) as err:
        raise DescriptorOpenError("safe cleanup directory open is unsupported") from err
    except OSError as err:
        raise RequestCleanupError(
            "request directory changed before artifact cleanup"
        ) from err
    try:
        try:
            os.unlink(filename, dir_fd=directory_descriptor)
        except FileNotFoundError:
            return
        except (TypeError, NotImplementedError, ValueError) as err:
            raise DescriptorOpenError(
                "descriptor-relative unlink is unsupported"
            ) from err
        except OSError as err:
            raise RequestCleanupError(
                f"could not remove request artifact {filename}"
            ) from err
        try:
            os.stat(
                filename,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        except (TypeError, NotImplementedError, ValueError) as err:
            raise DescriptorOpenError(
                "descriptor-relative cleanup verification is unsupported"
            ) from err
        except OSError as err:
            raise RequestCleanupError(
                f"could not verify request artifact removal: {filename}"
            ) from err
        raise RequestCleanupError(
            f"request artifact still exists after cleanup: {filename}"
        )
    finally:
        os.close(directory_descriptor)


def _read_named_file_nofollow(
    request_dir: Path,
    filename: str,
    *,
    max_bytes: int,
) -> bytes:
    """Open a bounded regular file relative to a no-follow directory."""
    if not filename or "/" in filename or filename in (".", ".."):
        raise RequestDirectoryError("unsafe internal request filename")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        raise DescriptorOpenError(
            "host must support O_NOFOLLOW and O_DIRECTORY for sandbox output"
        )
    directory_flags = os.O_RDONLY | nofollow | directory_flag
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        directory_descriptor = os.open(request_dir, directory_flags)
    except (TypeError, NotImplementedError, ValueError) as err:
        raise DescriptorOpenError("safe directory open is unsupported") from err
    except OSError as err:
        raise RequestDirectoryError(
            "request directory changed before result read"
        ) from err
    try:
        result_flags = os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0)
        result_flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            result_descriptor = os.open(
                filename,
                result_flags,
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            raise
        except (TypeError, NotImplementedError, ValueError) as err:
            raise DescriptorOpenError(
                "descriptor-relative file open is unsupported"
            ) from err
        except OSError as err:
            if err.errno in (errno.ELOOP, errno.EMLINK):
                raise RequestDirectoryError(
                    f"{filename} must not be a symlink"
                ) from err
            raise SandboxOutputError(f"{filename} could not be opened safely") from err

        try:
            result_stat = os.fstat(result_descriptor)
            if not stat.S_ISREG(result_stat.st_mode):
                raise RequestDirectoryError(f"{filename} must be a regular file")
            if result_stat.st_nlink != 1:
                raise RequestDirectoryError(f"{filename} must not be a hard link")
            if result_stat.st_size > max_bytes:
                raise SandboxLimitError(f"{filename} exceeds {max_bytes} bytes")
            with os.fdopen(result_descriptor, "rb") as result_file:
                result_descriptor = -1
                content = result_file.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise SandboxLimitError(f"{filename} exceeds {max_bytes} bytes")
                return content
        finally:
            if result_descriptor >= 0:
                os.close(result_descriptor)
    finally:
        os.close(directory_descriptor)


def _read_result_file_nofollow(request_dir: Path) -> str:
    return _read_named_file_nofollow(
        request_dir,
        "result.json",
        max_bytes=MAX_RESULT_JSON_BYTES,
    ).decode("utf-8")


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
    resolved = path.resolve(strict=False)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    repo_run_root = (Path(__file__).resolve().parents[2] / "content" / "run").resolve(
        strict=False
    )
    return (
        resolved == temp_root
        or temp_root in resolved.parents
        or resolved == repo_run_root
        or repo_run_root in resolved.parents
    )


def _container_name(request_dir: Path) -> str:
    digest = hashlib.sha256(str(request_dir).encode("utf-8")).hexdigest()[:24]
    return f"pgrep-shadow-{digest}"


def _create_request_directory(parent: Path) -> Path:
    for _attempt in range(10):
        request_dir = parent / f"shadow-{secrets.token_hex(16)}"
        try:
            request_dir.mkdir(mode=0o700)
        except FileExistsError:
            continue
        return request_dir
    raise RequestDirectoryError("could not reserve a unique request directory")


def _rmtree(path: Path) -> None:
    shutil.rmtree(path)


def _remove_request_path(request_dir: Path) -> None:
    try:
        request_stat = request_dir.lstat()
    except FileNotFoundError:
        return
    except Exception as err:
        raise RequestCleanupError(
            f"request cleanup could not inspect {request_dir}"
        ) from err
    try:
        if stat.S_ISDIR(request_stat.st_mode) and not stat.S_ISLNK(
            request_stat.st_mode
        ):
            _rmtree(request_dir)
        else:
            request_dir.unlink()
    except Exception as err:
        raise RequestCleanupError(f"request cleanup failed for {request_dir}") from err
    try:
        request_dir.lstat()
    except FileNotFoundError:
        return
    except Exception as err:
        raise RequestCleanupError(
            f"request cleanup could not verify removal: {request_dir}"
        ) from err
    raise RequestCleanupError(f"request path still exists after cleanup: {request_dir}")


def _verify_retained_request_path(request_dir: Path, parent: Path) -> None:
    try:
        request_info = request_dir.lstat()
        resolved = request_dir.resolve(strict=True)
        if (
            stat.S_ISLNK(request_info.st_mode)
            or not stat.S_ISDIR(request_info.st_mode)
            or resolved.parent != parent
            or not _retain_location_ok(resolved)
        ):
            raise RequestDirectoryError(
                "debug-retained request path escaped its allowed root"
            )
        _ensure_isolated_request_dir(
            resolved,
            parent,
            require_readable=True,
        )
    except Exception as err:
        _remove_request_path(request_dir)
        raise RequestRetentionError(
            "unsafe request directory was removed instead of retained"
        ) from err


class CursorSandbox:
    """Runs the Cursor worker image inside a disposable Docker container."""

    def __init__(
        self,
        config: SandboxConfig,
        *,
        runner: CommandRunner | None = None,
        api_key: str = "",
        endpoint_resolver: Callable[[str], LocalRuntime] | None = None,
    ) -> None:
        self._config = config
        self._runner: CommandRunner = (
            runner if runner is not None else SubprocessRunner()
        )
        self._api_key = api_key
        self._endpoint_resolver = endpoint_resolver

    def build_image(self, *, context: Path | str | None = None) -> str:
        """Build the worker image from a whitelisted build context."""
        endpoint = self._local_runtime()
        context_dir = _validated_worker_context(context)
        command = [
            str(endpoint.binary),
            "build",
            "-t",
            self._config.image,
            "--",
            str(context_dir),
        ]
        try:
            completed = self._runner.run(
                command,
                env=self._endpoint_subprocess_env(endpoint),
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

    def image_digest(self) -> str:
        """Return the immutable digest for the configured worker image."""
        return self._inspect_image_digest(self._local_runtime())

    def probe_models(self, *, parent: Path | str | None = None) -> dict[str, object]:
        """Probe account models and the actual worker SDK version."""
        body = self._execute({"action": "models"}, parent=parent)
        status = str(body.get("status") or "")
        if status != "finished":
            raise WorkerFailure(
                self._redact_text(str(body.get("text") or "model listing failed"))
            )
        models = body.get("models")
        if not isinstance(models, list):
            raise SandboxOutputError("model listing is missing the models array")
        sdk_version = body.get("sdk_version")
        if not isinstance(sdk_version, str) or not sdk_version.strip():
            raise SandboxOutputError("model listing is missing the SDK version")
        return {"models": models, "sdk_version": sdk_version.strip()}

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
                "debug retention requires the exact repo content/run or OS temp root"
            )
        request_dir = _create_request_directory(parent_dir)
        lifecycle = _LifecycleState()
        try:
            _ensure_isolated_request_dir(request_dir, parent_dir)
            request_dir = request_dir.resolve(strict=True)
            _write_request_file(request_dir, payload)
            _ensure_isolated_request_dir(request_dir, parent_dir)
            _reject_private_markers(json.dumps(payload, sort_keys=True))
            endpoint = self._local_runtime()
            image_digest = self._ensure_mount_probe(
                endpoint,
                request_dir,
                lifecycle,
            )
            container_name = _validate_cli_value(
                _container_name(request_dir),
                name="container name",
            )
            completed = self._run_worker(
                endpoint=endpoint,
                request_dir=request_dir,
                container_name=container_name,
                image_digest=image_digest,
                lifecycle=lifecycle,
            )
            _ensure_isolated_request_dir(request_dir, parent_dir)
            return self._load_result(request_dir, completed)
        finally:
            if self._config.debug_retain and lifecycle.can_retain:
                _verify_retained_request_path(request_dir, parent_dir)
            else:
                _remove_request_path(request_dir)
                if (
                    self._config.debug_retain
                    and not lifecycle.can_retain
                    and sys.exc_info()[0] is None
                ):
                    raise SecurityCleanupError(
                        "debug retention requires proven container absence"
                    )

    def _local_runtime(self) -> LocalRuntime:
        resolver = self._endpoint_resolver or discover_local_runtime
        endpoint = resolver(self._config.runtime)
        if type(endpoint) is not LocalRuntime:
            raise RuntimeEndpointError(
                "runtime resolver did not return a verified LocalRuntime"
            )
        if endpoint.kind != self._config.runtime:
            raise RuntimeEndpointError("runtime resolver returned the wrong runtime")
        endpoint = _revalidate_local_runtime(endpoint)
        if self._config.socket is not None:
            try:
                configured_socket = Path(self._config.socket).resolve(strict=True)
            except OSError as err:
                raise RuntimeEndpointError(
                    "configured runtime socket is unavailable"
                ) from err
            if endpoint.socket != configured_socket:
                raise RuntimeEndpointError(
                    "runtime resolver returned a different socket than configured"
                )
        return endpoint

    def _endpoint_subprocess_env(
        self,
        endpoint: LocalRuntime,
    ) -> dict[str, str]:
        return _endpoint_environment(_revalidate_local_runtime(endpoint))

    def _inspect_image_digest(self, endpoint: LocalRuntime) -> str:
        command = [
            str(endpoint.binary),
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "--",
            self._config.image,
        ]
        try:
            completed = self._runner.run(
                command,
                env=self._endpoint_subprocess_env(endpoint),
                timeout=self._config.timeout,
            )
        except Exception as err:
            raise MountProbeError(
                self._redact_text(err or "worker image inspection failed")
            ) from err
        digest = completed.stdout.strip()
        if completed.returncode != 0 or not _IMAGE_DIGEST_RE.fullmatch(digest):
            raise MountProbeError("worker image has no verified immutable digest")
        if _IMAGE_DIGEST_RE.fullmatch(self._config.image) and (
            digest != self._config.image
        ):
            raise MountProbeError(
                "immutable worker image resolved to a different digest"
            )
        return digest

    def _ensure_mount_probe(
        self,
        endpoint: LocalRuntime,
        request_dir: Path,
        lifecycle: _LifecycleState,
    ) -> str:
        image_digest = self._inspect_image_digest(endpoint)
        self._perform_mount_probe(
            endpoint=endpoint,
            request_dir=request_dir,
            image_digest=image_digest,
            lifecycle=lifecycle,
        )
        return image_digest

    def _perform_mount_probe(
        self,
        *,
        endpoint: LocalRuntime,
        request_dir: Path,
        image_digest: str,
        lifecycle: _LifecycleState,
    ) -> None:
        nonce = secrets.token_hex(32).encode("ascii")
        _write_named_file_nofollow(
            request_dir,
            ".mount-probe-input",
            nonce,
        )
        probe_identity = "|".join(
            (
                endpoint.binary_identity,
                endpoint.socket_identity,
                image_digest,
                str(request_dir),
            )
        )
        probe_digest = hashlib.sha256(probe_identity.encode("utf-8")).hexdigest()[:24]
        container_name = f"pgrep-probe-{probe_digest}"
        command = self._probe_command(
            endpoint=endpoint,
            request_dir=request_dir,
            container_name=container_name,
            image_digest=image_digest,
        )
        try:
            try:
                completed = self._run_named_container(
                    endpoint=endpoint,
                    command=command,
                    container_name=container_name,
                    timeout=self._config.timeout,
                    lifecycle=lifecycle,
                )
            except SecurityCleanupError:
                raise
            except subprocess.TimeoutExpired as err:
                raise MountProbeError("mount nonce probe timed out") from err
            except Exception as err:
                raise MountProbeError(
                    self._redact_text(err or "mount nonce probe failed")
                ) from err
            if completed.returncode != 0:
                raise MountProbeError("mount nonce probe process failed")
            _ensure_isolated_request_dir(request_dir, request_dir.parent)
            try:
                returned = _read_named_file_nofollow(
                    request_dir,
                    ".mount-probe-output",
                    max_bytes=MAX_PROBE_BYTES,
                )
            except FileNotFoundError as err:
                raise MountProbeError("mount nonce probe produced no output") from err
            if returned != nonce:
                raise MountProbeError("mount nonce probe returned the wrong value")
        finally:
            self._remove_probe_artifacts(request_dir)

    def _remove_probe_artifacts(self, request_dir: Path) -> None:
        for filename in (".mount-probe-input", ".mount-probe-output"):
            _unlink_named_file_nofollow(request_dir, filename)
        _ensure_isolated_request_dir(request_dir, request_dir.parent)

    def _host_user(self) -> str:
        if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
            raise RuntimeEndpointError("host uid:gid is required for Docker runs")
        return f"{os.getuid()}:{os.getgid()}"

    def _probe_command(
        self,
        *,
        endpoint: LocalRuntime,
        request_dir: Path,
        container_name: str,
        image_digest: str,
    ) -> list[str]:
        return [
            str(endpoint.binary),
            "run",
            "--rm",
            "--name",
            _validate_cli_value(container_name, name="container name"),
            *_DOCKER_HARDENING_OPTIONS,
            "--network",
            "none",
            "--user",
            self._host_user(),
            "--entrypoint",
            "/bin/sh",
            "--volume",
            f"{request_dir}:{WORK_MOUNT}",
            "--workdir",
            WORK_MOUNT,
            "--",
            image_digest,
            "-c",
            ("umask 077; cat /work/.mount-probe-input > /work/.mount-probe-output"),
        ]

    def _run_worker(
        self,
        *,
        endpoint: LocalRuntime,
        request_dir: Path,
        container_name: str,
        image_digest: str,
        lifecycle: _LifecycleState,
    ) -> CommandResult:
        command = self._run_command(
            endpoint,
            request_dir,
            container_name,
            image_digest,
        )
        environment = self._run_subprocess_env(endpoint)
        try:
            return self._run_named_container(
                endpoint=endpoint,
                command=command,
                container_name=container_name,
                timeout=self._config.timeout,
                environment=environment,
                lifecycle=lifecycle,
            )
        except SecurityCleanupError:
            raise
        except BaseException as err:
            if isinstance(err, subprocess.TimeoutExpired):
                raise SandboxTimeout(
                    f"worker timed out after {self._config.timeout} seconds"
                ) from err
            if isinstance(err, Exception):
                raise SandboxProcessError(
                    self._redact_text(err or "worker process failed")
                ) from err
            raise

    def _run_named_container(
        self,
        *,
        endpoint: LocalRuntime,
        command: Sequence[str],
        container_name: str,
        timeout: float,
        lifecycle: _LifecycleState,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        if environment is None:
            environment = self._endpoint_subprocess_env(endpoint)
        lifecycle.container_starting()
        try:
            completed = self._runner.run(
                command,
                env=environment,
                timeout=timeout,
            )
        except BaseException as primary:
            lifecycle.forbid_retention()
            try:
                self._remove_and_verify_container(
                    endpoint,
                    container_name,
                    lifecycle,
                )
            except SecurityCleanupError as cleanup:
                raise cleanup from primary
            raise
        if completed.returncode < 0:
            lifecycle.forbid_retention()
        self._remove_and_verify_container(
            endpoint,
            container_name,
            lifecycle,
        )
        return completed

    def _remove_and_verify_container(
        self,
        endpoint: LocalRuntime,
        container_name: str,
        lifecycle: _LifecycleState,
    ) -> None:
        name = _validate_cli_value(container_name, name="container name")
        try:
            environment = self._endpoint_subprocess_env(endpoint)
        except Exception as err:
            lifecycle.forbid_retention()
            raise SecurityCleanupError(
                f"could not reach local endpoint to remove container: {name}"
            ) from err
        remove_command = [
            str(endpoint.binary),
            "rm",
            "-f",
            "--",
            name,
        ]
        remove_error: BaseException | None = None
        remove_result: CommandResult | None = None
        try:
            remove_result = self._runner.run(
                remove_command,
                env=environment,
                timeout=DEFAULT_CLEANUP_TIMEOUT_SECONDS,
            )
        except BaseException as err:
            remove_error = err
            lifecycle.forbid_retention()

        inspect_command = [
            str(endpoint.binary),
            "container",
            "inspect",
            "--format",
            "{{.Id}}",
            "--",
            name,
        ]
        try:
            inspected = self._runner.run(
                inspect_command,
                env=environment,
                timeout=DEFAULT_CLEANUP_TIMEOUT_SECONDS,
            )
        except BaseException as err:
            lifecycle.forbid_retention()
            raise SecurityCleanupError(
                f"could not verify container absence: {name}"
            ) from (remove_error or err)
        rendered_error = inspected.stderr.lower()
        absent = (
            inspected.returncode != 0
            and not inspected.stdout.strip()
            and any(marker in rendered_error for marker in _ABSENT_CONTAINER_MARKERS)
        )
        if not absent:
            lifecycle.forbid_retention()
            raise SecurityCleanupError(
                f"container could not be proven absent: {name}"
            ) from remove_error
        lifecycle.prove_absence()
        if remove_error is not None or remove_result is None:
            lifecycle.forbid_retention()
            raise SecurityCleanupError(
                f"container removal command failed: {name}"
            ) from remove_error

    def _run_command(
        self,
        endpoint: LocalRuntime,
        request_dir: Path,
        container_name: str,
        image_digest: str,
    ) -> list[str]:
        # Only the request directory is mounted, the key is forwarded by name,
        # and network stays on the bridge/default path so the container can
        # reach the Cursor API without host networking.
        command = [
            str(endpoint.binary),
            "run",
            "--rm",
            "--name",
            _validate_cli_value(container_name, name="container name"),
            *_DOCKER_HARDENING_OPTIONS,
            "--user",
            self._host_user(),
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
                image_digest,
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

    def _run_subprocess_env(
        self,
        endpoint: LocalRuntime,
    ) -> dict[str, str]:
        env = self._endpoint_subprocess_env(endpoint)
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
