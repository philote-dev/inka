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
import secrets
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
import atomic_rename  # noqa: E402

_AI_ROOT = Path(_ai_path.add_ai_core()).resolve()

import shadow_foundry  # noqa: E402
from pgrep.ai import (  # type: ignore[import-not-found]  # noqa: E402
    calibration_ruler,
    calibration_sheet,
    shadow_portfolio,
)

_SOURCE_PATHS = {
    "atomic_rename": Path(atomic_rename.__file__).resolve(),
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
BUILD_CAPABILITY_PROBE_ROOT = ".calibration-build-probes"

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


@dataclass
class _RetainedDirectory:
    path: Path
    fd: int
    identity: LockIdentity
    parent: _RetainedDirectory | None
    name: str | None


@dataclass(frozen=True)
class _FileFingerprint:
    name: str
    path: Path
    sha256: str
    parent: _RetainedDirectory
    fd: int
    identity: LockIdentity
    content: bytes


@dataclass(frozen=True)
class _OwnedFile:
    identity: LockIdentity
    content: bytes


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

    def _bindings(self) -> dict[Path, int]:
        try:
            return self._directory_bindings
        except AttributeError:
            self._directory_bindings: dict[Path, int] = {}
            return self._directory_bindings

    def _files(self) -> dict[Path, _OwnedFile]:
        try:
            return self._owned_files
        except AttributeError:
            self._owned_files: dict[Path, _OwnedFile] = {}
            return self._owned_files

    def bind_directory(self, path: Path, fd: int) -> None:
        self._bindings()[path.absolute()] = fd

    def unbind_directory(self, path: Path) -> None:
        self._bindings().pop(path.absolute(), None)

    def directory_fd(self, path: Path) -> int:
        try:
            return self._bindings()[path.absolute()]
        except KeyError as error:
            raise PublicationCleanupError(
                f"retained directory descriptor is unavailable: {path}"
            ) from error

    def close_bindings(self) -> None:
        bindings = self._bindings()
        for fd in set(bindings.values()):
            try:
                os.close(fd)
            except OSError:
                pass
        bindings.clear()
        self._files().clear()

    def _parent_fd(self, path: Path) -> int:
        return self.directory_fd(path.parent)

    def open_lock(self, path: Path) -> int:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            self.write_lock(fd, f"pid={os.getpid()}\n".encode())
            self.sync_lock(fd)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def write_lock(self, fd: int, content: bytes) -> None:
        os.write(fd, content)

    def sync_lock(self, fd: int) -> None:
        os.fsync(fd)

    def create_temp(self, root: Path, run_id: str) -> Path:
        root_fd = self.directory_fd(root)
        for _ in range(128):
            name = f".{run_id}.{secrets.token_hex(12)}.tmp"
            try:
                os.mkdir(name, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                continue
            path = root / name
            preopen = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            fd = os.open(name, _directory_flags(), dir_fd=root_fd)
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (
                preopen.st_dev,
                preopen.st_ino,
            ) or not stat.S_ISDIR(opened.st_mode):
                os.close(fd)
                raise PublicationCleanupError(
                    "builder staging identity changed while opening"
                )
            self.bind_directory(path, fd)
            return path
        raise PublicationCleanupError("could not reserve builder staging directory")

    def make_dir(self, path: Path) -> None:
        parent_fd = self._parent_fd(path)
        os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
        preopen = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        fd = os.open(path.name, _directory_flags(), dir_fd=parent_fd)
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (
            preopen.st_dev,
            preopen.st_ino,
        ) or not stat.S_ISDIR(opened.st_mode):
            os.close(fd)
            raise PublicationCleanupError(
                f"builder directory identity changed while opening: {path.name}"
            )
        self.bind_directory(path, fd)

    def reserve_final(self, path: Path) -> None:
        self.make_dir(path)

    def link_payload(self, source: Path, destination: Path) -> None:
        content = _read_file_at(
            self._parent_fd(source),
            source.name,
            label=f"publication payload {source.name}",
        )
        identity = _write_exclusive_at(
            self._parent_fd(destination),
            destination.name,
            content,
        )
        self._files()[destination.absolute()] = _OwnedFile(identity, content)

    def write_text(self, path: Path, content: str) -> None:
        encoded = content.encode("utf-8")
        identity = _write_exclusive_at(self._parent_fd(path), path.name, encoded)
        self._files()[path.absolute()] = _OwnedFile(identity, encoded)

    def write_bytes(self, path: Path, content: bytes) -> None:
        identity = _write_exclusive_at(self._parent_fd(path), path.name, content)
        self._files()[path.absolute()] = _OwnedFile(identity, content)

    def read_text(self, path: Path) -> str:
        return _read_file_at(
            self._parent_fd(path),
            path.name,
            label=f"published {path.name}",
        ).decode("utf-8", errors="strict")

    def read_bytes(self, path: Path) -> bytes:
        return _read_file_at(
            self._parent_fd(path),
            path.name,
            label=f"published {path.name}",
        )

    def write_marker(self, path: Path, content: str) -> None:
        self.write_text(path, content)

    def attest_file(self, path: Path, expected: bytes) -> None:
        try:
            owned = self._files()[path.absolute()]
        except KeyError as error:
            raise RulerBuildError(
                f"published file ownership is unavailable: {path.name}"
            ) from error
        parent_fd = self._parent_fd(path)
        try:
            bound = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            fd = os.open(
                path.name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise RulerBuildError(
                f"published file binding is unavailable: {path.name}"
            ) from error
        try:
            opened = os.fstat(fd)
            chunks: list[bytes] = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
            actual = b"".join(chunks)
            bound_after = os.stat(
                path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        finally:
            os.close(fd)
        if (
            (bound.st_dev, bound.st_ino) != owned.identity
            or (bound_after.st_dev, bound_after.st_ino) != owned.identity
            or (opened.st_dev, opened.st_ino) != owned.identity
            or not stat.S_ISREG(bound.st_mode)
            or not stat.S_ISREG(bound_after.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or actual != expected
            or actual != owned.content
        ):
            raise RulerBuildError(f"published file identity/bytes changed: {path.name}")

    def fsync_dir(self, path: Path) -> None:
        os.fsync(self.directory_fd(path))

    def cleanup_tree(self, path: Path) -> None:
        del path

    def remove_lock(self, path: Path, identity: LockIdentity) -> None:
        del path, identity

    def after_input_open(self, name: str) -> None:
        pass

    def before_input_attestation(self, name: str) -> None:
        pass

    def before_output_root_open(self, path: Path) -> None:
        pass

    def before_final_payload(self, relative: str) -> None:
        pass

    def before_success_marker(self) -> None:
        pass

    def before_quarantine(self, relative: str) -> None:
        pass

    def before_quarantine_rename(self, relative: str, target_name: str) -> None:
        pass

    def preflight_rename_noreplace(self) -> None:
        atomic_rename.preflight_rename_noreplace()

    def rename_noreplace(
        self,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        atomic_rename.rename_noreplace(
            source_dir_fd,
            source_name,
            destination_dir_fd,
            destination_name,
        )

    def after_capability_probe(self, relative: str) -> None:
        pass


def _write_exclusive_at(
    parent_fd: int,
    name: str,
    content: bytes,
) -> LockIdentity:
    fd = os.open(
        name,
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=parent_fd,
    )
    try:
        identity = _descriptor_identity(fd)
        written = 0
        while written < len(content):
            count = os.write(fd, content[written:])
            if count <= 0:
                raise OSError("short publication write")
            written += count
        os.fsync(fd)
    finally:
        os.close(fd)
    return identity


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _read_file_at(parent_fd: int, component: str, *, label: str) -> bytes:
    fd = os.open(
        component,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RulerBuildError(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _descriptor_identity(fd: int) -> LockIdentity:
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino)


def _reattest_directory(directory: _RetainedDirectory) -> None:
    info = os.fstat(directory.fd)
    if (info.st_dev, info.st_ino) != directory.identity or not stat.S_ISDIR(
        info.st_mode
    ):
        raise RulerBuildError("retained directory identity changed")
    if directory.parent is None:
        return
    try:
        bound = os.stat(
            cast(str, directory.name),
            dir_fd=directory.parent.fd,
            follow_symlinks=False,
        )
    except OSError as error:
        raise RulerBuildError("retained directory binding changed") from error
    if (
        (bound.st_dev, bound.st_ino) != directory.identity
        or not stat.S_ISDIR(bound.st_mode)
        or stat.S_ISLNK(bound.st_mode)
    ):
        raise RulerBuildError("retained directory binding identity changed")


def _reattest_directory_chain(directory: _RetainedDirectory) -> None:
    chain: list[_RetainedDirectory] = []
    current: _RetainedDirectory | None = directory
    while current is not None:
        chain.append(current)
        current = current.parent
    for retained in reversed(chain):
        _reattest_directory(retained)


def _close_directories(directories: Sequence[_RetainedDirectory]) -> None:
    for directory in reversed(directories):
        try:
            os.close(directory.fd)
        except OSError:
            pass


def _open_output_root(
    root: Path,
    io: PublicationIO,
) -> tuple[_RetainedDirectory, tuple[_RetainedDirectory, ...]]:
    directories: list[_RetainedDirectory] = []
    try:
        root_fd = os.open("/", _directory_flags())
        filesystem_root = _RetainedDirectory(
            path=Path("/"),
            fd=root_fd,
            identity=_descriptor_identity(root_fd),
            parent=None,
            name=None,
        )
        directories.append(filesystem_root)
        io.bind_directory(filesystem_root.path, root_fd)
        parent = filesystem_root
        current = Path("/")
        for component in root.parts[1:]:
            current /= component
            try:
                preopen = os.stat(
                    component,
                    dir_fd=parent.fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=parent.fd)
                preopen = os.stat(
                    component,
                    dir_fd=parent.fd,
                    follow_symlinks=False,
                )
            if not stat.S_ISDIR(preopen.st_mode) or stat.S_ISLNK(preopen.st_mode):
                raise RulerBuildError(
                    f"output root component is not a directory: {current}"
                )
            io.before_output_root_open(current)
            fd = os.open(component, _directory_flags(), dir_fd=parent.fd)
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (
                preopen.st_dev,
                preopen.st_ino,
            ) or not stat.S_ISDIR(opened.st_mode):
                os.close(fd)
                raise RulerBuildError(
                    f"output root identity changed while opening: {current}"
                )
            child = _RetainedDirectory(
                path=current,
                fd=fd,
                identity=(opened.st_dev, opened.st_ino),
                parent=parent,
                name=component,
            )
            directories.append(child)
            io.bind_directory(current, fd)
            parent = child
        return parent, tuple(directories)
    except BaseException:
        _close_directories(directories)
        for directory in directories:
            io.unbind_directory(directory.path)
        raise


def _retained_child(io: PublicationIO, path: Path) -> _RetainedDirectory:
    parent_path = path.parent
    parent_fd = io.directory_fd(parent_path)
    info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    fd = io.directory_fd(path)
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISDIR(
        opened.st_mode
    ):
        raise RulerBuildError(f"owned directory identity changed: {path.name}")
    parent = _RetainedDirectory(
        path=parent_path,
        fd=parent_fd,
        identity=_descriptor_identity(parent_fd),
        parent=None,
        name=None,
    )
    return _RetainedDirectory(
        path=path,
        fd=fd,
        identity=(info.st_dev, info.st_ino),
        parent=parent,
        name=path.name,
    )


def _builder_rename_noreplace(
    io: PublicationIO,
    source_dir_fd: int,
    source_name: str,
    destination_dir_fd: int,
    destination_name: str,
) -> None:
    try:
        io.rename_noreplace(
            source_dir_fd,
            source_name,
            destination_dir_fd,
            destination_name,
        )
    except atomic_rename.AtomicRenameError as error:
        raise PublicationCleanupError(str(error)) from error


def _builder_quarantine(
    io: PublicationIO,
    root: _RetainedDirectory,
) -> _RetainedDirectory:
    name = ".calibration-build-quarantine"
    try:
        os.mkdir(name, mode=0o700, dir_fd=root.fd)
    except FileExistsError:
        pass
    preopen = os.stat(name, dir_fd=root.fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(preopen.st_mode)
        or stat.S_ISLNK(preopen.st_mode)
        or stat.S_IMODE(preopen.st_mode) != 0o700
        or preopen.st_dev != os.fstat(root.fd).st_dev
    ):
        raise PublicationCleanupError("builder quarantine root is not private")
    fd = os.open(name, _directory_flags(), dir_fd=root.fd)
    opened = os.fstat(fd)
    if (
        (opened.st_dev, opened.st_ino) != (preopen.st_dev, preopen.st_ino)
        or not stat.S_ISDIR(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o700
    ):
        os.close(fd)
        raise PublicationCleanupError(
            "builder quarantine root identity changed while opening"
        )
    path = root.path / name
    io.bind_directory(path, fd)
    return _RetainedDirectory(
        path=path,
        fd=fd,
        identity=(opened.st_dev, opened.st_ino),
        parent=root,
        name=name,
    )


def _names_with_identity(
    parent_fd: int,
    identity: LockIdentity,
) -> list[str]:
    matches: list[str] = []
    for name in os.listdir(parent_fd):
        if name == ".calibration-build-quarantine":
            continue
        try:
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) == identity:
            matches.append(name)
    return matches


def _move_to_builder_quarantine(
    io: PublicationIO,
    root: _RetainedDirectory,
    quarantine: _RetainedDirectory,
    source_name: str,
    *,
    relative: str,
) -> os.stat_result | None:
    for _ in range(128):
        target = f"{source_name}.{secrets.token_hex(16)}"
        io.before_quarantine_rename(relative, target)
        try:
            _builder_rename_noreplace(
                io,
                root.fd,
                source_name,
                quarantine.fd,
                target,
            )
        except FileExistsError:
            continue
        except FileNotFoundError:
            return None
        moved = os.stat(target, dir_fd=quarantine.fd, follow_symlinks=False)
        os.fsync(root.fd)
        os.fsync(quarantine.fd)
        return moved
    raise PublicationCleanupError(
        "builder quarantine destination remained occupied after 128 attempts"
    )


def _preserve_owned_binding(
    io: PublicationIO,
    root: _RetainedDirectory,
    source_name: str,
    identity: LockIdentity,
    *,
    relative: str,
) -> None:
    io.before_quarantine(relative)
    quarantine = _builder_quarantine(io, root)
    try:
        moved = _move_to_builder_quarantine(
            io,
            root,
            quarantine,
            source_name,
            relative=relative,
        )
        if moved is not None and (moved.st_dev, moved.st_ino) == identity:
            return
        matches = _names_with_identity(root.fd, identity)
        if len(matches) != 1:
            raise PublicationCleanupError(
                f"could not uniquely locate owned builder identity for {relative}"
            )
        owned = _move_to_builder_quarantine(
            io,
            root,
            quarantine,
            matches[0],
            relative=relative,
        )
        if owned is None or (owned.st_dev, owned.st_ino) != identity:
            raise PublicationCleanupError(
                f"owned builder identity changed while preserving {relative}"
            )
    finally:
        os.close(quarantine.fd)
        io.unbind_directory(quarantine.path)


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


# --- Input loading (trusted / failure) -------------------------------------


def _reject_private_input_path(path: Path, *, name: str) -> None:
    if _PRIVATE_DATASET_MARKER.search(str(path)):
        raise RulerBuildError(
            f"{name} path must not reference gold, held-out, ETS, or tier-3 data"
        )


def _validate_retained_input_location(
    path: Path | str,
    *,
    name: str,
    allow_test_paths: bool,
    required_root: Path,
) -> Path:
    raw = Path(path)
    _reject_path_escape(raw, name=name)
    absolute = Path(os.path.abspath(raw))
    _reject_private_input_path(absolute, name=name)
    if allow_test_paths and _is_relative_to(
        absolute,
        Path(tempfile.gettempdir()).resolve(),
    ):
        return absolute
    required = Path(os.path.abspath(required_root))
    if not _is_relative_to(absolute, required):
        raise RulerBuildError(
            f"{name} must be under the exact repository {required_root.name} root"
        )
    _git_ignored_path(absolute, name=name)
    return absolute


def _open_retained_directory(
    path: Path,
    *,
    name: str,
) -> tuple[_RetainedDirectory, tuple[_RetainedDirectory, ...]]:
    directories: list[_RetainedDirectory] = []
    try:
        root_fd = os.open("/", _directory_flags())
        root_info = os.fstat(root_fd)
        root = _RetainedDirectory(
            path=Path("/"),
            fd=root_fd,
            identity=_descriptor_identity(root_fd),
            parent=None,
            name=None,
        )
        if not stat.S_ISDIR(root_info.st_mode):
            raise RulerBuildError("filesystem root is not a directory")
        directories.append(root)
        parent = root
        current = Path("/")
        for component in path.parts[1:]:
            current /= component
            fd = os.open(component, _directory_flags(), dir_fd=parent.fd)
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                os.close(fd)
                raise RulerBuildError(f"{name} component is not a directory")
            child = _RetainedDirectory(
                path=current,
                fd=fd,
                identity=_descriptor_identity(fd),
                parent=parent,
                name=component,
            )
            directories.append(child)
            parent = child
        return parent, tuple(directories)
    except OSError as error:
        for directory in reversed(directories):
            os.close(directory.fd)
        raise RulerBuildError(
            f"could not open {name}; path component is missing, changed, "
            f"or a symlink component: {error}"
        ) from error
    except BaseException:
        for directory in reversed(directories):
            os.close(directory.fd)
        raise


def _open_retained_file_at(
    parent: _RetainedDirectory,
    filename: str,
    *,
    name: str,
    io: PublicationIO,
) -> _FileFingerprint:
    try:
        fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent.fd,
        )
    except OSError as error:
        raise RulerBuildError(
            f"could not open {name}; file is missing, changed, or a symlink: {error}"
        ) from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RulerBuildError(f"{name} must be a regular file")
        io.after_input_open(name)
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        raw = b"".join(chunks)
        return _FileFingerprint(
            name=name,
            path=parent.path / filename,
            sha256=hashlib.sha256(raw).hexdigest(),
            parent=parent,
            fd=fd,
            identity=_descriptor_identity(fd),
            content=raw,
        )
    except BaseException:
        os.close(fd)
        raise


def _open_retained_file(
    path: Path | str,
    *,
    name: str,
    allow_test_paths: bool,
    required_root: Path,
    io: PublicationIO,
) -> _FileFingerprint:
    absolute = _validate_retained_input_location(
        path,
        name=name,
        allow_test_paths=allow_test_paths,
        required_root=required_root,
    )
    parent, directories = _open_retained_directory(absolute.parent, name=name)
    try:
        return _open_retained_file_at(
            parent,
            absolute.name,
            name=name,
            io=io,
        )
    except BaseException:
        for directory in reversed(directories):
            os.close(directory.fd)
        raise


def _fingerprint_directories(
    fingerprint: _FileFingerprint,
) -> tuple[_RetainedDirectory, ...]:
    directories: list[_RetainedDirectory] = []
    current: _RetainedDirectory | None = fingerprint.parent
    while current is not None:
        directories.append(current)
        current = current.parent
    return tuple(reversed(directories))


def _close_fingerprints(fingerprints: Sequence[_FileFingerprint]) -> None:
    file_fds = {fingerprint.fd for fingerprint in fingerprints}
    directory_fds = {
        directory.fd
        for fingerprint in fingerprints
        for directory in _fingerprint_directories(fingerprint)
    }
    for fd in file_fds:
        try:
            os.close(fd)
        except OSError:
            pass
    for fd in directory_fds:
        try:
            os.close(fd)
        except OSError:
            pass


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
    io: PublicationIO,
) -> _LoadedProblemSet:
    fingerprint = _open_retained_file(
        path,
        name=f"{name} input",
        allow_test_paths=allow_test_paths,
        required_root=CONTENT_RUN_ROOT,
        io=io,
    )
    try:
        raw = fingerprint.content
        document = _parse_json_bytes(raw, name=f"{name} input")
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
            fingerprint,
        )
    except BaseException:
        _close_fingerprints((fingerprint,))
        raise


def load_problem_set(
    path: Path | str,
    *,
    name: str,
    allow_test_paths: bool = False,
) -> list[dict[str, object]]:
    """Load a trusted or failure problem set from one explicit JSON file."""
    loaded = _load_problem_set(
        path,
        name=name,
        allow_test_paths=allow_test_paths,
        io=PublicationIO(),
    )
    try:
        return list(loaded.items)
    finally:
        _close_fingerprints((loaded.fingerprint,))


# --- Shadow run loading (finalized _SUCCESS) -------------------------------


def _normalize_shadow_run_path(
    path: Path | str,
    *,
    allow_test_paths: bool,
) -> Path:
    raw = Path(path)
    if raw.name == "candidates.json":
        raw = raw.parent
    elif raw.suffix:
        raise RulerBuildError(
            "shadow input must be a finalized run directory or its candidates.json"
        )
    return _validate_retained_input_location(
        raw,
        name="shadow run",
        allow_test_paths=allow_test_paths,
        required_root=SHADOW_ROOT,
    )


def _require_finalized_marker(
    run_dir: _RetainedDirectory,
    *,
    io: PublicationIO,
) -> _FileFingerprint:
    try:
        os.stat(FAILED_MARKER, dir_fd=run_dir.fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise RulerBuildError("shadow run is a diagnostic _FAILED run")
    try:
        return _open_retained_file_at(
            run_dir,
            SUCCESS_MARKER,
            name="shadow success marker",
            io=io,
        )
    except RulerBuildError as error:
        raise RulerBuildError("shadow run has no finalized _SUCCESS marker") from error


def _load_shadow_artifact(
    run_dir: _RetainedDirectory,
    filename: str,
    *,
    io: PublicationIO,
) -> tuple[object, bytes, _FileFingerprint]:
    fingerprint = _open_retained_file_at(
        run_dir,
        filename,
        name=f"shadow {filename}",
        io=io,
    )
    try:
        return (
            _parse_json_bytes(fingerprint.content, name=f"shadow {filename}"),
            fingerprint.content,
            fingerprint,
        )
    except BaseException:
        os.close(fingerprint.fd)
        raise


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
    runtime = manifest.get("runtime")
    if not isinstance(runtime, Mapping):
        raise RulerBuildError("shadow run has no runtime metadata")
    if runtime.get("backend_kind") != "truefoundry-openai-compatible":
        raise RulerBuildError("shadow run must use the TrueFoundry backend")
    if runtime.get("execution_mode") != "gateway":
        raise RulerBuildError("shadow run must use gateway execution")
    sdk_version = runtime.get("openai_sdk_version")
    if type(sdk_version) is not str or not sdk_version.strip():
        raise RulerBuildError("shadow run has no OpenAI SDK version")
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


def _validate_loaded_shadow(
    *,
    run_path: Path,
    manifest: object,
    manifest_bytes: bytes,
    candidates: object,
    candidate_bytes: bytes,
    failures: object,
    failure_bytes: bytes,
    probe: object,
    probe_bytes: bytes,
    raw_responses: object,
    raw_response_bytes: bytes,
    fingerprints: tuple[_FileFingerprint, ...],
) -> _LoadedShadowRun:
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
            publication_run_id=run_path.name,
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
    return _LoadedShadowRun(
        tuple(items),
        str(manifest["run_id"]),
        hashlib.sha256(manifest_bytes).hexdigest(),
        model_ids,
        fingerprints,
    )


def _load_shadow_run(
    path: Path | str,
    *,
    allow_test_paths: bool,
    io: PublicationIO,
) -> _LoadedShadowRun:
    """Load and verify a finalized shadow-foundry ``_SUCCESS`` run.

    Returns the shadow-stratum problem items, the shadow run ID, and the hex
    SHA-256 of the run manifest for provenance. Rejects a ``_FAILED``,
    synthetic, partial, dirty, or stale run through the strict shadow contract.
    """
    run_path = _normalize_shadow_run_path(
        path,
        allow_test_paths=allow_test_paths,
    )
    run_dir, _directories = _open_retained_directory(
        run_path,
        name="shadow run",
    )
    opened: list[_FileFingerprint] = []
    try:
        success_fingerprint = _require_finalized_marker(run_dir, io=io)
        opened.append(success_fingerprint)
        manifest, manifest_bytes, manifest_fingerprint = _load_shadow_artifact(
            run_dir,
            MANIFEST_NAME,
            io=io,
        )
        opened.append(manifest_fingerprint)
        candidates, candidate_bytes, candidate_fingerprint = _load_shadow_artifact(
            run_dir,
            "candidates.json",
            io=io,
        )
        opened.append(candidate_fingerprint)
        failures, failure_bytes, failures_fingerprint = _load_shadow_artifact(
            run_dir,
            "failures.json",
            io=io,
        )
        opened.append(failures_fingerprint)
        probe, probe_bytes, probe_fingerprint = _load_shadow_artifact(
            run_dir,
            "probe.json",
            io=io,
        )
        opened.append(probe_fingerprint)
        (
            raw_responses,
            raw_response_bytes,
            raw_response_fingerprint,
        ) = _load_shadow_artifact(
            run_dir,
            "raw-responses.json",
            io=io,
        )
        opened.append(raw_response_fingerprint)
        artifact_fingerprints = (
            manifest_fingerprint,
            candidate_fingerprint,
            failures_fingerprint,
            probe_fingerprint,
            raw_response_fingerprint,
            success_fingerprint,
        )
        return _validate_loaded_shadow(
            run_path=run_path,
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            candidates=candidates,
            candidate_bytes=candidate_bytes,
            failures=failures,
            failure_bytes=failure_bytes,
            probe=probe,
            probe_bytes=probe_bytes,
            raw_responses=raw_responses,
            raw_response_bytes=raw_response_bytes,
            fingerprints=artifact_fingerprints,
        )
    except BaseException:
        if opened:
            _close_fingerprints(opened)
        else:
            _close_directories(_directories)
        raise


def load_shadow_run(
    path: Path | str,
    *,
    allow_test_paths: bool = False,
) -> tuple[list[dict[str, object]], str, str]:
    loaded = _load_shadow_run(
        path,
        allow_test_paths=allow_test_paths,
        io=PublicationIO(),
    )
    try:
        return list(loaded.items), loaded.run_id, loaded.manifest_sha256
    finally:
        _close_fingerprints(loaded.fingerprints)


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
    provenance_value = problem.get("provenance")
    if isinstance(provenance_value, Mapping):
        provenance_payload = dict(cast("Mapping[str, object]", provenance_value))
        quote_anchor = provenance_payload.get("quote_anchor")
        if not isinstance(quote_anchor, str) or not quote_anchor.strip():
            raise RulerBuildError(
                "shadow candidate provenance has no non-empty quote anchor"
            )
        item["source_excerpt"] = quote_anchor
        item["provenance"] = provenance_payload
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
    io: PublicationIO,
    *,
    notify_hooks: bool = True,
) -> None:
    for fingerprint in fingerprints:
        if notify_hooks:
            io.before_input_attestation(fingerprint.name)
        for directory in _fingerprint_directories(fingerprint):
            info = os.fstat(directory.fd)
            if _descriptor_identity(
                directory.fd
            ) != directory.identity or not stat.S_ISDIR(info.st_mode):
                raise RulerBuildError(
                    f"input directory identity changed: {fingerprint.name}"
                )
            if directory.parent is None:
                continue
            try:
                bound = os.stat(
                    cast(str, directory.name),
                    dir_fd=directory.parent.fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise RulerBuildError(
                    f"input directory binding changed: {fingerprint.name}"
                ) from error
            if (
                (bound.st_dev, bound.st_ino) != directory.identity
                or not stat.S_ISDIR(bound.st_mode)
                or stat.S_ISLNK(bound.st_mode)
            ):
                raise RulerBuildError(
                    f"input directory binding identity changed: {fingerprint.name}"
                )
        info = os.fstat(fingerprint.fd)
        try:
            bound = os.stat(
                fingerprint.path.name,
                dir_fd=fingerprint.parent.fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise RulerBuildError(
                f"input file binding changed: {fingerprint.name}"
            ) from error
        if (
            _descriptor_identity(fingerprint.fd) != fingerprint.identity
            or (bound.st_dev, bound.st_ino) != fingerprint.identity
            or not stat.S_ISREG(info.st_mode)
            or not stat.S_ISREG(bound.st_mode)
        ):
            raise RulerBuildError(f"input file identity changed: {fingerprint.name}")
        os.lseek(fingerprint.fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(fingerprint.fd, 1024 * 1024):
            chunks.append(chunk)
        raw = b"".join(chunks)
        if raw != fingerprint.content or hashlib.sha256(raw).hexdigest() != (
            fingerprint.sha256
        ):
            raise RulerBuildError(
                f"input fingerprint changed during build: {fingerprint.name}"
            )


def _reattest_before_success(
    *,
    entry: ExecutionAttestation,
    attestation_fn: AttestationFn,
    fingerprints: Sequence[_FileFingerprint],
    io: PublicationIO,
    notify_hooks: bool = True,
) -> None:
    final = attestation_fn()
    if final != entry:
        raise RulerBuildError("execution attestation changed during build")
    _verify_input_fingerprints(
        fingerprints,
        io,
        notify_hooks=notify_hooks,
    )


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


def _require_pass_b_content(
    ruler: calibration_ruler.RulerManifest,
) -> None:
    missing = [
        cast(str, item.review_id)
        for item in ruler.items
        if not isinstance(item.source_excerpt, str) or not item.source_excerpt.strip()
    ]
    if missing:
        raise RulerBuildError(
            "every selected ruler item requires a non-empty source excerpt; "
            "missing review ID(s): " + ", ".join(missing)
        )


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
    io.attest_file(temporary / MANIFEST_NAME, manifest_json.encode("utf-8"))
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
    expected = [_block_filename(number) for number in range(1, len(blocks) + 1)]
    written = sorted(os.listdir(io.directory_fd(temporary / PASS_A_DIRNAME)))
    if written != expected:
        raise RulerBuildError(
            "published Pass A entries do not exactly match rendered blocks"
        )
    for number, block in enumerate(blocks, start=1):
        path = temporary / PASS_A_DIRNAME / _block_filename(number)
        io.attest_file(path, block.encode("utf-8"))


def _verify_assets(
    io: PublicationIO,
    temporary: Path,
    assets: Mapping[str, bytes],
) -> None:
    written = sorted(os.listdir(io.directory_fd(temporary / FIGURES_DIRNAME)))
    expected = sorted(Path(relative).name for relative in assets)
    if written != expected:
        raise RulerBuildError("published figure assets do not match the ruler")
    for relative, data in assets.items():
        io.attest_file(temporary / relative, data)


def _attest_workspace_directory_bindings(
    io: PublicationIO,
    workspace: Path,
) -> None:
    workspace_fd = io.directory_fd(workspace)
    for child_name in (PASS_A_DIRNAME, FIGURES_DIRNAME):
        child_path = workspace / child_name
        child_fd = io.directory_fd(child_path)
        opened = os.fstat(child_fd)
        try:
            bound = os.stat(
                child_name,
                dir_fd=workspace_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise RulerBuildError(
                f"published workspace directory binding changed: {child_name}"
            ) from error
        if (
            (opened.st_dev, opened.st_ino) != (bound.st_dev, bound.st_ino)
            or not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(bound.st_mode)
            or stat.S_ISLNK(bound.st_mode)
        ):
            raise RulerBuildError(
                f"published workspace directory identity changed: {child_name}"
            )


def _verify_workspace(
    io: PublicationIO,
    temporary: Path,
    *,
    manifest_json: str,
    index_md: str,
    blocks: Sequence[str],
    assets: Mapping[str, bytes],
    ruler: calibration_ruler.RulerManifest,
    include_success: bool = False,
) -> None:
    _attest_workspace_directory_bindings(io, temporary)
    expected_root = {
        MANIFEST_NAME,
        INDEX_NAME,
        PASS_A_DIRNAME,
        FIGURES_DIRNAME,
    }
    if include_success:
        expected_root.add(SUCCESS_MARKER)
    actual_root = set(os.listdir(io.directory_fd(temporary)))
    if actual_root != expected_root:
        raise RulerBuildError(
            "published workspace entries do not exactly match the manifest"
        )
    _verify_manifest_roundtrip(io, temporary, manifest_json=manifest_json, ruler=ruler)
    io.attest_file(temporary / INDEX_NAME, index_md.encode("utf-8"))
    _verify_blocks(io, temporary, blocks)
    _verify_assets(io, temporary, assets)
    if include_success:
        io.attest_file(temporary / SUCCESS_MARKER, b"ok\n")
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
        io.before_final_payload(filename)
        io.link_payload(temporary / filename, final / filename)
    for number in range(1, len(blocks) + 1):
        filename = _block_filename(number)
        io.before_final_payload(f"{PASS_A_DIRNAME}/{filename}")
        io.link_payload(
            temporary / PASS_A_DIRNAME / filename,
            final / PASS_A_DIRNAME / filename,
        )
    for relative in assets:
        io.before_final_payload(relative)
        io.link_payload(temporary / relative, final / relative)
    io.fsync_dir(final / PASS_A_DIRNAME)
    io.fsync_dir(final / FIGURES_DIRNAME)
    io.fsync_dir(final)


def _open_private_probe_directory(
    parent_fd: int,
    name: str,
    *,
    create: bool,
) -> tuple[int, LockIdentity]:
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    preopen = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(preopen.st_mode)
        or stat.S_ISLNK(preopen.st_mode)
        or stat.S_IMODE(preopen.st_mode) != 0o700
        or preopen.st_dev != os.fstat(parent_fd).st_dev
    ):
        raise RulerBuildError("builder capability probe directory is not private")
    fd = os.open(name, _directory_flags(), dir_fd=parent_fd)
    opened = os.fstat(fd)
    identity = (opened.st_dev, opened.st_ino)
    if (
        identity != (preopen.st_dev, preopen.st_ino)
        or not stat.S_ISDIR(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o700
    ):
        os.close(fd)
        raise RulerBuildError(
            "builder capability probe directory identity changed while opening"
        )
    return fd, identity


def _runtime_probe_rename_noreplace(
    io: PublicationIO,
    root: _RetainedDirectory,
) -> None:
    probe_root_fd: int | None = None
    probe_fd: int | None = None
    relative = ""
    try:
        probe_root_fd, _root_identity = _open_private_probe_directory(
            root.fd,
            BUILD_CAPABILITY_PROBE_ROOT,
            create=True,
        )
        for _ in range(128):
            probe_name = f"{os.getpid()}.{secrets.token_hex(16)}"
            try:
                os.mkdir(probe_name, mode=0o700, dir_fd=probe_root_fd)
            except FileExistsError:
                continue
            probe_fd, _probe_identity = _open_private_probe_directory(
                probe_root_fd,
                probe_name,
                create=False,
            )
            relative = f"{BUILD_CAPABILITY_PROBE_ROOT}/{probe_name}"
            break
        if probe_fd is None:
            raise RulerBuildError("could not reserve builder capability probe")
        moved_content = b"builder-rename-no-replace-move\n"
        collision_content = b"builder-rename-no-replace-source\n"
        occupied_content = b"builder-rename-no-replace-occupied\n"
        moved_identity = _write_exclusive_at(
            probe_fd,
            "move-source",
            moved_content,
        )
        collision_identity = _write_exclusive_at(
            probe_fd,
            "collision-source",
            collision_content,
        )
        occupied_identity = _write_exclusive_at(
            probe_fd,
            "occupied",
            occupied_content,
        )
        _builder_rename_noreplace(
            io,
            probe_fd,
            "move-source",
            probe_fd,
            "moved",
        )
        moved = os.stat("moved", dir_fd=probe_fd, follow_symlinks=False)
        if (moved.st_dev, moved.st_ino) != moved_identity or _read_file_at(
            probe_fd, "moved", label="builder capability probe"
        ) != moved_content:
            raise RulerBuildError(
                "builder rename-no-replace probe changed moved identity/bytes"
            )
        try:
            os.stat("move-source", dir_fd=probe_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RulerBuildError(
                "builder rename-no-replace probe retained moved source"
            )
        collision_error = False
        try:
            _builder_rename_noreplace(
                io,
                probe_fd,
                "collision-source",
                probe_fd,
                "occupied",
            )
        except FileExistsError:
            collision_error = True
        source = os.stat(
            "collision-source",
            dir_fd=probe_fd,
            follow_symlinks=False,
        )
        occupied = os.stat(
            "occupied",
            dir_fd=probe_fd,
            follow_symlinks=False,
        )
        if (
            not collision_error
            or (source.st_dev, source.st_ino) != collision_identity
            or (occupied.st_dev, occupied.st_ino) != occupied_identity
            or _read_file_at(
                probe_fd,
                "occupied",
                label="builder occupied capability probe",
            )
            != occupied_content
        ):
            raise RulerBuildError(
                "builder rename-no-replace collision semantics allowed overwrite"
            )
        os.fsync(probe_fd)
        os.fsync(probe_root_fd)
        os.fsync(root.fd)
        io.after_capability_probe(relative)
    except (atomic_rename.AtomicRenameError, OSError) as error:
        raise RulerBuildError(
            "builder runtime rename-no-replace capability probe failed"
        ) from error
    finally:
        if probe_fd is not None:
            try:
                os.close(probe_fd)
            except OSError:
                pass
        if probe_root_fd is not None:
            try:
                os.close(probe_root_fd)
            except OSError:
                pass


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
    reattest: Callable[[bool], None],
) -> Path:
    lock_path = root / f".{run_id}.lock"
    run_dir = root / run_id
    lock_fd: int | None = None
    lock_identity: LockIdentity | None = None
    lock_owned = False
    temporary: Path | None = None
    temporary_identity: LockIdentity | None = None
    final: Path | None = None
    final_identity: LockIdentity | None = None
    root_directory: _RetainedDirectory | None = None
    final_directory: _RetainedDirectory | None = None
    try:
        try:
            io.preflight_rename_noreplace()
        except atomic_rename.AtomicRenameError as error:
            raise RulerBuildError(
                "builder rename-no-replace capability is unavailable"
            ) from error
        root_directory, _root_chain = _open_output_root(root, io)
        _runtime_probe_rename_noreplace(io, root_directory)
        try:
            os.stat(run_id, dir_fd=root_directory.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RulerBuildError(
                f"calibration run directory already exists: {run_dir}"
            )
        try:
            lock_fd = os.open(
                lock_path.name,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=root_directory.fd,
            )
        except FileExistsError as error:
            raise RulerBuildError(
                f"calibration publication lock already exists: {lock_path}"
            ) from error
        lock_identity = _descriptor_identity(lock_fd)
        lock_owned = True
        io.write_lock(lock_fd, f"pid={os.getpid()}\n".encode())
        io.sync_lock(lock_fd)
        io.fsync_dir(root)
        temporary = io.create_temp(root, run_id)
        temporary_info = os.stat(
            temporary.name,
            dir_fd=root_directory.fd,
            follow_symlinks=False,
        )
        temporary_identity = (temporary_info.st_dev, temporary_info.st_ino)
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
        final_info = os.stat(
            run_id,
            dir_fd=root_directory.fd,
            follow_symlinks=False,
        )
        final_identity = (final_info.st_dev, final_info.st_ino)
        final_directory = _retained_child(io, run_dir)
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
        reattest(True)
        io.cleanup_tree(temporary)
        _preserve_owned_binding(
            io,
            root_directory,
            temporary.name,
            cast(LockIdentity, temporary_identity),
            relative=temporary.name,
        )
        temporary = None
        io.fsync_dir(root)
        os.close(lock_fd)
        lock_fd = None
        if lock_identity is None:
            raise PublicationCleanupError("owned lock has no identity")
        io.remove_lock(lock_path, lock_identity)
        _preserve_owned_binding(
            io,
            root_directory,
            lock_path.name,
            lock_identity,
            relative=lock_path.name,
        )
        lock_owned = False
        io.fsync_dir(root)
        io.before_success_marker()
        reattest(False)
        _reattest_directory_chain(root_directory)
        if final_directory is None:
            raise PublicationCleanupError("final run descriptor is unavailable")
        _reattest_directory(final_directory)
        _verify_workspace(
            io,
            run_dir,
            manifest_json=manifest_json,
            index_md=index_md,
            blocks=blocks,
            assets=assets,
            ruler=ruler,
        )
        io.write_marker(run_dir / SUCCESS_MARKER, "ok\n")
        io.fsync_dir(run_dir)
        io.fsync_dir(root)
        reattest(False)
        _reattest_directory_chain(root_directory)
        _reattest_directory(final_directory)
        _verify_workspace(
            io,
            run_dir,
            manifest_json=manifest_json,
            index_md=index_md,
            blocks=blocks,
            assets=assets,
            ruler=ruler,
            include_success=True,
        )
        final = None
        return run_dir
    except BaseException as error:
        if root_directory is not None:
            _cleanup(
                io,
                root=root_directory,
                temporary=temporary,
                temporary_identity=temporary_identity,
                final=final,
                final_identity=final_identity,
                lock_path=lock_path,
                lock_fd=lock_fd,
                lock_identity=lock_identity,
                lock_owned=lock_owned,
                primary=error,
            )
        elif lock_fd is not None:
            os.close(lock_fd)
        raise
    finally:
        io.close_bindings()


def _cleanup(
    io: PublicationIO,
    *,
    root: _RetainedDirectory,
    temporary: Path | None,
    temporary_identity: LockIdentity | None,
    final: Path | None,
    final_identity: LockIdentity | None,
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
    for path, identity in (
        (temporary, temporary_identity),
        (final, final_identity),
    ):
        if path is None or identity is None:
            continue
        try:
            io.cleanup_tree(path)
            _preserve_owned_binding(
                io,
                root,
                path.name,
                identity,
                relative=path.name,
            )
        except BaseException as err:  # noqa: BLE001
            errors.append(err)
    if lock_owned:
        try:
            if lock_identity is None:
                raise PublicationCleanupError("owned lock has no identity")
            io.remove_lock(lock_path, lock_identity)
            _preserve_owned_binding(
                io,
                root,
                lock_path.name,
                lock_identity,
                relative=lock_path.name,
            )
        except BaseException as err:  # noqa: BLE001
            errors.append(err)
    try:
        os.fsync(root.fd)
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
    retained: list[_FileFingerprint] = []
    try:
        trusted = _load_problem_set(
            trusted_path,
            name="trusted",
            allow_test_paths=allow_test_paths,
            io=publisher,
        )
        retained.append(trusted.fingerprint)
        failures = _load_problem_set(
            failures_path,
            name="failure",
            allow_test_paths=allow_test_paths,
            io=publisher,
        )
        retained.append(failures.fingerprint)
        shadow = _load_shadow_run(
            shadow_path,
            allow_test_paths=allow_test_paths,
            io=publisher,
        )
        retained.extend(shadow.fingerprints)

        ruler = calibration_ruler.build_ruler(
            trusted.items,
            failures.items,
            shadow.items,
            seed=seed,
        )
        _require_pass_b_content(ruler)
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

        fingerprints = tuple(retained)
        return _publish(
            publisher,
            root=root,
            run_id=run_id,
            ruler=ruler,
            manifest_json=manifest_json,
            index_md=index_md,
            blocks=blocks,
            assets=assets,
            reattest=lambda notify_hooks: _reattest_before_success(
                entry=entry_attestation,
                attestation_fn=attestation_fn,
                fingerprints=fingerprints,
                io=publisher,
                notify_hooks=notify_hooks,
            ),
        )
    finally:
        _close_fingerprints(retained)


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
    return shadow_foundry.RunEnvironment(
        code_sha=sha,
        tree_status="clean",
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
        "source_excerpt": (
            f"OpenStax grounding excerpt {index} for {category} principles."
        ),
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


def _cli_error_category(error: BaseException) -> str:
    message = str(error).casefold()
    if any(
        token in message
        for token in (
            "path",
            "symlink",
            "directory",
            "lock",
            "identity",
            "rename",
            "capability",
            "publication",
        )
    ):
        return "filesystem_state"
    if any(
        token in message for token in ("input", "shadow", "manifest", "ruler", "source")
    ):
        return "input_invalid"
    return "build_failed"


class _SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "CALIBRATION_BUILD_ERROR:arguments\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _SanitizedArgumentParser(
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
    except Exception as error:
        parser.exit(2, f"CALIBRATION_BUILD_ERROR:{_cli_error_category(error)}\n")
    del run_dir
    print("CALIBRATION_BUILD_COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
