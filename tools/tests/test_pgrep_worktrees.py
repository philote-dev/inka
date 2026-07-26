# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
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
    b"worktree /repo\0"
    b"HEAD 1111111111111111111111111111111111111111\0"
    b"branch refs/heads/main\0\0"
    b"worktree /repo/.worktrees/demo\0"
    b"HEAD 2222222222222222222222222222222222222222\0"
    b"branch refs/heads/feat/demo\0\0"
    b"worktree /repo/.worktrees/detached\0"
    b"HEAD 3333333333333333333333333333333333333333\0"
    b"detached\0\0"
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


def git_allow_file(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def initialized_submodule_worktree(
    tmp_path: Path,
    *,
    nested: bool = False,
    branch: str = "candidate",
    worktree_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    leaf_source = committed_repo(tmp_path / "leaf-source")
    (leaf_source / ".gitignore").write_text(
        "cache/\nprivate/\n",
        encoding="utf8",
    )
    git(leaf_source, "add", ".gitignore")
    git(leaf_source, "commit", "-m", "ignore local output")

    if nested:
        parent_source = committed_repo(tmp_path / "parent-source")
        git_allow_file(
            parent_source,
            "submodule",
            "add",
            str(leaf_source),
            "nested",
        )
        git(
            parent_source,
            "config",
            "-f",
            ".gitmodules",
            "submodule.nested.ignore",
            "all",
        )
        git(parent_source, "add", ".gitmodules", "nested")
        git(parent_source, "commit", "-m", "add nested submodule")
        source = parent_source
        submodule_path = Path("modules/child/nested")
    else:
        source = leaf_source
        submodule_path = Path("modules/child")

    repo = committed_repo(tmp_path / "repo")
    git_allow_file(repo, "submodule", "add", str(source), "modules/child")
    git(
        repo,
        "config",
        "-f",
        ".gitmodules",
        "submodule.modules/child.ignore",
        "all",
    )
    git(repo, "add", ".gitmodules", "modules/child")
    git(repo, "commit", "-m", "add local submodule")
    candidate_path = worktree_path or tmp_path / branch
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate = add_worktree(repo, candidate_path, branch)
    git_allow_file(candidate, "submodule", "update", "--init", "--recursive")
    return repo, candidate, candidate / submodule_path


def add_worktree(repo: Path, path: Path, branch: str) -> Path:
    git(repo, "branch", branch)
    git(repo, "worktree", "add", str(path), branch)
    return path


def install_review_sync_tools(repo: Path) -> Path:
    tools = repo / "tools"
    tools.mkdir(exist_ok=True)
    worktree_cli = tools / "pgrep_worktrees.py"
    worktree_cli.write_text(
        Path(module.__file__).read_text(encoding="utf8"), encoding="utf8"
    )
    worktree_cli.chmod(0o755)
    sync_script = tools / "pgrep-sync-review"
    source_script = Path(module.__file__).with_name("pgrep-sync-review")
    sync_script.write_text(source_script.read_text(encoding="utf8"), encoding="utf8")
    sync_script.chmod(0o755)
    return sync_script


def worktree_operation_lock_path(repo: Path, worktree: Path) -> Path:
    normalized = os.path.abspath(os.path.normpath(worktree))
    digest = hashlib.sha256(os.fsencode(normalized)).hexdigest()
    return repo / ".git" / f"pgrep-worktree-{digest}.lock"


def test_parse_worktrees_marks_primary_and_detached() -> None:
    parsed = parse_worktree_porcelain(PORCELAIN)

    assert parsed[0].primary is True
    assert parsed[1].branch == "feat/demo"
    assert parsed[2].branch is None


def test_parse_worktrees_preserves_newline_in_nul_delimited_path() -> None:
    output = (
        b"worktree /repo\nwith-newline\0"
        b"HEAD 1111111111111111111111111111111111111111\0"
        b"branch refs/heads/main\0\0"
    )

    parsed = parse_worktree_porcelain(output)

    assert parsed == [Worktree(Path("/repo\nwith-newline"), "main", True)]


@pytest.mark.skipif(os.name == "nt", reason="surrogateescape is a Unix path behavior")
def test_parse_worktrees_preserves_non_utf8_path_bytes() -> None:
    raw_path = b"/repo/\xff-worktree"
    output = (
        b"worktree "
        + raw_path
        + b"\0HEAD 1111111111111111111111111111111111111111\0"
        + b"branch refs/heads/main\0\0"
    )

    parsed = parse_worktree_porcelain(output)

    assert os.fsencode(parsed[0].path) == raw_path


def test_discover_worktrees_requests_nul_delimited_porcelain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git_bytes(
        _repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return subprocess.CompletedProcess(
            ["git", *args], returncode=0, stdout=PORCELAIN, stderr=b""
        )

    def fake_git(
        _repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        calls.append(("text-mode", *args))
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=0,
            stdout=PORCELAIN.decode(),
            stderr="",
        )

    monkeypatch.setattr(module, "_git_bytes", fake_git_bytes, raising=False)
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

    assert attributed[Path("/repo")] == [(102, "python /repo/app.py")]
    assert attributed[Path("/repo/.worktrees/review")] == [
        (101, "python /repo/.worktrees/review/app.py")
    ]


def test_processes_do_not_match_similarly_prefixed_path() -> None:
    primary = Worktree(Path("/repo"), "main", True)

    attributed = attribute_processes(
        [primary],
        [(104, "python /repo-copy/app.py")],
        own_pid=100,
    )

    assert attributed[Path("/repo")] == []


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

    assert attributed[Path("/repo with spaces")] == []
    assert attributed[Path("/repo with spaces/.worktrees/review with spaces")] == [
        (104, command)
    ]


def test_review_dashboard_launches_absolute_worktree_run_path() -> None:
    source = Path(module.__file__).with_name("pgrep-review").read_text(encoding="utf8")

    assert '[str(Path(path) / "run")]' in source
    assert '["./run"]' not in source


def test_running_processes_matches_stale_worktree_by_normalized_path(
    tmp_path: Path,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate_path = add_worktree(repo, tmp_path / "candidate", "candidate")
    stale = Worktree(candidate_path / ".." / "candidate", "candidate", False)
    git(candidate_path, "switch", "-c", "replacement")
    process = subprocess.Popen(["sleep", "30"], cwd=candidate_path)
    try:
        running = module.running_processes(repo, stale)
        assert any(pid == process.pid for pid, _detail in running)
    finally:
        process.terminate()
        process.wait(timeout=5)


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


@pytest.mark.parametrize("state", ["nested", "other-branch", "detached"])
def test_review_sync_refuses_invalid_existing_review_path_before_mutation(
    tmp_path: Path,
    state: str,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    sync_script = install_review_sync_tools(repo)
    git(repo, "branch", "review")
    review_path = repo / ".worktrees" / "review"
    review_path.parent.mkdir()
    if state == "nested":
        review_path.mkdir()
        (review_path / "sentinel.txt").write_text("nested", encoding="utf8")
    elif state == "other-branch":
        add_worktree(repo, review_path, "other")
        (review_path / "tracked.txt").write_text("other-dirty", encoding="utf8")
    else:
        git(repo, "worktree", "add", "--detach", str(review_path), "main")
        (review_path / "tracked.txt").write_text("detached-dirty", encoding="utf8")

    primary_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    review_ref = git(repo, "rev-parse", "refs/heads/review").stdout.strip()
    target_head = (
        git(review_path, "rev-parse", "HEAD").stdout.strip()
        if state != "nested"
        else None
    )
    (repo / "tracked.txt").write_text("primary-dirty", encoding="utf8")
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

    assert result.returncode != 0
    assert "review worktree identity" in result.stderr
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == primary_head
    assert git(repo, "rev-parse", "refs/heads/review").stdout.strip() == review_ref
    assert (repo / "tracked.txt").read_text(encoding="utf8") == "primary-dirty"
    if state == "nested":
        assert (review_path / "sentinel.txt").read_text(encoding="utf8") == "nested"
    else:
        assert review_path.exists()
        assert git(review_path, "rev-parse", "HEAD").stdout.strip() == target_head
        assert "dirty" in (review_path / "tracked.txt").read_text(encoding="utf8")
    assert not (repo / ".git" / "pgrep-review-operation.lock").exists()


def test_review_sync_accepts_exact_registered_direct_review_worktree(
    tmp_path: Path,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    sync_script = install_review_sync_tools(repo)
    review_path = repo / ".worktrees" / "review"
    review_path.parent.mkdir()
    add_worktree(repo, review_path, "review")
    (repo / "tracked.txt").write_text("primary-dirty", encoding="utf8")
    (review_path / "tracked.txt").write_text("review-dirty", encoding="utf8")
    generated = review_path / "generated.tmp"
    generated.write_text("generated", encoding="utf8")
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
    assert (repo / "tracked.txt").read_text(encoding="utf8") == "primary-dirty"
    assert (review_path / "tracked.txt").read_text(encoding="utf8") == "base"
    assert not generated.exists()
    assert (
        git(review_path, "symbolic-ref", "--no-recurse", "-q", "HEAD").stdout.strip()
        == "refs/heads/review"
    )
    assert not (repo / ".git" / "pgrep-review-operation.lock").exists()


def test_review_sync_treats_leading_dash_branch_as_revision(
    tmp_path: Path,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    sync_script = install_review_sync_tools(repo)
    git(repo, "switch", "-c", "source")
    (repo / "leading-dash.txt").write_text("merged", encoding="utf8")
    git(repo, "add", "leading-dash.txt")
    git(repo, "commit", "-m", "leading dash branch")
    branch_oid = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "main")
    git(repo, "update-ref", "refs/heads/-leading-dash", branch_oid)
    env = os.environ.copy()
    env["PGREP_REVIEW_AVAILABLE_BYTES"] = str(30 * 1024**3)

    result = subprocess.run(
        [str(sync_script), "-leading-dash"],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (repo / ".worktrees" / "review" / "leading-dash.txt").read_text(
        encoding="utf8"
    ) == "merged"
    assert "merged  (1): -leading-dash" in result.stdout


def test_review_sync_cleanup_preserves_reacquired_lock(
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
    signal = tmp_path / "lock-acquired"
    proceed = tmp_path / "proceed"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "show-ref" ]; then\n'
        '  : > "$PGREP_TEST_SIGNAL"\n'
        '  while [ ! -e "$PGREP_TEST_PROCEED" ]; do sleep 0.01; done\n'
        "fi\n"
        f'exec "{real_git}" "$@"\n',
        encoding="utf8",
    )
    fake_git.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PGREP_REVIEW_AVAILABLE_BYTES": str(30 * 1024**3),
            "PGREP_TEST_PROCEED": str(proceed),
            "PGREP_TEST_SIGNAL": str(signal),
        }
    )
    process = subprocess.Popen(
        [str(sync_script), "main"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(500):
            if signal.exists():
                break
            time.sleep(0.01)
        assert signal.exists()
        lock = repo / ".git" / "pgrep-review-operation.lock"
        shutil.rmtree(lock)
        lock.mkdir()
        second_owner = lock / "owner"
        second_record = "review-clean pid=999999 token=second-owner"
        second_owner.write_text(second_record + "\n", encoding="utf8")
        proceed.touch()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        assert second_owner.read_text(encoding="utf8").strip() == second_record
        assert lock.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


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
    assert "[positional-arguments]\nreview-clean *args:\n" in source
    assert './tools/pgrep_worktrees.py review-clean "$@"' in source


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


def test_prune_refuses_existing_worktree_operation_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    lock = worktree_operation_lock_path(repo, candidate)
    lock.mkdir()
    (lock / "owner").write_text("trim pid=999999 token=owner\n", encoding="utf8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 2

    assert candidate.exists()
    assert lock.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_refuses_relative_process_with_worktree_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    monkeypatch.chdir(repo)
    process = subprocess.Popen(["sleep", "30"], cwd=candidate)
    try:
        assert main(["prune", "--apply"]) == 0
        assert "running" in capsys.readouterr().out
        assert candidate.exists()
        assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0
    finally:
        process.terminate()
        process.wait(timeout=5)


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
        ("out/\n", Path("out/content/private-corpus.json")),
        ("out/\n", Path("out/.ssh/config")),
        ("out/\n", Path("out/.envrc")),
        ("out/\n", Path("out/cache/nested/private/gold.json")),
        ("out/\n", Path("out/cache/corpus.bin")),
        ("out/\n", Path("out/cache/held_out/eval.json")),
        ("out/\n", Path("out/cache/credentials/service.json")),
        ("out/\n", Path("out/api-token.txt")),
        ("out/\n", Path("out/cache/private-key.pem")),
        ("out/\n", Path("out/cache/service_api_key")),
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


@pytest.mark.parametrize(
    "path",
    [
        Path("out/privateCorpus.json"),
        Path("out/apiKey.json"),
        Path("out/accessToken.txt"),
        Path("out/heldout.json"),
        Path("out/privateData.bin"),
        Path("out/credentialStore.json"),
        Path("out/clientSecret.txt"),
        Path("out/refreshToken.txt"),
        Path("out/passwords.json"),
        Path("out/dbPasswd.txt"),
        Path("out/userPassphrase"),
        Path("out/databasePassword.json"),
        Path("out/password123.json"),
        Path("out/dbPassword2.txt"),
        Path("out/passwd7"),
        Path("out/passphrase42.bin"),
    ],
)
def test_ignored_compact_sensitive_names_block_disposal(path: Path) -> None:
    assert module._ignored_path_is_disposable(path) is False


@pytest.mark.parametrize(
    "path",
    [
        Path("out/monkey.json"),
        Path("out/tokenizer-cache.bin"),
        Path("out/golden-ratio.json"),
        Path("out/secretary-notes.txt"),
        Path("out/passwordless-cache.bin"),
        Path("out/compass-words.json"),
    ],
)
def test_ignored_sensitive_matching_avoids_unrelated_substrings(path: Path) -> None:
    assert module._ignored_path_is_disposable(path) is True


def test_ignored_paths_decode_non_utf8_nul_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_path = b"out/\xffprivateCorpus.json"

    def fake_git_bytes(
        _repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=0,
            stdout=raw_path + b"\0",
            stderr=b"",
        )

    monkeypatch.setattr(module, "_git_bytes", fake_git_bytes)

    paths = module._ignored_paths(Worktree(Path("/repo"), "candidate", False))

    assert [os.fsencode(path) for path in paths] == [raw_path]


@pytest.mark.skipif(
    os.name == "nt" or sys.platform == "darwin",
    reason="requires a filesystem accepting non-UTF-8 path bytes",
)
def test_ignored_paths_preserve_non_utf8_bytes_and_classify_safely(
    tmp_path: Path,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("out/\n", encoding="utf8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore output")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    raw_path = b"out/\xffprivateCorpus.json"
    ignored = candidate / Path(os.fsdecode(raw_path))
    ignored.parent.mkdir()
    ignored.write_bytes(b"private")

    blockers = module.ignored_private_paths(Worktree(candidate, "candidate", False))

    assert [os.fsencode(path) for path in blockers] == [raw_path]


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

    assert process_checks >= 2
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


def test_final_preflight_rejects_changed_direct_branch_with_relative_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate_path = add_worktree(repo, tmp_path / "candidate", "candidate")
    discovered = module.discover_worktrees(repo)
    real_revalidate = module.RefSnapshot.revalidate
    process: subprocess.Popen[str] | None = None

    def switch_branch_before_final_preflight(
        snapshot: module.RefSnapshot,
        primary: Path,
    ) -> None:
        nonlocal process
        if process is None:
            git(candidate_path, "switch", "-c", "replacement")
            process = subprocess.Popen(
                ["sleep", "30"],
                cwd=candidate_path,
                text=True,
            )
        real_revalidate(snapshot, primary)

    monkeypatch.setattr(
        module.RefSnapshot,
        "revalidate",
        switch_branch_before_final_preflight,
    )
    try:
        with pytest.raises(module.LifecycleError, match="direct HEAD branch changed"):
            module.prune_worktrees(repo, apply=True, worktrees=discovered)
        assert candidate_path.exists()
        assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0
        assert (
            git(repo, "show-ref", "--verify", "refs/heads/replacement").returncode == 0
        )
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=5)


def test_prune_refuses_symbolic_branch_ref_and_preserves_referent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    git(repo, "symbolic-ref", "refs/heads/candidate", "refs/heads/main")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["prune", "--apply"]) == 0

    assert "symbolic" in capsys.readouterr().out
    assert candidate.exists()
    assert (
        git(repo, "symbolic-ref", "refs/heads/candidate").stdout.strip()
        == "refs/heads/main"
    )
    assert git(repo, "show-ref", "--verify", "refs/heads/main").returncode == 0


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
    monkeypatch.setattr(
        module,
        "_registered_submodule_paths",
        lambda _worktree: [Path("modules/child")],
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "_preflight_initialized_submodules",
        lambda _worktree: None,
        raising=False,
    )
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match="submodule"):
        module.prune_worktrees(repo, apply=True, force_submodules=True)

    assert candidate_path.exists()
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_refuses_submodule_worktree_without_explicit_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, candidate, submodule = initialized_submodule_worktree(tmp_path)
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match="--force-submodules"):
        module.prune_worktrees(repo, apply=True)

    assert candidate.exists()
    assert os.path.lexists(submodule / ".git")
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_force_submodules_refuses_nonempty_uninitialized_submodule_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, candidate, submodule = initialized_submodule_worktree(tmp_path)
    git(candidate, "submodule", "deinit", "--all")
    submodule.mkdir(parents=True, exist_ok=True)
    hidden_data = submodule / ".local-private-data"
    hidden_data.write_text("preserve", encoding="utf8")
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(
        module.LifecycleError,
        match="uninitialized submodule path.*nonempty",
    ):
        module.prune_worktrees(repo, apply=True, force_submodules=True)

    assert candidate.exists()
    assert hidden_data.read_text(encoding="utf8") == "preserve"
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_rejects_force_submodules_without_apply(tmp_path: Path) -> None:
    repo = committed_repo(tmp_path / "repo")

    result = subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "prune",
            "--force-submodules",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--force-submodules requires --apply" in result.stderr


@pytest.mark.parametrize(
    ("state", "relative_path"),
    [
        ("ignored private", Path("private/credentials.json")),
        ("ignored ordinary", Path("cache/artifact.bin")),
        ("untracked", Path("loose.txt")),
        ("tracked", Path("tracked.txt")),
    ],
)
def test_prune_refuses_initialized_submodule_with_local_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    relative_path: Path,
) -> None:
    repo, candidate, submodule = initialized_submodule_worktree(tmp_path)
    local_data = submodule / relative_path
    local_data.parent.mkdir(parents=True, exist_ok=True)
    local_data.write_text(state, encoding="utf8")
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(
        module.LifecycleError,
        match="initialized submodule.*not clean",
    ):
        module.prune_worktrees(repo, apply=True, force_submodules=True)

    assert candidate.exists()
    assert os.path.lexists(submodule / ".git")
    assert local_data.read_text(encoding="utf8") == state
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_prune_deinitializes_fully_clean_submodule_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, candidate, _submodule = initialized_submodule_worktree(tmp_path)
    monkeypatch.setattr(module, "process_table", lambda: [])

    module.prune_worktrees(repo, apply=True, force_submodules=True)

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


def test_prune_recursively_refuses_ignored_data_in_nested_submodule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, candidate, nested = initialized_submodule_worktree(tmp_path, nested=True)
    ignored = nested / "cache" / "nested-artifact.bin"
    ignored.parent.mkdir()
    ignored.write_text("nested", encoding="utf8")
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(
        module.LifecycleError,
        match="initialized submodule.*not clean",
    ):
        module.prune_worktrees(repo, apply=True, force_submodules=True)

    assert candidate.exists()
    assert os.path.lexists(nested / ".git")
    assert ignored.read_text(encoding="utf8") == "nested"
    assert git(repo, "show-ref", "--verify", "refs/heads/candidate").returncode == 0


def test_review_clean_refuses_submodule_without_explicit_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_path = tmp_path / "repo" / ".worktrees" / "review"
    repo, review, submodule = initialized_submodule_worktree(
        tmp_path,
        branch="review",
        worktree_path=review_path,
    )
    monkeypatch.setattr(module, "process_table", lambda: [])

    with pytest.raises(module.LifecycleError, match="--force-submodules"):
        module.review_clean(repo)

    assert review.exists()
    assert os.path.lexists(submodule / ".git")
    assert git(repo, "show-ref", "--verify", "refs/heads/review").returncode == 0


def test_review_clean_force_submodules_removes_clean_initialized_submodule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_path = tmp_path / "repo" / ".worktrees" / "review"
    repo, review, _submodule = initialized_submodule_worktree(
        tmp_path,
        branch="review",
        worktree_path=review_path,
    )
    monkeypatch.setattr(module, "process_table", lambda: [])

    message = module.review_clean(repo, force_submodules=True)

    assert message == f"review: removed {review}"
    assert not review.exists()
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/review"],
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        != 0
    )


def test_force_submodules_does_not_force_worktree_without_submodules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    real_git = module._git
    removal_args: list[tuple[str, ...]] = []

    def capture_remove(
        git_repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "remove"):
            removal_args.append(args)
        return real_git(git_repo, *args, check=check)

    monkeypatch.setattr(module, "_git", capture_remove)
    monkeypatch.setattr(module, "process_table", lambda: [])

    module.prune_worktrees(repo, apply=True, force_submodules=True)

    assert not candidate.exists()
    assert len(removal_args) == 1
    assert "--force" not in removal_args[0]


def test_submodule_deinit_never_uses_force() -> None:
    source = Path(module.__file__).read_text(encoding="utf8")

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


def test_cwd_inspection_fails_closed_when_lsof_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], returncode=1, stdout="", stderr="permission denied"
        ),
    )

    inspect_cwds: Callable[[], dict[int, Path]] = getattr(
        module, "_process_cwds", lambda: {}
    )
    with pytest.raises(module.LifecycleError, match="cwd inspection"):
        inspect_cwds()


