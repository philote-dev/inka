# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Import private human labels from the blind two-pass calibration workspace.

Every production filesystem operation is anchored to retained directory file
descriptors. Import publication, staging cleanup, input re-attestation, and
lock release form one transaction: no output is committed unless the final
lock and every input/path identity remain bound to the workspace that was
opened at entry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402
import atomic_rename  # noqa: E402

_ai_path.add_ai_core()

import build_calibration_ruler as ruler_builder  # noqa: E402
from pgrep.ai import calibration_ruler, calibration_sheet  # noqa: E402

CALIBRATION_ROOT = ruler_builder.CALIBRATION_ROOT
MANIFEST_VERSION = ruler_builder.MANIFEST_VERSION

PASS_A_REPORT_VERSION = "pgrep-calibration-pass-a-labels/v1"
PASS_B_REPORT_VERSION = "pgrep-calibration-pass-b-labels/v1"
LOCK_NAME = ".calibration-import.lock"
SUCCESS_MARKER = "_SUCCESS"
FAILED_MARKER = "_FAILED"
PASS_B_SUCCESS = "_SUCCESS"
REPORTS_DIRNAME = "reports"
PASS_A_DIRNAME = "pass-a"
PASS_B_DIRNAME = "pass-b"
FIGURES_DIRNAME = "figures"
QUARANTINE_ROOT_NAME = ".calibration-rollback-quarantine"
CAPABILITY_PROBE_ROOT_NAME = ".capability-probes"

_BASE_ENTRIES = frozenset(
    {
        SUCCESS_MARKER,
        "manifest.json",
        "index.md",
        PASS_A_DIRNAME,
        FIGURES_DIRNAME,
        LOCK_NAME,
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "manifest_version",
        "kind",
        "private",
        "run_id",
        "seed",
        "build",
        "inputs",
        "counts",
        "ruler",
    }
)
_BUILD_FIELDS = frozenset(
    {"code_sha", "head_sha", "tree_status", "source_hashes", "tool"}
)
_SOURCE_ATTESTATION_FIELDS = frozenset(
    {"loaded_sha256", "current_sha256", "head_blob_sha256"}
)
_INPUT_FIELDS = frozenset({"trusted", "failure", "shadow"})
_PROBLEM_INPUT_FIELDS = frozenset({"sha256", "count"})
_SHADOW_INPUT_FIELDS = frozenset({"manifest_sha256", "run_id", "candidate_count"})
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_COMMIT_SHA = re.compile(r"[0-9a-f]{40,64}\Z", re.ASCII)
Identity = tuple[int, int]


class CalibrationImportError(ValueError):
    """The private calibration workspace cannot be imported safely."""


