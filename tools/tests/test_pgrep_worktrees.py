# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tools import pgrep_worktrees as module
from tools.pgrep_worktrees import (
    Worktree,
    attribute_processes,
    branch_merged,
    build_size,
    checkout_size,
    is_dirty,
    main,
    parse_worktree_porcelain,
    review_disk_guard,
    status_lines,
)

PORCELAIN = """\
worktree /repo
HEAD 1111111111111111111111111111111111111111
branch refs/heads/main

worktree /repo/.worktrees/demo
HEAD 2222222222222222222222222222222222222222
branch refs/heads/feat/demo

worktree /repo/.worktrees/detached
HEAD 3333333333333333333333333333333333333333
detached
"""


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Lifecycle Test",
            "-c",
            "user.email=lifecycle@example.invalid",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def committed_repo(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-b", "main")
    (path / "tracked.txt").write_text("base", encoding="utf8")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-m", "base")
    return path


def add_worktree(repo: Path, path: Path, branch: str) -> Path:
    git(repo, "branch", branch)
    git(repo, "worktree", "add", str(path), branch)
    return path


def test_parse_worktrees_marks_primary_and_detached() -> None:
    parsed = parse_worktree_porcelain(PORCELAIN)

    assert parsed[0].primary is True
    assert parsed[1].branch == "feat/demo"
    assert parsed[2].branch is None


@pytest.mark.parametrize(
    ("gib", "code", "fragment"),
    [(31, 0, ""), (29, 0, "LOW DISK"), (9, 2, "REFUSING REVIEW BUILD")],
)
def test_review_disk_guard_thresholds(gib: int, code: int, fragment: str) -> None:
    actual_code, message = review_disk_guard(gib * 1024**3)

    assert actual_code == code
    assert fragment in message


def test_review_disk_guard_messages_name_lifecycle_commands() -> None:
    _, message = review_disk_guard(9 * 1024**3)

    assert (
        "Run `just worktree-status`, `just worktree-trim <branch-or-path>`, "
        "or `just review-clean`." in message
    )


def test_size_reporting_counts_files_and_only_out_as_build(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.bin").write_bytes(b"src")
    out = tmp_path / "out"
    out.mkdir()
    (out / "build.bin").write_bytes(b"build")
    (tmp_path / "linked-build").symlink_to(out, target_is_directory=True)

    assert checkout_size(tmp_path) == 8
    assert build_size(tmp_path) == 5


def test_status_size_excludes_registered_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "primary.bin").write_bytes(b"main")
    descendant = tmp_path / ".worktrees" / "feature"
    descendant.mkdir(parents=True)
    (descendant / "feature.bin").write_bytes(b"branch")
    primary = Worktree(tmp_path, "main", True)
    feature = Worktree(descendant, "feature", False)
    monkeypatch.setattr(module, "discover_worktrees", lambda _repo: [primary, feature])
    monkeypatch.setattr(module, "is_dirty", lambda _worktree: False)
    monkeypatch.setattr(module, "branch_merged", lambda _repo, _branch: False)
    monkeypatch.setattr(module, "process_table", lambda: [])

    lines = status_lines(tmp_path)

    assert "total=4.0B" in lines[0]
    assert "total=6.0B" in lines[1]


def test_dirty_and_merge_reporting_uses_git_state(tmp_path: Path) -> None:
    repo = committed_repo(tmp_path / "repo")
    git(repo, "branch", "merged")
    git(repo, "switch", "-c", "unmerged")
    (repo / "branch.txt").write_text("branch", encoding="utf8")
    git(repo, "add", "branch.txt")
    git(repo, "commit", "-m", "unmerged")
    git(repo, "switch", "main")
    worktree = Worktree(repo, "main", True)

    assert is_dirty(worktree) is False
    assert branch_merged(repo, "merged") is True
    assert branch_merged(repo, "unmerged") is False

    (repo / "untracked.txt").write_text("dirty", encoding="utf8")
    assert is_dirty(worktree) is True


def test_processes_use_longest_worktree_path_and_exclude_self() -> None:
    primary = Worktree(Path("/repo"), "main", True)
    review = Worktree(Path("/repo/.worktrees/review"), "review", False)
    processes = [
        (100, "python /repo/.worktrees/review/tools/pgrep_worktrees.py status"),
        (101, "python /repo/.worktrees/review/app.py"),
        (102, "python /repo/app.py"),
        (103, "python /elsewhere/app.py"),
    ]

    attributed = attribute_processes([primary, review], processes, own_pid=100)

    assert attributed[primary] == [(102, "python /repo/app.py")]
    assert attributed[review] == [(101, "python /repo/.worktrees/review/app.py")]


def test_processes_do_not_match_similarly_prefixed_path() -> None:
    primary = Worktree(Path("/repo"), "main", True)

    attributed = attribute_processes(
        [primary],
        [(104, "python /repo-copy/app.py")],
        own_pid=100,
    )

    assert attributed[primary] == []


def test_status_prints_every_inventory_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = Worktree(Path("/repo"), "main", True)
    feature = Worktree(Path("/repo/.worktrees/demo"), "feat/demo", False)
    monkeypatch.setattr(module, "discover_worktrees", lambda _repo: [primary, feature])
    monkeypatch.setattr(module, "is_dirty", lambda wt: wt == feature)
    monkeypatch.setattr(
        module, "branch_merged", lambda _repo, branch: branch == "feat/demo"
    )
    monkeypatch.setattr(
        module,
        "process_table",
        lambda: [(123, "python /repo/.worktrees/demo/app.py")],
    )
    monkeypatch.setattr(module, "checkout_size", lambda wt, *_excluded: 2 * 1024**3)
    monkeypatch.setattr(module, "build_size", lambda wt: 512 * 1024**2)

    lines = status_lines(Path("/repo"))

    assert len(lines) == 2
    assert lines[0].split() == [
        "main",
        "clean",
        "primary",
        "stopped",
        "total=2.0GiB",
        "build=512.0MiB",
        "/repo",
    ]
    assert lines[1].split() == [
        "feat/demo",
        "dirty",
        "merged",
        "running",
        "total=2.0GiB",
        "build=512.0MiB",
        "/repo/.worktrees/demo",
    ]


def test_disk_guard_cli_uses_available_bytes_override(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PGREP_REVIEW_AVAILABLE_BYTES", str(9 * 1024**3))

    assert main(["review-disk-guard"]) == 2
    assert "REFUSING REVIEW BUILD" in capsys.readouterr().err


def test_prune_defaults_to_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = committed_repo(tmp_path / "repo")
    worktree = add_worktree(repo, tmp_path / "merged", "merged")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune"]) == 0

    assert "eligible" in capsys.readouterr().out
    assert worktree.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/merged").returncode == 0


def test_prune_apply_removes_only_clean_merged_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    worktree = add_worktree(repo, tmp_path / "merged", "merged")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert not worktree.exists()
    branch = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/merged"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert branch.returncode != 0


def test_prune_compares_merges_to_primary_when_run_from_secondary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    caller = add_worktree(repo, tmp_path / "caller", "caller")
    (caller / "caller.txt").write_text("caller", encoding="utf8")
    git(caller, "add", "caller.txt")
    git(caller, "commit", "-m", "caller advance")
    (repo / "main.txt").write_text("main", encoding="utf8")
    git(repo, "add", "main.txt")
    git(repo, "commit", "-m", "main advance")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    monkeypatch.chdir(caller)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert not candidate.exists()
    assert caller.exists()


@pytest.mark.parametrize(
    ("worktree", "dirty", "running", "merged", "reason"),
    [
        (Worktree(Path("/repo"), "main", True), False, False, True, "primary"),
        (
            Worktree(Path("/repo/detached"), None, False),
            False,
            False,
            True,
            "detached",
        ),
        (
            Worktree(Path("/repo/dirty"), "dirty", False),
            True,
            False,
            True,
            "dirty",
        ),
        (
            Worktree(Path("/repo/running"), "running", False),
            False,
            True,
            True,
            "running",
        ),
        (
            Worktree(Path("/repo/unmerged"), "unmerged", False),
            False,
            False,
            False,
            "unmerged",
        ),
    ],
)
def test_prune_eligibility_rejects_unsafe_worktrees(
    worktree: Worktree,
    dirty: bool,
    running: bool,
    merged: bool,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "is_dirty", lambda _worktree: dirty)
    monkeypatch.setattr(
        module,
        "running_processes",
        lambda _repo, _worktree: [(123, "app")] if running else [],
    )
    monkeypatch.setattr(module, "branch_merged", lambda _repo, _branch: merged)

    eligible, actual_reason = module.prune_eligibility(Path("/repo"), worktree)

    assert eligible is False
    assert reason in actual_reason


def test_trim_runs_primary_cleaner_in_selected_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    tools = repo / "tools"
    tools.mkdir()
    cleaner = tools / "clean"
    cleaner.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$PWD" > "$PGREP_TEST_LOG"\n'
        'printf "%s\\n" "$@" >> "$PGREP_TEST_LOG"\n',
        encoding="utf8",
    )
    cleaner.chmod(0o755)
    git(repo, "add", "tools/clean")
    git(repo, "commit", "-m", "add cleaner")
    worktree = add_worktree(repo, tmp_path / "feature", "feature")
    log = tmp_path / "clean.log"
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PGREP_TEST_LOG", str(log))
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["trim", "feature"]) == 0

    assert log.read_text(encoding="utf8").splitlines() == [
        str(worktree),
        "keep-env",
    ]


