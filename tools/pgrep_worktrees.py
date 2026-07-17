#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Inspect, trim, and safely remove pgrep worktrees."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

REVIEW_OPERATION_LOCK = "pgrep-review-operation.lock"


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    primary: bool


class LifecycleError(RuntimeError):
    """Raised when a requested worktree operation is unsafe."""


def parse_worktree_porcelain(output: bytes) -> list[Worktree]:
    """Parse NUL-delimited ``git worktree list --porcelain -z`` output."""
    worktrees: list[Worktree] = []
    path: Path | None = None
    branch: str | None = None
    for field in output.split(b"\0"):
        if not field:
            if path is None:
                continue
            worktrees.append(Worktree(path=path, branch=branch, primary=not worktrees))
            path = None
            branch = None
            continue
        key, _, value = field.partition(b" ")
        if key == b"worktree":
            path = Path(os.fsdecode(value))
        elif key == b"branch":
            branch = os.fsdecode(value).removeprefix("refs/heads/")
    return worktrees


def _git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _git_bytes(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
    )


def discover_worktrees(repo: Path) -> list[Worktree]:
    result = _git_bytes(repo, "worktree", "list", "--porcelain", "-z")
    return parse_worktree_porcelain(result.stdout)


def review_disk_guard(available_bytes: int) -> tuple[int, str]:
    gib = available_bytes / 1024**3
    commands = (
        "Run `just worktree-status`, `just worktree-trim <branch-or-path>`, "
        "or `just review-clean`."
    )
    if gib < 10:
        return 2, f"REFUSING REVIEW BUILD: only {gib:.1f} GiB available. {commands}"
    if gib < 30:
        return 0, f"LOW DISK: only {gib:.1f} GiB available. {commands}"
    return 0, ""


def _tree_size(path: Path, excluded_paths: Sequence[Path] = ()) -> int:
    total = 0
    if not path.exists():
        return total
    excluded = {
        Path(os.path.abspath(os.path.normpath(candidate)))
        for candidate in excluded_paths
    }
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        directories[:] = [
            directory
            for directory in directories
            if not (root_path / directory).is_symlink()
            and Path(os.path.abspath(os.path.normpath(root_path / directory)))
            not in excluded
        ]
        for filename in files:
            candidate = root_path / filename
            if not candidate.is_symlink():
                try:
                    total += candidate.stat().st_size
                except FileNotFoundError:
                    pass
    return total


def checkout_size(path: Path, excluded_paths: Sequence[Path] = ()) -> int:
    return _tree_size(path, excluded_paths)


def build_size(path: Path) -> int:
    return _tree_size(path / "out")


def is_dirty(worktree: Worktree) -> bool:
    return bool(_git(worktree.path, "status", "--porcelain").stdout)


def _ignored_paths(worktree: Worktree) -> list[Path]:
    result = _git(
        worktree.path,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
    )
    return [Path(record) for record in result.stdout.split("\0") if record]


def _ignored_component_is_sensitive(part: str) -> bool:
    sensitive_words = {
        "content",
        "corpus",
        "credential",
        "credentials",
        "gold",
        "heldout",
        "key",
        "private",
        "secret",
        "secrets",
        "token",
        "tokens",
    }
    word_list = re.findall(r"[a-z0-9]+", part)
    words = set(word_list)
    compact = "".join(word_list)
    return (
        part == ".ssh"
        or part == ".envrc"
        or part == ".env"
        or part.startswith(".env.")
        or part in {"id_dsa", "id_ecdsa", "id_ed25519", "id_rsa"}
        or "heldout" in compact
        or bool(sensitive_words.intersection(words))
    )


