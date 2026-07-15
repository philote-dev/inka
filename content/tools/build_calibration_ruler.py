# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Build the private blind human calibration ruler and its Pass A workspace.

This offline tool loads three explicit inputs, a trusted problem set, a rejected
(failure) set, and a finalized shadow-foundry run, builds the exact frozen ruler
through the Task 2 sampling APIs, and atomically publishes a private review
workspace: a hidden manifest, a blind index, seven Pass A Markdown blocks, one
sanitized SVG per figure review, and a final ``_SUCCESS`` marker written last.

Nothing about the hidden answer key, the source origin, the shadow model family,
the calibration/validation split, or the repeat pairing ever reaches a
human-facing sheet. The workspace is fixed under the git-ignored repository
``content/run/calibration`` root; internal tests may inject an OS temporary
root. No Pass B directory, reviewer label, recommendation, preference data, or
bundle change is ever written.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, cast
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402

_AI_ROOT = Path(_ai_path.add_ai_core()).resolve()

import shadow_foundry  # noqa: E402
from pgrep.ai import (  # type: ignore[import-not-found]  # noqa: E402
    calibration_ruler,
    calibration_sheet,
    shadow_portfolio,
)

_SOURCE_PATHS = {
    "build_calibration_ruler": Path(__file__).resolve(),
    "calibration_ruler": Path(calibration_ruler.__file__).resolve(),
    "calibration_sheet": Path(calibration_sheet.__file__).resolve(),
    "shadow_foundry": Path(shadow_foundry.__file__).resolve(),
    "shadow_portfolio": Path(shadow_portfolio.__file__).resolve(),
}
_LOADED_SOURCE_SHA256 = {
    name: hashlib.sha256(path.read_bytes()).hexdigest()
    for name, path in _SOURCE_PATHS.items()
}

REPO_ROOT = _AI_ROOT.parents[1]
CONTENT_RUN_ROOT = REPO_ROOT / "content" / "run"
SHADOW_ROOT = CONTENT_RUN_ROOT / "shadow-foundry"
CALIBRATION_ROOT = REPO_ROOT / "content" / "run" / "calibration"

MANIFEST_NAME = "manifest.json"
INDEX_NAME = "index.md"
SUCCESS_MARKER = "_SUCCESS"
FAILED_MARKER = "_FAILED"
PASS_A_DIRNAME = "pass-a"
PASS_B_DIRNAME = "pass-b"
FIGURES_DIRNAME = "figures"
MANIFEST_VERSION = "pgrep-calibration-ruler/v1"

_SHADOW_FAMILIES = ("sol", "opus", "grok")

# Broad dataset tokens forbidden in an input file path or anywhere inside a
# trusted/failure item. Ruler inputs must never be drawn from gold, held-out,
# ETS, or tier-3 sources.
_PRIVATE_DATASET_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"ets|gr9677|gr1777"
    r"|held[\s_./\\-]*out"
    r"|tier[\s_./\\-]*3"
    r"|content[/\\]+gold(?=$|[/\\._:-])"
    r"|gold[\s_.-]+(?:set|items?|dataset|corpus|\d+)(?![a-z0-9])"
    r"|gold(?=[/\\])"
    r")(?![a-z0-9])"
)

_PATH_KEY_TOKEN = re.compile(
    r"(?:^|_)(?:path|file|filename|filepath|directory|dir|folder|cwd|home)"
    r"(?:$|_)",
    re.IGNORECASE,
)
_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:^|[\s\"'=(:])(?:/[A-Za-z0-9._~-]+(?:/|$)|[A-Za-z]:\\|\\\\)"
)
_RELATIVE_PATH = re.compile(
    r"(?i)(?:^|[\s\"'=(:])(?:\.\.?[/\\]|~[/\\]|"
    r"(?:content|pylib|qt|rslib|tools|docs_pgrep|\.git)[/\\])"
    r"|(?<![A-Za-z0-9])(?:[A-Za-z0-9_.-]+[/\\])+"
    r"[A-Za-z0-9_.-]+\.(?:jsonl?|db|sqlite|pdf|py|toml|ya?ml|env|md|txt"
    r"|svg|png|jpe?g|tex)\b"
    r"|(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]+\."
    r"(?:jsonl?|db|sqlite|pdf|py|toml|ya?ml|env|md|txt|svg|png|jpe?g|tex)"
    r"(?![A-Za-z0-9_.-])"
)
_FORBIDDEN_ASSET_TERMS = frozenset(
    {
        "source_ref",
        "source_excerpt",
        "solution_decomposition",
        "decomposition",
        "model_id",
        "model_family",
        "origin",
        "provenance",
        "trace",
        "verifier_decision",
        "verifier_verdict",
        "stratum",
        "split",
        "repeat_of",
        "content_hash",
        "pass_a_hash",
        "pass_b_hash",
        "manifest.json",
        "candidates.json",
        "failures.json",
        "source_file",
        "source_path",
        "filesystem_path",
        "file_path",
        "original_path",
        "input_file",
        "stored_key",
        "stored-key",
    }
)
_BLIND_FIGURE_FORBIDDEN_WORDS = frozenset(
    {
        "answer",
        "answers",
        "solution",
        "solutions",
        "correct",
        "incorrect",
        "key",
        "keys",
        "choice",
        "choices",
        "recommendation",
        "recommendations",
        "confidence",
        "verifier",
        "verifiers",
        "model",
        "models",
    }
)
_CSS_ESCAPE = re.compile(
    r"\\(?:([0-9a-fA-F]{1,6})(?:\r\n|[ \t\r\n\f])?|([^\r\n\f0-9a-fA-F]))"
)


class RulerBuildError(ValueError):
    """A ruler build precondition or publication invariant was violated."""


class PublicationCleanupError(RuntimeError):
    """A failed publication could not be cleaned up completely."""


LockIdentity = tuple[int, int]
RepoStateFn = Callable[[], tuple[str, str]]
HeadBlobFn = Callable[[str, Path], bytes]
AttestationFn = Callable[[], "ExecutionAttestation"]


@dataclass(frozen=True)
class SourceAttestation:
    loaded_sha256: str
    current_sha256: str
    head_blob_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "loaded_sha256": self.loaded_sha256,
            "current_sha256": self.current_sha256,
            "head_blob_sha256": self.head_blob_sha256,
        }


@dataclass(frozen=True)
class ExecutionAttestation:
    head_sha: str
    tree_status: str
    source_hashes: dict[str, SourceAttestation]

    def to_dict(self) -> dict[str, object]:
        return {
            "head_sha": self.head_sha,
            "tree_status": self.tree_status,
            "source_hashes": {
                name: hashes.to_dict() for name, hashes in self.source_hashes.items()
            },
        }


@dataclass(frozen=True)
class _FileFingerprint:
    name: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class _LoadedProblemSet:
    items: tuple[dict[str, object], ...]
    sha256: str
    fingerprint: _FileFingerprint


@dataclass(frozen=True)
class _LoadedShadowRun:
    items: tuple[dict[str, object], ...]
    run_id: str
    manifest_sha256: str
    model_ids: tuple[str, ...]
    fingerprints: tuple[_FileFingerprint, ...]


# --- Filesystem seam -------------------------------------------------------