def test_trim_refuses_running_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = Worktree(tmp_path, "feature", False)
    monkeypatch.setattr(module, "running_processes", lambda *_args: [(123, "app")])

    with pytest.raises(module.LifecycleError, match="running"):
        module.trim_worktrees([worktree])


def test_review_clean_removes_clean_unmerged_review_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    git(repo, "switch", "-c", "review")
    (repo / "review.txt").write_text("review", encoding="utf8")
    git(repo, "add", "review.txt")
    git(repo, "commit", "-m", "review")
    git(repo, "switch", "main")
    worktree = tmp_path / "review"
    git(repo, "worktree", "add", str(worktree), "review")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["review-clean"]) == 0

    assert not worktree.exists()
    branch = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/review"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert branch.returncode != 0


@pytest.mark.parametrize("unsafe_state", ["dirty", "running"])
def test_review_clean_refuses_unsafe_review_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_state: str,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    worktree_path = add_worktree(repo, tmp_path / "review", "review")
    worktree = Worktree(worktree_path, "review", False)
    monkeypatch.setattr(module, "is_dirty", lambda _worktree: unsafe_state == "dirty")
    monkeypatch.setattr(
        module,
        "running_processes",
        lambda _repo, _worktree: ([(123, "app")] if unsafe_state == "running" else []),
    )

    with pytest.raises(module.LifecycleError, match=unsafe_state):
        module.review_clean(repo, worktrees=[Worktree(repo, "main", True), worktree])

    assert worktree_path.exists()


def test_temporary_repo_helper_does_not_write_git_config(tmp_path: Path) -> None:
    repo = committed_repo(tmp_path / "repo")

    assert (
        not (repo / ".git" / "config")
        .read_text(encoding="utf8")
        .count("Lifecycle Test")
    )
    assert "lifecycle@example.invalid" not in (repo / ".git" / "config").read_text(
        encoding="utf8"
    )


def test_module_uses_only_stdlib_runtime_imports() -> None:
    source = Path(module.__file__).read_text(encoding="utf8")
    imported_roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            assert node.module is not None
            imported_roots.add(node.module.partition(".")[0])

    assert imported_roots <= sys.stdlib_module_names