def _ignored_path_is_disposable(path: Path) -> bool:
    """Return true only for known rebuildable ignored output.

    Sensitive components are denied before this allowlist so private corpora,
    gold data, and secrets can never be treated as build output, even if they
    appear under an otherwise disposable directory.
    """
    parts = path.parts
    if not parts:
        return False
    lowered = tuple(part.lower() for part in parts)
    if any(_ignored_component_is_sensitive(part) for part in lowered):
        return False

    # These directories contain only generated dependencies, compiler output,
    # or tool caches. Everything else fails closed.
    if lowered[0] == "out":
        return True
    disposable_directories = {
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svelte-kit",
        ".venv",
        ".yarn",
        "__pycache__",
        "node_modules",
        "target",
    }
    if any(part in disposable_directories for part in lowered):
        return True
    if lowered[0] in {".coverage", "coverage.xml", "htmlcov"}:
        return True
    if lowered[:2] in {
        ("docs", "_build"),
        ("docs", ".doctrees"),
        ("docs_pgrep", "_build"),
    }:
        return True
    paper_suffixes = {
        ".aux",
        ".bbl",
        ".bcf",
        ".blg",
        ".fdb_latexmk",
        ".fls",
        ".run.xml",
        ".synctex.gz",
        ".toc",
    }
    return "paper" in lowered[:-1] and any(
        path.name.endswith(suffix) for suffix in paper_suffixes
    )


def ignored_private_paths(worktree: Worktree) -> list[Path]:
    return [
        path
        for path in _ignored_paths(worktree)
        if not _ignored_path_is_disposable(path)
    ]


def _ignored_private_reason(worktree: Worktree) -> str | None:
    blockers = ignored_private_paths(worktree)
    if not blockers:
        return None
    displayed = ", ".join(str(path) for path in blockers[:3])
    if len(blockers) > 3:
        displayed += f", and {len(blockers) - 3} more"
    return f"ignored private data ({displayed})"


def branch_merged(repo: Path, branch: str) -> bool:
    result = _git(
        repo,
        "merge-base",
        "--is-ancestor",
        f"refs/heads/{branch}",
        "refs/heads/main",
        check=False,
    )
    return result.returncode == 0


def _direct_head_branch(worktree: Worktree) -> str | None:
    result = _git(
        worktree.path,
        "symbolic-ref",
        "--no-recurse",
        "-q",
        "HEAD",
        check=False,
    )
    if result.returncode:
        return None
    return result.stdout.strip().removeprefix("refs/heads/")


def _branch_ref(branch: str) -> str:
    return f"refs/heads/{branch}"


