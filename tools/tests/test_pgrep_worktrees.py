# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from __future__ import annotations

import ast
import json
import os
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

PORCELAIN = (
    "worktree /repo\0"
    "HEAD 1111111111111111111111111111111111111111\0"
    "branch refs/heads/main\0\0"
    "worktree /repo/.worktrees/demo\0"
    "HEAD 2222222222222222222222222222222222222222\0"
    "branch refs/heads/feat/demo\0\0"
    "worktree /repo/.worktrees/detached\0"
    "HEAD 3333333333333333333333333333333333333333\0"
    "detached\0\0"
)


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


def test_parse_worktrees_preserves_newline_in_nul_delimited_path() -> None:
    output = (
        "worktree /repo\nwith-newline\0"
        "HEAD 1111111111111111111111111111111111111111\0"
        "branch refs/heads/main\0\0"
    )

    parsed = parse_worktree_porcelain(output)

    assert parsed == [Worktree(Path("/repo\nwith-newline"), "main", True)]


def test_discover_worktrees_requests_nul_delimited_porcelain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(
        _repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            ["git", *args], returncode=0, stdout=PORCELAIN, stderr=""
        )

    monkeypatch.setattr(module, "_git", fake_git)

    discovered = module.discover_worktrees(Path("/repo"))

    assert len(discovered) == 3
    assert calls == [("worktree", "list", "--porcelain", "-z")]


