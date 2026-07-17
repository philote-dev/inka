#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Inspect, trim, and safely remove pgrep worktrees."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    primary: bool


class LifecycleError(RuntimeError):
    """Raised when a requested worktree operation is unsafe."""


def parse_worktree_porcelain(output: str) -> list[Worktree]:
    """Parse ``git worktree list --porcelain`` output."""
    worktrees: list[Worktree] = []
    for record in output.split("\n\n"):
        path: Path | None = None
        branch: str | None = None
        for line in record.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                path = Path(value)
            elif key == "branch":
                branch = value.removeprefix("refs/heads/")
        if path is not None:
            worktrees.append(Worktree(path=path, branch=branch, primary=not worktrees))
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


def discover_worktrees(repo: Path) -> list[Worktree]:
    result = _git(repo, "worktree", "list", "--porcelain")
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


def running_processes(repo: Path, worktree: Worktree) -> list[tuple[int, str]]:
    worktrees = discover_worktrees(repo)
    return attribute_processes(worktrees, process_table()).get(worktree, [])


def _primary_worktree(worktrees: Sequence[Worktree]) -> Worktree:
    primary = next((worktree for worktree in worktrees if worktree.primary), None)
    if primary is None:
        raise LifecycleError("primary checkout not found")
    return primary


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
    if is_dirty(worktree):
        return False, "dirty"
    if running_processes(repo, worktree):
        return False, "running"
    if not branch_merged(repo, worktree.branch):
        return False, "unmerged"
    return True, "eligible"


def _remove_worktree(primary: Worktree, worktree: Worktree) -> None:
    """Safely remove a worktree after a final state check."""
    deinit = _git(
        worktree.path,
        "submodule",
        "deinit",
        "--all",
        check=False,
    )
    if deinit.returncode:
        detail = deinit.stderr.strip() or "git submodule deinit refused"
        raise LifecycleError(f"{worktree.path} submodule deinit failed: {detail}")

    if is_dirty(worktree):
        raise LifecycleError(f"{worktree.path} became dirty before removal")
    if processes := running_processes(primary.path, worktree):
        pid_list = ", ".join(str(pid) for pid, _command in processes)
        raise LifecycleError(
            f"{worktree.path} has running processes before removal (PIDs {pid_list})"
        )

    try:
        _git(primary.path, "worktree", "remove", str(worktree.path))
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if error.stderr else str(error)
        raise LifecycleError(
            f"git refused to remove {worktree.path}: {detail}"
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
    lines = [
        f"{worktree.branch or '(detached)'}: {reason} {worktree.path}"
        for worktree, _eligible, reason in results
    ]
    if not apply:
        return lines

    for worktree, eligible, _reason in results:
        if not eligible:
            continue
        assert worktree.branch is not None
        _remove_worktree(primary, worktree)
        _git(primary.path, "branch", "-d", worktree.branch)
    _git(primary.path, "worktree", "prune")
    return lines


def review_clean(
    repo: Path,
    *,
    worktrees: Sequence[Worktree] | None = None,
) -> str:
    """Remove the disposable review worktree without requiring a merge."""
    discovered = list(worktrees) if worktrees is not None else discover_worktrees(repo)
    review = next(
        (worktree for worktree in discovered if worktree.branch == "review"),
        None,
    )
    if review is None:
        return "review: not found"
    primary = _primary_worktree(discovered)
    if review.primary:
        raise LifecycleError("refusing to remove primary review checkout")
    expected_path = _normalized_absolute_path(primary.path / ".worktrees" / "review")
    if _normalized_absolute_path(review.path) != expected_path:
        raise LifecycleError(
            f"refusing review checkout outside expected path {expected_path}: "
            f"{review.path}"
        )
    if is_dirty(review):
        raise LifecycleError(f"{review.path} is dirty")
    if processes := running_processes(repo, review):
        pid_list = ", ".join(str(pid) for pid, _command in processes)
        raise LifecycleError(f"{review.path} has running processes (PIDs {pid_list})")

    _remove_worktree(primary, review)
    _git(primary.path, "branch", "-D", "review")
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
