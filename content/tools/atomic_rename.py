# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Portable fd-relative atomic rename-no-replace primitives."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

_DARWIN_RENAME_EXCL = 0x00000004
_LINUX_RENAME_NOREPLACE = 1
_LINUX_RENAMEAT2_SYSCALLS = {
    "x86_64": 316,
    "amd64": 316,
    "aarch64": 276,
    "arm64": 276,
    "i386": 353,
    "i686": 353,
}


class AtomicRenameError(ValueError):
    """The required atomic no-replace primitive is unavailable or invalid."""


def _safe_component(name: str, *, label: str) -> str:
    if (
        type(name) is not str
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or Path(name).name != name
    ):
        raise AtomicRenameError(f"{label} is not a safe path component")
    return name


def _raise_rename_error(
    error_number: int,
    *,
    source_name: str,
    destination_name: str,
) -> None:
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(
            error_number,
            os.strerror(error_number),
            destination_name,
        )
    if error_number in {errno.ENOSYS, errno.ENOTSUP}:
        raise AtomicRenameError(
            "atomic rename-no-replace is unavailable on this platform"
        )
    raise OSError(
        error_number,
        f"rename-no-replace {source_name!r} -> {destination_name!r}: "
        f"{os.strerror(error_number)}",
    )


def preflight_rename_noreplace(
    *,
    _platform: str | None = None,
    _libc: object | None = None,
    _machine: str | None = None,
) -> None:
    """Verify a no-replace primitive exists without touching the filesystem."""
    platform_name = _platform or sys.platform
    libc = _libc if _libc is not None else ctypes.CDLL(None, use_errno=True)
    if platform_name == "darwin":
        try:
            primitive = getattr(libc, "renameatx_np")
        except AttributeError as error:
            raise AtomicRenameError(
                "atomic rename-no-replace capability is unavailable on Darwin"
            ) from error
        if not callable(primitive):
            raise AtomicRenameError(
                "atomic rename-no-replace capability is invalid on Darwin"
            )
        return
    if platform_name.startswith("linux"):
        try:
            primitive = getattr(libc, "renameat2")
        except AttributeError:
            machine = (_machine or os.uname().machine).casefold()
            if machine not in _LINUX_RENAMEAT2_SYSCALLS:
                raise AtomicRenameError(
                    "atomic rename-no-replace syscall is unknown for "
                    f"Linux architecture {machine!r}"
                )
            try:
                primitive = getattr(libc, "syscall")
            except AttributeError as error:
                raise AtomicRenameError(
                    "atomic rename-no-replace syscall capability is unavailable"
                ) from error
        if not callable(primitive):
            raise AtomicRenameError(
                "atomic rename-no-replace capability is invalid on Linux"
            )
        return
    raise AtomicRenameError(
        "atomic dir-fd rename-no-replace has no safe capability for "
        f"platform {platform_name!r}"
    )


def rename_noreplace(
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
    source = os.fsencode(_safe_component(source_name, label="rename source"))
    destination = os.fsencode(
        _safe_component(destination_name, label="rename destination")
    )
    platform_name = _platform or sys.platform
    libc = _libc if _libc is not None else ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    if platform_name == "darwin":
        try:
            renameatx_np = getattr(libc, "renameatx_np")
        except AttributeError as error:
            raise AtomicRenameError(
                "atomic rename-no-replace is unavailable on Darwin"
            ) from error
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(
            source_dir_fd,
            source,
            destination_dir_fd,
            destination,
            _DARWIN_RENAME_EXCL,
        )
    elif platform_name.startswith("linux"):
        try:
            renameat2 = getattr(libc, "renameat2")
        except AttributeError:
            machine = (_machine or os.uname().machine).casefold()
            syscall_number = _LINUX_RENAMEAT2_SYSCALLS.get(machine)
            if syscall_number is None:
                raise AtomicRenameError(
                    "atomic rename-no-replace syscall is unknown for "
                    f"Linux architecture {machine!r}"
                )
            syscall = getattr(libc, "syscall")
            syscall.restype = ctypes.c_long
            result = syscall(
                ctypes.c_long(syscall_number),
                ctypes.c_int(source_dir_fd),
                ctypes.c_char_p(source),
                ctypes.c_int(destination_dir_fd),
                ctypes.c_char_p(destination),
                ctypes.c_uint(_LINUX_RENAME_NOREPLACE),
            )
        else:
            renameat2.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            renameat2.restype = ctypes.c_int
            result = renameat2(
                source_dir_fd,
                source,
                destination_dir_fd,
                destination,
                _LINUX_RENAME_NOREPLACE,
            )
    else:
        raise AtomicRenameError(
            "atomic dir-fd rename-no-replace has no safe implementation for "
            f"platform {platform_name!r}"
        )
    if result != 0:
        _raise_rename_error(
            ctypes.get_errno(),
            source_name=source_name,
            destination_name=destination_name,
        )