def test_trim_refuses_running_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = Worktree(tmp_path, "feature", False)
    monkeypatch.setattr(module, "running_processes", lambda *_args: [(123, "app")])

    with pytest.raises(module.LifecycleError, match="running"):
        module.trim_worktrees([worktree])


def test_trim_refuses_existing_worktree_operation_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    tools = repo / "tools"
    tools.mkdir()
    cleaner = tools / "clean"
    cleaner.write_text("#!/bin/sh\nrm -f out/disposable\n", encoding="utf8")
    cleaner.chmod(0o755)
    git(repo, "add", "tools/clean")
    git(repo, "commit", "-m", "add cleaner")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    disposable = candidate / "out" / "disposable"
    disposable.parent.mkdir()
    disposable.write_text("build", encoding="utf8")
    lock = worktree_operation_lock_path(repo, candidate)
    lock.mkdir()
    (lock / "owner").write_text("prune pid=999999 token=owner\n", encoding="utf8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["trim", "candidate"]) == 2

    assert disposable.exists()
    assert lock.exists()


def test_trim_review_refuses_active_review_sync_lock_without_cleaning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    tools = repo / "tools"
    tools.mkdir()
    cleaner = tools / "clean"
    cleaner.write_text("#!/bin/sh\nrm -f out/disposable\n", encoding="utf8")
    cleaner.chmod(0o755)
    git(repo, "add", "tools/clean")
    git(repo, "commit", "-m", "add cleaner")
    review = repo / ".worktrees" / "review"
    review.parent.mkdir()
    add_worktree(repo, review, "review")
    disposable = review / "out" / "disposable"
    disposable.parent.mkdir()
    disposable.write_text("build", encoding="utf8")
    lock = repo / ".git" / "pgrep-review-operation.lock"
    lock.mkdir()
    (lock / "owner").write_text(
        f"sync pid={os.getpid()} token=active\n",
        encoding="utf8",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["trim", "review"]) == 2

    assert disposable.exists()
    assert lock.exists()


def test_trim_refuses_relative_process_with_worktree_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    tools = repo / "tools"
    tools.mkdir()
    cleaner = tools / "clean"
    cleaner.write_text("#!/bin/sh\nrm -f out/disposable\n", encoding="utf8")
    cleaner.chmod(0o755)
    git(repo, "add", "tools/clean")
    git(repo, "commit", "-m", "add cleaner")
    candidate = add_worktree(repo, tmp_path / "candidate", "candidate")
    disposable = candidate / "out" / "disposable"
    disposable.parent.mkdir()
    disposable.write_text("build", encoding="utf8")
    monkeypatch.chdir(repo)
    process = subprocess.Popen(["sleep", "30"], cwd=candidate)
    try:
        assert main(["trim", "candidate"]) == 2
        assert disposable.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)


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