def _read_ref_oid(repo: Path, ref: str) -> str | None:
    result = _git(repo, "rev-parse", "--verify", ref, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _symbolic_ref_target(repo: Path, ref: str) -> str | None:
    result = _git(repo, "symbolic-ref", "-q", ref, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _oid_merged_to_main(repo: Path, oid: str) -> bool:
    return (
        _git(
            repo,
            "merge-base",
            "--is-ancestor",
            oid,
            "refs/heads/main",
            check=False,
        ).returncode
        == 0
    )


@dataclass(frozen=True)
class RefSnapshot:
    branch: str
    ref: str
    oid: str
    require_main: bool

    @classmethod
    def capture(
        cls,
        repo: Path,
        branch: str,
        *,
        require_main: bool,
    ) -> RefSnapshot:
        ref = _branch_ref(branch)
        if target := _symbolic_ref_target(repo, ref):
            raise LifecycleError(
                f"refusing symbolic branch ref before removal: {ref} -> {target}"
            )
        oid = _read_ref_oid(repo, ref)
        if oid is None:
            raise LifecycleError(f"branch moved or disappeared before removal: {ref}")
        if require_main and not _oid_merged_to_main(repo, oid):
            raise LifecycleError(f"branch moved or is no longer merged to main: {ref}")
        return cls(branch, ref, oid, require_main)

    def revalidate(self, repo: Path) -> None:
        if target := _symbolic_ref_target(repo, self.ref):
            raise LifecycleError(
                f"branch became symbolic before worktree removal: "
                f"{self.ref} -> {target}"
            )
        current_oid = _read_ref_oid(repo, self.ref)
        if current_oid != self.oid:
            raise LifecycleError(
                f"branch moved before worktree removal: {self.ref} expected "
                f"{self.oid}, found {current_oid or '(missing)'}"
            )
        if self.require_main and not _oid_merged_to_main(repo, self.oid):
            raise LifecycleError(f"branch is no longer merged to main: {self.ref}")

    def delete(self, repo: Path) -> None:
        result = _git(
            repo,
            "update-ref",
            "--no-deref",
            "-d",
            self.ref,
            self.oid,
            check=False,
        )
        if result.returncode:
            current_oid = _read_ref_oid(repo, self.ref)
            raise LifecycleError(
                f"worktree removed but branch preserved because it moved: "
                f"{self.ref} expected {self.oid}, "
                f"found {current_oid or '(missing)'}"
            )


def _capture_validated_ref_oid(
    repo: Path,
    branch: str,
    *,
    require_main: bool,
) -> str:
    return RefSnapshot.capture(repo, branch, require_main=require_main).oid


def _revalidate_ref_oid(
    repo: Path,
    branch: str,
    expected_oid: str,
    *,
    require_main: bool,
) -> None:
    RefSnapshot(
        branch=branch,
        ref=_branch_ref(branch),
        oid=expected_oid,
        require_main=require_main,
    ).revalidate(repo)


def _delete_branch_ref(
    repo: Path,
    branch: str,
    expected_oid: str,
) -> None:
    RefSnapshot(
        branch=branch,
        ref=_branch_ref(branch),
        oid=expected_oid,
        require_main=False,
    ).delete(repo)


def process_table() -> list[tuple[int, str]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    processes: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        pid_text, separator, command = line.strip().partition(" ")
        if separator and pid_text.isdigit():
            processes.append((int(pid_text), command.lstrip()))
    return processes


def _normalized_absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.normpath(path)))


def _command_contains_path(command: str, path: Path) -> bool:
    target = _normalized_absolute_path(path)
    target_text = str(target)
    start = 0
    while (index := command.find(target_text, start)) >= 0:
        before_ok = index == 0 or command[index - 1] in " \t='\""
        end = index + len(target_text)
        after_ok = end == len(command) or command[end] in "/ \t'\""
        if before_ok and after_ok:
            return True
        start = index + 1

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for token in tokens:
        value = token.partition("=")[2] if "=" in token else token
        if not os.path.isabs(value):
            continue
        candidate = _normalized_absolute_path(value)
        if candidate == target or candidate.is_relative_to(target):
            return True
    return False


def attribute_processes(
    worktrees: Sequence[Worktree],
    processes: Sequence[tuple[int, str]],
    *,
    own_pid: int | None = None,
) -> dict[Worktree, list[tuple[int, str]]]:
    """Assign commands to the longest worktree path present in each command."""
    own_pid = os.getpid() if own_pid is None else own_pid
    attributed: dict[Worktree, list[tuple[int, str]]] = {
        worktree: [] for worktree in worktrees
    }
    longest_first = sorted(
        worktrees,
        key=lambda worktree: len(str(worktree.path)),
        reverse=True,
    )
    for pid, command in processes:
        if pid == own_pid:
            continue
        for worktree in longest_first:
            if _command_contains_path(command, worktree.path):
                attributed[worktree].append((pid, command))
                break
    return attributed


def _process_cwds() -> list[tuple[int, Path]]:
    """Return current-user process CWDs, or fail if inspection is unavailable."""
    own_pid = os.getpid()
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["lsof", "-a", "-d", "cwd", "-F0pn", "-u", str(os.getuid())],
                check=False,
                capture_output=True,
            )
        except OSError as error:
            raise LifecycleError(
                f"process cwd inspection unavailable: {error}"
            ) from error
        if result.returncode:
            detail = os.fsdecode(result.stderr).strip() or f"exit {result.returncode}"
            raise LifecycleError(f"process cwd inspection failed: lsof {detail}")

        cwd_by_pid: list[tuple[int, Path]] = []
        pid: int | None = None
        for raw_field in result.stdout.split(b"\0"):
            field = raw_field.lstrip(b"\n")
            if field.startswith(b"p") and field[1:].isdigit():
                pid = int(field[1:])
            elif field.startswith(b"n") and pid is not None and pid != own_pid:
                cwd_by_pid.append((pid, Path(os.fsdecode(field[1:]))))
        return cwd_by_pid

    if sys.platform.startswith("linux"):
        proc = Path("/proc")
        if not proc.is_dir():
            raise LifecycleError("process cwd inspection unavailable: /proc missing")
        cwd_by_pid = []
        uid = os.getuid()
        try:
            entries = list(proc.iterdir())
        except OSError as error:
            raise LifecycleError(
                f"process cwd inspection unavailable: {error}"
            ) from error
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == own_pid:
                continue
            try:
                if entry.stat().st_uid != uid:
                    continue
                cwd = Path(os.readlink(entry / "cwd"))
            except FileNotFoundError:
                # Processes can exit, and kernel threads have no cwd.
                continue
            except OSError as error:
                raise LifecycleError(
                    f"process cwd inspection failed for PID {pid}: {error}"
                ) from error
            cwd_by_pid.append((pid, cwd))
        return cwd_by_pid

    raise LifecycleError(
        f"process cwd inspection unavailable on platform {sys.platform}"
    )


