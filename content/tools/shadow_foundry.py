# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Quarantined multi-model shadow-foundry CLI.

The host retrieves corpus excerpts, the Task 3 Docker sandbox runs exact
Sol/Opus/Grok models, and finalized artifacts remain under the repository's
git-ignored shadow-foundry root. Success is impossible unless the complete
portfolio and its replay metadata satisfy the strict manifest contract.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

import _ai_path  # noqa: E402

_AI_ROOT = Path(_ai_path.add_ai_core()).resolve()

import cursor_sandbox  # noqa: E402
from pgrep.ai import (  # type: ignore[import-not-found]  # noqa: E402
    generation_core,
    model_backend,
    provenance,
    shadow_portfolio,
)

REPO_ROOT = _AI_ROOT.parents[1]
WORKER_CONTEXT = REPO_ROOT / "tools" / "shadow_worker"
QUARANTINE_ROOT = REPO_ROOT / "content" / "run" / "shadow-foundry"
DEFAULT_OUTPUT_ROOT = QUARANTINE_ROOT
DEFAULT_N = 3
DEFAULT_TOPIC = "mechanics/circular-motion"
DEFAULT_SEED = 7
DEFAULT_REASONING = "high"

SUCCESS_MARKER = "_SUCCESS"
FAILED_MARKER = "_FAILED"
MANIFEST_VERSION = "pgrep-shadow-run/v2"

_FAMILIES = ("sol", "opus", "grok")
_WORKER_FILES = ("Dockerfile", "pyproject.toml", "uv.lock", "worker.py")
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_PRIVATE_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"(?:gold|ets|gr9677|gr1777)(?=$|[-_/:\\])"
    r"|held[\s_-]*out(?=$|[\s_/:\\-])"
    r"|tier[\s_-]*3(?=$|[\s_/:\\-])"
    r")"
)
_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:^|[\s\"'=(:])(?:/Users/|/home/|/var/|/tmp/|/private/|"
    r"/run/|/etc/|[A-Za-z]:\\|\\\\[^\\\s]+\\)"
)
_RELATIVE_PATH = re.compile(
    r"(?i)(?:^|[\s\"'=(:])(?:\.\.?/|~/|"
    r"(?:content|pylib|qt|rslib|tools|docs_pgrep|\.git)/)"
    r"|(?<![A-Za-z0-9])(?:[A-Za-z0-9_.-]+/)+"
    r"[A-Za-z0-9_.-]+\.(?:jsonl?|db|sqlite|pdf|py|toml|yaml|yml|env)\b"
)
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*)"
        r"(?:(?:bearer|basic|token)\s+)?[^\s;,]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-=]+"),
    re.compile(r"(?i)(\bapi[-_ ]?key\s*[:=]\s*)[^\s;,]+"),
    re.compile(
        r"(?i)\b(?:cursor|crsr)_[A-Za-z0-9._-]{6,}\b"
        r"|\bsk-[A-Za-z0-9._-]{6,}\b"
    ),
)
_FORBIDDEN_PATH_KEYS = frozenset(
    {
        "source_file",
        "source_path",
        "filesystem_path",
        "file_path",
        "working_directory",
        "cwd",
        "home",
    }
)
_SOURCE_REF_KEYS = frozenset({"source_ref", "source_refs"})

_TOP_LEVEL_FIELDS = frozenset(
    {
        "manifest_version",
        "mode",
        "status",
        "run_id",
        "training_eligible",
        "expected_candidate_count",
        "candidate_count",
        "failure_count",
        "origins",
        "roles",
        "probe",
        "code",
        "worker",
        "corpus_index",
        "topic",
        "allocation",
        "seeds",
        "choice_permutations",
        "prompt_versions",
        "schema_versions",
        "request_traces",
        "artifacts",
    }
)
_TRACE_FIELDS = frozenset(
    {
        "slot",
        "phase",
        "attempt",
        "request_hash",
        "role",
        "family",
        "requested_model_id",
        "actual_model_id",
        "prompt_version",
        "schema_version",
        "seed",
        "choice_order",
        "agent_id",
        "run_id",
        "status",
        "parser_outcome",
        "parse_error",
    }
)

SearchFn = Callable[..., Sequence[object]]


class ShadowLeakageError(ValueError):
    """A private marker, filesystem path, or unsafe key crossed the firewall."""


class PublicationCleanupError(RuntimeError):
    """A failed publication could not be cleaned up completely."""


class ShadowRunFailed(RuntimeError):
    """A shadow run finalized a diagnostic artifact instead of succeeding."""

    def __init__(self, run_dir: Path, message: str) -> None:
        self.run_dir = run_dir
        super().__init__(f"{message}; diagnostic run: {run_dir}")


@dataclass(frozen=True)
class RunEnvironment:
    """Host and sandbox metadata frozen before candidate retrieval."""

    code_sha: str
    tree_status: str
    worker_image: str
    worker_image_digest: str | None
    corpus_index_fingerprint: str | None
    probe: Mapping[str, object]

    def __post_init__(self) -> None:
        if not _SHA_RE.fullmatch(self.code_sha):
            raise ValueError("code SHA must be a complete hexadecimal commit ID")
        if self.tree_status not in {"clean", "dirty"}:
            raise ValueError("tree status must be clean or dirty")
        _non_empty_string(self.worker_image, name="worker image")
        if self.worker_image_digest is not None and not _DIGEST_RE.fullmatch(
            self.worker_image_digest
        ):
            raise ValueError("worker image digest must be sha256")
        if self.corpus_index_fingerprint is not None and not _DIGEST_RE.fullmatch(
            self.corpus_index_fingerprint
        ):
            raise ValueError("corpus index fingerprint must be sha256")
        _validate_probe(self.probe, allow_incomplete=True)


@dataclass(frozen=True)
class PreparedSandbox:
    """A verified Task 3 sandbox and immutable worker identity."""

    sandbox: cursor_sandbox.CursorSandbox
    image: str
    image_digest: str
    runtime: str
    socket: str


class SandboxFactory(Protocol):
    def __call__(
        self,
        config: cursor_sandbox.SandboxConfig,
        **kwargs: object,
    ) -> cursor_sandbox.CursorSandbox: ...


def _strict_json(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


class PublicationIO:
    """Injectable filesystem seam for atomic publication tests."""

    def dumps(self, value: object) -> str:
        return _strict_json(value)

    def create_lock(self, path: Path) -> int:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, f"pid={os.getpid()}\n".encode())
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            path.unlink()
            raise
        return fd

    def create_temp(self, root: Path, run_id: str) -> Path:
        return Path(tempfile.mkdtemp(prefix=f".{run_id}.", suffix=".tmp", dir=root))

    def write_payload(self, path: Path, content: str) -> None:
        _write_exclusive(path, content)

    def reserve_final(self, path: Path) -> None:
        path.mkdir(mode=0o700, exist_ok=False)

    def link_payload(self, source: Path, destination: Path) -> None:
        os.link(source, destination, follow_symlinks=False)

    def write_marker(self, path: Path, content: str) -> None:
        _write_exclusive(path, content)

    def cleanup_tree(self, path: Path) -> None:
        _remove_tree_verified(path)

    def remove_lock(self, path: Path) -> None:
        path.unlink()
        if path.exists() or path.is_symlink():
            raise PublicationCleanupError(f"publication lock remains: {path}")