@pytest.mark.parametrize(
    ("gib", "code", "fragment"),
    [
        (30, 0, ""),
        (10, 0, "LOW DISK"),
        (9, 2, "REFUSING REVIEW BUILD"),
    ],
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


def test_processes_match_unquoted_absolute_executable_path_with_spaces() -> None:
    primary = Worktree(Path("/repo with spaces"), "main", True)
    review = Worktree(
        Path("/repo with spaces/.worktrees/review with spaces"), "review", False
    )
    command = "/repo with spaces/.worktrees/review with spaces/run --flag"

    attributed = attribute_processes(
        [primary, review],
        [(104, command)],
        own_pid=100,
    )

    assert attributed[primary] == []
    assert attributed[review] == [(104, command)]


def test_review_dashboard_launches_absolute_worktree_run_path() -> None:
    source = Path(module.__file__).with_name("pgrep-review").read_text(encoding="utf8")

    assert '[str(Path(path) / "run")]' in source
    assert '["./run"]' not in source


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


@pytest.mark.parametrize("repo_name", ["repo with spaces", "repo\nwith newline"])
def test_review_sync_checks_disk_before_review_mutation_in_unusual_path(
    tmp_path: Path,
    repo_name: str,
) -> None:
    repo = committed_repo(tmp_path / repo_name)
    tools = repo / "tools"
    tools.mkdir()
    worktree_cli = tools / "pgrep_worktrees.py"
    worktree_cli.write_text(
        Path(module.__file__).read_text(encoding="utf8"), encoding="utf8"
    )
    worktree_cli.chmod(0o755)
    sync_script = tools / "pgrep-sync-review"
    source_script = Path(module.__file__).with_name("pgrep-sync-review")
    sync_script.write_text(source_script.read_text(encoding="utf8"), encoding="utf8")
    sync_script.chmod(0o755)
    env = os.environ.copy()
    env["PGREP_REVIEW_AVAILABLE_BYTES"] = str(9 * 1024**3)

    result = subprocess.run(
        [str(sync_script)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 75
    assert "REFUSING REVIEW BUILD" in result.stderr
    review_branch = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/review"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert review_branch.returncode != 0
    assert not (repo / ".worktrees" / "review").exists()


def test_review_sync_uses_common_dir_for_primary_root() -> None:
    sync_source = (
        Path(module.__file__).with_name("pgrep-sync-review").read_text(encoding="utf8")
    )
    just_source = Path("justfile").read_text(encoding="utf8")

    assert "rev-parse --path-format=absolute --git-common-dir" in sync_source
    assert "worktree list --porcelain" not in sync_source
    assert 'mkdir "$REVIEW_LOCK"' in sync_source
    assert "trap release_review_lock EXIT" in sync_source
    assert "rev-parse --path-format=absolute --git-common-dir" in just_source


def test_review_sync_refuses_existing_review_operation_lock(
    tmp_path: Path,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    tools = repo / "tools"
    tools.mkdir()
    worktree_cli = tools / "pgrep_worktrees.py"
    worktree_cli.write_text(
        Path(module.__file__).read_text(encoding="utf8"), encoding="utf8"
    )
    worktree_cli.chmod(0o755)
    sync_script = tools / "pgrep-sync-review"
    source_script = Path(module.__file__).with_name("pgrep-sync-review")
    sync_script.write_text(source_script.read_text(encoding="utf8"), encoding="utf8")
    sync_script.chmod(0o755)
    lock = repo / ".git" / "pgrep-review-operation.lock"
    lock.mkdir()
    (lock / "owner").write_text(
        f"review-clean pid={os.getpid()}\n",
        encoding="utf8",
    )
    env = os.environ.copy()
    env["PGREP_REVIEW_AVAILABLE_BYTES"] = str(30 * 1024**3)

    result = subprocess.run(
        [str(sync_script)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "review-clean" in result.stderr
    assert "active" in result.stderr.lower()
    assert lock.exists()
    assert not (repo / ".worktrees" / "review").exists()
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/review"],
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        != 0
    )


def test_review_sync_releases_operation_lock_after_success(
    tmp_path: Path,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    tools = repo / "tools"
    tools.mkdir()
    worktree_cli = tools / "pgrep_worktrees.py"
    worktree_cli.write_text(
        Path(module.__file__).read_text(encoding="utf8"), encoding="utf8"
    )
    worktree_cli.chmod(0o755)
    sync_script = tools / "pgrep-sync-review"
    source_script = Path(module.__file__).with_name("pgrep-sync-review")
    sync_script.write_text(source_script.read_text(encoding="utf8"), encoding="utf8")
    sync_script.chmod(0o755)
    env = os.environ.copy()
    env["PGREP_REVIEW_AVAILABLE_BYTES"] = str(30 * 1024**3)

    result = subprocess.run(
        [str(sync_script), "main"],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not (repo / ".git" / "pgrep-review-operation.lock").exists()


def test_review_sync_recipe_retries_two_and_maps_only_internal_75_to_two(
    tmp_path: Path,
) -> None:
    root = committed_repo(tmp_path / "repo with spaces")
    tools = root / "tools"
    tools.mkdir()
    counter = tmp_path / "calls"
    args_log = tmp_path / "args"
    fake_sync = tools / "pgrep-sync-review"
    fake_sync.write_text(
        "#!/bin/sh\n"
        'printf "%s\\0" "$@" > "$PGREP_TEST_ARGS"\n'
        'count=$(($(cat "$PGREP_TEST_COUNTER" 2>/dev/null || printf 0) + 1))\n'
        'printf "%s" "$count" > "$PGREP_TEST_COUNTER"\n'
        'case "$count" in\n'
        "  1) exit 1 ;;\n"
        "  2) exit 2 ;;\n"
        "  *) exit 75 ;;\n"
        "esac\n",
        encoding="utf8",
    )
    fake_sync.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PGREP_REVIEW_INTERVAL": "0",
            "PGREP_TEST_ARGS": str(args_log),
            "PGREP_TEST_COUNTER": str(counter),
        }
    )
    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(Path("justfile").resolve()),
            "--working-directory",
            str(root),
            "review-sync",
            "branch with spaces",
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert counter.read_text(encoding="utf8") == "3"
    assert result.stdout.count("next sync in 0s") == 2
    assert args_log.read_bytes().split(b"\0") == [
        b"branch with spaces",
        b"",
    ]


def test_justfile_exposes_worktree_lifecycle_recipes() -> None:
    source = Path("justfile").read_text(encoding="utf8")

    assert "worktree-status:\n    ./tools/pgrep_worktrees.py status" in source
    assert (
        "[positional-arguments]\n"
        "worktree-trim *worktrees:\n"
        '    ./tools/pgrep_worktrees.py trim "$@"' in source
    )
    assert (
        "[positional-arguments]\n"
        "worktree-prune *args:\n"
        '    ./tools/pgrep_worktrees.py prune "$@"' in source
    )
    assert "[positional-arguments]\nreview-sync *branches:\n" in source
    assert 'if "$root/tools/pgrep-sync-review" "$@"; then' in source
    assert "review-clean:\n    ./tools/pgrep_worktrees.py review-clean" in source


@pytest.mark.parametrize(
    ("recipe", "command"),
    [("worktree-trim", "trim"), ("worktree-prune", "prune")],
)
def test_justfile_lifecycle_recipes_preserve_argument_boundaries(
    tmp_path: Path,
    recipe: str,
    command: str,
) -> None:
    repo = tmp_path / "repo with spaces"
    tools = repo / "tools"
    tools.mkdir(parents=True)
    log = tmp_path / f"{recipe}.json"
    fake_cli = tools / "pgrep_worktrees.py"
    fake_cli.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        'Path(os.environ["PGREP_TEST_LOG"]).write_text(json.dumps(sys.argv[1:]))\n',
        encoding="utf8",
    )
    fake_cli.chmod(0o755)
    hostile = "branch;$(touch should-not-exist)"
    env = os.environ.copy()
    env["PGREP_TEST_LOG"] = str(log)

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(Path("justfile").resolve()),
            "--working-directory",
            str(repo),
            recipe,
            "branch with spaces",
            hostile,
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(log.read_text(encoding="utf8")) == [
        command,
        "branch with spaces",
        hostile,
    ]
    assert not (repo / "should-not-exist").exists()


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


def test_prune_routes_review_checkout_through_locked_review_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = committed_repo(tmp_path / "repo")
    review = repo / ".worktrees" / "review"
    review.parent.mkdir()
    add_worktree(repo, review, "review")
    lock = repo / ".git" / "pgrep-review-operation.lock"
    lock.mkdir()
    (lock / "owner").write_text(f"sync pid={os.getpid()}\n", encoding="utf8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert "use review-clean" in capsys.readouterr().out
    assert review.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/review").returncode == 0


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


def test_prune_compares_candidate_to_main_when_primary_is_on_feature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    (candidate / "candidate.txt").write_text("candidate", encoding="utf8")
    git(candidate, "add", "candidate.txt")
    git(candidate, "commit", "-m", "candidate")
    git(repo, "switch", "-c", "primary-feature")
    git(repo, "merge", "--no-edit", "candidate")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert "candidate: unmerged" in capsys.readouterr().out
    assert candidate.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_apply_preserves_dirty_and_unmerged_alongside_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    eligible = add_worktree(repo, tmp_path / "eligible", "eligible")
    dirty = add_worktree(repo, tmp_path / "dirty", "dirty")
    (dirty / "untracked.txt").write_text("dirty", encoding="utf8")
    unmerged = add_worktree(repo, tmp_path / "unmerged", "unmerged")
    (unmerged / "unmerged.txt").write_text("unmerged", encoding="utf8")
    git(unmerged, "add", "unmerged.txt")
    git(unmerged, "commit", "-m", "unmerged")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert not eligible.exists()
    assert dirty.exists()
    assert unmerged.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/dirty").returncode == 0
    assert git(repo, "show-ref", "--verify", "refs/heads/unmerged").returncode == 0


@pytest.mark.parametrize(
    ("ignore_pattern", "private_path"),
    [
        ("content/\n", Path("content/private-corpus.json")),
        (".env\n", Path(".env")),
        ("out/\n", Path("out/.env")),
        ("out/\n", Path("out/api-token.txt")),
    ],
)
def test_prune_preserves_ignored_private_data_and_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ignore_pattern: str,
    private_path: Path,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(ignore_pattern, encoding="utf8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore private data")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    ignored = candidate / private_path
    ignored.parent.mkdir(parents=True, exist_ok=True)
    ignored.write_text("private", encoding="utf8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert "ignored private data" in capsys.readouterr().out
    assert candidate.exists()
    assert ignored.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_allows_ignored_disposable_build_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("out/\n", encoding="utf8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore build output")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    output = candidate / "out" / "rust" / "artifact"
    output.parent.mkdir(parents=True)
    output.write_text("build", encoding="utf8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert not candidate.exists()
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/candidate"],
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        != 0
    )


def test_prune_rechecks_ignored_private_data_immediately_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("content/\n", encoding="utf8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore private data")
    candidate_path = add_worktree(repo, tmp_path / "candidate", "candidate")
    candidate = Worktree(candidate_path, "candidate", False)
    process_checks = 0

    def create_private_data_on_final_check(
        _repo: Path, worktree: Worktree
    ) -> list[tuple[int, str]]:
        nonlocal process_checks
        if worktree == candidate:
            process_checks += 1
            if process_checks == 2:
                private = candidate_path / "content" / "late-private.json"
                private.parent.mkdir()
                private.write_text("private", encoding="utf8")
        return []

    monkeypatch.setattr(module, "running_processes", create_private_data_on_final_check)

    with pytest.raises(module.LifecycleError, match="ignored private data"):
        module.prune_worktrees(repo, apply=True)

    assert process_checks == 2
    assert candidate_path.exists()
    assert (candidate_path / "content" / "late-private.json").exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_rechecks_dirty_state_immediately_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate_path = add_worktree(repo, tmp_path / "candidate", "candidate")
    real_is_dirty = module.is_dirty
    checks = 0

    def dirty_on_final_check(worktree: Worktree) -> bool:
        nonlocal checks
        if worktree.path == candidate_path:
            checks += 1
            if checks == 2:
                (candidate_path / "late.txt").write_text("late", encoding="utf8")
        return real_is_dirty(worktree)

    monkeypatch.setattr(module, "is_dirty", dirty_on_final_check)
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match="dirty"):
        module.prune_worktrees(repo, apply=True)

    assert checks == 2
    assert candidate_path.exists()
    assert (candidate_path / "late.txt").exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_detects_ref_movement_before_worktree_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    previous_oid = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "second.txt").write_text("second", encoding="utf8")
    git(repo, "add", "second.txt")
    git(repo, "commit", "-m", "second")
    candidate_path = add_worktree(repo, tmp_path / "candidate", "candidate")
    candidate = Worktree(candidate_path, "candidate", False)
    process_checks = 0

    def move_ref_on_final_check(
        _repo: Path, worktree: Worktree
    ) -> list[tuple[int, str]]:
        nonlocal process_checks
        if worktree == candidate:
            process_checks += 1
            if process_checks == 2:
                git(repo, "update-ref", "refs/heads/candidate", previous_oid)
        return []

    monkeypatch.setattr(module, "running_processes", move_ref_on_final_check)

    with pytest.raises(module.LifecycleError, match="branch moved"):
        module.prune_worktrees(repo, apply=True)

    assert candidate_path.exists()
    assert git(repo, "rev-parse", "refs/heads/candidate").stdout.strip() == previous_oid


def test_prune_compare_delete_preserves_ref_moved_after_worktree_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    previous_oid = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "second.txt").write_text("second", encoding="utf8")
    git(repo, "add", "second.txt")
    git(repo, "commit", "-m", "second")
    candidate_path = add_worktree(repo, tmp_path / "candidate", "candidate")
    real_git = module._git

    def move_ref_after_remove(
        git_repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        result = real_git(git_repo, *args, check=check)
        if args[:2] == ("worktree", "remove"):
            git(repo, "update-ref", "refs/heads/candidate", previous_oid)
        return result

    monkeypatch.setattr(module, "_git", move_ref_after_remove)
    monkeypatch.setattr(module, "process_table", lambda: [])
    monkeypatch.chdir(repo)

    assert main(["prune", "--apply"]) == 2

    assert not candidate_path.exists()
    assert git(repo, "rev-parse", "refs/heads/candidate").stdout.strip() == previous_oid


def test_prune_preserves_worktree_when_submodule_deinit_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate_path = add_worktree(repo, tmp_path / "candidate", "candidate")
    real_git = module._git

    def refuse_deinit(
        git_repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args == ("submodule", "deinit", "--all"):
            return subprocess.CompletedProcess(
                ["git", *args], returncode=1, stdout="", stderr="dirty submodule"
            )
        return real_git(git_repo, *args, check=check)

    monkeypatch.setattr(module, "_git", refuse_deinit)
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match="submodule"):
        module.prune_worktrees(repo, apply=True)

    assert candidate_path.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_destructive_worktree_removal_never_uses_force() -> None:
    source = Path(module.__file__).read_text(encoding="utf8")

    assert '"worktree", "remove", "--force"' not in source
    assert '"submodule", "deinit", "--all", "--force"' not in source


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


def test_trim_preflights_all_targets_before_cleaning_any(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    tools = repo / "tools"
    tools.mkdir()
    log = tmp_path / "clean.log"
    cleaner = tools / "clean"
    cleaner.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$PWD" >> "$PGREP_TEST_LOG"\n',
        encoding="utf8",
    )
    cleaner.chmod(0o755)
    first_path = add_worktree(repo, tmp_path / "first", "first")
    second_path = add_worktree(repo, tmp_path / "second", "second")
    first = Worktree(first_path, "first", False)
    second = Worktree(second_path, "second", False)
    monkeypatch.setenv("PGREP_TEST_LOG", str(log))
    monkeypatch.setattr(
        module,
        "running_processes",
        lambda _repo, worktree: [(123, "app")] if worktree == second else [],
    )

    with pytest.raises(module.LifecycleError, match="running"):
        module.trim_worktrees([first, second])

    assert not log.exists()


def test_real_cleaner_preserves_source_and_shared_build_dependencies(
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "cleaner sandbox"
    out = sandbox / "out"
    for directory in ("node_modules", "pyenv", "download", "rust", "review-logs"):
        (out / directory).mkdir(parents=True)
        (out / directory / "marker").write_text(directory, encoding="utf8")
    source = sandbox / "source.txt"
    source.write_text("source", encoding="utf8")
    cleaner = Path(module.__file__).with_name("clean")

    subprocess.run([str(cleaner), "keep-env"], cwd=sandbox, check=True)

    assert source.read_text(encoding="utf8") == "source"
    for preserved in ("node_modules", "pyenv", "download"):
        assert (out / preserved / "marker").exists()
    assert not (out / "rust").exists()
    assert not (out / "review-logs").exists()


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
    worktree = repo / ".worktrees" / "review"
    worktree.parent.mkdir()
    git(repo, "worktree", "add", str(worktree), "review")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["review-clean"]) == 0

    assert not worktree.exists()
    assert not (repo / ".git" / "pgrep-review-operation.lock").exists()
    branch = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/review"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert branch.returncode != 0


def test_review_clean_refuses_active_sync_lock_and_preserves_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    review_path = repo / ".worktrees" / "review"
    review_path.parent.mkdir()
    add_worktree(repo, review_path, "review")
    lock = repo / ".git" / "pgrep-review-operation.lock"
    lock.mkdir()
    (lock / "owner").write_text(
        f"sync pid={os.getpid()}\n",
        encoding="utf8",
    )
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match="active.*sync"):
        module.review_clean(repo)

    assert lock.exists()
    assert review_path.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/review").returncode == 0


def test_review_clean_preserves_ignored_private_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("content/\n", encoding="utf8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore private content")
    review_path = repo / ".worktrees" / "review"
    review_path.parent.mkdir()
    add_worktree(repo, review_path, "review")
    private = review_path / "content" / "credentials.json"
    private.parent.mkdir()
    private.write_text("private", encoding="utf8")
    monkeypatch.setattr(module, "process_table", lambda: [])
    monkeypatch.chdir(repo)

    assert main(["review-clean"]) == 2

    assert review_path.exists()
    assert private.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/review").returncode == 0


def test_review_clean_compare_delete_preserves_ref_moved_after_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    previous_oid = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "second.txt").write_text("second", encoding="utf8")
    git(repo, "add", "second.txt")
    git(repo, "commit", "-m", "second")
    review_path = repo / ".worktrees" / "review"
    review_path.parent.mkdir()
    add_worktree(repo, review_path, "review")
    real_git = module._git

    def move_ref_after_remove(
        git_repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        result = real_git(git_repo, *args, check=check)
        if args[:2] == ("worktree", "remove"):
            git(repo, "update-ref", "refs/heads/review", previous_oid)
        return result

    monkeypatch.setattr(module, "_git", move_ref_after_remove)
    monkeypatch.setattr(module, "process_table", lambda: [])
    monkeypatch.chdir(repo)

    assert main(["review-clean"]) == 2

    assert not review_path.exists()
    assert git(repo, "rev-parse", "refs/heads/review").stdout.strip() == previous_oid


def test_review_clean_refuses_review_branch_outside_disposable_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    worktree = tmp_path / "elsewhere" / "review"
    worktree.parent.mkdir()
    add_worktree(repo, worktree, "review")
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match=r"\.worktrees/review"):
        module.review_clean(repo)

    assert worktree.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/review").returncode == 0


def test_review_clean_rechecks_dirty_state_immediately_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    review_path = repo / ".worktrees" / "review"
    review_path.parent.mkdir()
    add_worktree(repo, review_path, "review")
    real_is_dirty = module.is_dirty
    checks = 0

    def dirty_on_final_check(worktree: Worktree) -> bool:
        nonlocal checks
        if worktree.path == review_path:
            checks += 1
            if checks == 2:
                (review_path / "late.txt").write_text("late", encoding="utf8")
        return real_is_dirty(worktree)

    monkeypatch.setattr(module, "is_dirty", dirty_on_final_check)
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match="dirty"):
        module.review_clean(repo)

    assert checks == 2
    assert review_path.exists()
    assert (review_path / "late.txt").exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/review").returncode == 0


@pytest.mark.parametrize("unsafe_state", ["dirty", "running"])
def test_review_clean_refuses_unsafe_review_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_state: str,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    worktree_path = repo / ".worktrees" / "review"
    worktree_path.parent.mkdir()
    add_worktree(repo, worktree_path, "review")
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