def attribute_process_cwds(
    worktrees: Sequence[Worktree],
    cwd_processes: Sequence[tuple[int, Path]],
    *,
    own_pid: int | None = None,
) -> dict[Worktree, list[tuple[int, str]]]:
    """Assign CWDs to the longest containing worktree path."""
    own_pid = os.getpid() if own_pid is None else own_pid
    attributed: dict[Worktree, list[tuple[int, str]]] = {
        worktree: [] for worktree in worktrees
    }
    longest_first = sorted(
        worktrees,
        key=lambda worktree: len(os.fsencode(worktree.path)),
        reverse=True,
    )
    for pid, cwd in cwd_processes:
        if pid == own_pid:
            continue
        normalized_cwd = _normalized_absolute_path(cwd)
        for worktree in longest_first:
            target = _normalized_absolute_path(worktree.path)
            if normalized_cwd == target or normalized_cwd.is_relative_to(target):
                attributed[worktree].append((pid, f"cwd={cwd}"))
                break
    return attributed


def running_processes(repo: Path, worktree: Worktree) -> list[tuple[int, str]]:
    worktrees = discover_worktrees(repo)
    commands = attribute_processes(worktrees, process_table()).get(worktree, [])
    cwd_processes = attribute_process_cwds(worktrees, _process_cwds()).get(worktree, [])
    seen = {pid for pid, _command in commands}
    return commands + [process for process in cwd_processes if process[0] not in seen]


def _primary_worktree(worktrees: Sequence[Worktree]) -> Worktree:
    primary = next((worktree for worktree in worktrees if worktree.primary), None)
    if primary is None:
        raise LifecycleError("primary checkout not found")
    return primary