class ImportIO:
    """Injectable transaction hooks used by deterministic fault tests."""

    def after_read(self, relative: str) -> None:
        pass

    def before_stage_write(self, relative: str) -> None:
        pass

    def fsync_file(self, fd: int, relative: str) -> None:
        os.fsync(fd)

    def fsync_directory(self, fd: int, relative: str) -> None:
        os.fsync(fd)

    def device_id(self, fd: int, role: str) -> int:
        del role
        return os.fstat(fd).st_dev

    def before_publish(self) -> None:
        pass

    def after_publish(self, relative: str) -> None:
        pass

    def before_published_outputs_attestation(self) -> None:
        pass

    def before_final_commit_attestation(self) -> None:
        pass

    def before_commit_artifact_attestation(self, relative: str) -> None:
        pass

    def before_final_revalidate(self) -> None:
        pass

    def before_lock_release(self) -> None:
        pass

    def before_rollback(self, relative: str) -> None:
        pass

    def before_quarantine(self, relative: str) -> None:
        pass

    def before_quarantine_rename(
        self,
        relative: str,
        quarantine_directory: str,
        target_name: str,
    ) -> None:
        pass

    def after_rollback_preserve(
        self,
        relative: str,
        quarantine_directory: str,
        item_name: str,
    ) -> None:
        pass

    def after_publish_move_before_attestation(self, relative: str) -> None:
        pass

    def before_root_open(self, role: str, root_name: str) -> None:
        pass

    def close_lock_fd(self, fd: int) -> None:
        os.close(fd)

    def preflight_rename_noreplace(self) -> None:
        _preflight_rename_noreplace()

    def after_capability_probe(self, probe_directory: str) -> None:
        pass

    def rename_noreplace(
        self,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        _rename_noreplace(
            source_dir_fd,
            source_name,
            destination_dir_fd,
            destination_name,
        )


@dataclass(eq=False)
class _Directory:
    fd: int
    identity: Identity
    parent: _Directory | None
    name: str | None
    label: str
    active: bool = True


@dataclass(frozen=True)
class _SnapshotFile:
    parent: _Directory
    name: str
    relative: str
    identity: Identity
    content: bytes


@dataclass
class _OwnedEntry:
    parent: _Directory
    name: str
    relative: str
    identity: Identity
    directory: bool
    child: _Directory | None = None
    expected_bytes: bytes | None = None
    published: bool = False
    commit_artifact: bool = False
    removed: bool = False


@dataclass
class _Layout:
    pass_a: _Directory
    figures: _Directory
    reports: _Directory | None = None
    pass_b: _Directory | None = None


@dataclass(frozen=True)
class _LoadedWorkspace:
    manifest: calibration_ruler.RulerManifest
    manifest_sha256: str
    pass_a_labels: dict[str, calibration_sheet.PassALabel]
    pass_a_report: dict[str, object]
    snapshots: tuple[_SnapshotFile, ...]


@dataclass
class _Stage:
    root: _Directory
    pass_b: _Directory | None
    block_names: list[str]
    report_bytes: bytes
    block_bytes: dict[str, bytes]
    records: list[_OwnedEntry]


@dataclass(frozen=True)
class _PreservedBinding:
    target_name: str
    info: os.stat_result
    collisions: tuple[str, ...]


def _identity(info: os.stat_result) -> Identity:
    return (info.st_dev, info.st_ino)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_component(name: str, *, label: str) -> str:
    if (
        type(name) is not str
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or Path(name).name != name
    ):
        raise CalibrationImportError(f"{label} is not a safe path component")
    return name


def _preflight_rename_noreplace(
    *,
    _platform: str | None = None,
    _libc: object | None = None,
    _machine: str | None = None,
) -> None:
    """Verify a no-replace primitive exists without touching the filesystem."""
    try:
        atomic_rename.preflight_rename_noreplace(
            _platform=_platform,
            _libc=_libc,
            _machine=_machine,
        )
    except atomic_rename.AtomicRenameError as error:
        raise CalibrationImportError(str(error)) from error


def _rename_noreplace(
    source_dir_fd: int,
    source_name: str,
    destination_dir_fd: int,
    destination_name: str,
    *,
    _platform: str | None = None,
    _libc: object | None = None,
    _machine: str | None = None,
) -> None:
    """Atomically rename one fd-relative binding without replacing a target."""
    try:
        atomic_rename.rename_noreplace(
            source_dir_fd,
            source_name,
            destination_dir_fd,
            destination_name,
            _platform=_platform,
            _libc=_libc,
            _machine=_machine,
        )
    except atomic_rename.AtomicRenameError as error:
        raise CalibrationImportError(str(error)) from error


def _require_secure_dirfd_primitives() -> None:
    dirfd_functions = (
        os.open,
        os.stat,
        os.mkdir,
        os.link,
        os.rename,
    )
    if (
        not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or any(function not in os.supports_dir_fd for function in dirfd_functions)
        or os.listdir not in os.supports_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        raise CalibrationImportError(
            "secure directory-fd filesystem primitives are unavailable; "
            "calibration import fails closed on this platform"
        )


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _file_read_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _file_create_flags() -> int:
    return (
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _stat_at(parent: _Directory, name: str, *, label: str) -> os.stat_result:
    _safe_component(name, label=label)
    try:
        return os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
    except OSError as error:
        raise CalibrationImportError(f"could not stat {label}: {error}") from error


def _validated_run_path(
    run_dir: Path | str,
    *,
    allow_test_paths: bool,
) -> tuple[Path, bool, Path]:
    _require_secure_dirfd_primitives()
    raw = Path(run_dir)
    if ".." in raw.parts:
        raise CalibrationImportError("calibration run path contains a path escape")
    absolute = Path(os.path.abspath(raw))
    try:
        ruler_builder._validate_run_id(absolute.name)  # noqa: SLF001
    except ValueError as error:
        raise CalibrationImportError(str(error)) from error
    production_root = Path(os.path.abspath(CALIBRATION_ROOT))
    production = absolute.parent == production_root
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not production and not (
        allow_test_paths and _is_relative_to(absolute, temp_root)
    ):
        raise CalibrationImportError(
            "calibration run must be under the exact repository calibration root"
        )
    if absolute.anchor != "/":
        raise CalibrationImportError(
            "secure calibration import requires an absolute POSIX path"
        )
    return absolute, production, production_root


def _open_absolute_directory_chain(path: Path) -> list[int]:
    fds: list[int] = []
    try:
        root_fd = os.open("/", _directory_flags())
        fds.append(root_fd)
        parent_fd = root_fd
        for part in path.parts[1:]:
            component = _safe_component(part, label="calibration root component")
            fd = os.open(component, _directory_flags(), dir_fd=parent_fd)
            fds.append(fd)
            parent_fd = fd
        return fds
    except BaseException:
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _create_probe_file(
    directory_fd: int,
    name: str,
    content: bytes,
) -> Identity:
    fd = os.open(name, _file_create_flags(), 0o600, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        _write_all(fd, content)
        os.fsync(fd)
        return _identity(info)
    finally:
        os.close(fd)


def _runtime_probe_rename_noreplace(  # noqa: PLR0912, PLR0915
    run_dir: Path | str,
    *,
    allow_test_paths: bool,
    io: ImportIO,
) -> None:
    absolute, production, production_root = _validated_run_path(
        run_dir,
        allow_test_paths=allow_test_paths,
    )
    calibration_root = absolute.parent
    chain = _open_absolute_directory_chain(calibration_root)
    calibration_root_fd = chain[-1]
    try:
        run_fd = os.open(
            absolute.name,
            _directory_flags(),
            dir_fd=calibration_root_fd,
        )
    except OSError as error:
        for fd in reversed(chain):
            os.close(fd)
        raise CalibrationImportError(
            "run path is missing, not a directory, or a symlink"
        ) from error
    calibration_device = io.device_id(calibration_root_fd, "calibration_root")
    run_device = io.device_id(run_fd, "run")
    if run_device != calibration_device:
        os.close(run_fd)
        for fd in reversed(chain):
            os.close(fd)
        raise CalibrationImportError(
            "run and calibration root device mismatch; refusing EXDEV risk"
        )
    for root_name, role in (
        (QUARANTINE_ROOT_NAME, "quarantine_root"),
        (CAPABILITY_PROBE_ROOT_NAME, "probe_root"),
    ):
        try:
            preopen = os.stat(
                root_name,
                dir_fd=calibration_root_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        if (
            not stat.S_ISDIR(preopen.st_mode)
            or stat.S_ISLNK(preopen.st_mode)
            or stat.S_IMODE(preopen.st_mode) != 0o700
            or preopen.st_dev != calibration_device
        ):
            raise CalibrationImportError(
                f"{role} must be an exact private mode-0700 directory"
            )
        io.before_root_open(role, root_name)
        try:
            existing_fd = os.open(
                root_name,
                _directory_flags(),
                dir_fd=calibration_root_fd,
            )
        except OSError as error:
            raise CalibrationImportError(f"{role} changed while opening") from error
        try:
            opened = os.fstat(existing_fd)
            if (
                _identity(opened) != _identity(preopen)
                or not stat.S_ISDIR(opened.st_mode)
                or opened.st_dev != preopen.st_dev
                or opened.st_dev != calibration_device
                or stat.S_IMODE(opened.st_mode) != 0o700
            ):
                raise CalibrationImportError(
                    f"{role} identity/private mode changed while opening"
                )
            if io.device_id(existing_fd, role) != calibration_device:
                raise CalibrationImportError(
                    f"{role} device mismatch; refusing EXDEV risk"
                )
        finally:
            os.close(existing_fd)
    probe_root_fd: int | None = None
    probe_name = f"{os.getpid()}.{secrets.token_hex(16)}"
    probe_relative = f"{CAPABILITY_PROBE_ROOT_NAME}/{probe_name}"
    probe_fd: int | None = None
    owned_identities: set[Identity] = set()
    primary: BaseException | None = None
    hook_called = False
    try:
        if production:
            try:
                ruler_builder.validate_output_root(production_root)
            except ValueError as error:
                raise CalibrationImportError(str(error)) from error
        try:
            os.mkdir(
                CAPABILITY_PROBE_ROOT_NAME,
                mode=0o700,
                dir_fd=calibration_root_fd,
            )
        except FileExistsError:
            pass
        probe_root_info = os.stat(
            CAPABILITY_PROBE_ROOT_NAME,
            dir_fd=calibration_root_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(probe_root_info.st_mode)
            or stat.S_ISLNK(probe_root_info.st_mode)
            or stat.S_IMODE(probe_root_info.st_mode) != 0o700
        ):
            raise CalibrationImportError(
                "capability probe root must be a private mode-0700 directory"
            )
        io.before_root_open("probe_root", CAPABILITY_PROBE_ROOT_NAME)
        probe_root_fd = os.open(
            CAPABILITY_PROBE_ROOT_NAME,
            _directory_flags(),
            dir_fd=calibration_root_fd,
        )
        opened_probe_root = os.fstat(probe_root_fd)
        if (
            _identity(opened_probe_root) != _identity(probe_root_info)
            or not stat.S_ISDIR(opened_probe_root.st_mode)
            or opened_probe_root.st_dev != probe_root_info.st_dev
            or opened_probe_root.st_dev != calibration_device
            or stat.S_IMODE(opened_probe_root.st_mode) != 0o700
        ):
            raise CalibrationImportError(
                "capability probe root identity/private mode changed while opening"
            )
        if io.device_id(probe_root_fd, "probe_root") != calibration_device:
            raise CalibrationImportError(
                "probe root device mismatch; refusing EXDEV risk"
            )
        os.mkdir(probe_name, mode=0o700, dir_fd=probe_root_fd)
        probe_fd = os.open(probe_name, _directory_flags(), dir_fd=probe_root_fd)
        probe_info = os.fstat(probe_fd)
        if (
            not stat.S_ISDIR(probe_info.st_mode)
            or stat.S_IMODE(probe_info.st_mode) != 0o700
        ):
            raise CalibrationImportError("runtime probe directory is not private")
        moved_content = b"rename-no-replace-success\n"
        collision_content = b"rename-no-replace-collision-source\n"
        occupied_content = b"rename-no-replace-occupied\n"
        owned_identities.add(_create_probe_file(probe_fd, "move-source", moved_content))
        owned_identities.add(
            _create_probe_file(probe_fd, "collision-source", collision_content)
        )
        occupied_identity = _create_probe_file(
            probe_fd,
            "occupied",
            occupied_content,
        )
        owned_identities.add(occupied_identity)
        try:
            io.rename_noreplace(
                probe_fd,
                "move-source",
                probe_fd,
                "moved",
            )
        except (CalibrationImportError, OSError) as error:
            raise CalibrationImportError(
                f"runtime rename-no-replace probe failed: {error}"
            ) from error
        moved = os.stat("moved", dir_fd=probe_fd, follow_symlinks=False)
        if _identity(moved) not in owned_identities:
            raise CalibrationImportError(
                "runtime rename-no-replace probe changed source identity"
            )
        moved_snapshot = os.open("moved", _file_read_flags(), dir_fd=probe_fd)
        try:
            if os.read(moved_snapshot, len(moved_content) + 1) != moved_content:
                raise CalibrationImportError(
                    "runtime rename-no-replace probe changed source bytes"
                )
        finally:
            os.close(moved_snapshot)
        try:
            os.stat("move-source", dir_fd=probe_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CalibrationImportError(
                "runtime rename-no-replace probe left source binding"
            )

        collision_error = False
        try:
            io.rename_noreplace(
                probe_fd,
                "collision-source",
                probe_fd,
                "occupied",
            )
        except FileExistsError:
            collision_error = True
        except (CalibrationImportError, OSError) as error:
            raise CalibrationImportError(
                f"runtime rename-no-replace probe failed: {error}"
            ) from error
        if not collision_error:
            raise CalibrationImportError(
                "runtime rename-no-replace collision semantics allowed overwrite"
            )
        source_info = os.stat(
            "collision-source",
            dir_fd=probe_fd,
            follow_symlinks=False,
        )
        occupied_info = os.stat(
            "occupied",
            dir_fd=probe_fd,
            follow_symlinks=False,
        )
        if (
            _identity(source_info) not in owned_identities
            or _identity(occupied_info) != occupied_identity
        ):
            raise CalibrationImportError(
                "runtime rename-no-replace collision semantics changed identities"
            )
        io.after_capability_probe(probe_relative)
        hook_called = True
    except BaseException as error:  # noqa: BLE001
        primary = error
    finally:
        if probe_fd is not None and not hook_called:
            try:
                io.after_capability_probe(probe_relative)
            except BaseException as error:  # noqa: BLE001
                if primary is None:
                    primary = error
        retained_count = len(os.listdir(probe_fd)) if probe_fd is not None else 0
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
        try:
            os.close(run_fd)
        except OSError:
            pass
        for fd in reversed(chain):
            try:
                os.close(fd)
            except OSError:
                pass
    if primary is not None:
        raise CalibrationImportError(
            f"{primary}; capability probe retained at "
            f"{calibration_root / probe_relative} ({retained_count} entries)"
        ) from primary


class _AnchoredWorkspace:
    def __init__(
        self,
        *,
        path: Path,
        directories: list[_Directory],
        production: bool,
    ) -> None:
        self.path = path
        self.directories = directories
        self.run = directories[-1]
        self.run_name = path.name
        self.production = production

    @classmethod
    def open(
        cls,
        run_dir: Path | str,
        *,
        allow_test_paths: bool,
    ) -> _AnchoredWorkspace:
        absolute, production, production_root = _validated_run_path(
            run_dir,
            allow_test_paths=allow_test_paths,
        )
        directories: list[_Directory] = []
        try:
            root_fd = os.open("/", _directory_flags())
            root_info = os.fstat(root_fd)
            root = _Directory(
                fd=root_fd,
                identity=_identity(root_info),
                parent=None,
                name=None,
                label="/",
            )
            directories.append(root)
            parent = root
            for part in absolute.parts[1:]:
                component = _safe_component(part, label="calibration path component")
                try:
                    fd = os.open(component, _directory_flags(), dir_fd=parent.fd)
                except OSError as error:
                    raise CalibrationImportError(
                        "calibration path component is missing, not a directory, "
                        f"or a symlink: {component}"
                    ) from error
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode):
                    os.close(fd)
                    raise CalibrationImportError(
                        f"calibration path component is not a directory: {component}"
                    )
                child = _Directory(
                    fd=fd,
                    identity=_identity(info),
                    parent=parent,
                    name=component,
                    label=str(absolute),
                )
                directories.append(child)
                parent = child
            workspace = cls(
                path=absolute,
                directories=directories,
                production=production,
            )
            workspace.reattest()
            if production:
                try:
                    ruler_builder.validate_output_root(production_root)
                except ValueError as error:
                    raise CalibrationImportError(str(error)) from error
            return workspace
        except BaseException:
            for directory in reversed(directories):
                try:
                    os.close(directory.fd)
                except OSError:
                    pass
            raise

    def close(self) -> None:
        for directory in reversed(self.directories):
            try:
                os.close(directory.fd)
            except OSError:
                pass
        self.directories.clear()

    def reattest(self) -> None:
        for directory in self.directories:
            if not directory.active:
                continue
            try:
                info = os.fstat(directory.fd)
            except OSError as error:
                raise CalibrationImportError(
                    f"directory identity unavailable for {directory.label}: {error}"
                ) from error
            if _identity(info) != directory.identity or not stat.S_ISDIR(info.st_mode):
                raise CalibrationImportError(
                    f"directory identity changed for {directory.label}"
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
                raise CalibrationImportError(
                    f"directory binding changed for {directory.label}: {error}"
                ) from error
            if (
                _identity(bound) != directory.identity
                or not stat.S_ISDIR(bound.st_mode)
                or stat.S_ISLNK(bound.st_mode)
            ):
                raise CalibrationImportError(
                    f"directory binding identity changed for {directory.label}"
                )

    def open_directory(
        self,
        parent: _Directory,
        name: str,
        *,
        label: str,
    ) -> _Directory:
        component = _safe_component(name, label=label)
        try:
            fd = os.open(component, _directory_flags(), dir_fd=parent.fd)
        except OSError as error:
            raise CalibrationImportError(f"could not open {label}: {error}") from error
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            os.close(fd)
            raise CalibrationImportError(f"{label} must be a directory")
        directory = _Directory(
            fd=fd,
            identity=_identity(info),
            parent=parent,
            name=component,
            label=label,
        )
        self.directories.append(directory)
        return directory

    def list_names(self, directory: _Directory, *, label: str) -> set[str]:
        try:
            names = os.listdir(directory.fd)
        except OSError as error:
            raise CalibrationImportError(
                f"could not inspect {label}: {error}"
            ) from error
        if any(type(name) is not str for name in names):
            raise CalibrationImportError(f"{label} contains a non-text filename")
        return set(cast(list[str], names))

    def read_file(
        self,
        parent: _Directory,
        name: str,
        *,
        relative: str,
        label: str,
        io: ImportIO,
        notify: bool = True,
    ) -> _SnapshotFile:
        component = _safe_component(name, label=label)
        try:
            fd = os.open(component, _file_read_flags(), dir_fd=parent.fd)
        except OSError as error:
            raise CalibrationImportError(
                f"could not open {label}; file is missing, unsafe, or a symlink: "
                f"{error}"
            ) from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise CalibrationImportError(f"{label} must be a regular file")
            chunks: list[bytes] = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
            content = b"".join(chunks)
            snapshot = _SnapshotFile(
                parent=parent,
                name=component,
                relative=relative,
                identity=_identity(info),
                content=content,
            )
        finally:
            os.close(fd)
        if notify:
            io.after_read(relative)
        return snapshot


def _write_all(fd: int, content: bytes) -> None:
    written = 0
    while written < len(content):
        count = os.write(fd, content[written:])
        if count <= 0:
            raise OSError("short write")
        written += count


class _ImportTransaction:
    def __init__(self, fs: _AnchoredWorkspace, io: ImportIO) -> None:
        self.fs = fs
        self.io = io
        self.owned: list[_OwnedEntry] = []
        self.lock_fd: int | None = None
        self.lock_identity: Identity | None = None
        self.committed = False
        self.quarantine_root: _Directory | None = None
        self.quarantine_transaction: _Directory | None = None
        self.quarantine_relative: str | None = None
        self.preserved_count = 0

    def __enter__(self) -> _ImportTransaction:
        try:
            self.lock_fd = os.open(
                LOCK_NAME,
                _file_create_flags(),
                0o600,
                dir_fd=self.fs.run.fd,
            )
        except FileExistsError as error:
            raise CalibrationImportError(
                "calibration import lock already exists; refusing ambiguous import"
            ) from error
        try:
            info = os.fstat(self.lock_fd)
            self.lock_identity = _identity(info)
            _write_all(self.lock_fd, f"pid={os.getpid()}\n".encode())
            self.io.fsync_file(self.lock_fd, LOCK_NAME)
            self.io.fsync_directory(self.fs.run.fd, "run")
            return self
        except BaseException:
            self._cleanup_lock(required=False)
            self._close_lock()
            raise

    def __exit__(
        self,
        exc_type: object,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        if not self.committed:
            errors: list[BaseException] = []
            try:
                self._rollback()
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
            try:
                self._cleanup_lock(required=False)
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
            try:
                self._close_lock()
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
            if self.preserved_count:
                detail = f"; rollback detail: {errors[0]}" if errors else ""
                raise CalibrationImportError(
                    f"{exc}; rollback quarantine: "
                    f"{self._quarantine_display_path()} "
                    f"({self.preserved_count} entries){detail}"
                ) from exc
            if errors:
                raise CalibrationImportError(
                    f"failed transactional rollback after {exc}: {errors[0]}"
                ) from exc
        else:
            self._close_lock(suppress_errors=True)
        return False

    def _close_lock(self, *, suppress_errors: bool = False) -> None:
        fd = self.lock_fd
        if fd is None:
            return
        self.lock_fd = None
        try:
            self.io.close_lock_fd(fd)
        except OSError:
            if not suppress_errors:
                raise

    def _cleanup_lock(self, *, required: bool) -> None:
        identity = self.lock_identity
        if identity is None:
            if required:
                raise CalibrationImportError("import lock identity is unavailable")
            return
        if required:
            self.attest_lock()
            self.io.before_quarantine(LOCK_NAME)
        try:
            info = os.stat(
                LOCK_NAME,
                dir_fd=self.fs.run.fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as error:
            if required:
                raise CalibrationImportError(
                    "calibration import lock binding disappeared"
                ) from error
            return
        preserved = self._preserve_binding(
            self.fs.run,
            LOCK_NAME,
            relative=LOCK_NAME,
        )
        if preserved is None:
            if required:
                raise CalibrationImportError(
                    "calibration import lock binding disappeared"
                )
            return
        quarantine_info = preserved.info
        if (
            _identity(info) != identity
            or _identity(quarantine_info) != identity
            or not stat.S_ISREG(quarantine_info.st_mode)
            or preserved.collisions
        ):
            owned_matches = self._names_with_identity(self.fs.run, identity)
            if len(owned_matches) == 1:
                self._preserve_binding(
                    self.fs.run,
                    owned_matches[0],
                    relative=LOCK_NAME,
                )
            elif len(owned_matches) > 1:
                raise CalibrationImportError(
                    "multiple names match originally owned import lock inode"
                )
            raise CalibrationImportError(
                "calibration import lock binding identity changed; "
                f"foreign replacement was preserved in "
                f"{self._quarantine_display_path()}"
            )

    def _new_owned_directory(
        self,
        parent: _Directory,
        name: str,
        *,
        relative: str,
    ) -> _Directory:
        component = _safe_component(name, label=relative)
        os.mkdir(component, mode=0o700, dir_fd=parent.fd)
        info = os.stat(component, dir_fd=parent.fd, follow_symlinks=False)
        record = _OwnedEntry(
            parent=parent,
            name=component,
            relative=relative,
            identity=_identity(info),
            directory=True,
        )
        self.owned.append(record)
        child = self.fs.open_directory(parent, component, label=relative)
        if child.identity != record.identity:
            raise CalibrationImportError(
                f"owned directory identity changed while opening {relative}"
            )
        record.child = child
        return child

    def create_unique_stage(self) -> _Directory:
        for _ in range(128):
            name = f".calibration-import.{secrets.token_hex(12)}"
            try:
                return self._new_owned_directory(
                    self.fs.run,
                    name,
                    relative=name,
                )
            except FileExistsError:
                continue
        raise CalibrationImportError("could not reserve unique import staging")

    def create_stage_file(
        self,
        parent: _Directory,
        name: str,
        content: bytes,
        *,
        relative: str,
    ) -> None:
        self.io.before_stage_write(relative)
        component = _safe_component(name, label=relative)
        fd = os.open(
            component,
            _file_create_flags(),
            0o600,
            dir_fd=parent.fd,
        )
        try:
            info = os.fstat(fd)
            self.owned.append(
                _OwnedEntry(
                    parent=parent,
                    name=component,
                    relative=relative,
                    identity=_identity(info),
                    directory=False,
                    expected_bytes=content,
                )
            )
            _write_all(fd, content)
            self.io.fsync_file(fd, relative)
        finally:
            os.close(fd)

    def link_published_file(
        self,
        source_parent: _Directory,
        source_name: str,
        destination_parent: _Directory,
        destination_name: str,
        *,
        relative: str,
        expected_bytes: bytes,
        commit_artifact: bool = False,
    ) -> _OwnedEntry:
        source = _safe_component(source_name, label=f"{relative} source")
        destination = _safe_component(destination_name, label=relative)
        source_record = next(
            (
                record
                for record in self.owned
                if record.parent is source_parent
                and record.name == source
                and not record.removed
            ),
            None,
        )
        if source_record is None:
            raise CalibrationImportError(
                f"published source ownership is unavailable: {relative}"
            )
        source_identity = source_record.identity
        try:
            self.io.rename_noreplace(
                source_parent.fd,
                source,
                destination_parent.fd,
                destination,
            )
        except FileExistsError as error:
            raise CalibrationImportError(
                f"{relative} appeared during import; refusing overwrite"
            ) from error
        record = _OwnedEntry(
            parent=destination_parent,
            name=destination,
            relative=relative,
            identity=source_identity,
            directory=False,
            expected_bytes=expected_bytes,
            published=True,
            commit_artifact=commit_artifact,
        )
        self.owned.append(record)
        self.io.after_publish_move_before_attestation(relative)
        try:
            info = os.stat(
                destination,
                dir_fd=destination_parent.fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise CalibrationImportError(
                f"published destination binding unavailable after move: {relative}"
            ) from error
        if _identity(info) != source_identity or not stat.S_ISREG(info.st_mode):
            raise CalibrationImportError(
                f"published destination identity changed after move: {relative}"
            )
        source_record.removed = True
        self.io.after_publish(relative)
        return record

    def fsync_directory(self, directory: _Directory, relative: str) -> None:
        self.io.fsync_directory(directory.fd, relative)

    def attest_published(
        self,
        records: Sequence[_OwnedEntry],
    ) -> None:
        for record in records:
            if not record.published or record.directory:
                continue
            self._attest_published_file(record)

    def _attest_published_file(self, record: _OwnedEntry) -> None:
        expected = record.expected_bytes
        if expected is None:
            raise CalibrationImportError(
                f"published output expectation missing: {record.relative}"
            )
        try:
            fd = os.open(
                record.name,
                _file_read_flags(),
                dir_fd=record.parent.fd,
            )
        except OSError as error:
            raise CalibrationImportError(
                f"published output binding unavailable: {record.relative}: {error}"
            ) from error
        try:
            info = os.fstat(fd)
            if (
                _identity(info) != record.identity
                or not stat.S_ISREG(info.st_mode)
                or info.st_size != len(expected)
            ):
                raise CalibrationImportError(
                    f"published output identity/type/size changed: {record.relative}"
                )
            chunks: list[bytes] = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
            actual = b"".join(chunks)
        finally:
            os.close(fd)
        if (
            actual != expected
            or hashlib.sha256(actual).digest() != hashlib.sha256(expected).digest()
        ):
            raise CalibrationImportError(
                f"published output exact bytes changed: {record.relative}"
            )

    def attest_lock(self) -> None:
        identity = self.lock_identity
        if identity is None:
            raise CalibrationImportError("import lock identity is unavailable")
        try:
            info = os.stat(
                LOCK_NAME,
                dir_fd=self.fs.run.fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise CalibrationImportError(
                f"calibration import lock binding disappeared: {error}"
            ) from error
        if _identity(info) != identity or not stat.S_ISREG(info.st_mode):
            raise CalibrationImportError(
                "calibration import lock binding identity changed"
            )

    def preserve_owned(self, records: Sequence[_OwnedEntry]) -> None:
        errors = self._preserve_records(records, invoke_hook=False)
        preserved_ids = {id(record) for record in records if record.removed}
        self.owned = [
            record for record in self.owned if id(record) not in preserved_ids
        ]
        if errors:
            raise CalibrationImportError(
                f"failed to preserve import staging: {errors[0]}"
            )

    def _rollback(self) -> None:
        errors = self._preserve_records(tuple(self.owned), invoke_hook=True)
        if errors:
            raise CalibrationImportError(
                f"rollback preservation ambiguity: {errors[0]}"
            )

    def _preserve_records(
        self,
        records: Sequence[_OwnedEntry],
        *,
        invoke_hook: bool,
    ) -> list[BaseException]:
        errors: list[BaseException] = []
        for record in reversed(records):
            if record.removed:
                continue
            try:
                if invoke_hook:
                    self.io.before_rollback(record.relative)
                    self.io.before_quarantine(record.relative)
                ambiguity = self._preserve_record(record)
                if ambiguity is not None:
                    errors.append(ambiguity)
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
        return errors

    def _preserve_record(self, record: _OwnedEntry) -> BaseException | None:
        preserved = self._preserve_binding(
            record.parent,
            record.name,
            relative=record.relative,
        )
        if preserved is None:
            matches = self._names_with_identity(record.parent, record.identity)
            if len(matches) == 1:
                return self._preserve_owned_name(record, matches[0])
            if len(matches) > 1:
                return CalibrationImportError(
                    f"multiple names match owned identity for {record.relative}"
                )
            record.removed = True
            if record.child is not None:
                record.child.active = False
            return None

        preserved_info = preserved.info
        if _identity(preserved_info) == record.identity:
            record.removed = True
            if record.child is not None:
                record.child.active = False
            if preserved.collisions:
                return CalibrationImportError(
                    "atomic quarantine destination collision preserved at "
                    f"{self._quarantine_display_path()}"
                )
            return None

        owned_matches = self._names_with_identity(record.parent, record.identity)
        owned_error: BaseException | None = None
        if len(owned_matches) == 1:
            owned_error = self._preserve_owned_name(record, owned_matches[0])
        elif len(owned_matches) > 1:
            owned_error = CalibrationImportError(
                f"multiple names match owned identity for {record.relative}"
            )
        else:
            record.removed = True
            if record.child is not None:
                record.child.active = False
        detail = (
            f"; owned preservation also failed: {owned_error}"
            if owned_error is not None
            else ""
        )
        return CalibrationImportError(
            "foreign replacement preserved for "
            f"{record.relative} in {self._quarantine_display_path()}{detail}"
        )

    def _names_with_identity(
        self,
        parent: _Directory,
        identity: Identity,
    ) -> list[str]:
        matches: list[str] = []
        for name in os.listdir(parent.fd):
            try:
                info = os.stat(
                    name,
                    dir_fd=parent.fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            if _identity(info) == identity:
                matches.append(name)
        return matches

    def _preserve_owned_name(
        self,
        record: _OwnedEntry,
        name: str,
    ) -> BaseException | None:
        preserved = self._preserve_binding(
            record.parent,
            name,
            relative=record.relative,
        )
        if preserved is None:
            record.removed = True
            return None
        preserved_info = preserved.info
        if _identity(preserved_info) != record.identity:
            return CalibrationImportError(
                f"preserved identity changed for {record.relative}; "
                f"object retained in {self._quarantine_display_path()}"
            )
        record.removed = True
        if record.child is not None:
            record.child.active = False
        if preserved.collisions:
            return CalibrationImportError(
                "atomic quarantine destination collision preserved at "
                f"{self._quarantine_display_path()}"
            )
        return None

    def _ensure_quarantine_transaction(self) -> _Directory:
        if self.quarantine_transaction is not None:
            return self.quarantine_transaction
        calibration_root = self.fs.run.parent
        if calibration_root is None:
            raise CalibrationImportError("calibration root handle is unavailable")
        calibration_device = self.io.device_id(
            calibration_root.fd,
            "calibration_root",
        )
        if self.io.device_id(self.fs.run.fd, "run") != calibration_device:
            raise CalibrationImportError(
                "run and quarantine root device mismatch; refusing EXDEV risk"
            )
        try:
            os.mkdir(
                QUARANTINE_ROOT_NAME,
                mode=0o700,
                dir_fd=calibration_root.fd,
            )
        except FileExistsError:
            pass
        root_info = os.stat(
            QUARANTINE_ROOT_NAME,
            dir_fd=calibration_root.fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or stat.S_ISLNK(root_info.st_mode)
            or stat.S_IMODE(root_info.st_mode) != 0o700
        ):
            raise CalibrationImportError(
                "rollback quarantine root must be a private mode-0700 directory"
            )
        self.io.before_root_open("quarantine_root", QUARANTINE_ROOT_NAME)
        self.quarantine_root = self.fs.open_directory(
            calibration_root,
            QUARANTINE_ROOT_NAME,
            label="rollback quarantine root",
        )
        opened_root_info = os.fstat(self.quarantine_root.fd)
        if (
            _identity(opened_root_info) != _identity(root_info)
            or not stat.S_ISDIR(opened_root_info.st_mode)
            or opened_root_info.st_dev != root_info.st_dev
            or opened_root_info.st_dev != calibration_device
            or stat.S_IMODE(opened_root_info.st_mode) != 0o700
        ):
            raise CalibrationImportError(
                "rollback quarantine root identity/private mode changed while opening"
            )
        if (
            self.io.device_id(self.quarantine_root.fd, "quarantine_root")
            != calibration_device
        ):
            raise CalibrationImportError(
                "quarantine root device mismatch; refusing EXDEV risk"
            )
        for _ in range(128):
            transaction_name = (
                f"{self.fs.run_name}.{os.getpid()}.{secrets.token_hex(12)}"
            )
            try:
                os.mkdir(
                    transaction_name,
                    mode=0o700,
                    dir_fd=self.quarantine_root.fd,
                )
            except FileExistsError:
                continue
            info = os.stat(
                transaction_name,
                dir_fd=self.quarantine_root.fd,
                follow_symlinks=False,
            )
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                raise CalibrationImportError(
                    "rollback transaction quarantine is not private"
                )
            self.quarantine_transaction = self.fs.open_directory(
                self.quarantine_root,
                transaction_name,
                label="rollback transaction quarantine",
            )
            self.quarantine_relative = f"{QUARANTINE_ROOT_NAME}/{transaction_name}"
            return self.quarantine_transaction
        raise CalibrationImportError(
            "could not reserve unique rollback transaction quarantine"
        )

    def _preserve_binding(
        self,
        parent: _Directory,
        name: str,
        *,
        relative: str,
    ) -> _PreservedBinding | None:
        try:
            os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        transaction = self._ensure_quarantine_transaction()
        collisions: list[str] = []
        for _ in range(128):
            target_name = f"{self.preserved_count + 1:04d}.{secrets.token_hex(16)}"
            self.io.before_quarantine_rename(
                relative,
                cast(str, self.quarantine_relative),
                target_name,
            )
            try:
                self.io.rename_noreplace(
                    parent.fd,
                    name,
                    transaction.fd,
                    target_name,
                )
            except FileExistsError:
                collisions.append(target_name)
                self.preserved_count += 1
                continue
            except FileNotFoundError:
                return None
            info = os.stat(
                target_name,
                dir_fd=transaction.fd,
                follow_symlinks=False,
            )
            self.preserved_count += 1
            self.io.after_rollback_preserve(
                relative,
                cast(str, self.quarantine_relative),
                target_name,
            )
            return _PreservedBinding(
                target_name=target_name,
                info=info,
                collisions=tuple(collisions),
            )
        raise CalibrationImportError(
            "atomic quarantine destination remained occupied after 128 attempts"
        )

    def _quarantine_display_path(self) -> Path:
        if self.quarantine_relative is None:
            return self.fs.path.parent / QUARANTINE_ROOT_NAME
        return self.fs.path.parent / self.quarantine_relative

    def precommit(
        self,
        snapshots: Sequence[_SnapshotFile],
        published: Sequence[_OwnedEntry],
        validate_precommit: Callable[[], None],
    ) -> None:
        self.io.before_final_revalidate()
        self.io.before_published_outputs_attestation()
        self.fs.reattest()
        _assert_snapshots_unchanged(self.fs, snapshots, self.io)
        self.attest_published(published)
        validate_precommit()
        self.attest_lock()
        self.io.fsync_directory(self.fs.run.fd, "run")

    def final_attest_before_commit(
        self,
        snapshots: Sequence[_SnapshotFile],
        published: Sequence[_OwnedEntry],
    ) -> None:
        self.io.before_final_commit_attestation()
        self.fs.reattest()
        _assert_snapshots_unchanged(self.fs, snapshots, self.io)
        self.attest_published(published)
        self.attest_lock()

    def commit(
        self,
        commit_record: _OwnedEntry,
        stage_records: Sequence[_OwnedEntry],
        snapshots: Sequence[_SnapshotFile],
        published: Sequence[_OwnedEntry],
    ) -> None:
        self.io.before_commit_artifact_attestation(commit_record.relative)
        self.fs.reattest()
        self.attest_published([commit_record])
        self.preserve_owned(stage_records)
        quarantine, lock_target = self._prepare_lock_quarantine()
        self.io.before_lock_release()
        self.fs.reattest()
        _assert_snapshots_unchanged(self.fs, snapshots, self.io)
        self.attest_published(published)
        self.attest_lock()
        try:
            self.io.rename_noreplace(
                self.fs.run.fd,
                LOCK_NAME,
                quarantine.fd,
                lock_target,
            )
        except FileExistsError as error:
            raise CalibrationImportError(
                "prepared lock quarantine destination became occupied"
            ) from error
        moved = os.stat(
            lock_target,
            dir_fd=quarantine.fd,
            follow_symlinks=False,
        )
        if (
            self.lock_identity is None
            or _identity(moved) != self.lock_identity
            or not stat.S_ISREG(moved.st_mode)
        ):
            raise CalibrationImportError(
                "quarantined import lock identity changed after atomic movement"
            )
        self.preserved_count += 1
        self.io.fsync_directory(self.fs.run.fd, "run")
        self.io.fsync_directory(quarantine.fd, "rollback quarantine transaction")
        if self.quarantine_root is None:
            raise CalibrationImportError("rollback quarantine root is unavailable")
        self.io.fsync_directory(
            self.quarantine_root.fd,
            "rollback quarantine root",
        )
        self.committed = True

    def _prepare_lock_quarantine(self) -> tuple[_Directory, str]:
        self.attest_lock()
        self.io.before_quarantine(LOCK_NAME)
        transaction = self._ensure_quarantine_transaction()
        for _ in range(128):
            target_name = f"{self.preserved_count + 1:04d}.{secrets.token_hex(16)}"
            self.io.before_quarantine_rename(
                LOCK_NAME,
                cast(str, self.quarantine_relative),
                target_name,
            )
            try:
                os.stat(
                    target_name,
                    dir_fd=transaction.fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return transaction, target_name
            self.preserved_count += 1
        raise CalibrationImportError(
            "could not reserve an absent atomic lock-quarantine destination"
        )


def _decode_text(raw: bytes, *, name: str) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CalibrationImportError(f"{name} is not strict UTF-8") from error


def _reject_json_constant(value: str) -> object:
    raise CalibrationImportError(f"non-finite JSON number is forbidden: {value}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CalibrationImportError(
                f"duplicate JSON object key is forbidden: {key!r}"
            )
        result[key] = value
    return result


def _parse_json_bytes(raw: bytes, *, name: str) -> object:
    text = _decode_text(raw, name=name)
    try:
        return json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except json.JSONDecodeError as error:
        raise CalibrationImportError(f"{name} is not valid JSON: {error}") from error


def _json_bytes(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        return (rendered + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise CalibrationImportError(
            f"label report is not strict JSON: {error}"
        ) from error


def _require_regular_at(parent: _Directory, name: str, *, label: str) -> None:
    info = _stat_at(parent, name, label=label)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise CalibrationImportError(f"{label} must be a regular file")


def _validate_run_layout(
    fs: _AnchoredWorkspace,
    pass_name: str,
) -> _Layout:
    actual = fs.list_names(fs.run, label="calibration run")
    if FAILED_MARKER in actual:
        raise CalibrationImportError("calibration run is in the _FAILED state")
    if SUCCESS_MARKER not in actual:
        raise CalibrationImportError("calibration run has no finalized _SUCCESS marker")
    if pass_name == "a":
        existing = actual & {REPORTS_DIRNAME, PASS_B_DIRNAME}
        if existing:
            raise CalibrationImportError(
                "Pass A output already or partially exists; refusing overwrite"
            )
        expected = set(_BASE_ENTRIES)
    else:
        expected = set(_BASE_ENTRIES) | {REPORTS_DIRNAME, PASS_B_DIRNAME}
        if REPORTS_DIRNAME not in actual or PASS_B_DIRNAME not in actual:
            raise CalibrationImportError(
                "Pass B requires a successful Pass A report and generated Pass B"
            )
    if actual != expected:
        raise CalibrationImportError(
            "calibration run state is ambiguous; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    for filename in (SUCCESS_MARKER, "manifest.json", "index.md", LOCK_NAME):
        _require_regular_at(fs.run, filename, label=filename)
    pass_a = fs.open_directory(fs.run, PASS_A_DIRNAME, label="Pass A directory")
    figures = fs.open_directory(fs.run, FIGURES_DIRNAME, label="figure directory")
    reports = (
        fs.open_directory(fs.run, REPORTS_DIRNAME, label="private report directory")
        if pass_name == "b"
        else None
    )
    pass_b = (
        fs.open_directory(fs.run, PASS_B_DIRNAME, label="Pass B directory")
        if pass_name == "b"
        else None
    )
    return _Layout(
        pass_a=pass_a,
        figures=figures,
        reports=reports,
        pass_b=pass_b,
    )


def _exact_object(
    value: object,
    *,
    fields: frozenset[str],
    name: str,
) -> dict[str, object]:
    if type(value) is not dict or set(cast(dict[str, object], value)) != set(fields):
        raise CalibrationImportError(f"{name} field set is invalid")
    return cast(dict[str, object], value)


def _require_sha256(value: object, *, name: str) -> str:
    if type(value) is not str or _HEX_SHA256.fullmatch(value) is None:
        raise CalibrationImportError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _require_positive_count(value: object, *, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise CalibrationImportError(f"{name} must be an integer at least {minimum}")
    return value


def _validate_manifest_provenance(
    payload: Mapping[str, object],
    manifest: calibration_ruler.RulerManifest,
) -> None:
    build = _exact_object(
        payload.get("build"),
        fields=_BUILD_FIELDS,
        name="manifest build provenance",
    )
    head_sha = build.get("head_sha")
    if type(head_sha) is not str or _COMMIT_SHA.fullmatch(head_sha) is None:
        raise CalibrationImportError("manifest build head SHA is invalid")
    if build.get("code_sha") != head_sha:
        raise CalibrationImportError(
            "manifest build code SHA must equal attested head SHA"
        )
    if build.get("tree_status") != "clean":
        raise CalibrationImportError("manifest build tree status must be clean")
    if build.get("tool") != "build_calibration_ruler.py":
        raise CalibrationImportError("manifest build tool is invalid")
    source_hashes = _exact_object(
        build.get("source_hashes"),
        fields=frozenset(ruler_builder._SOURCE_PATHS),  # noqa: SLF001
        name="manifest source attestations",
    )
    for source_name, value in source_hashes.items():
        attestation = _exact_object(
            value,
            fields=_SOURCE_ATTESTATION_FIELDS,
            name=f"manifest source attestation {source_name}",
        )
        hashes = [
            _require_sha256(
                attestation[field],
                name=f"manifest source attestation {source_name}.{field}",
            )
            for field in sorted(_SOURCE_ATTESTATION_FIELDS)
        ]
        if len(set(hashes)) != 1:
            raise CalibrationImportError(
                f"manifest source attestation {source_name} hashes disagree"
            )

    inputs = _exact_object(
        payload.get("inputs"),
        fields=_INPUT_FIELDS,
        name="manifest input provenance",
    )
    primary = [item for item in manifest.items if item.repeat_of is None]
    support = {
        stratum: sum(1 for item in primary if item.stratum == stratum)
        for stratum in ("trusted", "failure", "shadow")
    }
    for name in ("trusted", "failure"):
        problem_input = _exact_object(
            inputs[name],
            fields=_PROBLEM_INPUT_FIELDS,
            name=f"manifest input {name}",
        )
        _require_sha256(
            problem_input["sha256"],
            name=f"manifest input {name}.sha256",
        )
        _require_positive_count(
            problem_input["count"],
            name=f"manifest input {name}.count",
            minimum=support[name],
        )
    shadow = _exact_object(
        inputs["shadow"],
        fields=_SHADOW_INPUT_FIELDS,
        name="manifest input shadow",
    )
    _require_sha256(
        shadow["manifest_sha256"],
        name="manifest input shadow.manifest_sha256",
    )
    if type(shadow["run_id"]) is not str:
        raise CalibrationImportError("manifest input shadow.run_id is invalid")
    try:
        ruler_builder._validate_run_id(cast(str, shadow["run_id"]))  # noqa: SLF001
    except ValueError as error:
        raise CalibrationImportError(
            f"manifest input shadow.run_id is invalid: {error}"
        ) from error
    _require_positive_count(
        shadow["candidate_count"],
        name="manifest input shadow.candidate_count",
        minimum=support["shadow"],
    )


def _expected_counts(
    manifest: calibration_ruler.RulerManifest,
) -> dict[str, object]:
    primary = [item for item in manifest.items if item.repeat_of is None]
    repeats = [item for item in manifest.items if item.repeat_of is not None]
    strata: dict[str, int] = {}
    splits: dict[str, int] = {}
    families: dict[str, int] = {}
    for item in primary:
        stratum = cast(str, item.stratum)
        split = cast(str, item.split)
        strata[stratum] = strata.get(stratum, 0) + 1
        splits[split] = splits.get(split, 0) + 1
        if item.stratum == "shadow":
            family = cast(str, item.metadata["model_family"])
            families[family] = families.get(family, 0) + 1
    return {
        "primary": len(primary),
        "repeats": len(repeats),
        "strata": strata,
        "splits": splits,
        "shadow_families": families,
    }


def _load_manifest(
    fs: _AnchoredWorkspace,
    io: ImportIO,
) -> tuple[calibration_ruler.RulerManifest, _SnapshotFile]:
    snapshot = fs.read_file(
        fs.run,
        "manifest.json",
        relative="manifest.json",
        label="private manifest",
        io=io,
    )
    document = _parse_json_bytes(snapshot.content, name="private manifest")
    if type(document) is not dict:
        raise CalibrationImportError("private manifest must be a JSON object")
    payload = cast(dict[str, object], document)
    if set(payload) != set(_MANIFEST_FIELDS):
        raise CalibrationImportError("private manifest field set is invalid")
    if payload.get("manifest_version") != MANIFEST_VERSION:
        raise CalibrationImportError("private manifest version is unsupported")
    if payload.get("kind") != "blind-human-calibration-ruler":
        raise CalibrationImportError("private manifest kind is invalid")
    if payload.get("private") is not True:
        raise CalibrationImportError("calibration manifest must remain private")
    if payload.get("run_id") != fs.run_name:
        raise CalibrationImportError("private manifest run ID does not match workspace")
    try:
        manifest = calibration_ruler.RulerManifest.from_dict(payload.get("ruler"))
        calibration_ruler.validate_manifest(manifest)
    except (TypeError, ValueError) as error:
        raise CalibrationImportError(
            f"private ruler manifest is invalid: {error}"
        ) from error
    if payload.get("seed") != manifest.seed:
        raise CalibrationImportError("private manifest seed does not match ruler")
    if payload.get("ruler") != manifest.to_dict():
        raise CalibrationImportError("private ruler manifest is not canonical")
    if payload.get("counts") != _expected_counts(manifest):
        raise CalibrationImportError("private manifest counts do not match ruler")
    _validate_manifest_provenance(payload, manifest)
    return manifest, snapshot


def _block_names(count: int) -> list[str]:
    return [f"block-{number:02d}.md" for number in range(1, count + 1)]


def _load_blocks(
    fs: _AnchoredWorkspace,
    directory: _Directory,
    *,
    pass_name: str,
    item_count: int,
    io: ImportIO,
) -> tuple[list[str], list[_SnapshotFile]]:
    pass_label = f"Pass {pass_name.upper()}"
    expected_count = (
        item_count + calibration_sheet.BLOCK_CAPACITY - 1
    ) // calibration_sheet.BLOCK_CAPACITY
    filenames = _block_names(expected_count)
    expected = set(filenames)
    if pass_name == "b":
        expected.add(PASS_B_SUCCESS)
    actual = fs.list_names(directory, label=f"{pass_label} directory")
    if actual != expected:
        raise CalibrationImportError(
            f"{pass_label} block set differs; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    documents: list[str] = []
    snapshots: list[_SnapshotFile] = []
    for filename in filenames:
        snapshot = fs.read_file(
            directory,
            filename,
            relative=f"pass-{pass_name}/{filename}",
            label=f"{pass_label} {filename}",
            io=io,
        )
        documents.append(
            _decode_text(snapshot.content, name=f"{pass_label} {filename}")
        )
        snapshots.append(snapshot)
    if pass_name == "b":
        marker = fs.read_file(
            directory,
            PASS_B_SUCCESS,
            relative=f"pass-{pass_name}/{PASS_B_SUCCESS}",
            label="Pass B success marker",
            io=io,
        )
        if marker.content != b"ok\n":
            raise CalibrationImportError("Pass B success marker is invalid")
        snapshots.append(marker)
    return documents, snapshots


def _load_assets(
    fs: _AnchoredWorkspace,
    figures: _Directory,
    manifest: calibration_ruler.RulerManifest,
    io: ImportIO,
) -> tuple[dict[str, bytes], list[_SnapshotFile]]:
    expected_assets = calibration_sheet.figure_assets(manifest)
    expected_names = {Path(relative).name for relative in expected_assets}
    actual_names = fs.list_names(figures, label="figure asset directory")
    if actual_names != expected_names:
        raise CalibrationImportError(
            "figure asset set differs; "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )
    assets: dict[str, bytes] = {}
    snapshots: list[_SnapshotFile] = []
    for relative in expected_assets:
        name = Path(relative).name
        snapshot = fs.read_file(
            figures,
            name,
            relative=relative,
            label=f"figure asset {relative}",
            io=io,
        )
        assets[relative] = snapshot.content
        snapshots.append(snapshot)
    return assets, snapshots


def _pass_a_consistency(
    labels: Mapping[str, calibration_sheet.PassALabel],
    manifest: calibration_ruler.RulerManifest,
) -> tuple[dict[str, object], dict[str, object]]:
    full = calibration_sheet.repeat_consistency(labels, manifest)
    consistency = {
        "repeat_count": full["repeat_count"],
        "exact_answer": full["exact_answer"],
        "categorical_fields": full["categorical_fields"],
    }
    gate = calibration_sheet.consistency_gate(consistency)
    return consistency, gate


def _serialized_labels(
    labels: Mapping[
        str,
        calibration_sheet.PassALabel | calibration_sheet.PassBLabel,
    ],
) -> dict[str, dict[str, str]]:
    return {review_id: label.to_dict() for review_id, label in labels.items()}


def _make_pass_a_report(
    *,
    run_id: str,
    manifest_sha256: str,
    labels: Mapping[str, calibration_sheet.PassALabel],
    manifest: calibration_ruler.RulerManifest,
) -> dict[str, object]:
    consistency, gate = _pass_a_consistency(labels, manifest)
    status = "PASS_A_COMPLETE" if gate["passed"] is True else "ADJUDICATION_REQUIRED"
    return {
        "report_version": PASS_A_REPORT_VERSION,
        "pass": "a",
        "status": status,
        "run_id": run_id,
        "manifest_sha256": manifest_sha256,
        "label_count": len(labels),
        "labels": _serialized_labels(labels),
        "repeat_consistency": consistency,
        "consistency_gate": gate,
    }


def _load_pass_a_workspace(
    fs: _AnchoredWorkspace,
    layout: _Layout,
    io: ImportIO,
) -> _LoadedWorkspace:
    manifest, manifest_snapshot = _load_manifest(fs, io)
    manifest_sha256 = hashlib.sha256(manifest_snapshot.content).hexdigest()
    snapshots = [manifest_snapshot]
    marker = fs.read_file(
        fs.run,
        SUCCESS_MARKER,
        relative=SUCCESS_MARKER,
        label="ruler success marker",
        io=io,
    )
    if marker.content != b"ok\n":
        raise CalibrationImportError("ruler success marker is invalid")
    snapshots.append(marker)
    index = fs.read_file(
        fs.run,
        "index.md",
        relative="index.md",
        label="blind review index",
        io=io,
    )
    if index.content != calibration_sheet.render_index(manifest).encode("utf-8"):
        raise CalibrationImportError("immutable blind review index changed")
    snapshots.append(index)
    documents, block_snapshots = _load_blocks(
        fs,
        layout.pass_a,
        pass_name="a",
        item_count=len(manifest.items),
        io=io,
    )
    assets, asset_snapshots = _load_assets(
        fs,
        layout.figures,
        manifest,
        io,
    )
    snapshots.extend(block_snapshots)
    snapshots.extend(asset_snapshots)
    try:
        labels = calibration_sheet.parse_pass_a(
            documents,
            manifest=manifest,
            assets=assets,
        )
    except (TypeError, ValueError) as error:
        raise CalibrationImportError(str(error)) from error
    report = _make_pass_a_report(
        run_id=fs.run_name,
        manifest_sha256=manifest_sha256,
        labels=labels,
        manifest=manifest,
    )
    return _LoadedWorkspace(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        pass_a_labels=labels,
        pass_a_report=report,
        snapshots=tuple(snapshots),
    )


def _load_successful_pass_a_report(
    fs: _AnchoredWorkspace,
    reports: _Directory,
    workspace: _LoadedWorkspace,
    io: ImportIO,
) -> _SnapshotFile:
    actual = fs.list_names(reports, label="private report directory")
    if actual != {"pass-a-labels.json"}:
        raise CalibrationImportError(
            "private report state is partial or already contains Pass B output"
        )
    snapshot = fs.read_file(
        reports,
        "pass-a-labels.json",
        relative="reports/pass-a-labels.json",
        label="Pass A label report",
        io=io,
    )
    document = _parse_json_bytes(snapshot.content, name="Pass A label report")
    if type(document) is not dict:
        raise CalibrationImportError("Pass A label report must be a JSON object")
    payload = cast(dict[str, object], document)
    if payload.get("status") != "PASS_A_COMPLETE":
        raise CalibrationImportError(
            "Pass B import requires a successful Pass A report"
        )
    expected = _json_bytes(workspace.pass_a_report)
    if snapshot.content != expected:
        raise CalibrationImportError(
            "Pass B requires the exact immutable Pass A report bytes"
        )
    return snapshot


def _load_pass_b_labels(
    fs: _AnchoredWorkspace,
    pass_b: _Directory,
    manifest: calibration_ruler.RulerManifest,
    io: ImportIO,
) -> tuple[dict[str, calibration_sheet.PassBLabel], list[_SnapshotFile]]:
    documents, snapshots = _load_blocks(
        fs,
        pass_b,
        pass_name="b",
        item_count=len(manifest.items),
        io=io,
    )
    try:
        labels = calibration_sheet.parse_pass_b(documents, manifest=manifest)
    except (TypeError, ValueError) as error:
        raise CalibrationImportError(str(error)) from error
    return labels, snapshots


def _make_pass_b_report(
    *,
    run_id: str,
    manifest_sha256: str,
    pass_a_report_raw: bytes,
    labels: Mapping[str, calibration_sheet.PassBLabel],
) -> dict[str, object]:
    return {
        "report_version": PASS_B_REPORT_VERSION,
        "pass": "b",
        "status": "PASS_B_COMPLETE",
        "run_id": run_id,
        "manifest_sha256": manifest_sha256,
        "pass_a_report_sha256": hashlib.sha256(pass_a_report_raw).hexdigest(),
        "label_count": len(labels),
        "labels": _serialized_labels(labels),
    }


def _assert_snapshots_unchanged(
    fs: _AnchoredWorkspace,
    snapshots: Sequence[_SnapshotFile],
    io: ImportIO,
) -> None:
    for expected in snapshots:
        actual = fs.read_file(
            expected.parent,
            expected.name,
            relative=expected.relative,
            label=f"import input {expected.relative}",
            io=io,
            notify=False,
        )
        if actual.identity != expected.identity or actual.content != expected.content:
            raise CalibrationImportError(
                f"workspace input identity changed during import: {expected.relative}"
            )


def _stage_outputs(
    transaction: _ImportTransaction,
    *,
    report_bytes: bytes,
    pass_b_blocks: Sequence[str] | None,
) -> _Stage:
    start = len(transaction.owned)
    root = transaction.create_unique_stage()
    transaction.create_stage_file(
        root,
        "report.json",
        report_bytes,
        relative="report.json",
    )
    block_names: list[str] = []
    block_bytes: dict[str, bytes] = {}
    pass_b: _Directory | None = None
    if pass_b_blocks is not None:
        pass_b = transaction._new_owned_directory(  # noqa: SLF001
            root,
            PASS_B_DIRNAME,
            relative="stage/pass-b",
        )
        for number, block in enumerate(pass_b_blocks, start=1):
            filename = f"block-{number:02d}.md"
            encoded = block.encode("utf-8")
            transaction.create_stage_file(
                pass_b,
                filename,
                encoded,
                relative=f"stage/pass-b/{filename}",
            )
            block_names.append(filename)
            block_bytes[filename] = encoded
        transaction.create_stage_file(
            pass_b,
            PASS_B_SUCCESS,
            b"ok\n",
            relative=f"stage/pass-b/{PASS_B_SUCCESS}",
        )
        block_bytes[PASS_B_SUCCESS] = b"ok\n"
        transaction.fsync_directory(pass_b, "stage/pass-b")
    transaction.fsync_directory(root, "stage")
    transaction.fsync_directory(transaction.fs.run, "run")
    return _Stage(
        root=root,
        pass_b=pass_b,
        block_names=block_names,
        report_bytes=report_bytes,
        block_bytes=block_bytes,
        records=list(transaction.owned[start:]),
    )


def _publish_pass_b(
    transaction: _ImportTransaction,
    stage: _Stage,
) -> _Directory:
    if stage.pass_b is None:
        raise CalibrationImportError("Pass B staging is unavailable")
    destination = transaction._new_owned_directory(  # noqa: SLF001
        transaction.fs.run,
        PASS_B_DIRNAME,
        relative=PASS_B_DIRNAME,
    )
    for filename in [*stage.block_names, PASS_B_SUCCESS]:
        transaction.link_published_file(
            stage.pass_b,
            filename,
            destination,
            filename,
            relative=f"pass-b/{filename}",
            expected_bytes=stage.block_bytes[filename],
        )
    transaction.fsync_directory(destination, "pass-b")
    transaction.fsync_directory(transaction.fs.run, "run")
    return destination


def _prepare_report_directory(
    transaction: _ImportTransaction,
    layout: _Layout,
    *,
    pass_name: str,
) -> _Directory:
    if pass_name == "a":
        return transaction._new_owned_directory(  # noqa: SLF001
            transaction.fs.run,
            REPORTS_DIRNAME,
            relative=REPORTS_DIRNAME,
        )
    reports = layout.reports
    if reports is None:
        raise CalibrationImportError("private report directory is unavailable")
    return reports


def _publish_report(
    transaction: _ImportTransaction,
    stage: _Stage,
    reports: _Directory,
    *,
    pass_name: str,
) -> _OwnedEntry:
    filename = f"pass-{pass_name}-labels.json"
    record = transaction.link_published_file(
        stage.root,
        "report.json",
        reports,
        filename,
        relative=f"reports/{filename}",
        expected_bytes=stage.report_bytes,
        commit_artifact=True,
    )
    transaction.fsync_directory(reports, "reports")
    transaction.fsync_directory(transaction.fs.run, "run")
    return record


def _validate_precommit_layout(
    fs: _AnchoredWorkspace,
    layout: _Layout,
    *,
    pass_name: str,
    pass_a_complete: bool,
    item_count: int,
    stage_name: str,
) -> None:
    fs.reattest()
    expected = set(_BASE_ENTRIES) | {REPORTS_DIRNAME, stage_name}
    if pass_name == "b" or pass_a_complete:
        expected.add(PASS_B_DIRNAME)
    actual = fs.list_names(fs.run, label="calibration run")
    if actual != expected:
        raise CalibrationImportError("precommit calibration import state is partial")
    if layout.reports is None:
        raise CalibrationImportError("precommit report directory is unavailable")
    reports_expected = set() if pass_name == "a" else {"pass-a-labels.json"}
    if (
        fs.list_names(layout.reports, label="private report directory")
        != reports_expected
    ):
        raise CalibrationImportError("precommit private report state is partial")
    for filename in reports_expected:
        _require_regular_at(layout.reports, filename, label=f"report {filename}")
    if PASS_B_DIRNAME in expected:
        if layout.pass_b is None:
            raise CalibrationImportError("precommit Pass B directory is unavailable")
        expected_blocks = set(
            _block_names(
                (item_count + calibration_sheet.BLOCK_CAPACITY - 1)
                // calibration_sheet.BLOCK_CAPACITY
            )
        ) | {PASS_B_SUCCESS}
        if fs.list_names(layout.pass_b, label="Pass B directory") != expected_blocks:
            raise CalibrationImportError("precommit Pass B publication is partial")
        for filename in expected_blocks:
            _require_regular_at(layout.pass_b, filename, label=f"Pass B {filename}")


def _import_pass_a(
    fs: _AnchoredWorkspace,
    transaction: _ImportTransaction,
    io: ImportIO,
) -> dict[str, object]:
    layout = _validate_run_layout(fs, "a")
    workspace = _load_pass_a_workspace(fs, layout, io)
    fs.reattest()
    _assert_snapshots_unchanged(fs, workspace.snapshots, io)
    complete = workspace.pass_a_report["status"] == "PASS_A_COMPLETE"
    pass_b_blocks = (
        calibration_sheet.render_blocks(workspace.manifest, pass_name="b")
        if complete
        else None
    )
    stage = _stage_outputs(
        transaction,
        report_bytes=_json_bytes(workspace.pass_a_report),
        pass_b_blocks=pass_b_blocks,
    )
    io.before_publish()
    fs.reattest()
    _assert_snapshots_unchanged(fs, workspace.snapshots, io)
    if complete:
        layout.pass_b = _publish_pass_b(transaction, stage)
    layout.reports = _prepare_report_directory(
        transaction,
        layout,
        pass_name="a",
    )
    transaction.preserve_owned(
        [
            record
            for record in stage.records
            if record.relative.startswith("stage/pass-b")
        ]
    )
    noncommit_outputs = [
        record
        for record in transaction.owned
        if record.published and not record.commit_artifact
    ]
    transaction.precommit(
        workspace.snapshots,
        noncommit_outputs,
        lambda: _validate_precommit_layout(
            fs,
            layout,
            pass_name="a",
            pass_a_complete=complete,
            item_count=len(workspace.manifest.items),
            stage_name=cast(str, stage.root.name),
        ),
    )
    transaction.final_attest_before_commit(
        workspace.snapshots,
        noncommit_outputs,
    )
    commit_record = _publish_report(
        transaction,
        stage,
        layout.reports,
        pass_name="a",
    )
    transaction.commit(
        commit_record,
        [record for record in stage.records if not record.removed],
        workspace.snapshots,
        [*noncommit_outputs, commit_record],
    )
    return workspace.pass_a_report


def _import_pass_b(
    fs: _AnchoredWorkspace,
    transaction: _ImportTransaction,
    io: ImportIO,
) -> dict[str, object]:
    layout = _validate_run_layout(fs, "b")
    if layout.reports is None or layout.pass_b is None:
        raise CalibrationImportError("Pass B workspace is incomplete")
    workspace = _load_pass_a_workspace(fs, layout, io)
    pass_a_snapshot = _load_successful_pass_a_report(
        fs,
        layout.reports,
        workspace,
        io,
    )
    labels, pass_b_snapshots = _load_pass_b_labels(
        fs,
        layout.pass_b,
        workspace.manifest,
        io,
    )
    snapshots = [
        *workspace.snapshots,
        pass_a_snapshot,
        *pass_b_snapshots,
    ]
    fs.reattest()
    _assert_snapshots_unchanged(fs, snapshots, io)
    report = _make_pass_b_report(
        run_id=fs.run_name,
        manifest_sha256=workspace.manifest_sha256,
        pass_a_report_raw=pass_a_snapshot.content,
        labels=labels,
    )
    stage = _stage_outputs(
        transaction,
        report_bytes=_json_bytes(report),
        pass_b_blocks=None,
    )
    io.before_publish()
    fs.reattest()
    _assert_snapshots_unchanged(fs, snapshots, io)
    reports = _prepare_report_directory(
        transaction,
        layout,
        pass_name="b",
    )
    noncommit_outputs = [
        record
        for record in transaction.owned
        if record.published and not record.commit_artifact
    ]
    transaction.precommit(
        snapshots,
        noncommit_outputs,
        lambda: _validate_precommit_layout(
            fs,
            layout,
            pass_name="b",
            pass_a_complete=True,
            item_count=len(workspace.manifest.items),
            stage_name=cast(str, stage.root.name),
        ),
    )
    transaction.final_attest_before_commit(
        snapshots,
        noncommit_outputs,
    )
    commit_record = _publish_report(
        transaction,
        stage,
        reports,
        pass_name="b",
    )
    transaction.commit(
        commit_record,
        [record for record in stage.records if not record.removed],
        snapshots,
        [*noncommit_outputs, commit_record],
    )
    return report


def import_pass(
    run_dir: Path | str,
    pass_name: str,
    *,
    _allow_test_paths: bool = False,
    _io: ImportIO | None = None,
) -> dict[str, object]:
    """Validate and atomically import one completed human-review pass."""
    if pass_name not in {"a", "b"}:
        raise CalibrationImportError("pass must be exactly 'a' or 'b'")
    io = _io or ImportIO()
    io.preflight_rename_noreplace()
    _runtime_probe_rename_noreplace(
        run_dir,
        allow_test_paths=_allow_test_paths,
        io=io,
    )
    fs: _AnchoredWorkspace | None = None
    try:
        fs = _AnchoredWorkspace.open(
            run_dir,
            allow_test_paths=_allow_test_paths,
        )
        with _ImportTransaction(fs, io) as transaction:
            return (
                _import_pass_a(fs, transaction, io)
                if pass_name == "a"
                else _import_pass_b(fs, transaction, io)
            )
    except CalibrationImportError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise CalibrationImportError(str(error)) from error
    finally:
        if fs is not None:
            fs.close()


def _cli_summary(
    report: Mapping[str, object],
    *,
    run_dir: Path,
    pass_name: str,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "status": report.get("status"),
        "report_path": str(run_dir / REPORTS_DIRNAME / f"pass-{pass_name}-labels.json"),
        "label_count": report.get("label_count"),
        "repeat_consistency": (
            report.get("repeat_consistency") if pass_name == "a" else None
        ),
    }
    return summary


def _cli_error_category(error: BaseException) -> str:
    message = str(error).casefold()
    if "reviewer edit required" in message:
        return "reviewer_field"
    if "manifest" in message or "schema" in message:
        return "workspace_schema"
    if any(
        token in message
        for token in ("path", "symlink", "device", "lock", "quarantine")
    ):
        return "filesystem_state"
    return "import_failed"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import one private blind calibration review pass."
    )
    parser.add_argument(
        "--run",
        required=True,
        help="run ID directly below content/run/calibration",
    )
    parser.add_argument("--pass", dest="pass_name", choices=("a", "b"), required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        ruler_builder._validate_run_id(args.run)  # noqa: SLF001
        run_dir = CALIBRATION_ROOT / args.run
        report = import_pass(
            run_dir,
            args.pass_name,
        )
    except (CalibrationImportError, ValueError) as error:
        parser.error(f"CALIBRATION_IMPORT_ERROR:{_cli_error_category(error)}")
    print(
        json.dumps(
            _cli_summary(
                report,
                run_dir=run_dir,
                pass_name=args.pass_name,
            ),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