class PublicationIO:
    """Injectable filesystem seam so tests can inject partial failures."""

    def open_lock(self, path: Path) -> int:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        identity = _descriptor_identity(fd)
        try:
            self.write_lock(fd, f"pid={os.getpid()}\n".encode())
            self.sync_lock(fd)
        except BaseException:
            os.close(fd)
            if _path_matches_identity(path, identity):
                path.unlink()
            if path.exists() or path.is_symlink():
                raise PublicationCleanupError(
                    f"failed lock initialization left an owned lock: {path}"
                )
            raise
        return fd

    def write_lock(self, fd: int, content: bytes) -> None:
        os.write(fd, content)

    def sync_lock(self, fd: int) -> None:
        os.fsync(fd)

    def create_temp(self, root: Path, run_id: str) -> Path:
        return Path(tempfile.mkdtemp(prefix=f".{run_id}.", suffix=".tmp", dir=root))

    def make_dir(self, path: Path) -> None:
        path.mkdir(mode=0o700, exist_ok=False)

    def reserve_final(self, path: Path) -> None:
        path.mkdir(mode=0o700, exist_ok=False)

    def link_payload(self, source: Path, destination: Path) -> None:
        os.link(source, destination, follow_symlinks=False)

    def write_text(self, path: Path, content: str) -> None:
        _write_exclusive(path, content.encode("utf-8"))

    def write_bytes(self, path: Path, content: bytes) -> None:
        _write_exclusive(path, content)

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_marker(self, path: Path, content: str) -> None:
        _write_exclusive(path, content.encode("utf-8"))

    def fsync_dir(self, path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def cleanup_tree(self, path: Path) -> None:
        _remove_tree_verified(path)

    def remove_lock(self, path: Path, identity: LockIdentity) -> None:
        if not _path_matches_identity(path, identity):
            raise PublicationCleanupError(
                "publication lock identity changed before removal"
            )
        path.unlink()
        if path.exists() or path.is_symlink():
            raise PublicationCleanupError(f"publication lock remains: {path}")


def _write_exclusive(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)


def _descriptor_identity(fd: int) -> LockIdentity:
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino)


def _path_matches_identity(path: Path, identity: LockIdentity) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return not stat.S_ISLNK(info.st_mode) and (info.st_dev, info.st_ino) == identity


def _remove_tree_verified(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise PublicationCleanupError(f"refusing to remove symlink: {path}")
    shutil.rmtree(path)
    if path.exists() or path.is_symlink():
        raise PublicationCleanupError(f"cleanup tree remains: {path}")


# --- Output-root safety ----------------------------------------------------


def _reject_symlink_components(path: Path, *, name: str = "path") -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise RulerBuildError(f"{name} contains a symlink component: {current}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _git_ignored_path(path: Path, *, name: str) -> None:
    try:
        relative = path.absolute().relative_to(REPO_ROOT.absolute())
    except ValueError as error:
        raise RulerBuildError(f"{name} is outside the repository") from error
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(relative)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        timeout=5,
    )
    if completed.returncode != 0:
        raise RulerBuildError(f"{name} is not git-ignored")


def _reject_path_escape(path: Path, *, name: str) -> None:
    if ".." in Path(path).parts:
        raise RulerBuildError(f"{name} contains a path escape")


def _is_test_path(path: Path) -> bool:
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    return _is_relative_to(resolved, temp_root)


def validate_output_root(
    out_root: Path | str,
    *,
    allow_test_paths: bool = False,
) -> Path:
    """Accept only the exact private root, unless an internal test opts in."""
    raw = Path(out_root)
    _reject_path_escape(raw, name="output root")
    requested = raw.absolute()
    _reject_symlink_components(requested, name="output root")
    if requested == CALIBRATION_ROOT.absolute():
        _git_ignored_path(requested, name="calibration output root")
        return requested
    if allow_test_paths and _is_test_path(requested):
        return requested
    raise RulerBuildError("output root must be the exact repository calibration root")


def _normalize_input_path(
    path: Path | str,
    *,
    name: str,
    allow_test_paths: bool,
    required_root: Path,
    require_file: bool,
) -> Path:
    raw = Path(path)
    _reject_path_escape(raw, name=name)
    absolute = raw.absolute()
    _reject_symlink_components(absolute, name=name)
    try:
        resolved = absolute.resolve(strict=True)
    except FileNotFoundError as error:
        raise RulerBuildError(f"{name} does not exist: {absolute}") from error
    info = resolved.lstat()
    expected = stat.S_ISREG if require_file else stat.S_ISDIR
    if stat.S_ISLNK(info.st_mode) or not expected(info.st_mode):
        kind = "regular JSON file" if require_file else "directory"
        raise RulerBuildError(f"{name} must be a {kind}: {resolved}")
    if allow_test_paths and _is_test_path(resolved):
        return resolved
    canonical_root = required_root.resolve(strict=True)
    if not _is_relative_to(resolved, canonical_root):
        raise RulerBuildError(
            f"{name} must be under the exact repository {required_root.name} root"
        )
    _git_ignored_path(resolved, name=name)
    return resolved


def _validate_run_id(run_id: str) -> None:
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
        or "\\" in run_id
        or "/" in run_id
    ):
        raise RulerBuildError("run ID must be a non-empty directory name")
    if _PRIVATE_DATASET_MARKER.search(run_id):
        raise RulerBuildError("run ID must not contain a private dataset marker")


def _ensure_directory_chain(root: Path) -> None:
    parts: list[Path] = []
    current = root.absolute()
    while not current.exists():
        parts.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for path in reversed(parts):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise RulerBuildError(f"output root component is not a directory: {path}")


# --- Input loading (trusted / failure) -------------------------------------


def _reject_private_input_path(path: Path, *, name: str) -> None:
    if _PRIVATE_DATASET_MARKER.search(str(path)):
        raise RulerBuildError(
            f"{name} path must not reference gold, held-out, ETS, or tier-3 data"
        )