def test_python_lock_cleanup_preserves_reacquired_lock(tmp_path: Path) -> None:
    repo = committed_repo(tmp_path / "repo")
    lock = repo / ".git" / "pgrep-review-operation.lock"

    with module.review_operation_lock(repo, "review-clean"):
        shutil.rmtree(lock)
        lock.mkdir()
        second_owner = lock / "owner"
        second_record = "sync pid=999999 token=second-owner"
        second_owner.write_text(second_record + "\n", encoding="utf8")

    assert second_owner.read_text(encoding="utf8").strip() == second_record
    assert lock.exists()


def test_review_clean_refuses_existing_worktree_operation_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    review = repo / ".worktrees" / "review"
    add_worktree(repo, review, "review")
    lock = worktree_operation_lock_path(repo, review)
    lock.mkdir()
    (lock / "owner").write_text("prune pid=999999 token=owner\n", encoding="utf8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["review-clean"]) == 2

    assert review.exists()
    assert lock.exists()
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


def test_review_clean_refuses_symbolic_branch_ref_and_preserves_referent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = committed_repo(tmp_path / "repo")
    review = repo / ".worktrees" / "review"
    add_worktree(repo, review, "review")
    git(repo, "symbolic-ref", "refs/heads/review", "refs/heads/main")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module, "process_table", lambda: [])

    assert main(["review-clean"]) == 2

    assert review.exists()
    assert (
        git(repo, "symbolic-ref", "refs/heads/review").stdout.strip()
        == "refs/heads/main"
    )
    assert git(repo, "show-ref", "--verify", "refs/heads/main").returncode == 0


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