def _git_common_dir(repo: Path) -> Path:
    result = _git(
        repo,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    return Path(result.stdout.removesuffix("\n"))


def review_operation_lock_path(repo: Path) -> Path:
    return _git_common_dir(repo) / REVIEW_OPERATION_LOCK


def worktree_operation_lock_path(repo: Path, worktree: Path) -> Path:
    normalized = _normalized_absolute_path(worktree)
    digest = hashlib.sha256(os.fsencode(normalized)).hexdigest()
    return _git_common_dir(repo) / f"pgrep-worktree-{digest}.lock"


@dataclass(frozen=True)
class LockOwnership:
    lock_path: Path
    token: str
    owner_path: Path
    owner_record: str

    def release(self) -> None:
        """Release only this exact token; never disturb a reacquired lock."""
        try:
            if self.owner_path.read_text(encoding="utf8") != self.owner_record:
                return
            self.owner_path.unlink()
            self.lock_path.rmdir()
        except OSError:
            # A missing/reacquired/modified lock belongs to nobody we can safely
            # identify. Leave it in place so future operations fail closed.
            return


def _existing_lock_detail(lock: Path) -> str:
    try:
        owners = sorted(
            (
                path
                for path in lock.iterdir()
                if path.name == "owner" or path.name.startswith("owner.")
            ),
            key=lambda path: path.name,
        )
    except OSError:
        return "owner unknown"
    for owner in owners:
        try:
            return owner.read_text(encoding="utf8").strip() or "owner unknown"
        except OSError:
            continue
    return "owner unknown"


@contextmanager
def _operation_lock(
    lock: Path, operation: str, purpose: str
) -> Iterator[LockOwnership]:
    try:
        lock.mkdir()
    except FileExistsError as error:
        detail = _existing_lock_detail(lock)
        raise LifecycleError(
            f"active {purpose} lock at {lock} ({detail}); stop the owner, "
            "or if the lock is stale, verify no lifecycle operation is running "
            "before removing the lock manually"
        ) from error

    token = secrets.token_hex(16)
    record = f"{operation} pid={os.getpid()} token={token}\n"
    ownership = LockOwnership(
        lock_path=lock,
        token=token,
        owner_path=lock / f"owner.{token}",
        owner_record=record,
    )
    try:
        ownership.owner_path.write_text(record, encoding="utf8")
        yield ownership
    finally:
        ownership.release()


@contextmanager
def review_operation_lock(repo: Path, operation: str) -> Iterator[LockOwnership]:
    with _operation_lock(
        review_operation_lock_path(repo), operation, "review operation"
    ) as ownership:
        yield ownership


@contextmanager
def worktree_operation_lock(
    repo: Path,
    worktree: Path,
    operation: str,
) -> Iterator[LockOwnership]:
    with _operation_lock(
        worktree_operation_lock_path(repo, worktree),
        operation,
        "worktree lifecycle operation",
    ) as ownership:
        yield ownership


def _select_worktrees(
    worktrees: Sequence[Worktree],
    targets: Sequence[str],
    *,
    cwd: Path,
) -> list[Worktree]:
    selected: list[Worktree] = []
    for target in targets:
        target_path = Path(target)
        if not target_path.is_absolute():
            target_path = cwd / target_path
        normalized_target = _normalized_absolute_path(target_path)
        match = next(
            (
                worktree
                for worktree in worktrees
                if worktree.branch == target
                or _normalized_absolute_path(worktree.path) == normalized_target
            ),
            None,
        )
        if match is None:
            raise LifecycleError(f"unknown worktree branch or path: {target}")
        if match not in selected:
            selected.append(match)
    return selected


def trim_worktrees(worktrees: Sequence[Worktree]) -> None:
    """Run the primary checkout's cleaner in selected stopped worktrees."""
    if not worktrees:
        return
    repo = worktrees[0].path
    for worktree in worktrees:
        if processes := running_processes(repo, worktree):
            pid_list = ", ".join(str(pid) for pid, _command in processes)
            raise LifecycleError(
                f"{worktree.path} has running processes (PIDs {pid_list})"
            )

    discovered = discover_worktrees(repo)
    primary = _primary_worktree(discovered)
    cleaner = primary.path / "tools" / "clean"
    if not cleaner.is_file():
        raise LifecycleError(f"cleaner not found: {cleaner}")
    with ExitStack() as locks:
        for worktree in sorted(worktrees, key=lambda item: os.fsencode(item.path)):
            locks.enter_context(
                worktree_operation_lock(primary.path, worktree.path, "trim")
            )

        # Repeat after all target locks are held, preserving all-or-none trim.
        for worktree in worktrees:
            if processes := running_processes(primary.path, worktree):
                pid_list = ", ".join(str(pid) for pid, _command in processes)
                raise LifecycleError(
                    f"{worktree.path} has running processes after lock acquisition "
                    f"(PIDs {pid_list})"
                )
        for worktree in worktrees:
            subprocess.run(
                [str(cleaner), "keep-env"],
                cwd=worktree.path,
                check=True,
            )


def prune_eligibility(repo: Path, worktree: Worktree) -> tuple[bool, str]:
    if worktree.primary:
        return False, "primary checkout"
    if worktree.branch is None:
        return False, "detached"
    if worktree.branch == "review":
        return False, "use review-clean (operation lock required)"
    if is_dirty(worktree):
        return False, "dirty"
    if running_processes(repo, worktree):
        return False, "running"
    if not branch_merged(repo, worktree.branch):
        return False, "unmerged"
    if reason := _ignored_private_reason(worktree):
        return False, reason
    direct_branch = _direct_head_branch(worktree)
    if direct_branch != worktree.branch:
        return (
            False,
            f"symbolic branch chain ({direct_branch or '(detached)'} resolves "
            f"as {worktree.branch})",
        )
    return True, "eligible"


@dataclass(frozen=True)
class RemovalPreflight:
    primary: Worktree
    worktree: Worktree
    ref_snapshot: RefSnapshot

    def check(self) -> None:
        """Repeat every mutable deletion guard while its operation lock is held."""
        self.ref_snapshot.revalidate(self.primary.path)
        if is_dirty(self.worktree):
            raise LifecycleError(f"{self.worktree.path} became dirty before removal")
        if processes := running_processes(self.primary.path, self.worktree):
            pid_list = ", ".join(str(pid) for pid, _command in processes)
            raise LifecycleError(
                f"{self.worktree.path} has running processes before removal "
                f"(PIDs {pid_list})"
            )
        if reason := _ignored_private_reason(self.worktree):
            raise LifecycleError(f"{self.worktree.path} has {reason} before removal")


def _remove_worktree(
    preflight: RemovalPreflight,
) -> None:
    """Safely remove a worktree after a final state check."""
    deinit = _git(
        preflight.worktree.path,
        "submodule",
        "deinit",
        "--all",
        check=False,
    )
    if deinit.returncode:
        detail = deinit.stderr.strip() or "git submodule deinit refused"
        raise LifecycleError(
            f"{preflight.worktree.path} submodule deinit failed: {detail}"
        )

    # This check is intentionally adjacent to Git's non-forced removal. The
    # operation lock has been held since the earlier destructive preflight.
    preflight.check()
    try:
        _git(
            preflight.primary.path,
            "worktree",
            "remove",
            str(preflight.worktree.path),
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if error.stderr else str(error)
        raise LifecycleError(
            f"git refused to remove {preflight.worktree.path}: {detail}"
        ) from error


def prune_worktrees(
    repo: Path,
    *,
    apply: bool = False,
    worktrees: Sequence[Worktree] | None = None,
) -> list[str]:
    """Report removable worktrees and optionally remove eligible ones."""
    discovered = list(worktrees) if worktrees is not None else discover_worktrees(repo)
    primary = _primary_worktree(discovered)
    results = [
        (worktree, *prune_eligibility(primary.path, worktree))
        for worktree in discovered
    ]
    snapshots: dict[Worktree, RefSnapshot] = {}
    if apply:
        validated_results: list[tuple[Worktree, bool, str]] = []
        for worktree, eligible, reason in results:
            if eligible:
                assert worktree.branch is not None
                try:
                    snapshots[worktree] = RefSnapshot.capture(
                        primary.path,
                        worktree.branch,
                        require_main=True,
                    )
                except LifecycleError as error:
                    eligible = False
                    reason = str(error)
            validated_results.append((worktree, eligible, reason))
        results = validated_results
    lines = [
        f"{worktree.branch or '(detached)'}: {reason} {worktree.path}"
        for worktree, _eligible, reason in results
    ]
    if not apply:
        return lines

    removable = [worktree for worktree, eligible, _reason in results if eligible]
    with ExitStack() as locks:
        for worktree in sorted(removable, key=lambda item: os.fsencode(item.path)):
            locks.enter_context(
                worktree_operation_lock(primary.path, worktree.path, "prune")
            )

        preflights: list[RemovalPreflight] = []
        for worktree in removable:
            eligible, reason = prune_eligibility(primary.path, worktree)
            if not eligible:
                raise LifecycleError(
                    f"{worktree.path} became unsafe after lock acquisition: {reason}"
                )
            snapshot = snapshots[worktree]
            preflight = RemovalPreflight(primary, worktree, snapshot)
            preflight.check()
            preflights.append(preflight)

        for preflight in preflights:
            _remove_worktree(preflight)
            preflight.ref_snapshot.delete(primary.path)
        _git(primary.path, "worktree", "prune")
    return lines


def review_clean(
    repo: Path,
    *,
    worktrees: Sequence[Worktree] | None = None,
) -> str:
    """Remove the disposable review worktree without requiring a merge."""
    initial = list(worktrees) if worktrees is not None else discover_worktrees(repo)
    primary = _primary_worktree(initial)
    with review_operation_lock(primary.path, "review-clean"):
        discovered = (
            list(worktrees)
            if worktrees is not None
            else discover_worktrees(primary.path)
        )
        primary = _primary_worktree(discovered)
        expected_path = _normalized_absolute_path(
            primary.path / ".worktrees" / "review"
        )
        review = next(
            (
                worktree
                for worktree in discovered
                if _normalized_absolute_path(worktree.path) == expected_path
            ),
            None,
        )
        branch_review = next(
            (worktree for worktree in discovered if worktree.branch == "review"),
            None,
        )
        if review is None:
            if branch_review is None:
                return "review: not found"
            raise LifecycleError(
                f"refusing review checkout outside expected path {expected_path}: "
                f"{branch_review.path}"
            )
        if review.primary:
            raise LifecycleError("refusing to remove primary review checkout")

        with worktree_operation_lock(primary.path, review.path, "review-clean"):
            snapshot = RefSnapshot.capture(
                primary.path,
                "review",
                require_main=False,
            )
            if review.branch != "review":
                raise LifecycleError(
                    f"refusing expected review path checked out on "
                    f"{review.branch or '(detached)'}"
                )
            preflight = RemovalPreflight(primary, review, snapshot)
            preflight.check()
            _remove_worktree(preflight)
            snapshot.delete(primary.path)
            _git(primary.path, "worktree", "prune")
            return f"review: removed {review.path}"


def _format_size(size: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(size)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.1f}{unit}"


def status_lines(repo: Path) -> list[str]:
    worktrees = discover_worktrees(repo)
    if not worktrees:
        return []
    process_map = attribute_processes(worktrees, process_table())
    primary = next(
        (worktree for worktree in worktrees if worktree.primary), worktrees[0]
    )
    lines: list[str] = []
    for worktree in worktrees:
        branch = worktree.branch or "(detached)"
        clean_state = "dirty" if is_dirty(worktree) else "clean"
        if worktree.primary:
            merge_state = "primary"
        elif worktree.branch and branch_merged(primary.path, worktree.branch):
            merge_state = "merged"
        else:
            merge_state = "unmerged"
        process_state = "running" if process_map[worktree] else "stopped"
        descendants = [
            candidate.path
            for candidate in worktrees
            if candidate != worktree and candidate.path.is_relative_to(worktree.path)
        ]
        total = _format_size(checkout_size(worktree.path, descendants))
        build = _format_size(build_size(worktree.path))
        lines.append(
            f"{branch} {clean_state} {merge_state} {process_state} "
            f"total={total} build={build} {worktree.path}"
        )
    return lines


def _available_bytes(repo: Path) -> int:
    override = os.environ.get("PGREP_REVIEW_AVAILABLE_BYTES")
    if override is not None:
        return int(override)
    worktrees = discover_worktrees(repo)
    primary = next((worktree for worktree in worktrees if worktree.primary), None)
    disk_path = primary.path if primary else repo
    return shutil.disk_usage(disk_path).free


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="report registered worktree state")
    trim = commands.add_parser("trim", help="clean selected stopped worktrees")
    trim.add_argument("targets", nargs="+", metavar="BRANCH_OR_PATH")
    prune = commands.add_parser("prune", help="report safely removable worktrees")
    prune.add_argument(
        "--apply",
        action="store_true",
        help="remove eligible worktrees (default: dry run)",
    )
    commands.add_parser("review-clean", help="remove the disposable review worktree")
    commands.add_parser(
        "review-disk-guard", help="warn or refuse review builds when disk is low"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = Path.cwd()
    try:
        if args.command == "status":
            for line in status_lines(repo):
                print(line)
            return 0
        if args.command == "trim":
            worktrees = discover_worktrees(repo)
            selected = _select_worktrees(worktrees, args.targets, cwd=repo)
            trim_worktrees(selected)
            for worktree in selected:
                print(f"trimmed {worktree.branch or '(detached)'} {worktree.path}")
            return 0
        if args.command == "prune":
            for line in prune_worktrees(repo, apply=args.apply):
                print(line)
            return 0
        if args.command == "review-clean":
            print(review_clean(repo))
            return 0
    except LifecycleError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    code, message = review_disk_guard(_available_bytes(repo))
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