def _read_file_once(path: Path, *, name: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise RulerBuildError(f"could not open {name}: {error}") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RulerBuildError(f"{name} must be a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _reject_json_constant(value: str) -> object:
    raise RulerBuildError(f"non-finite JSON number is forbidden: {value}")


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RulerBuildError(f"duplicate JSON object key is forbidden: {key!r}")
        result[key] = value
    return result


def _parse_json_bytes(raw: bytes, *, name: str) -> object:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RulerBuildError(f"{name} is not strict UTF-8") from error
    try:
        return json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except json.JSONDecodeError as error:
        raise RulerBuildError(f"{name} is not valid JSON: {error}") from error


def _load_json_once(path: Path, *, name: str) -> tuple[object, bytes]:
    raw = _read_file_once(path, name=name)
    return _parse_json_bytes(raw, name=name), raw


def _items_from_document(document: object, *, name: str) -> list[object]:
    if isinstance(document, list):
        return list(cast("list[object]", document))
    if isinstance(document, Mapping):
        mapping = cast("Mapping[str, object]", document)
        for key in ("items", "candidates"):
            if key in mapping:
                value = mapping[key]
                if not isinstance(value, list):
                    raise RulerBuildError(f"{name} {key!r} field must be a JSON array")
                return list(cast("list[object]", value))
        raise RulerBuildError(
            f"{name} object must contain an 'items' or 'candidates' array"
        )
    raise RulerBuildError(f"{name} input must be a JSON array or object")


def _normalized_key(key: str) -> str:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^A-Za-z0-9]+", "_", snake).strip("_").lower()


def _looks_like_filesystem_path(value: str) -> bool:
    without_urls = re.sub(r"(?i)\bhttps?://\S+", "", value)
    return bool(
        _ABSOLUTE_PATH.search(without_urls) or _RELATIVE_PATH.search(without_urls)
    )


def _reject_path_fields_and_values(value: object, *, name: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in cast("Mapping[str, object]", value).items():
            if isinstance(key, str) and _PATH_KEY_TOKEN.search(_normalized_key(key)):
                raise RulerBuildError(
                    f"{name} item must not carry a source path field: {key}"
                )
            _reject_path_fields_and_values(nested, name=name)
    elif isinstance(value, list):
        for nested in cast("list[object]", value):
            _reject_path_fields_and_values(nested, name=name)
    elif isinstance(value, str) and _looks_like_filesystem_path(value):
        raise RulerBuildError(f"{name} item contains a filesystem-looking value")


def _is_identifier_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return (
        normalized in {"id", "ids", "dataset", "dataset_id", "source_id"}
        or normalized.endswith("_id")
        or normalized.endswith("_ids")
    )


def _reject_recursive_markers(
    value: object,
    *,
    name: str,
    identifier: bool = False,
) -> None:
    if isinstance(value, str):
        marker = _PRIVATE_DATASET_MARKER.search(value)
        if marker is None and identifier:
            marker = re.search(r"(?i)(?<![a-z0-9])gold[-_.]?\d+(?![a-z0-9])", value)
        if marker is not None:
            raise RulerBuildError(
                f"{name} item contains a forbidden dataset marker: {value!r}"
            )
    elif isinstance(value, Mapping):
        for key, nested in cast("Mapping[str, object]", value).items():
            if isinstance(key, str) and _PRIVATE_DATASET_MARKER.search(key):
                raise RulerBuildError(
                    f"{name} item key contains a forbidden dataset marker: {key!r}"
                )
            _reject_recursive_markers(
                nested,
                name=name,
                identifier=identifier
                or (isinstance(key, str) and _is_identifier_key(key)),
            )
    elif isinstance(value, list):
        for nested in cast("list[object]", value):
            _reject_recursive_markers(nested, name=name, identifier=identifier)


def _load_problem_set(
    path: Path | str,
    *,
    name: str,
    allow_test_paths: bool,
) -> _LoadedProblemSet:
    resolved = _normalize_input_path(
        path,
        name=f"{name} input",
        allow_test_paths=allow_test_paths,
        required_root=CONTENT_RUN_ROOT,
        require_file=True,
    )
    _reject_private_input_path(resolved, name=name)
    document, raw = _load_json_once(resolved, name=f"{name} input")
    calibration_ruler._validate_json(document)  # noqa: SLF001
    _reject_path_fields_and_values(document, name=name)
    _reject_recursive_markers(document, name=name)
    items = _items_from_document(document, name=name)
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise RulerBuildError(f"{name} item {index} must be a JSON object")
    copied = tuple(dict(cast("Mapping[str, object]", item)) for item in items)
    digest = hashlib.sha256(raw).hexdigest()
    return _LoadedProblemSet(
        copied,
        digest,
        _FileFingerprint(f"{name} input", resolved, digest),
    )


def load_problem_set(
    path: Path | str,
    *,
    name: str,
    allow_test_paths: bool = False,
) -> list[dict[str, object]]:
    """Load a trusted or failure problem set from one explicit JSON file."""
    return list(
        _load_problem_set(
            path,
            name=name,
            allow_test_paths=allow_test_paths,
        ).items
    )


# --- Shadow run loading (finalized _SUCCESS) -------------------------------


def _normalize_shadow_run_path(
    path: Path | str,
    *,
    allow_test_paths: bool,
) -> Path:
    raw = Path(path)
    if raw.name == "candidates.json":
        candidates_path = _normalize_input_path(
            raw,
            name="shadow candidates input",
            allow_test_paths=allow_test_paths,
            required_root=SHADOW_ROOT,
            require_file=True,
        )
        run_dir = candidates_path.parent
        _normalize_input_path(
            run_dir,
            name="shadow run",
            allow_test_paths=allow_test_paths,
            required_root=SHADOW_ROOT,
            require_file=False,
        )
        return run_dir
    if raw.suffix:
        raise RulerBuildError(
            "shadow input must be a finalized run directory or its candidates.json"
        )
    return _normalize_input_path(
        raw,
        name="shadow run",
        allow_test_paths=allow_test_paths,
        required_root=SHADOW_ROOT,
        require_file=False,
    )


def _require_finalized_marker(run_dir: Path) -> _FileFingerprint:
    failed = run_dir / FAILED_MARKER
    success = run_dir / SUCCESS_MARKER
    if failed.exists() or failed.is_symlink():
        raise RulerBuildError("shadow run is a diagnostic _FAILED run")
    if not success.is_file() or success.is_symlink():
        raise RulerBuildError("shadow run has no finalized _SUCCESS marker")
    raw = _read_file_once(success, name="shadow success marker")
    return _FileFingerprint(
        "shadow success marker",
        success,
        hashlib.sha256(raw).hexdigest(),
    )


def _load_shadow_artifact(
    run_dir: Path,
    filename: str,
) -> tuple[object, bytes]:
    path = run_dir / filename
    _reject_symlink_components(path, name=f"shadow {filename}")
    if path.is_symlink() or not path.is_file():
        raise RulerBuildError(f"shadow run is missing {filename}")
    return _load_json_once(path, name=f"shadow {filename}")


def _assert_trusted_shadow_manifest(
    manifest: Mapping[str, object],
) -> None:
    if manifest.get("mode") != "shadow":
        raise RulerBuildError("shadow manifest is not mode shadow")
    if manifest.get("training_eligible") is not False:
        raise RulerBuildError("shadow manifest must not be training eligible")
    if manifest.get("status") != "success":
        raise RulerBuildError("shadow manifest is not a successful run")
    if manifest.get("replayable") is not True:
        raise RulerBuildError("shadow manifest is not replayable")
    code = manifest.get("code")
    if not isinstance(code, Mapping) or code.get("tree_status") != "clean":
        raise RulerBuildError("shadow run was built from a dirty tree")
    if manifest.get("synthetic") is not False:
        raise RulerBuildError("shadow run is synthetic and cannot enter the ruler")
    if manifest.get("execution_mode") != "real":
        raise RulerBuildError("shadow run must use real execution")
    origins = manifest.get("origins")
    if not isinstance(origins, list) or set(origins) != set(_SHADOW_FAMILIES):
        raise RulerBuildError("shadow run does not verify exactly three families")


def _local_canonical_hash(value: object) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()


def _independently_verify_raw_responses(
    manifest: Mapping[str, object],
    candidates: Sequence[object],
    raw_responses: Sequence[object],
    *,
    raw_response_bytes: bytes,
) -> None:
    digests = manifest.get("artifact_digests")
    if not isinstance(digests, Mapping):
        raise RulerBuildError("independent raw response manifest digest is missing")
    raw_digest = "sha256:" + hashlib.sha256(raw_response_bytes).hexdigest()
    if digests.get("raw_responses_json") != raw_digest:
        raise RulerBuildError("independent raw response artifact digest mismatch")
    by_request: dict[str, Mapping[str, object]] = {}
    for raw in raw_responses:
        if not isinstance(raw, Mapping):
            raise RulerBuildError("independent raw response record is invalid")
        request_id = raw.get("request_id")
        response_text = raw.get("response_text")
        if type(request_id) is not str or type(response_text) is not str:
            raise RulerBuildError("independent raw response identity is invalid")
        if request_id in by_request:
            raise RulerBuildError("independent raw response request is duplicated")
        if (
            raw.get("response_hash")
            != hashlib.sha256(response_text.encode()).hexdigest()
        ):
            raise RulerBuildError("independent raw response hash mismatch")
        by_request[request_id] = raw
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise RulerBuildError("independent raw response candidate is invalid")
        payload = candidate.get("candidate")
        generator = candidate.get("generator")
        if not isinstance(payload, Mapping) or not isinstance(generator, Mapping):
            raise RulerBuildError("independent raw response evidence is incomplete")
        traces = generator.get("traces")
        if not isinstance(traces, list):
            raise RulerBuildError("independent raw response trace list is invalid")
        final = [
            trace
            for trace in traces
            if isinstance(trace, Mapping) and trace.get("parser_outcome") == "parsed"
        ]
        if len(final) != 1:
            raise RulerBuildError(
                "independent raw response requires one final generator trace"
            )
        trace = cast("Mapping[str, object]", final[0])
        request_id = trace.get("request_id")
        if type(request_id) is not str or request_id not in by_request:
            raise RulerBuildError("independent raw response is missing")
        raw = by_request[request_id]
        response_text = cast(str, raw["response_text"])
        if raw.get("response_hash") != trace.get("response_hash"):
            raise RulerBuildError("independent raw response trace hash mismatch")
        try:
            parsed = shadow_portfolio.parse_candidate(response_text)
        except (TypeError, ValueError) as error:
            raise RulerBuildError(
                "independent raw response strict parse failed"
            ) from error
        authored = {
            key: value
            for key, value in payload.items()
            if key not in {"source_ref", "provenance"}
        }
        if parsed != authored:
            raise RulerBuildError(
                "independent raw response does not match candidate payload"
            )
        parsed_hash = _local_canonical_hash(parsed)
        if (
            trace.get("parsed_candidate_sha256") != parsed_hash
            or raw.get("parsed_candidate_sha256") != parsed_hash
        ):
            raise RulerBuildError("independent raw response candidate hash mismatch")


def _load_shadow_run(
    path: Path | str,
    *,
    allow_test_paths: bool,
) -> _LoadedShadowRun:
    """Load and verify a finalized shadow-foundry ``_SUCCESS`` run.

    Returns the shadow-stratum problem items, the shadow run ID, and the hex
    SHA-256 of the run manifest for provenance. Rejects a ``_FAILED``,
    synthetic, partial, dirty, or stale run through the strict shadow contract.
    """
    run_dir = _normalize_shadow_run_path(
        path,
        allow_test_paths=allow_test_paths,
    )
    success_fingerprint = _require_finalized_marker(run_dir)
    manifest, manifest_bytes = _load_shadow_artifact(run_dir, MANIFEST_NAME)
    candidates, candidate_bytes = _load_shadow_artifact(run_dir, "candidates.json")
    failures, failure_bytes = _load_shadow_artifact(run_dir, "failures.json")
    probe, probe_bytes = _load_shadow_artifact(run_dir, "probe.json")
    raw_responses, raw_response_bytes = _load_shadow_artifact(
        run_dir,
        "raw-responses.json",
    )
    if not isinstance(manifest, Mapping):
        raise RulerBuildError("shadow manifest must be a JSON object")
    if (
        not isinstance(candidates, list)
        or not isinstance(failures, list)
        or not isinstance(raw_responses, list)
    ):
        raise RulerBuildError(
            "shadow candidates, failures, and raw responses must be JSON arrays"
        )
    if probe != manifest.get("probe"):
        raise RulerBuildError("shadow probe artifact does not match manifest")
    try:
        shadow_foundry.validate_manifest(
            manifest,
            candidates=candidates,
            failures=failures,
            raw_responses=raw_responses,
            artifact_bytes={
                "candidates.json": candidate_bytes,
                "failures.json": failure_bytes,
                "probe.json": probe_bytes,
                "raw-responses.json": raw_response_bytes,
            },
            publication_run_id=run_dir.name,
        )
    except (ValueError, RuntimeError) as error:
        raise RulerBuildError(
            f"shadow run does not satisfy the finalized manifest contract: {error}"
        ) from error
    try:
        shadow_foundry.validate_raw_response_binding(
            cast("list[Mapping[str, object]]", candidates),
            raw_responses,
            require_complete=True,
        )
    except (TypeError, ValueError) as error:
        raise RulerBuildError(
            f"shadow raw response binding is invalid: {error}"
        ) from error
    _independently_verify_raw_responses(
        cast("Mapping[str, object]", manifest),
        candidates,
        raw_responses,
        raw_response_bytes=raw_response_bytes,
    )
    _assert_trusted_shadow_manifest(cast("Mapping[str, object]", manifest))
    items = [
        _shadow_candidate_to_item(
            cast("Mapping[str, object]", candidate),
            manifest=cast("Mapping[str, object]", manifest),
            index=index,
        )
        for index, candidate in enumerate(cast("list[object]", candidates))
    ]
    roles = cast("Mapping[str, object]", manifest["roles"])
    model_ids = tuple(
        str(cast("Mapping[str, object]", roles[family])["model_id"])
        for family in _SHADOW_FAMILIES
    )
    artifact_fingerprints = (
        _FileFingerprint(
            "shadow manifest",
            run_dir / MANIFEST_NAME,
            hashlib.sha256(manifest_bytes).hexdigest(),
        ),
        _FileFingerprint(
            "shadow candidates",
            run_dir / "candidates.json",
            hashlib.sha256(candidate_bytes).hexdigest(),
        ),
        _FileFingerprint(
            "shadow failures",
            run_dir / "failures.json",
            hashlib.sha256(failure_bytes).hexdigest(),
        ),
        _FileFingerprint(
            "shadow probe",
            run_dir / "probe.json",
            hashlib.sha256(probe_bytes).hexdigest(),
        ),
        _FileFingerprint(
            "shadow raw responses",
            run_dir / "raw-responses.json",
            hashlib.sha256(raw_response_bytes).hexdigest(),
        ),
        success_fingerprint,
    )
    return _LoadedShadowRun(
        tuple(items),
        str(manifest["run_id"]),
        hashlib.sha256(manifest_bytes).hexdigest(),
        model_ids,
        artifact_fingerprints,
    )


def load_shadow_run(
    path: Path | str,
    *,
    allow_test_paths: bool = False,
) -> tuple[list[dict[str, object]], str, str]:
    loaded = _load_shadow_run(path, allow_test_paths=allow_test_paths)
    return list(loaded.items), loaded.run_id, loaded.manifest_sha256


def _shadow_candidate_to_item(
    candidate: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    index: int,
) -> dict[str, object]:
    payload = candidate.get("candidate")
    origin = candidate.get("origin_family")
    if not isinstance(payload, Mapping):
        raise RulerBuildError("shadow candidate is missing its problem payload")
    if origin not in _SHADOW_FAMILIES:
        raise RulerBuildError("shadow candidate has an unknown origin family")
    category = str(manifest["category"])
    problem = cast("Mapping[str, object]", payload)
    item: dict[str, object] = {
        "id": f"shadow-{index:04d}",
        "topic": category,
        "blueprint_category": category,
        "stem": problem["stem"],
        "choices": problem["choices"],
        "key": problem["key"],
        "source_ref": problem.get("source_ref"),
        "model_family": origin,
    }
    if isinstance(problem.get("problem_kind"), str):
        item["problem_kind"] = problem["problem_kind"]
    if problem.get("difficulty") is not None:
        item["difficulty"] = problem["difficulty"]
    if isinstance(problem.get("solution_decomposition"), list):
        item["solution_decomposition"] = problem["solution_decomposition"]
    return item


# --- Manifest and content --------------------------------------------------


def _read_head_blob(head_sha: str, path: Path) -> bytes:
    try:
        relative = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError as error:
        raise RulerBuildError("attested source is outside the repository") from error
    try:
        completed = subprocess.run(
            ["git", "show", f"{head_sha}:{relative.as_posix()}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RulerBuildError("could not read builder source from HEAD") from error
    return completed.stdout


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def _require_clean_repo_state(repo_state_fn: RepoStateFn) -> tuple[str, str]:
    code_sha, tree_status = repo_state_fn()
    if not re.fullmatch(r"[0-9a-f]{40,64}", code_sha):
        raise RulerBuildError("build code SHA must resolve to a complete commit ID")
    if tree_status != "clean":
        raise RulerBuildError("ruler publication requires a clean git tree")
    return code_sha, tree_status


def _capture_execution_attestation(
    *,
    repo_state_fn: RepoStateFn = shadow_foundry.collect_repo_state,
    head_blob_fn: HeadBlobFn = _read_head_blob,
) -> ExecutionAttestation:
    head_sha, tree_status = _require_clean_repo_state(repo_state_fn)
    source_hashes: dict[str, SourceAttestation] = {}
    for name, path in _SOURCE_PATHS.items():
        loaded_sha = _LOADED_SOURCE_SHA256[name]
        current_sha = _source_hash(path)
        head_sha256 = hashlib.sha256(head_blob_fn(head_sha, path)).hexdigest()
        if loaded_sha != current_sha:
            raise RulerBuildError(f"loaded source differs from current bytes: {name}")
        if current_sha != head_sha256:
            raise RulerBuildError(f"current source differs from HEAD blob: {name}")
        source_hashes[name] = SourceAttestation(
            loaded_sha256=loaded_sha,
            current_sha256=current_sha,
            head_blob_sha256=head_sha256,
        )
    return ExecutionAttestation(
        head_sha=head_sha,
        tree_status=tree_status,
        source_hashes=source_hashes,
    )


def _test_execution_attestation(repo_state_fn: RepoStateFn) -> ExecutionAttestation:
    head_sha, tree_status = _require_clean_repo_state(repo_state_fn)
    digest = hashlib.sha256(head_sha.encode()).hexdigest()
    return ExecutionAttestation(
        head_sha=head_sha,
        tree_status=tree_status,
        source_hashes={
            name: SourceAttestation(
                loaded_sha256=digest,
                current_sha256=digest,
                head_blob_sha256=digest,
            )
            for name in _SOURCE_PATHS
        },
    )


def _verify_input_fingerprints(
    fingerprints: Sequence[_FileFingerprint],
) -> None:
    for fingerprint in fingerprints:
        _reject_symlink_components(fingerprint.path, name=fingerprint.name)
        raw = _read_file_once(fingerprint.path, name=fingerprint.name)
        if hashlib.sha256(raw).hexdigest() != fingerprint.sha256:
            raise RulerBuildError(
                f"input fingerprint changed during build: {fingerprint.name}"
            )


def _reattest_before_success(
    *,
    entry: ExecutionAttestation,
    attestation_fn: AttestationFn,
    fingerprints: Sequence[_FileFingerprint],
) -> None:
    final = attestation_fn()
    if final != entry:
        raise RulerBuildError("execution attestation changed during build")
    _verify_input_fingerprints(fingerprints)


def _build_manifest(
    ruler: calibration_ruler.RulerManifest,
    *,
    run_id: str,
    seed: int,
    inputs: Mapping[str, object],
    attestation: ExecutionAttestation,
) -> dict[str, object]:
    primary = [item for item in ruler.items if item.repeat_of is None]
    repeats = [item for item in ruler.items if item.repeat_of is not None]
    strata: dict[str, int] = {}
    splits: dict[str, int] = {}
    families: dict[str, int] = {}
    for item in primary:
        strata[str(item.stratum)] = strata.get(str(item.stratum), 0) + 1
        splits[str(item.split)] = splits.get(str(item.split), 0) + 1
        if item.stratum == "shadow":
            family = str(item.metadata.get("model_family"))
            families[family] = families.get(family, 0) + 1
    return {
        "manifest_version": MANIFEST_VERSION,
        "kind": "blind-human-calibration-ruler",
        "private": True,
        "run_id": run_id,
        "seed": seed,
        "build": {
            "code_sha": attestation.head_sha,
            **attestation.to_dict(),
            "tool": "build_calibration_ruler.py",
        },
        "inputs": dict(inputs),
        "counts": {
            "primary": len(primary),
            "repeats": len(repeats),
            "strata": strata,
            "splits": splits,
            "shadow_families": families,
        },
        "ruler": ruler.to_dict(),
    }


def _rendered_workspace(
    ruler: calibration_ruler.RulerManifest,
) -> tuple[str, list[str], dict[str, bytes]]:
    index = calibration_sheet.render_index(ruler)
    blocks = calibration_sheet.render_blocks(ruler, pass_name="a")
    assets = calibration_sheet.figure_assets(ruler)
    return index, blocks, assets


def _block_filename(number: int) -> str:
    return f"block-{number:02d}.md"


# --- Blinding leak scan ----------------------------------------------------


def _collect_text(value: object, sink: set[str]) -> None:
    if isinstance(value, str):
        if len(value) >= 4:
            sink.add(value)
    elif isinstance(value, Mapping):
        for nested in cast("Mapping[str, object]", value).values():
            _collect_text(nested, sink)
    elif isinstance(value, (list, tuple)):
        for nested in cast("Sequence[object]", value):
            _collect_text(nested, sink)


def _hidden_sentinels(ruler: calibration_ruler.RulerManifest) -> set[str]:
    """Collect content-specific hidden values that must never reach a sheet.

    The review IDs, stratum, split, and repeat pairing are omitted on purpose:
    review IDs are legitimately visible headings, and the classification labels
    are common English words whose blinding the renderer already guarantees.
    This scan targets the answer-carrying content: source citations, grounding
    excerpts, decomposition prose, and the shadow model family.
    """
    sentinels: set[str] = set()
    for item in ruler.items:
        if item.source_ref:
            sentinels.add(item.source_ref)
        if item.source_excerpt:
            sentinels.add(item.source_excerpt)
        family = item.metadata.get("model_family")
        if isinstance(family, str) and family:
            sentinels.add(family)
        _collect_text(item.solution_decomposition, sentinels)
    sentinels.update({"solution_decomposition", "model_family"})
    return {sentinel for sentinel in sentinels if len(sentinel) >= 4}


def _figure_sentinels(
    ruler: calibration_ruler.RulerManifest,
    *,
    model_ids: Sequence[str],
) -> set[str]:
    sentinels = set(model_ids)
    for item in ruler.items:
        for value in (
            item.source_ref,
            item.source_excerpt,
            item.stratum,
            item.split,
            item.repeat_of,
        ):
            if isinstance(value, str) and value:
                sentinels.add(value)
        _collect_text(item.solution_decomposition, sentinels)
        _collect_text(item.metadata, sentinels)
    sentinels.update(_SHADOW_FAMILIES)
    return {sentinel for sentinel in sentinels if sentinel}


def _contains_token(text: str, token: str) -> bool:
    return (
        re.search(
            rf"(?<![\w]){re.escape(token.casefold())}(?![\w])",
            text.casefold(),
        )
        is not None
    )


def _decode_css_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if hexadecimal := match.group(1):
            codepoint = int(hexadecimal, 16)
            if codepoint == 0 or codepoint > 0x10FFFF:
                return "\ufffd"
            return chr(codepoint)
        return match.group(2)

    return _CSS_ESCAPE.sub(replace, value)


def _is_default_ignorable(character: str) -> bool:
    codepoint = ord(character)
    return (
        unicodedata.category(character) == "Cf"
        or codepoint in {0x034F, 0x3164, 0xFFA0}
        or 0x115F <= codepoint <= 0x1160
        or 0x17B4 <= codepoint <= 0x17B5
        or 0x180B <= codepoint <= 0x180F
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0x1BCA0 <= codepoint <= 0x1BCAF
        or 0xE0100 <= codepoint <= 0xE01EF
    )


def _decode_svg_scan_text(value: str) -> str:
    decoded = value
    for _ in range(4):
        unescaped = html.unescape(decoded)
        if unescaped == decoded:
            break
        decoded = unescaped
    compatible = unicodedata.normalize("NFKC", _decode_css_escapes(decoded))
    visible = "".join(
        character for character in compatible if not _is_default_ignorable(character)
    )
    return unicodedata.normalize("NFC", visible)


def _forbidden_svg_words(value: str) -> set[str]:
    words = set(re.findall(r"[^\W_]+", value.casefold()))
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    words.update(re.findall(r"[^\W_]+", camel_split.casefold()))
    return words & _BLIND_FIGURE_FORBIDDEN_WORDS


def _svg_scan_values(raw: bytes, *, path: str) -> tuple[str, ...]:
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RulerBuildError(f"figure asset {path} is not strict UTF-8") from error
    try:
        root = ElementTree.fromstring(decoded)
    except ElementTree.ParseError as error:
        raise RulerBuildError(f"figure asset {path} is not valid XML") from error
    values: list[str] = []
    for element in root.iter():
        descendant_text = "".join(element.itertext())
        if descendant_text:
            values.append(_decode_svg_scan_text(descendant_text))
        values.extend(
            _decode_svg_scan_text(attribute)
            for attribute in element.attrib.values()
            if attribute
        )
    return tuple(values)


def _assert_blind_svg_value(
    value: str,
    *,
    path: str,
    sentinels: set[str],
) -> None:
    forbidden_words = _forbidden_svg_words(value)
    if forbidden_words:
        raise RulerBuildError(
            f"figure asset {path} contains forbidden word(s): "
            + ", ".join(sorted(forbidden_words))
        )
    if _looks_like_filesystem_path(value):
        raise RulerBuildError(
            f"figure asset {path} contains a forbidden filesystem path"
        )
    for term in _FORBIDDEN_ASSET_TERMS:
        if _contains_token(value, term):
            raise RulerBuildError(
                f"figure asset {path} contains forbidden metadata term"
            )
    for sentinel in sentinels:
        if _contains_token(value, sentinel):
            raise RulerBuildError(f"figure asset {path} exposes hidden ruler content")


def _assert_blind_figure_assets(
    assets: Mapping[str, bytes],
    *,
    ruler: calibration_ruler.RulerManifest,
    model_ids: Sequence[str],
) -> None:
    sentinels = _figure_sentinels(ruler, model_ids=model_ids)
    items_by_review_id = {
        item.review_id: item for item in ruler.items if item.review_id is not None
    }
    for path, raw in assets.items():
        review_id = Path(path).stem
        item = items_by_review_id.get(review_id)
        if item is None:
            raise RulerBuildError(f"figure asset {path} has no manifest item")
        for value in _svg_scan_values(raw, path=path):
            _assert_blind_svg_value(value, path=path, sentinels=sentinels)


def _assert_no_blinding_leak(
    documents: Sequence[str],
    sentinels: set[str],
    *,
    context: str,
) -> None:
    haystack = "\n".join(documents)
    for sentinel in sentinels:
        if sentinel in haystack:
            raise RulerBuildError(
                f"blinding leak in {context}: a hidden value would be exposed"
            )


# --- Publication -----------------------------------------------------------


def _write_workspace(
    io: PublicationIO,
    temporary: Path,
    *,
    manifest_json: str,
    index_md: str,
    blocks: Sequence[str],
    assets: Mapping[str, bytes],
) -> None:
    io.write_text(temporary / MANIFEST_NAME, manifest_json)
    io.write_text(temporary / INDEX_NAME, index_md)
    io.make_dir(temporary / PASS_A_DIRNAME)
    for number, block in enumerate(blocks, start=1):
        io.write_text(temporary / PASS_A_DIRNAME / _block_filename(number), block)
    io.make_dir(temporary / FIGURES_DIRNAME)
    for relative, data in assets.items():
        io.write_bytes(temporary / relative, data)
    io.fsync_dir(temporary / PASS_A_DIRNAME)
    io.fsync_dir(temporary / FIGURES_DIRNAME)
    io.fsync_dir(temporary)


def _verify_manifest_roundtrip(
    io: PublicationIO,
    temporary: Path,
    *,
    manifest_json: str,
    ruler: calibration_ruler.RulerManifest,
) -> None:
    if io.read_text(temporary / MANIFEST_NAME) != manifest_json:
        raise RulerBuildError("published manifest does not match rendered manifest")
    payload = json.loads(manifest_json)
    restored = calibration_ruler.RulerManifest.from_dict(
        cast("dict[str, object]", payload["ruler"])
    )
    calibration_ruler.validate_manifest(restored)
    if restored != ruler:
        raise RulerBuildError("published manifest does not round-trip the ruler")


def _verify_blocks(
    io: PublicationIO,
    temporary: Path,
    blocks: Sequence[str],
) -> None:
    written = sorted((temporary / PASS_A_DIRNAME).glob("block-*.md"))
    if len(written) != len(blocks):
        raise RulerBuildError(
            f"published {len(written)} Pass A blocks; expected {len(blocks)}"
        )
    for number, block in enumerate(blocks, start=1):
        path = temporary / PASS_A_DIRNAME / _block_filename(number)
        if io.read_text(path) != block:
            raise RulerBuildError(f"Pass A block {number} failed re-verification")


def _verify_assets(
    io: PublicationIO,
    temporary: Path,
    assets: Mapping[str, bytes],
) -> None:
    written = sorted(p.name for p in (temporary / FIGURES_DIRNAME).iterdir())
    expected = sorted(Path(relative).name for relative in assets)
    if written != expected:
        raise RulerBuildError("published figure assets do not match the ruler")
    for relative, data in assets.items():
        actual = io.read_bytes(temporary / relative)
        if hashlib.sha256(actual).hexdigest() != hashlib.sha256(data).hexdigest():
            raise RulerBuildError(f"figure asset {relative} failed re-hash")


def _verify_workspace(
    io: PublicationIO,
    temporary: Path,
    *,
    manifest_json: str,
    index_md: str,
    blocks: Sequence[str],
    assets: Mapping[str, bytes],
    ruler: calibration_ruler.RulerManifest,
) -> None:
    _verify_manifest_roundtrip(io, temporary, manifest_json=manifest_json, ruler=ruler)
    if io.read_text(temporary / INDEX_NAME) != index_md:
        raise RulerBuildError("published index does not match rendered index")
    _verify_blocks(io, temporary, blocks)
    _verify_assets(io, temporary, assets)
    if (temporary / PASS_B_DIRNAME).exists():
        raise RulerBuildError("Pass B directory must not be published")
    _assert_no_blinding_leak(
        [index_md, *blocks],
        _hidden_sentinels(ruler),
        context="published sheets",
    )


def _link_workspace(
    io: PublicationIO,
    temporary: Path,
    final: Path,
    *,
    blocks: Sequence[str],
    assets: Mapping[str, bytes],
) -> None:
    io.make_dir(final / PASS_A_DIRNAME)
    io.make_dir(final / FIGURES_DIRNAME)
    for filename in (MANIFEST_NAME, INDEX_NAME):
        io.link_payload(temporary / filename, final / filename)
    for number in range(1, len(blocks) + 1):
        filename = _block_filename(number)
        io.link_payload(
            temporary / PASS_A_DIRNAME / filename,
            final / PASS_A_DIRNAME / filename,
        )
    for relative in assets:
        io.link_payload(temporary / relative, final / relative)
    io.fsync_dir(final / PASS_A_DIRNAME)
    io.fsync_dir(final / FIGURES_DIRNAME)
    io.fsync_dir(final)


def _publish(
    io: PublicationIO,
    *,
    root: Path,
    run_id: str,
    ruler: calibration_ruler.RulerManifest,
    manifest_json: str,
    index_md: str,
    blocks: Sequence[str],
    assets: Mapping[str, bytes],
    reattest: Callable[[], None],
) -> Path:
    lock_path = root / f".{run_id}.lock"
    run_dir = root / run_id
    if run_dir.exists() or run_dir.is_symlink():
        raise RulerBuildError(f"calibration run directory already exists: {run_dir}")

    lock_fd: int | None = None
    lock_identity: LockIdentity | None = None
    lock_owned = False
    temporary: Path | None = None
    final: Path | None = None
    try:
        try:
            lock_fd = io.open_lock(lock_path)
        except FileExistsError as error:
            raise RulerBuildError(
                f"calibration publication lock already exists: {lock_path}"
            ) from error
        lock_identity = _descriptor_identity(lock_fd)
        lock_owned = True
        io.fsync_dir(root)
        temporary = io.create_temp(root, run_id)
        io.fsync_dir(root)
        _write_workspace(
            io,
            temporary,
            manifest_json=manifest_json,
            index_md=index_md,
            blocks=blocks,
            assets=assets,
        )
        _verify_workspace(
            io,
            temporary,
            manifest_json=manifest_json,
            index_md=index_md,
            blocks=blocks,
            assets=assets,
            ruler=ruler,
        )
        io.reserve_final(run_dir)
        final = run_dir
        io.fsync_dir(root)
        _link_workspace(
            io,
            temporary,
            run_dir,
            blocks=blocks,
            assets=assets,
        )
        _verify_workspace(
            io,
            run_dir,
            manifest_json=manifest_json,
            index_md=index_md,
            blocks=blocks,
            assets=assets,
            ruler=ruler,
        )
        io.cleanup_tree(temporary)
        temporary = None
        io.fsync_dir(root)
        os.close(lock_fd)
        lock_fd = None
        if lock_identity is None:
            raise PublicationCleanupError("owned lock has no identity")
        io.remove_lock(lock_path, lock_identity)
        lock_owned = False
        io.fsync_dir(root)
        reattest()
        _reject_symlink_components(run_dir)
        io.write_marker(run_dir / SUCCESS_MARKER, "ok\n")
        io.fsync_dir(run_dir)
        io.fsync_dir(root)
        if not (run_dir / SUCCESS_MARKER).is_file():
            raise RulerBuildError("final _SUCCESS marker could not be verified")
        final = None
        return run_dir
    except BaseException as error:
        _cleanup(
            io,
            root=root,
            temporary=temporary,
            final=final,
            lock_path=lock_path,
            lock_fd=lock_fd,
            lock_identity=lock_identity,
            lock_owned=lock_owned,
            primary=error,
        )
        raise


def _cleanup(
    io: PublicationIO,
    *,
    root: Path,
    temporary: Path | None,
    final: Path | None,
    lock_path: Path,
    lock_fd: int | None,
    lock_identity: LockIdentity | None,
    lock_owned: bool,
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
        except BaseException as err:  # noqa: BLE001
            errors.append(err)
    if lock_owned:
        try:
            if lock_identity is None:
                raise PublicationCleanupError("owned lock has no identity")
            io.remove_lock(lock_path, lock_identity)
        except BaseException as err:  # noqa: BLE001
            errors.append(err)
    try:
        io.fsync_dir(root)
    except BaseException as err:  # noqa: BLE001
        errors.append(err)
    if errors:
        raise PublicationCleanupError(
            f"publication cleanup failed: {type(errors[0]).__name__}"
        ) from primary


# --- Public build entry ----------------------------------------------------


def build(
    *,
    trusted_path: Path | str,
    failures_path: Path | str,
    shadow_path: Path | str,
    out_root: Path | str,
    run_id: str,
    seed: int = 7,
    io: PublicationIO | None = None,
    allow_test_paths: bool = False,
    _repo_state_fn: RepoStateFn = shadow_foundry.collect_repo_state,
    _attestation_fn: AttestationFn | None = None,
) -> Path:
    """Build the frozen ruler and atomically publish its Pass A workspace."""
    _validate_run_id(run_id)
    root = validate_output_root(
        out_root,
        allow_test_paths=allow_test_paths,
    )
    attestation_fn = _attestation_fn
    if attestation_fn is None:
        attestation_fn = (
            (lambda: _test_execution_attestation(_repo_state_fn))
            if allow_test_paths
            else _capture_execution_attestation
        )
    entry_attestation = attestation_fn()
    publisher = io or PublicationIO()

    trusted = _load_problem_set(
        trusted_path,
        name="trusted",
        allow_test_paths=allow_test_paths,
    )
    failures = _load_problem_set(
        failures_path,
        name="failure",
        allow_test_paths=allow_test_paths,
    )
    shadow = _load_shadow_run(
        shadow_path,
        allow_test_paths=allow_test_paths,
    )

    ruler = calibration_ruler.build_ruler(
        trusted.items,
        failures.items,
        shadow.items,
        seed=seed,
    )
    index_md, blocks, assets = _rendered_workspace(ruler)
    _assert_blind_figure_assets(
        assets,
        ruler=ruler,
        model_ids=shadow.model_ids,
    )

    inputs = {
        "trusted": {"sha256": trusted.sha256, "count": len(trusted.items)},
        "failure": {"sha256": failures.sha256, "count": len(failures.items)},
        "shadow": {
            "manifest_sha256": shadow.manifest_sha256,
            "run_id": shadow.run_id,
            "candidate_count": len(shadow.items),
        },
    }
    manifest = _build_manifest(
        ruler,
        run_id=run_id,
        seed=seed,
        inputs=inputs,
        attestation=entry_attestation,
    )
    manifest_json = (
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    _ensure_directory_chain(root)
    fingerprints = (
        trusted.fingerprint,
        failures.fingerprint,
        *shadow.fingerprints,
    )
    return _publish(
        publisher,
        root=root,
        run_id=run_id,
        ruler=ruler,
        manifest_json=manifest_json,
        index_md=index_md,
        blocks=blocks,
        assets=assets,
        reattest=lambda: _reattest_before_success(
            entry=entry_attestation,
            attestation_fn=attestation_fn,
            fingerprints=fingerprints,
        ),
    )


# --- Offline fixture and self-check ----------------------------------------


class _DistinctBackend:
    """A deterministic offline backend returning a distinct stem per slot."""

    _CHUNK_TEXT = (
        "A particle in uniform circular motion has constant speed while its "
        "velocity direction changes."
    )

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        request: object,
    ) -> object:
        from pgrep.ai import model_backend  # type: ignore[import-not-found]

        typed = cast("model_backend.ModelRequest", request)
        self.calls += 1
        if typed.role == "generator":
            text = json.dumps(self._candidate(typed.seed))
        else:
            text = json.dumps(
                {
                    "answer": "A",
                    "reasoning": f"{typed.model.family} independent solve",
                    "confidence": 0.75,
                }
            )
        return model_backend.ModelResult(
            request_id=typed.request_id,
            model_id=typed.model.model_id,
            status="finished",
            text=text,
            agent_id=f"offline-agent-{self.calls}",
            run_id=f"offline-run-{self.calls}",
        )

    def _candidate(self, seed: int) -> dict[str, object]:
        candidate = shadow_foundry._offline_candidate()  # noqa: SLF001
        candidate["stem"] = (
            f"{self._CHUNK_TEXT} Variant {seed} keeps the same physics with "
            "distinct wording so each ruler item is unique."
        )
        return candidate


def offline_shadow_run(
    root: Path | str,
    *,
    run_id: str = "offline-shadow",
    n: int = 45,
    seed: int = shadow_foundry.DEFAULT_SEED,
) -> Path:
    """Publish an explicitly synthetic, test-fake shadow run."""
    return _fixture_shadow_run(
        root,
        run_id=run_id,
        n=n,
        seed=seed,
    )


def _fixture_shadow_run(
    root: Path | str,
    *,
    run_id: str,
    n: int,
    seed: int,
) -> Path:
    from pgrep.ai import shadow_portfolio  # type: ignore[import-not-found]

    roles = shadow_foundry._default_roles()  # noqa: SLF001
    allocation = shadow_portfolio.allocate_families(n, seed=seed)
    recorder = shadow_foundry._RecordingBackend(  # noqa: SLF001
        _DistinctBackend(), secrets=()
    )
    chunks = shadow_foundry.sanitize_retrieved(
        shadow_foundry._offline_search(shadow_foundry.DEFAULT_TOPIC)  # noqa: SLF001
    )
    candidates: list[dict[str, object]] = []
    raw_responses: list[dict[str, object]] = []
    for slot, origin in enumerate(allocation):
        recorder.slot = slot
        recorder.bind_retrieval(chunks, origin=origin)
        record = shadow_portfolio.run_candidate(
            topic=shadow_foundry.DEFAULT_TOPIC,
            retrieved=chunks,
            origin=origin,
            roles=roles,
            backend=recorder,
            seed=seed + slot,
        )
        shadow_foundry._bind_candidate_replay_metadata(  # noqa: SLF001
            record,
            topic=shadow_foundry.DEFAULT_TOPIC,
            seed=seed + slot,
            retrieved=chunks,
        )
        candidate, candidate_raw = shadow_foundry._sanitize_candidate_evidence(  # noqa: SLF001
            record,
            slot=slot,
            secrets=(),
        )
        candidates.append(candidate)
        raw_responses.extend(candidate_raw)
    manifest = shadow_foundry.build_run_manifest(
        run_id=run_id,
        status="success",
        roles=roles,
        environment=_synthetic_fixture_environment(),
        topic=shadow_foundry.DEFAULT_TOPIC,
        expected_candidate_count=n,
        seed=seed,
        allocation=allocation,
        candidates=candidates,
        failures=[],
        raw_responses=raw_responses,
    )
    return shadow_foundry.publish_run(
        root,
        run_id,
        candidates=candidates,
        failures=[],
        raw_responses=raw_responses,
        manifest=manifest,
        allow_test_output=True,
    )


def _synthetic_fixture_environment() -> "shadow_foundry.RunEnvironment":
    sha, _tree_status = shadow_foundry.collect_repo_state()
    probe = shadow_foundry.make_probe_metadata(
        [
            {"id": "gpt-5.6-sol-max", "parameters": [], "variants": []},
            {
                "id": "claude-opus-4-8-thinking-high-fast",
                "parameters": [],
                "variants": [],
            },
            {"id": "cursor-grok-4.5-high-fast", "parameters": [], "variants": []},
        ],
        sdk_version="offline-fake-0.1.9",
    )
    fixture = b"offline-corpus-fixture"
    image_digest = "sha256:" + hashlib.sha256(b"offline-worker").hexdigest()
    return shadow_foundry.RunEnvironment(
        code_sha=sha,
        tree_status="clean",
        worker_image="pgrep-shadow-worker:synthetic-test",
        worker_image_digest=image_digest,
        corpus_index_fingerprint="sha256:" + hashlib.sha256(fixture).hexdigest(),
        probe=probe,
        synthetic=True,
        execution_mode="test-fake",
        corpus_index_mtime_ns=0,
        corpus_index_size=len(fixture),
    )


_SELF_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<rect x="1" y="1" width="8" height="8"/></svg>'
)
_SELF_CHECK_KINDS = ("conceptual", "computational")


def offline_problem_item(stratum: str, index: int) -> dict[str, object]:
    """Return one deterministic trusted/failure fixture problem."""
    slugs = tuple(sorted(calibration_ruler.BLUEPRINT_CATEGORIES))
    category = slugs[index % len(slugs)]
    stem = f"Consider configuration {index} governed by {category} principles."
    if index % 2 == 0:
        stem = f'{stem}<div class="pg-figure">{_SELF_CHECK_SVG}</div>'
    item: dict[str, object] = {
        "id": f"{stratum}-{index}",
        "topic": f"topic::{category}",
        "blueprint_category": category,
        "kind": _SELF_CHECK_KINDS[index % len(_SELF_CHECK_KINDS)],
        "difficulty": (0.1, 0.5, 0.9)[index % 3],
        "stem": stem,
        "choices": ["1", "2", "3", "4", "5"],
        "correct": "ABCDE"[index % 5],
        "source_ref": f"OpenStax {stratum} chapter {index}",
    }
    return item


def _self_check() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        trusted = base / "trusted.json"
        failures = base / "failure.json"
        trusted.write_text(
            json.dumps([offline_problem_item("trusted", i) for i in range(50)]),
            encoding="utf-8",
        )
        failures.write_text(
            json.dumps([offline_problem_item("failure", i) for i in range(50)]),
            encoding="utf-8",
        )
        shadow_dir = offline_shadow_run(base / "shadow-runs")
        try:
            load_shadow_run(shadow_dir, allow_test_paths=True)
        except RulerBuildError as error:
            assert "synthetic" in str(error)
        else:
            raise AssertionError("synthetic self-check run was accepted")
    print("[ok] calibration ruler self-check passed")
    return 0


# --- CLI -------------------------------------------------------------------


def _default_run_id() -> str:
    return "ruler-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the private blind calibration ruler and Pass A workspace."
    )
    parser.add_argument("--trusted", help="path to the trusted problem set JSON")
    parser.add_argument("--failures", help="path to the failure problem set JSON")
    parser.add_argument("--shadow", help="path to a finalized shadow-foundry run")
    parser.add_argument("--out", default=str(CALIBRATION_ROOT))
    parser.add_argument(
        "--run", default=None, help="new run directory name under --out"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run a fully offline end-to-end smoke and exit",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_check:
        return _self_check()
    for name in ("trusted", "failures", "shadow"):
        if not getattr(args, name):
            parser.error(f"--{name} is required unless --self-check is used")
    try:
        run_dir = build(
            trusted_path=args.trusted,
            failures_path=args.failures,
            shadow_path=args.shadow,
            out_root=args.out,
            run_id=args.run or _default_run_id(),
            seed=args.seed,
        )
    except (RulerBuildError, ValueError) as error:
        parser.error(str(error))
    print(f"wrote {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
