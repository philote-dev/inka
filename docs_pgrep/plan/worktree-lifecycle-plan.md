# Worktree Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, explicit commands that report worktree disk use, trim only
disposable build output, remove only clean merged worktrees, clean the disposable
review checkout, and prevent review builds from exhausting the disk.

**Architecture:** A stdlib-only Python CLI owns worktree discovery, eligibility,
process checks, disk accounting, and destructive preflight. Thin `just` recipes
expose that CLI. `pgrep-sync-review` delegates its free-space decision to the
same CLI before touching the disposable review checkout.

**Tech Stack:** Python 3 stdlib, Git CLI, Bash, `just`, pytest.

## Global Constraints

- Choose worktrees by concurrency, not by language.
- Never edit or delete tracked or untracked source during trim.
- Never prune a dirty, running, unmerged, detached, or primary checkout.
- `worktree-prune` is dry-run unless `--apply` is explicit.
- `review-clean` refuses a running or dirty review checkout.
- Warn below 30 GiB available; refuse a review build below 10 GiB.
- Keep `out/node_modules`, `out/pyenv`, and `out/download` when trimming.
- Use only stdlib modules so lifecycle commands work before a project build.

---

### Task 1: Worktree inventory and disk guard

**Files:**

- Create: `tools/pgrep_worktrees.py`
- Create: `tools/tests/test_pgrep_worktrees.py`

**Interfaces:**

- Produces: `Worktree(path: Path, branch: str | None, primary: bool)`.
- Produces: `discover_worktrees(repo: Path) -> list[Worktree]`.
- Produces: `review_disk_guard(available_bytes: int) -> tuple[int, str]`.
- Produces CLI commands `status` and `review-disk-guard`.

- [x] **Step 1: Write failing parsing and threshold tests**

```python
def test_parse_worktrees_marks_primary_and_detached():
    parsed = parse_worktree_porcelain(PORCELAIN)
    assert parsed[0].primary is True
    assert parsed[1].branch == "feat/demo"
    assert parsed[2].branch is None


@pytest.mark.parametrize(
    ("gib", "code", "fragment"),
    [(31, 0, ""), (29, 0, "LOW DISK"), (9, 2, "REFUSING REVIEW BUILD")],
)
def test_review_disk_guard_thresholds(gib, code, fragment):
    actual_code, message = review_disk_guard(gib * 1024**3)
    assert actual_code == code
    assert fragment in message
```

- [x] **Step 2: Run the tests and verify RED**

Run: `just test-py`

Expected: collection fails because `tools/pgrep_worktrees.py` does not exist.

- [x] **Step 3: Implement inventory, size, merge, dirty, and process reporting**

```python
@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    primary: bool


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
```

`status` prints one row per checkout with branch, clean/dirty, primary or
merged/unmerged, stopped/running, total size, build size, and path. Process
matching excludes the lifecycle process itself and attributes a command to the
longest matching worktree path.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `just test-py`

Expected: all `pgrep_worktrees` tests pass.

### Task 2: Safe trim, prune, and review cleanup

**Files:**

- Modify: `tools/pgrep_worktrees.py`
- Modify: `tools/tests/test_pgrep_worktrees.py`

**Interfaces:**

- Produces: `trim <branch-or-path>...`.
- Produces: `prune [--apply]`.
- Produces: `review-clean`.

- [x] **Step 1: Write failing command tests with temporary Git repositories**

```python
def test_prune_defaults_to_dry_run(repo_with_merged_worktree):
    result = run_cli(repo_with_merged_worktree, "prune")
    assert "eligible" in result.stdout
    assert repo_with_merged_worktree.worktree.exists()


def test_prune_apply_removes_only_clean_merged_worktree(repo_with_merged_worktree):
    result = run_cli(repo_with_merged_worktree, "prune", "--apply")
    assert result.returncode == 0
    assert not repo_with_merged_worktree.worktree.exists()


def test_trim_refuses_running_worktree(monkeypatch, discovered_worktree):
    monkeypatch.setattr(module, "running_processes", lambda *_: [(123, "app")])
    with pytest.raises(LifecycleError, match="running"):
        trim_worktrees([discovered_worktree])
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `just test-py`

Expected: failures for missing `trim`, `prune`, and `review-clean` behavior.

- [x] **Step 3: Implement strict preflight and mutations**

```python
def prune_eligibility(repo: Path, wt: Worktree) -> tuple[bool, str]:
    if wt.primary:
        return False, "primary checkout"
    if wt.branch is None:
        return False, "detached"
    if is_dirty(wt):
        return False, "dirty"
    if running_processes(repo, wt):
        return False, "running"
    if not branch_merged(repo, wt.branch):
        return False, "unmerged"
    return True, "eligible"
