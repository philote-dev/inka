#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Report pgrep worktree state and guard review builds from low disk space."""

from __future__ import annotations

import argparse
import os
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
            worktrees.append(
                Worktree(path=path, branch=branch, primary=not worktrees)
            )
    return worktrees


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
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


def _tree_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        directories[:] = [
            directory
            for directory in directories
            if not (root_path / directory).is_symlink()
        ]
        for filename in files:
            candidate = root_path / filename
            if not candidate.is_symlink():
                try:
                    total += candidate.stat().st_size
                except FileNotFoundError:
                    pass
    return total


def checkout_size(path: Path) -> int:
    return _tree_size(path)


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
        "HEAD",
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
            if str(worktree.path) in command:
                attributed[worktree].append((pid, command))
                break
    return attributed


def running_processes(repo: Path, worktree: Worktree) -> list[tuple[int, str]]:
    worktrees = discover_worktrees(repo)
    return attribute_processes(worktrees, process_table()).get(worktree, [])


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
    primary = next((worktree for worktree in worktrees if worktree.primary), worktrees[0])
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
        total = _format_size(checkout_size(worktree.path))
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
    commands.add_parser(
        "status", help="report registered worktree state"
    )
    commands.add_parser(
        "review-disk-guard", help="warn or refuse review builds when disk is low"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = Path.cwd()
    if args.command == "status":
        for line in status_lines(repo):
            print(line)
        return 0

    code, message = review_disk_guard(_available_bytes(repo))
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