def _non_empty_string(value: object, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _utc_timestamp(value: str | None = None) -> str:
    if value is None:
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError("probe time must be ISO-8601") from err
    if parsed.tzinfo is None:
        raise ValueError("probe time must include a timezone")
    return value


def _canonical_hash(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()


def _redact_string(value: str, secrets: Sequence[str] = ()) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[1].sub("Bearer [REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[2].sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[3].sub("[REDACTED]", redacted)
    return redacted


def _redact_value(value: object, secrets: Sequence[str] = ()) -> object:
    if type(value) is str:
        return _redact_string(value, secrets)
    if type(value) is dict:
        return {
            str(key): _redact_value(nested, secrets)
            for key, nested in cast(dict[object, object], value).items()
        }
    if type(value) is list:
        return [_redact_value(nested, secrets) for nested in value]
    if type(value) is tuple:
        return [_redact_value(nested, secrets) for nested in value]
    return value


def _looks_like_filesystem_path(value: str) -> bool:
    if re.search(r"(?i)\bhttps?://", value):
        value = re.sub(r"(?i)\bhttps?://\S+", "", value)
    return bool(_ABSOLUTE_PATH.search(value) or _RELATIVE_PATH.search(value))


def _assert_safe_value(
    value: object,
    path: str = "$",
    *,
    source_reference: bool = False,
) -> None:
    if type(value) is str:
        if marker := _PRIVATE_MARKER.search(value):
            raise ShadowLeakageError(
                f"{path}: private marker {marker.group(0)!r} is forbidden"
            )
        if not source_reference and _looks_like_filesystem_path(value):
            raise ShadowLeakageError(f"{path}: filesystem path is forbidden")
        return
    if type(value) is dict:
        for raw_key, nested in cast(dict[object, object], value).items():
            key = str(raw_key)
            child = f"{path}.{key}"
            lowered = key.lower()
            if lowered in _FORBIDDEN_PATH_KEYS:
                raise ShadowLeakageError(f"{child}: path field is forbidden")
            if marker := _PRIVATE_MARKER.search(key):
                raise ShadowLeakageError(
                    f"{child}: private marker {marker.group(0)!r} is forbidden"
                )
            _assert_safe_value(
                nested,
                child,
                source_reference=lowered in _SOURCE_REF_KEYS,
            )
        return
    if type(value) is list or type(value) is tuple:
        for index, nested in enumerate(value):
            _assert_safe_value(
                nested,
                f"{path}[{index}]",
                source_reference=source_reference,
            )


def _sanitize_for_publication(
    value: object,
    *,
    secrets: Sequence[str] = (),
) -> object:
    redacted = _redact_value(value, secrets)
    _assert_safe_value(redacted)
    return redacted


def _safe_failure_message(error: BaseException, secrets: Sequence[str]) -> str:
    message = _redact_string(str(error) or type(error).__name__, secrets)
    if _PRIVATE_MARKER.search(message) or _looks_like_filesystem_path(message):
        return "[REDACTED unsafe failure detail]"
    return message


def _validate_run_id(run_id: str) -> None:
    if (
        not run_id.strip()
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
        or "\\" in run_id
    ):
        raise ValueError("run ID must be a non-empty directory name")
    _assert_safe_value(run_id, "run_id")


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"output root contains a symlink component: {current}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _git_ignored_quarantine_root() -> None:
    relative = QUARANTINE_ROOT.relative_to(REPO_ROOT)
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(relative)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        timeout=5,
    )
    if completed.returncode != 0:
        raise ValueError("shadow quarantine root is not git-ignored")


def validate_output_root(
    output_root: Path | str,
    *,
    allow_test_output: bool = False,
) -> Path:
    """Accept the exact quarantine root, or an injected OS-temp test root."""
    requested = Path(output_root).absolute()
    _reject_symlink_components(requested)
    canonical = QUARANTINE_ROOT.absolute()
    if requested == canonical:
        _git_ignored_quarantine_root()
        return requested
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved_parent = requested.parent.resolve(strict=True)
    if allow_test_output and _is_relative_to(resolved_parent, temp_root):
        return requested
    raise ValueError(
        "CLI output must be the repository's exact git-ignored "
        "content/run/shadow-foundry root"
    )


def _ensure_directory_chain(root: Path) -> None:
    boundary = (
        REPO_ROOT
        if root == QUARANTINE_ROOT.absolute()
        else Path(tempfile.gettempdir()).resolve()
    )
    if not _is_relative_to(root, boundary):
        raise ValueError("output root escaped its allowed boundary")
    _reject_symlink_components(boundary)
    current = boundary
    for part in root.relative_to(boundary).parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"output root component is unsafe: {current}")
    _reject_symlink_components(root)


def _write_exclusive(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _remove_tree_verified(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise PublicationCleanupError(f"refusing to clean symlink: {path}")
    shutil.rmtree(path)
    if path.exists() or path.is_symlink():
        raise PublicationCleanupError(f"publication directory remains: {path}")


def _validate_exact_fields(
    value: Mapping[str, object],
    required: frozenset[str],
    *,
    name: str,
) -> None:
    actual = frozenset(value)
    if actual != required:
        missing = sorted(required - actual)
        unexpected = sorted(actual - required)
        raise ValueError(
            f"{name} fields are invalid; missing={missing}; unexpected={unexpected}"
        )


def _model_family(model_id: str) -> str | None:
    normalized = model_id.lower()
    matches = {
        "sol": bool(
            re.search(r"(?<![a-z0-9])gpt(?![a-z0-9])", normalized)
            and re.search(r"(?<!\d)5[._-]6(?!\d)", normalized)
            and re.search(r"(?<![a-z0-9])sol(?![a-z0-9])", normalized)
        ),
        "opus": bool(
            re.search(r"(?<![a-z0-9])claude(?![a-z0-9])", normalized)
            and re.search(r"(?<![a-z0-9])opus(?![a-z0-9])", normalized)
            and re.search(r"(?<!\d)4[._-]8(?!\d)", normalized)
        ),
        "grok": bool(
            re.search(r"(?<![a-z0-9])grok(?![a-z0-9])", normalized)
            and re.search(r"(?<!\d)4[._-]5(?!\d)", normalized)
        ),
    }
    families = [family for family, matched in matches.items() if matched]
    return families[0] if len(families) == 1 else None


def make_probe_metadata(
    models: Sequence[Mapping[str, object]] | Sequence[object],
    *,
    sdk_version: str,
    probed_at: str | None = None,
) -> dict[str, object]:
    """Normalize the complete account catalog and bind its content hash."""
    normalized: list[dict[str, object]] = []
    for index, entry in enumerate(models):
        if not isinstance(entry, Mapping):
            raise ValueError(f"models[{index}] must be an object")
        model_id = _non_empty_string(
            entry.get("id") or entry.get("model_id"),
            name=f"models[{index}].id",
        )
        normalized.append(
            {
                "id": model_id,
                "parameters": copy.deepcopy(entry.get("parameters", [])),
                "variants": copy.deepcopy(entry.get("variants", [])),
            }
        )
    normalized.sort(key=lambda item: cast(str, item["id"]))
    safe_models = cast(
        list[dict[str, object]],
        _sanitize_for_publication(normalized),
    )
    payload: dict[str, object] = {
        "models": safe_models,
        "sdk_version": _non_empty_string(sdk_version, name="SDK version"),
        "probed_at": _utc_timestamp(probed_at),
        "model_catalog_hash": _canonical_hash(safe_models),
    }
    _validate_probe(payload, allow_incomplete=True)
    return payload


def _validate_probe(
    probe: Mapping[str, object],
    *,
    allow_incomplete: bool,
) -> None:
    _validate_exact_fields(
        probe,
        frozenset({"models", "sdk_version", "probed_at", "model_catalog_hash"}),
        name="probe",
    )
    models = probe["models"]
    if not isinstance(models, list):
        raise ValueError("probe models must be an array")
    if not allow_incomplete and not models:
        raise ValueError("success probe must contain the complete model catalog")
    sdk_version = _non_empty_string(probe["sdk_version"], name="probe SDK version")
    if not allow_incomplete and sdk_version == "unavailable":
        raise ValueError("success probe must record the actual SDK version")
    _utc_timestamp(_non_empty_string(probe["probed_at"], name="probe time"))
    expected_hash = _canonical_hash(models)
    if probe["model_catalog_hash"] != expected_hash:
        raise ValueError("probe model catalog hash does not match the catalog")
    for index, model in enumerate(models):
        if not isinstance(model, Mapping):
            raise ValueError(f"probe.models[{index}] must be an object")
        _validate_exact_fields(
            model,
            frozenset({"id", "parameters", "variants"}),
            name=f"probe.models[{index}]",
        )
        _non_empty_string(model["id"], name=f"probe.models[{index}].id")


def validate_exact_roles(
    roles: shadow_portfolio.ModelRoles,
    probe_models: Sequence[Mapping[str, object]] | Sequence[object],
) -> list[str]:
    """Require exact, distinct, semantically correct account-listed IDs."""
    if type(roles) is not shadow_portfolio.ModelRoles:
        raise TypeError("roles must be ModelRoles")
    available: set[str] = set()
    for index, entry in enumerate(probe_models):
        model_id = (
            entry.get("id") or entry.get("model_id")
            if isinstance(entry, Mapping)
            else entry
        )
        available.add(_non_empty_string(model_id, name=f"probe_models[{index}].id"))
    requested = {
        "sol": roles.sol.model_id,
        "opus": roles.opus.model_id,
        "grok": roles.grok.model_id,
    }
    if len(set(requested.values())) != 3:
        raise ValueError("exact model roles must use distinct model IDs")
    for family, model_id in requested.items():
        lowered = model_id.lower()
        if lowered == "auto" or lowered.startswith("auto/"):
            raise ValueError("auto/substitution is forbidden for shadow model roles")
        if _model_family(model_id) != family:
            raise ValueError(
                f"{family} model {model_id!r} does not match its family identity"
            )
        if model_id not in available:
            raise ValueError(
                f"exact model {model_id!r} for {family} is not in the account probe"
            )
    return [requested[family] for family in _FAMILIES]


def format_probe(
    models: Sequence[Mapping[str, object]] | Sequence[object],
) -> tuple[str, dict[str, object]]:
    rows: list[dict[str, object]] = []
    lines = ["Available Cursor models:"]
    for index, entry in enumerate(models):
        model_id = (
            entry.get("id") or entry.get("model_id")
            if isinstance(entry, Mapping)
            else entry
        )
        model_id_s = _non_empty_string(model_id, name=f"models[{index}].id")
        rows.append({"id": model_id_s})
        lines.append(f"  - {model_id_s}")
    return "\n".join(lines) + "\n", {"models": rows, "count": len(rows)}


def _retrieved_field(item: object, name: str) -> object:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def sanitize_retrieved(chunks: Sequence[object]) -> list[dict[str, object]]:
    """Project host retrieval to fields needed by prompting and provenance."""
    if not chunks:
        raise ValueError("retrieved context must be non-empty")
    sanitized: list[dict[str, object]] = []
    for index, item in enumerate(chunks):
        chunk_id = _non_empty_string(
            _retrieved_field(item, "chunk_id"),
            name=f"retrieved[{index}].chunk_id",
        )
        source_ref = _non_empty_string(
            _retrieved_field(item, "source_ref"),
            name=f"retrieved[{index}].source_ref",
        )
        source_title = _non_empty_string(
            _retrieved_field(item, "source_title"),
            name=f"retrieved[{index}].source_title",
        )
        text = _non_empty_string(
            _retrieved_field(item, "text"),
            name=f"retrieved[{index}].text",
        )
        score = _retrieved_field(item, "score")
        if type(score) not in (int, float):
            raise ValueError(f"retrieved[{index}].score must be finite")
        numeric_score = cast(int | float, score)
        if not math.isfinite(float(numeric_score)):
            raise ValueError(f"retrieved[{index}].score must be finite")
        projected = {
            "chunk_id": chunk_id,
            "source_ref": source_ref,
            "source_title": source_title,
            "text": text,
            "score": float(numeric_score),
        }
        _assert_safe_value(projected, f"retrieved[{index}]")
        sanitized.append(projected)
    return sanitized


def collect_repo_state(
    *,
    repo_root: Path = REPO_ROOT,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> tuple[str, str]:
    """Record an exact commit ID and clean/dirty worktree state."""
    revision = runner(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        timeout=5,
    )
    sha = revision.stdout.decode().strip()
    if revision.returncode != 0 or not _SHA_RE.fullmatch(sha):
        raise RuntimeError("could not resolve an exact repository code SHA")
    status = runner(
        ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        timeout=5,
    )
    if status.returncode != 0:
        raise RuntimeError("could not determine repository tree status")
    return sha, "dirty" if status.stdout.strip() else "clean"


def file_fingerprint(path: Path | str) -> str:
    """Hash a regular, non-symlink file for replay identity."""
    candidate = Path(path)
    _reject_symlink_components(candidate)
    try:
        info = candidate.lstat()
    except OSError as err:
        raise RuntimeError(
            f"required fingerprint input is unavailable: {candidate.name}"
        ) from err
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"fingerprint input is not a regular file: {candidate.name}")
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def worker_context_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in _WORKER_FILES:
        path = WORKER_CONTEXT / name
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(file_fingerprint(path).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def worker_image_tag() -> str:
    return f"pgrep-shadow-worker:{worker_context_fingerprint()[:16]}"


def prepare_real_sandbox(
    api_key: str,
    *,
    force_build: bool = False,
    runtime_detector: Callable[[], str] = cursor_sandbox.detect_runtime,
    runtime_discoverer: Callable[[str], object] = cursor_sandbox.discover_local_runtime,
    sandbox_factory: SandboxFactory = cursor_sandbox.CursorSandbox,
) -> PreparedSandbox:
    """Discover local Docker and build or locate the pinned worker image."""
    runtime = runtime_detector()
    endpoint = runtime_discoverer(runtime)
    kind = _non_empty_string(getattr(endpoint, "kind", ""), name="runtime kind")
    socket = str(getattr(endpoint, "socket", ""))
    if not socket or not Path(socket).is_absolute():
        raise cursor_sandbox.RuntimeEndpointError(
            "verified runtime did not provide an absolute local socket"
        )
    image = worker_image_tag()
    config = cursor_sandbox.SandboxConfig(
        runtime=kind,
        socket=socket,
        image=image,
    )
    sandbox = sandbox_factory(
        config,
        api_key=api_key,
        endpoint_resolver=lambda _runtime: endpoint,
    )
    if force_build:
        sandbox.build_image(context=WORKER_CONTEXT)
    try:
        digest = sandbox.image_digest()
    except cursor_sandbox.MountProbeError:
        if force_build:
            raise
        sandbox.build_image(context=WORKER_CONTEXT)
        digest = sandbox.image_digest()
    if not _DIGEST_RE.fullmatch(digest):
        raise cursor_sandbox.MountProbeError(
            "worker image has no verified immutable digest"
        )
    return PreparedSandbox(
        sandbox=sandbox,
        image=image,
        image_digest=digest,
        runtime=kind,
        socket=socket,
    )


def _trace_summary(
    trace: Mapping[str, object],
    *,
    slot: int,
    choice_order: Sequence[str] | None,
    secrets: Sequence[str],
) -> dict[str, object]:
    safe = cast(
        Mapping[str, object],
        _sanitize_for_publication(copy.deepcopy(dict(trace)), secrets=secrets),
    )
    request = safe.get("request")
    result = safe.get("result")
    if not isinstance(request, Mapping) or not isinstance(result, Mapping):
        raise ValueError("trace must contain request and result objects")
    model = request.get("model")
    if not isinstance(model, Mapping):
        raise ValueError("trace request must contain model metadata")
    parse_error = safe.get("parse_error")
    attempt = safe.get("attempt", 0)
    seed = request.get("seed", 0)
    if type(attempt) is not int or type(seed) is not int:
        raise ValueError("trace attempt and seed must be integers")
    return {
        "slot": slot,
        "phase": _non_empty_string(safe.get("phase"), name="trace phase"),
        "attempt": attempt,
        "request_hash": _non_empty_string(
            safe.get("request_hash"), name="request hash"
        ),
        "role": _non_empty_string(request.get("role"), name="trace role"),
        "family": _non_empty_string(model.get("family"), name="trace family"),
        "requested_model_id": _non_empty_string(
            model.get("model_id"), name="requested model"
        ),
        "actual_model_id": _non_empty_string(
            result.get("model_id"), name="actual model"
        ),
        "prompt_version": _non_empty_string(
            request.get("prompt_version"), name="prompt version"
        ),
        "schema_version": _non_empty_string(
            request.get("schema_version"), name="schema version"
        ),
        "seed": seed,
        "choice_order": list(choice_order) if choice_order is not None else None,
        "agent_id": _non_empty_string(result.get("agent_id"), name="agent ID"),
        "run_id": _non_empty_string(result.get("run_id"), name="run ID"),
        "status": _non_empty_string(result.get("status"), name="trace status"),
        "parser_outcome": "parsed" if parse_error is None else "parse_error",
        "parse_error": parse_error,
    }


def _sanitize_candidate_record(
    record: Mapping[str, object],
    *,
    slot: int,
    secrets: Sequence[str],
) -> dict[str, object]:
    redacted = cast(
        dict[str, object],
        _sanitize_for_publication(copy.deepcopy(dict(record)), secrets=secrets),
    )
    generator = redacted.get("generator")
    if not isinstance(generator, dict):
        raise ValueError("candidate generator metadata is missing")
    traces = generator.get("traces")
    if not isinstance(traces, list):
        raise ValueError("candidate generator traces are missing")
    generator["traces"] = [
        _trace_summary(
            cast(Mapping[str, object], trace),
            slot=slot,
            choice_order=None,
            secrets=secrets,
        )
        for trace in traces
        if isinstance(trace, Mapping)
    ]
    verifiers = redacted.get("verifiers")
    if not isinstance(verifiers, list) or len(verifiers) != 2:
        raise ValueError("candidate must contain exactly two verifier records")
    for verifier in verifiers:
        if not isinstance(verifier, dict):
            raise ValueError("verifier record must be an object")
        order = verifier.get("choice_order")
        trace = verifier.get("trace")
        if not isinstance(order, list) or not isinstance(trace, Mapping):
            raise ValueError("verifier trace or choice permutation is missing")
        verifier["trace"] = _trace_summary(
            trace,
            slot=slot,
            choice_order=cast(list[str], order),
            secrets=secrets,
        )
    redacted["slot"] = slot
    return redacted


def _candidate_provenance(record: Mapping[str, object]) -> None:
    candidate = record.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate payload is missing")
    if candidate.get("refuse") is True:
        return
    evidence = candidate.get("provenance")
    if not isinstance(evidence, Mapping):
        raise ValueError("non-refused candidate has no bound provenance")
    for field in ("source_ref", "chunk_id", "source_title"):
        _non_empty_string(evidence.get(field), name=f"provenance {field}")
    score = evidence.get("support_score")
    if type(score) not in (int, float) or not math.isfinite(float(score)):
        raise ValueError("provenance support score must be finite")
    if float(score) < provenance.MIN_SUPPORT_SCORE:
        raise ValueError("provenance support score is below the binding floor")


def _candidate_traces(record: Mapping[str, object]) -> list[dict[str, object]]:
    traces: list[dict[str, object]] = []
    generator = record.get("generator")
    if isinstance(generator, Mapping):
        traces.extend(cast(list[dict[str, object]], generator.get("traces", [])))
    verifiers = record.get("verifiers")
    if not isinstance(verifiers, list):
        return traces
    for verifier in verifiers:
        if isinstance(verifier, Mapping) and isinstance(verifier.get("trace"), dict):
            traces.append(cast(dict[str, object], verifier["trace"]))
    return traces


def _choice_permutations(
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    permutations: list[dict[str, object]] = []
    for record in candidates:
        raw_verifiers = record.get("verifiers")
        verifiers = raw_verifiers if isinstance(raw_verifiers, list) else []
        permutations.append(
            {
                "slot": record.get("slot"),
                "origin_family": record.get("origin_family"),
                "verifiers": [
                    {
                        "family": verifier.get("family"),
                        "choice_order": verifier.get("choice_order"),
                    }
                    for verifier in verifiers
                    if isinstance(verifier, Mapping)
                ],
            }
        )
    return permutations


def _roles_dict(
    roles: shadow_portfolio.ModelRoles,
) -> dict[str, dict[str, str]]:
    return {
        family: {
            "family": family,
            "model_id": roles.by_family(family).model_id,
        }
        for family in _FAMILIES
    }


def _dedupe_traces(
    traces: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for trace in traces:
        request_hash = str(trace.get("request_hash") or "")
        if request_hash and request_hash not in seen:
            seen.add(request_hash)
            deduped.append(dict(trace))
    return deduped


def build_run_manifest(
    *,
    run_id: str,
    status: str,
    roles: shadow_portfolio.ModelRoles,
    environment: RunEnvironment,
    topic: str,
    expected_candidate_count: int,
    seed: int,
    allocation: Sequence[str],
    candidates: Sequence[Mapping[str, object]],
    failures: Sequence[Mapping[str, object]],
    failure_traces: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build the one strict manifest shape used by success and diagnostics."""
    traces = [
        trace for candidate in candidates for trace in _candidate_traces(candidate)
    ]
    traces.extend(dict(trace) for trace in failure_traces)
    manifest: dict[str, object] = {
        "manifest_version": MANIFEST_VERSION,
        "mode": "shadow",
        "status": status,
        "run_id": run_id,
        "training_eligible": False,
        "expected_candidate_count": expected_candidate_count,
        "candidate_count": len(candidates),
        "failure_count": len(failures),
        "origins": sorted(
            {
                str(candidate.get("origin_family"))
                for candidate in candidates
                if candidate.get("origin_family")
            }
        ),
        "roles": _roles_dict(roles),
        "probe": copy.deepcopy(dict(environment.probe)),
        "code": {
            "sha": environment.code_sha,
            "tree_status": environment.tree_status,
        },
        "worker": {
            "image": environment.worker_image,
            "image_digest": environment.worker_image_digest,
        },
        "corpus_index": {
            "fingerprint": environment.corpus_index_fingerprint,
        },
        "topic": topic,
        "allocation": list(allocation),
        "seeds": {
            "portfolio": seed,
            "slots": [seed + index for index in range(expected_candidate_count)],
        },
        "choice_permutations": _choice_permutations(candidates),
        "prompt_versions": {
            "generator": shadow_portfolio.GENERATOR_PROMPT_VERSION,
            "correction": shadow_portfolio.CORRECTION_PROMPT_VERSION,
            "verifier": shadow_portfolio.VERIFIER_PROMPT_VERSION,
            "generation_core_problem": generation_core.PROBLEM_PROMPT_VERSION,
        },
        "schema_versions": {
            "problem": shadow_portfolio.SCHEMA_VERSION,
            "solve": shadow_portfolio.VERIFIER_SCHEMA_VERSION,
        },
        "request_traces": _dedupe_traces(traces),
        "artifacts": {
            "accepted_json": False,
            "preferences_jsonl": False,
            "bundle_mutation": False,
            "assemble_call": False,
        },
    }
    return cast(dict[str, object], _sanitize_for_publication(manifest))


def _validate_trace(
    trace: Mapping[str, object],
    roles: Mapping[str, object],
    *,
    success: bool,
) -> None:
    _validate_exact_fields(trace, _TRACE_FIELDS, name="request trace")
    request_hash = _non_empty_string(trace["request_hash"], name="request hash")
    if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
        raise ValueError("request hash must be SHA-256")
    family = _non_empty_string(trace["family"], name="trace family")
    if family not in _FAMILIES:
        raise ValueError("trace family is unknown")
    role = roles.get(family)
    if not isinstance(role, Mapping):
        raise ValueError("trace family has no manifest role")
    requested = _non_empty_string(
        trace["requested_model_id"], name="requested model ID"
    )
    if requested != role.get("model_id"):
        raise ValueError("trace requested model does not match its exact role")
    actual = trace["actual_model_id"]
    if success and actual != requested:
        raise ValueError("success trace actual model does not match requested model")
    if success:
        _non_empty_string(trace["agent_id"], name="trace agent ID")
        _non_empty_string(trace["run_id"], name="trace run ID")
        if trace["status"] != "finished":
            raise ValueError("success trace did not finish")
    if type(trace["attempt"]) is not int or type(trace["seed"]) is not int:
        raise ValueError("trace attempt and seed must be integers")
    if trace["parser_outcome"] not in {
        "parsed",
        "parse_error",
        "returned",
        "not_returned",
    }:
        raise ValueError("trace parser outcome is invalid")
    if trace["role"] == "verifier" and (success or trace["choice_order"] is not None):
        order = trace["choice_order"]
        if not isinstance(order, list) or sorted(order) != list("ABCDE"):
            raise ValueError("verifier trace choice permutation is invalid")


def _validate_verifier_records(
    verifiers: object,
    *,
    origin: str,
    roles: Mapping[str, object],
) -> None:
    if not isinstance(verifiers, list) or len(verifiers) != 2:
        raise ValueError("candidate must have exactly two cross-verifiers")
    verifier_families: set[str] = set()
    for verifier in verifiers:
        if not isinstance(verifier, Mapping):
            raise ValueError("candidate verifier record is invalid")
        family = verifier.get("family")
        if family not in _FAMILIES or family == origin:
            raise ValueError("candidate verifier family is not origin-blind")
        verifier_families.add(cast(str, family))
        if verifier.get("model_id") != cast(
            Mapping[str, object], roles[cast(str, family)]
        ).get("model_id"):
            raise ValueError("candidate verifier identity does not match its role")
        if not isinstance(verifier.get("trace"), Mapping):
            raise ValueError("candidate verifier trace is missing")
    if verifier_families != set(_FAMILIES) - {origin}:
        raise ValueError("candidate cross-verifier coverage is incomplete")


def _validate_candidate_structure(
    record: Mapping[str, object],
    *,
    roles: Mapping[str, object],
    expected_slot: int | None,
) -> None:
    slot = record.get("slot")
    if type(slot) is not int or (expected_slot is not None and slot != expected_slot):
        raise ValueError("candidate slot is invalid")
    origin_value = record.get("origin_family")
    if origin_value not in _FAMILIES:
        raise ValueError("candidate origin family is invalid")
    origin = cast(str, origin_value)
    generator = record.get("generator")
    if not isinstance(generator, Mapping):
        raise ValueError("candidate generator record is missing")
    role = cast(Mapping[str, object], roles[origin])
    if generator.get("family") != origin or generator.get("model_id") != role.get(
        "model_id"
    ):
        raise ValueError("candidate generator identity does not match its role")
    generator_traces = generator.get("traces")
    if not isinstance(generator_traces, list) or not generator_traces:
        raise ValueError("candidate generator traces are incomplete")
    _validate_verifier_records(
        record.get("verifiers"),
        origin=origin,
        roles=roles,
    )


def _validate_manifest_nested_objects(manifest: Mapping[str, object]) -> None:
    exact_shapes = {
        "code": frozenset({"sha", "tree_status"}),
        "worker": frozenset({"image", "image_digest"}),
        "corpus_index": frozenset({"fingerprint"}),
        "seeds": frozenset({"portfolio", "slots"}),
        "prompt_versions": frozenset(
            {"generator", "correction", "verifier", "generation_core_problem"}
        ),
        "schema_versions": frozenset({"problem", "solve"}),
        "artifacts": frozenset(
            {
                "accepted_json",
                "preferences_jsonl",
                "bundle_mutation",
                "assemble_call",
            }
        ),
    }
    for name, fields in exact_shapes.items():
        value = manifest[name]
        if not isinstance(value, Mapping):
            raise ValueError(f"manifest {name} must be an object")
        _validate_exact_fields(value, fields, name=f"manifest.{name}")
    expected_prompts = {
        "generator": shadow_portfolio.GENERATOR_PROMPT_VERSION,
        "correction": shadow_portfolio.CORRECTION_PROMPT_VERSION,
        "verifier": shadow_portfolio.VERIFIER_PROMPT_VERSION,
        "generation_core_problem": generation_core.PROBLEM_PROMPT_VERSION,
    }
    if manifest["prompt_versions"] != expected_prompts:
        raise ValueError("manifest prompt versions are not the exact current versions")
    expected_schemas = {
        "problem": shadow_portfolio.SCHEMA_VERSION,
        "solve": shadow_portfolio.VERIFIER_SCHEMA_VERSION,
    }
    if manifest["schema_versions"] != expected_schemas:
        raise ValueError("manifest schema versions are not the exact current versions")
    if any(cast(Mapping[str, object], manifest["artifacts"]).values()):
        raise ValueError("shadow manifest enables a forbidden training artifact")


def _manifest_status_and_counts(
    manifest: Mapping[str, object],
    *,
    candidates: Sequence[object],
    failures: Sequence[object],
) -> tuple[str, int, int, int]:
    status = manifest["status"]
    if status not in {"success", "failed"}:
        raise ValueError("manifest status is invalid")
    expected = manifest["expected_candidate_count"]
    candidate_count = manifest["candidate_count"]
    failure_count = manifest["failure_count"]
    if type(expected) is not int or expected < 1:
        raise ValueError("expected candidate count must be positive")
    if type(candidate_count) is not int or type(failure_count) is not int:
        raise ValueError("manifest candidate/failure counts must be integers")
    if candidate_count != len(candidates) or failure_count != len(failures):
        raise ValueError("manifest candidate/failure counts do not match artifacts")
    return (
        cast(str, status),
        expected,
        candidate_count,
        failure_count,
    )


def _manifest_roles(manifest: Mapping[str, object]) -> Mapping[str, object]:
    roles = manifest["roles"]
    if not isinstance(roles, Mapping) or set(roles) != set(_FAMILIES):
        raise ValueError("manifest must contain exactly three model roles")
    for family in _FAMILIES:
        role = roles[family]
        if not isinstance(role, Mapping):
            raise ValueError("manifest role must be an object")
        _validate_exact_fields(
            role,
            frozenset({"family", "model_id"}),
            name=f"roles.{family}",
        )
        if role["family"] != family:
            raise ValueError("manifest role family does not match its key")
    return roles


def _validate_manifest_environment(
    manifest: Mapping[str, object],
    *,
    status: str,
) -> Mapping[str, object]:
    code = cast(Mapping[str, object], manifest["code"])
    if not _SHA_RE.fullmatch(str(code.get("sha", ""))):
        raise ValueError("manifest code SHA is missing or unknown")
    if code.get("tree_status") not in {"clean", "dirty"}:
        raise ValueError("manifest tree status is invalid")
    probe = manifest["probe"]
    if not isinstance(probe, Mapping):
        raise ValueError("manifest probe is missing")
    _validate_probe(probe, allow_incomplete=status == "failed")
    worker = cast(Mapping[str, object], manifest["worker"])
    corpus = cast(Mapping[str, object], manifest["corpus_index"])
    _non_empty_string(worker.get("image"), name="worker image")
    if status == "success" and not _DIGEST_RE.fullmatch(
        str(worker.get("image_digest", ""))
    ):
        raise ValueError("success manifest has no worker image digest")
    if status == "success" and not _DIGEST_RE.fullmatch(
        str(corpus.get("fingerprint", ""))
    ):
        raise ValueError("success manifest has no corpus index fingerprint")
    return probe


def _manifest_allocation_and_traces(
    manifest: Mapping[str, object],
    *,
    expected: int,
    roles: Mapping[str, object],
    success: bool,
) -> tuple[list[object], list[object]]:
    allocation = manifest["allocation"]
    seeds = cast(Mapping[str, object], manifest["seeds"])
    if not isinstance(allocation, list) or len(allocation) != expected:
        raise ValueError("manifest allocation count is incomplete")
    slots = seeds.get("slots")
    if not isinstance(slots, list) or len(slots) != expected:
        raise ValueError("manifest slot seeds are incomplete")
    traces = manifest["request_traces"]
    if not isinstance(traces, list):
        raise ValueError("manifest request traces must be an array")
    for trace in traces:
        if not isinstance(trace, Mapping):
            raise ValueError("request trace must be an object")
        _validate_trace(trace, roles, success=success)
    return allocation, traces


def _validated_candidate_artifacts(
    candidates: Sequence[object],
    *,
    roles: Mapping[str, object],
) -> list[Mapping[str, object]]:
    validated: list[Mapping[str, object]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("candidate artifact must contain objects")
        _validate_candidate_structure(
            candidate,
            roles=roles,
            expected_slot=None,
        )
        _candidate_provenance(candidate)
        validated.append(candidate)
    return validated


def _validate_success_role_models(
    roles: Mapping[str, object],
    probe: Mapping[str, object],
) -> None:
    model_ids = {
        family: str(cast(Mapping[str, object], roles[family])["model_id"])
        for family in _FAMILIES
    }
    if len(set(model_ids.values())) != 3:
        raise ValueError("success roles must use distinct exact model IDs")
    for family, model_id in model_ids.items():
        if _model_family(model_id) != family:
            raise ValueError("success role has the wrong semantic family identity")
    validate_exact_roles(
        shadow_portfolio.ModelRoles(
            **{
                family: model_backend.ModelSpec(
                    family,
                    model_ids[family],
                    DEFAULT_REASONING,
                )
                for family in _FAMILIES
            }
        ),
        cast(list[Mapping[str, object]], probe["models"]),
    )


def _validate_success_portfolio(
    manifest: Mapping[str, object],
    *,
    expected: int,
    candidate_count: int,
    failure_count: int,
    allocation: Sequence[object],
    traces: Sequence[object],
    candidates: Sequence[Mapping[str, object]],
) -> None:
    origins = {str(candidate.get("origin_family")) for candidate in candidates}
    manifest_origins = manifest["origins"]
    if not isinstance(manifest_origins, list):
        raise ValueError("manifest origins must be an array")
    if (
        failure_count
        or candidate_count != expected
        or origins != set(_FAMILIES)
        or set(manifest_origins) != set(_FAMILIES)
        or not traces
    ):
        raise ValueError("success manifest does not contain a complete portfolio")
    slots = {candidate.get("slot") for candidate in candidates}
    if slots != set(range(expected)):
        raise ValueError("success candidate slots are incomplete")
    for candidate in candidates:
        slot = cast(int, candidate["slot"])
        if allocation[slot] != candidate.get("origin_family"):
            raise ValueError("candidate origin does not match its allocation")
    if manifest["choice_permutations"] != _choice_permutations(candidates):
        raise ValueError("manifest choice permutations do not match candidates")
    candidate_hashes = [
        trace["request_hash"]
        for candidate in candidates
        for trace in _candidate_traces(candidate)
    ]
    manifest_hashes = [
        cast(Mapping[str, object], trace)["request_hash"] for trace in traces
    ]
    if manifest_hashes != candidate_hashes:
        raise ValueError("manifest request traces do not match candidate traces")


def validate_manifest(
    manifest: Mapping[str, object],
    *,
    candidates: Sequence[object],
    failures: Sequence[object],
) -> None:
    """Reject any manifest that could produce a false finalized marker."""
    _validate_exact_fields(manifest, _TOP_LEVEL_FIELDS, name="manifest")
    if manifest["manifest_version"] != MANIFEST_VERSION:
        raise ValueError("manifest version is invalid")
    _validate_manifest_nested_objects(manifest)
    if manifest["mode"] != "shadow" or manifest["training_eligible"] is not False:
        raise ValueError("manifest must be shadow-only and not training eligible")
    status, expected, candidate_count, failure_count = _manifest_status_and_counts(
        manifest,
        candidates=candidates,
        failures=failures,
    )
    roles = _manifest_roles(manifest)
    probe = _validate_manifest_environment(manifest, status=status)
    allocation, traces = _manifest_allocation_and_traces(
        manifest,
        expected=expected,
        roles=roles,
        success=status == "success",
    )
    validated_candidates = _validated_candidate_artifacts(
        candidates,
        roles=roles,
    )
    if status == "success":
        _validate_success_role_models(roles, probe)
        _validate_success_portfolio(
            manifest,
            expected=expected,
            candidate_count=candidate_count,
            failure_count=failure_count,
            allocation=allocation,
            traces=traces,
            candidates=validated_candidates,
        )
    elif failure_count < 1:
        raise ValueError("failed manifest must contain actual failures")
    _assert_safe_value(manifest, "manifest")
    _assert_safe_value(list(candidates), "candidates")
    _assert_safe_value(list(failures), "failures")


def _cleanup_publication(
    io: PublicationIO,
    *,
    temporary: Path | None,
    final: Path | None,
    lock_path: Path,
    lock_fd: int | None,
    primary: BaseException,
) -> None:
    errors: list[BaseException] = []
    if lock_fd is not None:
        try:
            os.close(lock_fd)
        except OSError as err:
            errors.append(err)
    for path in (temporary, final):
        if path is None:
            continue
        try:
            io.cleanup_tree(path)
        except BaseException as err:
            errors.append(err)
    if lock_path.exists() or lock_path.is_symlink():
        try:
            io.remove_lock(lock_path)
        except BaseException as err:
            errors.append(err)
    if errors:
        raise PublicationCleanupError(
            f"publication cleanup failed: {type(errors[0]).__name__}"
        ) from primary


def publish_run(
    output_root: Path | str,
    run_id: str,
    *,
    candidates: Sequence[object],
    failures: Sequence[object],
    manifest: Mapping[str, object],
    allow_test_output: bool = False,
    io: PublicationIO | None = None,
) -> Path:
    """Finalize one success or diagnostic run with its marker written last."""
    _validate_run_id(run_id)
    root = validate_output_root(
        output_root,
        allow_test_output=allow_test_output,
    )
    _ensure_directory_chain(root)
    safe_candidates = cast(
        list[object], _sanitize_for_publication(copy.deepcopy(list(candidates)))
    )
    safe_failures = cast(
        list[object], _sanitize_for_publication(copy.deepcopy(list(failures)))
    )
    safe_manifest = cast(
        dict[str, object],
        _sanitize_for_publication(copy.deepcopy(dict(manifest))),
    )
    validate_manifest(
        safe_manifest,
        candidates=safe_candidates,
        failures=safe_failures,
    )
    status = cast(str, safe_manifest["status"])
    marker = SUCCESS_MARKER if status == "success" else FAILED_MARKER
    publisher = io or PublicationIO()
    payloads = {
        "manifest.json": safe_manifest,
        "candidates.json": safe_candidates,
        "failures.json": safe_failures,
    }
    rendered = {name: publisher.dumps(value) for name, value in payloads.items()}
    lock_path = root / f".{run_id}.lock"
    run_dir = root / run_id
    if run_dir.exists() or run_dir.is_symlink():
        raise ValueError(f"shadow run directory already exists: {run_dir}")

    lock_fd: int | None = None
    temporary: Path | None = None
    final: Path | None = None
    try:
        lock_fd = publisher.create_lock(lock_path)
        temporary = publisher.create_temp(root, run_id)
        for name, content in rendered.items():
            publisher.write_payload(temporary / name, content)
        publisher.reserve_final(run_dir)
        final = run_dir
        for name in rendered:
            publisher.link_payload(temporary / name, run_dir / name)
        publisher.cleanup_tree(temporary)
        temporary = None
        os.close(lock_fd)
        lock_fd = None
        publisher.remove_lock(lock_path)
        _reject_symlink_components(run_dir)
        publisher.write_marker(run_dir / marker, "ok\n")
        if not (run_dir / marker).is_file():
            raise OSError("final marker write could not be verified")
        final = None
        return run_dir
    except BaseException as error:
        _cleanup_publication(
            publisher,
            temporary=temporary,
            final=final,
            lock_path=lock_path,
            lock_fd=lock_fd,
            primary=error,
        )
        raise


def _failure_record(
    error: BaseException,
    *,
    stage: str,
    slot: int | None,
    origin: str | None,
    seed: int | None,
    secrets: Sequence[str],
) -> dict[str, object]:
    return {
        "stage": stage,
        "slot": slot,
        "origin_family": origin,
        "seed": seed,
        "error_type": type(error).__name__,
        "message": _safe_failure_message(error, secrets),
    }


def _error_trace_summaries(
    error: BaseException,
    *,
    slot: int,
    secrets: Sequence[str],
) -> list[dict[str, object]]:
    traces = getattr(error, "traces", ())
    if not isinstance(traces, (list, tuple)):
        return []
    summaries: list[dict[str, object]] = []
    for trace in traces:
        if not isinstance(trace, Mapping):
            continue
        try:
            summaries.append(
                _trace_summary(
                    trace,
                    slot=slot,
                    choice_order=None,
                    secrets=secrets,
                )
            )
        except (ShadowLeakageError, ValueError):
            continue
    return summaries


def _is_immediate_abort(error: BaseException) -> bool:
    security_types = (
        ShadowLeakageError,
        cursor_sandbox.LeakageError,
        cursor_sandbox.ModelMismatchError,
        cursor_sandbox.SecurityCleanupError,
        cursor_sandbox.RequestCleanupError,
        cursor_sandbox.RequestRetentionError,
        cursor_sandbox.RuntimeEndpointError,
        cursor_sandbox.MountProbeError,
    )
    if isinstance(error, security_types):
        return True
    lowered = str(error).lower()
    return "model_id does not match" in lowered or "model identity" in lowered


class _RecordingBackend:
    """Validate every prompt/result and retain safe failure trace summaries."""

    def __init__(
        self,
        backend: model_backend.ModelBackend,
        *,
        secrets: Sequence[str],
    ) -> None:
        self.backend = backend
        self.secrets = tuple(secrets)
        self.events: list[dict[str, object]] = []
        self.slot = 0

    def complete(
        self,
        request: model_backend.ModelRequest,
    ) -> model_backend.ModelResult:
        safe_request = cast(
            Mapping[str, object],
            _sanitize_for_publication(
                request.to_dict(),
                secrets=self.secrets,
            ),
        )
        model = cast(Mapping[str, object], safe_request["model"])
        base = {
            "slot": self.slot,
            "phase": "backend_call",
            "attempt": 0,
            "request_hash": model_backend.request_hash(request),
            "role": safe_request["role"],
            "family": model["family"],
            "requested_model_id": model["model_id"],
            "actual_model_id": None,
            "prompt_version": safe_request["prompt_version"],
            "schema_version": safe_request["schema_version"],
            "seed": safe_request["seed"],
            "choice_order": None,
            "agent_id": None,
            "run_id": None,
            "status": "error",
            "parser_outcome": "not_returned",
            "parse_error": None,
        }
        try:
            result = self.backend.complete(request)
            safe_result = cast(
                Mapping[str, object],
                _sanitize_for_publication(
                    {
                        "model_id": result.model_id,
                        "status": result.status,
                        "text": result.text,
                        "agent_id": result.agent_id,
                        "run_id": result.run_id,
                        "error": result.error,
                    },
                    secrets=self.secrets,
                ),
            )
        except BaseException:
            self.events.append(base)
            raise
        event = dict(base)
        event.update(
            {
                "actual_model_id": safe_result["model_id"],
                "agent_id": safe_result["agent_id"],
                "run_id": safe_result["run_id"],
                "status": safe_result["status"],
                "parser_outcome": "returned",
            }
        )
        self.events.append(event)
        return model_backend.ModelResult(
            request_id=result.request_id,
            model_id=cast(str, safe_result["model_id"]),
            status=cast(str, safe_result["status"]),
            text=cast(str, safe_result["text"]),
            agent_id=cast(str, safe_result["agent_id"]),
            run_id=cast(str, safe_result["run_id"]),
            error=cast(str, safe_result["error"]),
        )


def _publish_failed_run(
    *,
    output_root: Path | str,
    allow_test_output: bool,
    run_id: str,
    roles: shadow_portfolio.ModelRoles,
    environment: RunEnvironment,
    topic: str,
    expected_candidate_count: int,
    seed: int,
    allocation: Sequence[str],
    candidates: Sequence[Mapping[str, object]],
    failures: Sequence[Mapping[str, object]],
    failure_traces: Sequence[Mapping[str, object]],
) -> Path:
    manifest = build_run_manifest(
        run_id=run_id,
        status="failed",
        roles=roles,
        environment=environment,
        topic=topic,
        expected_candidate_count=expected_candidate_count,
        seed=seed,
        allocation=allocation,
        candidates=candidates,
        failures=failures,
        failure_traces=failure_traces,
    )
    return publish_run(
        output_root,
        run_id,
        candidates=candidates,
        failures=failures,
        manifest=manifest,
        allow_test_output=allow_test_output,
    )


def run_shadow(
    *,
    roles: shadow_portfolio.ModelRoles,
    backend: model_backend.ModelBackend,
    environment: RunEnvironment,
    output_root: Path | str = QUARANTINE_ROOT,
    allow_test_output: bool = False,
    search_fn: SearchFn,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    topic: str = DEFAULT_TOPIC,
    run_id: str | None = None,
    secrets: Sequence[str] = (),
) -> Path:
    """Run a complete portfolio or finalize an auditable failed diagnostic."""
    resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    _validate_run_id(resolved_run_id)
    validate_output_root(output_root, allow_test_output=allow_test_output)
    candidates: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    failure_traces: list[dict[str, object]] = []
    allocation: list[str] = []
    recorder = _RecordingBackend(backend, secrets=secrets)

    try:
        if n < 3:
            raise ValueError("shadow runs require at least three candidates")
        _validate_probe(environment.probe, allow_incomplete=False)
        validate_exact_roles(
            roles,
            cast(Sequence[Mapping[str, object]], environment.probe["models"]),
        )
        allocation = shadow_portfolio.allocate_families(n, seed=seed)
        if set(allocation) != set(_FAMILIES):
            raise ValueError("allocation must cover all three model families")
    except BaseException as error:
        failures.append(
            _failure_record(
                error,
                stage="preflight",
                slot=None,
                origin=None,
                seed=None,
                secrets=secrets,
            )
        )
        if not allocation:
            allocation = ["unallocated"] * max(1, n)
        run_dir = _publish_failed_run(
            output_root=output_root,
            allow_test_output=allow_test_output,
            run_id=resolved_run_id,
            roles=roles,
            environment=environment,
            topic=topic,
            expected_candidate_count=max(1, n),
            seed=seed,
            allocation=allocation,
            candidates=candidates,
            failures=failures,
            failure_traces=[*failure_traces, *recorder.events],
        )
        raise ShadowRunFailed(run_dir, "shadow preflight failed") from error

    for slot, origin in enumerate(allocation):
        slot_seed = seed + slot
        recorder.slot = slot
        try:
            chunks = sanitize_retrieved(
                search_fn(topic, k=generation_core.CONTEXT_CHUNKS)
            )
            record = shadow_portfolio.run_candidate(
                topic=topic,
                retrieved=chunks,
                origin=origin,
                roles=roles,
                backend=recorder,
                seed=slot_seed,
            )
            sanitized = _sanitize_candidate_record(
                record,
                slot=slot,
                secrets=secrets,
            )
            _candidate_provenance(sanitized)
            candidates.append(sanitized)
        except BaseException as error:
            failure_traces.extend(
                _error_trace_summaries(
                    error,
                    slot=slot,
                    secrets=secrets,
                )
            )
            failures.append(
                _failure_record(
                    error,
                    stage="candidate",
                    slot=slot,
                    origin=origin,
                    seed=slot_seed,
                    secrets=secrets,
                )
            )
            if _is_immediate_abort(error):
                break

    origins = {str(candidate.get("origin_family")) for candidate in candidates}
    if failures or len(candidates) != n or origins != set(_FAMILIES):
        run_dir = _publish_failed_run(
            output_root=output_root,
            allow_test_output=allow_test_output,
            run_id=resolved_run_id,
            roles=roles,
            environment=environment,
            topic=topic,
            expected_candidate_count=n,
            seed=seed,
            allocation=allocation,
            candidates=candidates,
            failures=failures
            or [
                {
                    "stage": "portfolio",
                    "slot": None,
                    "origin_family": None,
                    "seed": None,
                    "error_type": "IncompletePortfolio",
                    "message": "all three model families did not complete",
                }
            ],
            failure_traces=[*failure_traces, *recorder.events],
        )
        raise ShadowRunFailed(
            run_dir,
            "shadow run did not complete all three model families",
        )

    manifest = build_run_manifest(
        run_id=resolved_run_id,
        status="success",
        roles=roles,
        environment=environment,
        topic=topic,
        expected_candidate_count=n,
        seed=seed,
        allocation=allocation,
        candidates=candidates,
        failures=[],
    )
    return publish_run(
        output_root,
        resolved_run_id,
        candidates=candidates,
        failures=[],
        manifest=manifest,
        allow_test_output=allow_test_output,
    )


def _offline_search(
    query: str,
    k: int = generation_core.CONTEXT_CHUNKS,
    **_kwargs: object,
) -> list[dict[str, object]]:
    del query, k
    return [
        {
            "chunk_id": "chunk-self-check-1",
            "source_ref": "OpenStax University Physics, p. 1",
            "source_title": "OpenStax University Physics",
            "text": (
                "A particle in uniform circular motion has constant speed while "
                "its velocity direction changes."
            ),
            "score": 0.95,
        }
    ]


def _offline_candidate() -> dict[str, object]:
    return {
        "stem": "A particle moves in a circle. Which statement is correct?",
        "choices": [
            "The speed is constant.",
            "The velocity is constant.",
            "The acceleration is zero.",
            "The momentum is zero.",
            "The radius must increase.",
        ],
        "key": "A",
        "distractors": [
            {
                "label": "B",
                "misconception_tag": "speed-is-velocity",
                "rationale": "Confuses constant speed with constant velocity.",
            },
            {
                "label": "C",
                "misconception_tag": "no-tangential-change",
                "rationale": "Ignores centripetal acceleration.",
            },
            {
                "label": "D",
                "misconception_tag": "vector-cancellation",
                "rationale": "Treats changing momentum as zero momentum.",
            },
            {
                "label": "E",
                "misconception_tag": "radius-drift",
                "rationale": "Assumes circular motion cannot stay bounded.",
            },
        ],
        "solution_decomposition": [
            {
                "subgoal": "Separate speed from velocity.",
                "rubric": "Identifies velocity as a vector.",
            },
            {
                "subgoal": "Identify the invariant scalar.",
                "rubric": "Uses the definition of uniform circular motion.",
            },
        ],
        "problem_kind": "conceptual",
        "difficulty": 0.4,
        "confidence": 0.8,
        "computational": None,
        "refuse": False,
    }


class _SelfCheckBackend:
    def __init__(self) -> None:
        self.payload = json.dumps(_offline_candidate())
        self.calls = 0

    def complete(
        self,
        request: model_backend.ModelRequest,
    ) -> model_backend.ModelResult:
        self.calls += 1
        text = (
            self.payload
            if request.role == "generator"
            else json.dumps(
                {
                    "answer": "A",
                    "reasoning": f"{request.model.family} independent solve",
                    "confidence": 0.75,
                }
            )
        )
        return model_backend.ModelResult(
            request_id=request.request_id,
            model_id=request.model.model_id,
            status="finished",
            text=text,
            agent_id=f"self-check-agent-{self.calls}",
            run_id=f"self-check-run-{self.calls}",
        )


def _default_roles() -> shadow_portfolio.ModelRoles:
    return shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", "gpt-5.6-sol-max", DEFAULT_REASONING),
        opus=model_backend.ModelSpec(
            "opus",
            "claude-opus-4-8-thinking-high-fast",
            DEFAULT_REASONING,
        ),
        grok=model_backend.ModelSpec(
            "grok",
            "cursor-grok-4.5-high-fast",
            DEFAULT_REASONING,
        ),
    )


def _offline_environment() -> RunEnvironment:
    sha, tree_status = collect_repo_state()
    probe = make_probe_metadata(
        [
            {"id": "gpt-5.6-sol-max", "parameters": [], "variants": []},
            {
                "id": "claude-opus-4-8-thinking-high-fast",
                "parameters": [],
                "variants": [],
            },
            {
                "id": "cursor-grok-4.5-high-fast",
                "parameters": [],
                "variants": [],
            },
        ],
        sdk_version="offline-fake-0.1.9",
    )
    return RunEnvironment(
        code_sha=sha,
        tree_status=tree_status,
        worker_image="pgrep-shadow-worker:offline-self-check",
        worker_image_digest="sha256:" + hashlib.sha256(b"offline-worker").hexdigest(),
        corpus_index_fingerprint=(
            "sha256:" + hashlib.sha256(b"offline-corpus-fixture").hexdigest()
        ),
        probe=probe,
    )


def offline_fixture(
    *,
    run_id: str,
    environment: RunEnvironment,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Build a complete fake portfolio without filesystem publication."""
    roles = _default_roles()
    allocation = shadow_portfolio.allocate_families(3, seed=DEFAULT_SEED)
    recorder = _RecordingBackend(_SelfCheckBackend(), secrets=())
    candidates: list[dict[str, object]] = []
    chunks = sanitize_retrieved(_offline_search(DEFAULT_TOPIC))
    for slot, origin in enumerate(allocation):
        recorder.slot = slot
        record = shadow_portfolio.run_candidate(
            topic=DEFAULT_TOPIC,
            retrieved=chunks,
            origin=origin,
            roles=roles,
            backend=recorder,
            seed=DEFAULT_SEED + slot,
        )
        candidates.append(_sanitize_candidate_record(record, slot=slot, secrets=()))
    manifest = build_run_manifest(
        run_id=run_id,
        status="success",
        roles=roles,
        environment=environment,
        topic=DEFAULT_TOPIC,
        expected_candidate_count=3,
        seed=DEFAULT_SEED,
        allocation=allocation,
        candidates=candidates,
        failures=[],
    )
    return candidates, manifest


def _self_check_at(
    output_root: Path | str,
    *,
    allow_test_output: bool,
) -> int:
    run_dir = run_shadow(
        roles=_default_roles(),
        backend=_SelfCheckBackend(),
        environment=_offline_environment(),
        output_root=output_root,
        allow_test_output=allow_test_output,
        search_fn=_offline_search,
        n=3,
        seed=DEFAULT_SEED,
        topic=DEFAULT_TOPIC,
        run_id=(
            f"self-check-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        ),
    )
    print(f"[ok] shadow-foundry self-check passed; wrote {run_dir}")
    return 0


def self_check() -> int:
    """Run the fully offline smoke only in the exact quarantine root."""
    return _self_check_at(QUARANTINE_ROOT, allow_test_output=False)


def _load_api_key() -> str:
    key = os.environ.get("CURSOR_API_KEY", "").strip()
    if key:
        return key
    for candidate in (REPO_ROOT / "content" / ".env", REPO_ROOT / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith("CURSOR_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _build_roles(
    *,
    sol_model: str,
    opus_model: str,
    grok_model: str,
) -> shadow_portfolio.ModelRoles:
    return shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", sol_model, DEFAULT_REASONING),
        opus=model_backend.ModelSpec("opus", opus_model, DEFAULT_REASONING),
        grok=model_backend.ModelSpec("grok", grok_model, DEFAULT_REASONING),
    )


def _partial_environment(
    *,
    image: str,
    digest: str | None = None,
    probe: Mapping[str, object] | None = None,
    corpus_fingerprint: str | None = None,
) -> RunEnvironment:
    sha, tree_status = collect_repo_state()
    return RunEnvironment(
        code_sha=sha,
        tree_status=tree_status,
        worker_image=image,
        worker_image_digest=digest,
        corpus_index_fingerprint=corpus_fingerprint,
        probe=probe
        or make_probe_metadata(
            [],
            sdk_version="unavailable",
        ),
    )


def _publish_cli_preflight_failure(
    *,
    run_id: str,
    roles: shadow_portfolio.ModelRoles,
    n: int,
    seed: int,
    topic: str,
    error: BaseException,
    environment: RunEnvironment,
    secrets: Sequence[str],
) -> Path:
    failures = [
        _failure_record(
            error,
            stage="sandbox_preflight",
            slot=None,
            origin=None,
            seed=None,
            secrets=secrets,
        )
    ]
    allocation = ["unallocated"] * max(1, n)
    return _publish_failed_run(
        output_root=QUARANTINE_ROOT,
        allow_test_output=False,
        run_id=run_id,
        roles=roles,
        environment=environment,
        topic=topic,
        expected_candidate_count=max(1, n),
        seed=seed,
        allocation=allocation,
        candidates=[],
        failures=failures,
        failure_traces=[],
    )


def _real_probe(
    prepared: PreparedSandbox,
) -> dict[str, object]:
    raw = prepared.sandbox.probe_models()
    models = raw.get("models")
    if not isinstance(models, list):
        raise cursor_sandbox.SandboxOutputError("model probe returned no catalog")
    sdk_version = _non_empty_string(
        raw.get("sdk_version"),
        name="model probe SDK version",
    )
    return make_probe_metadata(
        cast(list[Mapping[str, object]], models),
        sdk_version=sdk_version,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Quarantined multi-model shadow foundry. Never lands content or "
            "preference pairs."
        )
    )
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--build-worker", action="store_true")
    parser.add_argument("--probe-models", action="store_true")
    parser.add_argument("--shadow", action="store_true")
    parser.add_argument("--sol-model")
    parser.add_argument("--opus-model")
    parser.add_argument("--grok-model")
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--run")
    args = parser.parse_args(list(argv) if argv is not None else None)
    selected = sum(
        bool(flag)
        for flag in (
            args.self_check,
            args.build_worker,
            args.probe_models,
            args.shadow,
        )
    )
    if selected != 1:
        parser.error(
            "choose exactly one of --self-check, --build-worker, "
            "--probe-models, or --shadow"
        )
    if args.self_check:
        return self_check()

    run_id = args.run or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    key = _load_api_key()
    if not args.build_worker and not key:
        print("CURSOR_API_KEY is required for model probing or shadow mode")
        return 1
    if args.build_worker:
        try:
            prepared = prepare_real_sandbox("", force_build=True)
        except Exception as error:  # noqa: BLE001
            print(f"shadow worker build failed: {type(error).__name__}: {error}")
            return 1
        print(f"built {prepared.image} at immutable digest {prepared.image_digest}")
        return 0

    roles = _default_roles()
    if args.shadow:
        if not args.sol_model or not args.opus_model or not args.grok_model:
            parser.error(
                "--shadow requires --sol-model, --opus-model, and --grok-model"
            )
        roles = _build_roles(
            sol_model=args.sol_model,
            opus_model=args.opus_model,
            grok_model=args.grok_model,
        )
    partial = _partial_environment(image=worker_image_tag())
    try:
        prepared = prepare_real_sandbox(key)
        probe = _real_probe(prepared)
    except Exception as error:  # noqa: BLE001
        diagnostic = _publish_cli_preflight_failure(
            run_id=run_id,
            roles=roles,
            n=args.n,
            seed=args.seed,
            topic=args.topic,
            error=error,
            environment=partial,
            secrets=(key,),
        )
        print(
            f"shadow sandbox preflight failed: {type(error).__name__}: {error}; "
            f"diagnostic run: {diagnostic}"
        )
        return 1

    if args.probe_models:
        text, _payload = format_probe(cast(list[Mapping[str, object]], probe["models"]))
        print(text, end="")
        print(_strict_json(probe), end="")
        return 0

    try:
        validate_exact_roles(
            roles,
            cast(list[Mapping[str, object]], probe["models"]),
        )
        from pgrep.ai import retrieval  # type: ignore[import-not-found]

        index_path = Path(retrieval.default_index_path())
        environment = _partial_environment(
            image=prepared.image,
            digest=prepared.image_digest,
            probe=probe,
            corpus_fingerprint=file_fingerprint(index_path),
        )
        run_dir = run_shadow(
            roles=roles,
            backend=prepared.sandbox,
            environment=environment,
            output_root=QUARANTINE_ROOT,
            search_fn=lambda query, k: retrieval.search(
                query,
                k=k,
                db_path=str(index_path),
            ),
            n=args.n,
            seed=args.seed,
            topic=args.topic,
            run_id=run_id,
            secrets=(key,),
        )
    except ShadowRunFailed as error:
        print(str(error))
        return 1
    except Exception as error:  # noqa: BLE001
        complete = _partial_environment(
            image=prepared.image,
            digest=prepared.image_digest,
            probe=probe,
        )
        diagnostic = _publish_cli_preflight_failure(
            run_id=run_id,
            roles=roles,
            n=args.n,
            seed=args.seed,
            topic=args.topic,
            error=error,
            environment=complete,
            secrets=(key,),
        )
        print(
            f"shadow preflight failed: {type(error).__name__}: {error}; "
            f"diagnostic run: {diagnostic}"
        )
        return 1
    print(f"wrote quarantined shadow run {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