```

`trim` invokes the primary checkout's `tools/clean keep-env` with the selected
worktree as `cwd`. `prune --apply` uses `git worktree remove --force` only after
all eligibility checks pass, then `git branch -d`, then `git worktree prune`.
`review-clean` applies the same dirty/running checks but explicitly removes the
disposable `review` branch with `git branch -D`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `just test-py`

Expected: all lifecycle tests pass, including dry-run preservation.

### Task 3: Expose recipes and guard review synchronization

**Files:**

- Modify: `justfile`
- Modify: `tools/pgrep-sync-review`
- Modify: `tools/tests/test_pgrep_worktrees.py`

**Interfaces:**

- Produces recipes `worktree-status`, `worktree-trim`, `worktree-prune`, and
  `review-clean`.
- Consumes: `pgrep_worktrees.py review-disk-guard`.

- [x] **Step 1: Write a failing CLI guard test**

```python
def test_disk_guard_cli_returns_two_below_ten_gib(monkeypatch, capsys):
    monkeypatch.setenv("PGREP_REVIEW_AVAILABLE_BYTES", str(9 * 1024**3))
    assert main(["review-disk-guard"]) == 2
    assert "REFUSING REVIEW BUILD" in capsys.readouterr().err
```

- [x] **Step 2: Add thin `just` recipes**

```just
worktree-status:
    ./tools/pgrep_worktrees.py status

worktree-trim *worktrees:
    ./tools/pgrep_worktrees.py trim {{ worktrees }}

worktree-prune *args:
    ./tools/pgrep_worktrees.py prune {{ args }}

review-clean:
    ./tools/pgrep_worktrees.py review-clean
```

- [x] **Step 3: Guard sync before review branch creation or reset**

```bash
"$ROOT_DIR/tools/pgrep_worktrees.py" review-disk-guard || exit $?
```

`PGREP_REVIEW_AVAILABLE_BYTES` is a test-only override. Without it, the command
uses `shutil.disk_usage(primary_checkout).free`.
The `review-sync` loop propagates guard exit code `2` immediately while keeping
its existing report-and-retry behavior for other transient sync failures.

- [x] **Step 4: Verify recipes and guard**

Run: `just worktree-status`

Expected: every registered checkout appears with disk and safety state.

Run:
`PGREP_REVIEW_AVAILABLE_BYTES=$((9 * 1024 * 1024 * 1024)) just review-sync`

Expected: exit code 2 before creating, resetting, or building `review`. The
loop recipe propagates disk-guard exit code 2 instead of swallowing it; other
transient sync errors remain report-and-retry behavior.

### Task 4: Documentation and full gate

**Files:**

- Modify: `docs_pgrep/plan/dev-pipeline-design.md`
- Modify: `docs_pgrep/plan/worktree-lifecycle-plan.md`

- [x] **Step 1: Link this implementation plan from the approved design**

Add a sentence under “Worktree lifecycle and disk policy” pointing to
`worktree-lifecycle-plan.md`.

- [x] **Step 2: Mark implementation tasks complete after evidence exists**

Change each completed checkbox in this file from `[ ]` to `[x]` only after its
command has passed.

- [x] **Step 3: Run the branch gates**

Run: `just test-py`

Expected: exit 0.

Run: `just check`

Expected on the standalone branch: lifecycle files introduce no new failure.
If the current `main` baseline still reports the known `qt/tests/test_mediasrv.py`
format and `qt/aqt/mediasrv.py` type failures fixed on the separately committed
`chore/product-layer-cleanup` branch, record those exact blockers without
duplicating that branch's fixes.

- [x] **Step 4: Inspect and commit the documentation**

Run: `git status --short --branch`

Expected: only the intended lifecycle CLI, tests, recipes, sync guard, and docs
are changed across this branch. Commit the two lifecycle docs without amending
earlier task commits.

- [ ] **Step 5: Verify the integrated review branch**

After the controller merges `chore/worktree-lifecycle` into the existing
disposable `review` branch that already contains `chore/product-layer-cleanup`,
run `just check`.

Expected: exit 0.
