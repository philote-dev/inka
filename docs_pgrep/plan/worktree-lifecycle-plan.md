# Worktree Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, explicit commands that report worktree disk use, trim only
disposable build output, remove only clean merged worktrees, clean the disposable
review checkout, and prevent review builds from exhausting the disk.

**Architecture:** A stdlib-only Python CLI owns byte-preserving NUL-safe
worktree discovery, normalized-path-keyed command/CWD process checks, ignored-data
classification, per-worktree operation locks, destructive preflight, and
compare-and-delete ref handling. Thin `just` recipes expose that CLI.
`pgrep-sync-review` delegates its free-space decision to the same CLI and shares
an atomic review operation lock with `review-clean`.

**Tech Stack:** Python 3 stdlib, Git CLI, Bash, `just`, pytest.

## Global Constraints

- Choose worktrees by concurrency, not by language.
- Never edit or delete tracked or untracked source during trim.
- Never prune a dirty, running, unmerged, detached, or primary checkout.
- Never remove a checkout containing ignored private data. Ignored paths are
  allowed only when every file is known disposable build/cache output.
- Determine merge eligibility against `refs/heads/main`, regardless of the
  primary checkout's current branch.
- `worktree-prune` is dry-run unless `--apply` is explicit.
- `worktree-prune` never removes branch `review`; it routes users to the
  lock-protected `review-clean`.
- `review-clean` accepts only branch `review` at the normalized conventional
  path `<primary>/.worktrees/review`, and refuses a running or dirty checkout.
- Default destructive commands refuse worktrees with registered submodules and
  name the explicit `--force-submodules` opt-in. Because Git requires
  `git worktree remove --force` for any submodule-bearing worktree, force is
  allowed only with `prune --apply --force-submodules` or
  `review-clean --force-submodules`, after recursive clean checks and non-forced
  submodule deinit.
- Symbolic branch refs are never deletion candidates. Direct refs are deleted
  only with compare-and-delete
  `git update-ref --no-deref -d <ref> <expected-oid>`.
- `review-sync` and `review-clean` share an atomic Git-common-directory lock.
  All trim/prune/review-clean mutations also hold a per-worktree lock from
  destructive preflight through the final mutation. Unique ownership tokens
  ensure cleanup cannot release a manually removed and reacquired lock. An
  existing or stale lock fails closed with manual recovery guidance.
- The global lock order is always shared review-operation lock first, then
  per-worktree locks in normalized path order. Trimming the conventional review
  checkout participates in both lock scopes.
- Destructive process checks combine command text with process CWD inspection
  (`lsof` on macOS and `/proc/<pid>/cwd` on Linux) and fail closed when CWD
  inspection is unavailable.
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
matching excludes the lifecycle process itself, keys attribution by normalized
path instead of mutable branch metadata, and assigns a command to the longest
matching worktree path. Destructive checks additionally inspect each current-user
process CWD with `lsof` on macOS or `/proc/<pid>/cwd` on Linux, so a relative
command with no checkout path in `argv` still blocks mutation. They fail closed
if CWD inspection is unavailable. Discovery captures
`git worktree list --porcelain -z` as bytes and decodes paths with
`os.fsdecode`, preserving whitespace, embedded newlines, C-quoting-sensitive
characters, and non-UTF-8 Unix pathname bytes.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `just test-py`

Expected: all `pgrep_worktrees` tests pass.

### Task 2: Safe trim, prune, and review cleanup

**Files:**

- Modify: `tools/pgrep_worktrees.py`
- Modify: `tools/tests/test_pgrep_worktrees.py`

**Interfaces:**

- Produces: `trim <branch-or-path>...`.
- Produces: `prune [--apply [--force-submodules]]`.
- Produces: `review-clean [--force-submodules]`.

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
    # branch_merged compares to refs/heads/main, not HEAD.
    if not branch_merged(repo, wt.branch):
        return False, "unmerged"
    if ignored_private_paths(wt):
        return False, "ignored private data"
    return True, "eligible"
```

`trim` invokes the primary checkout's `tools/clean keep-env` with the selected
worktree as `cwd`. Before removal, `prune --apply` repeats
dirty/running/ignored-data checks and revalidates the captured ref OID and the
checkout's direct HEAD branch (plus `main` ancestry for normal prune). Worktrees
without registered submodules use non-forced `git worktree remove`.

Git requires `git worktree remove --force` even after a clean submodule is
deinitialized. The default therefore refuses every registered-submodule
worktree. The double opt-in `prune --apply --force-submodules` (or
`review-clean --force-submodules`) first discovers initialized submodules
recursively from byte/NUL-safe gitlink records. Every initialized repository
must have zero tracked modifications, untracked files, and ignored files. This
scan runs after locks and ordinary preflight, repeats immediately before
non-forced `git submodule deinit --all`, and only then permits forced worktree
removal. For each registered submodule without initialized Git metadata, the
filesystem path must be absent or a truly empty directory; nonempty, hidden,
symlinked, or otherwise invalid paths fail closed as local data. Worktrees
without registered submodules are never force-removed.

After removal the branch is deleted with
`git update-ref --no-deref -d <ref> <expected-oid>`; symbolic refs are refused
during capture and revalidation. If a ref moved, the worktree may already be
gone but the moved branch survives and the command reports a safe partial
result. `review-clean` applies the same sequence without the `main` ancestry
requirement, while requiring both branch `review` and path
`<primary>/.worktrees/review`.

Ignored files are enumerated individually with NUL-delimited
`git ls-files --others --ignored --exclude-standard -z`. The allowlist covers
only root `out/`; `.venv`, `node_modules`, `target`, `.svelte-kit`, `.yarn`,
Python caches, coverage output, documented generated-doc trees, and compiler
artifacts under paper directories. Before applying that allowlist, every path
component is denied if it names content, private data, corpora, gold/held-out
sets, `.ssh`, `.env`/`.envrc`, credentials, secrets, tokens, or key material.
Password, passwd, and passphrase names (including CamelCase and explicit compact
forms) are denied by the same pre-allowlist rule.
CamelCase is split before normalization, and common compact forms such as
`privateCorpus`, `apiKey`, and `accessToken` are denied without treating
unrelated words such as `monkey` or `tokenizer` as credentials. These names
block removal at any depth, including beneath root `out/`. Ignored-path output
is also captured as NUL-delimited bytes and filesystem-decoded, matching
worktree discovery's non-UTF-8 pathname handling.
Password-family tokens followed by digits (for example `password123`,
`dbPassword2`, `passwd7`, and `passphrase42`) are also denied, while
`passwordless` remains unrelated.

`review-clean` acquires `<git-common-dir>/pgrep-review-operation.lock` before
its fresh preflight and holds it through compare-and-delete ref removal.
`pgrep-sync-review` uses the same atomic directory lock from before review
branch/worktree creation through reset, clean, merge, lock refresh, and build.
After acquiring that lock and creating an absent checkout, sync proves that the
normalized review path is an exact NUL-porcelain registration, its reported Git
top-level is the same path, direct HEAD is `refs/heads/review`, and that branch
ref is itself direct. Any mismatch refuses before reset, clean, merge, or build.
Per-branch merge commands place `--` before the branch argument so a valid ref
whose short name begins with `-` cannot be interpreted as an option.
Each trim, prune, and review-clean mutation also holds a path-hashed
per-worktree lock under the Git common directory from destructive preflight
through cleanup/ref deletion. The shared review-operation lock is always
acquired before path-sorted per-worktree locks; trim of
`<primary>/.worktrees/review` acquires both. Owner records include a unique token; cleanup
removes only its token-specific, exactly matching record and removes the lock
directory only when empty. A first owner therefore cannot release a lock that
was manually removed and reacquired. Existing locks, including stale ones,
fail closed; the error tells the user to verify no owner is active before
manual lock removal.

These locks serialize cooperating lifecycle and review tools, while CWD
inspection blocks visible active local writers. No local CLI can make deletion
atomic against an uncooperative external writer that ignores the locks and
creates a file after the final check; Git's own removal checks remain the last
guard for that residual case.

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

[positional-arguments]
worktree-trim *worktrees:
    ./tools/pgrep_worktrees.py trim "$@"

[positional-arguments]
worktree-prune *args:
    ./tools/pgrep_worktrees.py prune "$@"

[positional-arguments]
review-clean *args:
    ./tools/pgrep_worktrees.py review-clean "$@"
```

`review-sync` also uses per-recipe `[positional-arguments]` and quoted `"$@"`.
Shell entry points derive the primary root from
`git rev-parse --path-format=absolute --git-common-dir`, avoiding line or field
splitting. Checkout paths and argument values containing spaces, shell
metacharacters, or embedded newlines retain their original boundaries.

- [x] **Step 3: Guard sync before review branch creation or reset**

The sync script maps only disk-guard exit `2` to private status `75`. The
looping `review-sync` recipe maps `75` back to public exit `2`; all unrelated
statuses, including `2` from later sync work, remain transient and retry.

`PGREP_REVIEW_AVAILABLE_BYTES` is a test-only override. Without it, the command
uses `shutil.disk_usage(primary_checkout).free`.

- [x] **Step 4: Verify recipes and guard**

Run: `just worktree-status`

Expected: every registered checkout appears with disk and safety state.

Run:
`PGREP_REVIEW_AVAILABLE_BYTES=$((9 * 1024 * 1024 * 1024)) just review-sync`

Expected: exit code 2 before creating, resetting, or building `review`. The
sync script emits internal status `75`, which the loop maps to public exit `2`;
other transient sync errors, including an unrelated status `2`, remain
report-and-retry behavior.

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

- [x] **Step 3: Run and record the standalone branch gates**

Run: `just test-py`

Expected: exit 0.

Run: `just check`

Expected on the standalone branch: lifecycle files introduce no new failure.
Because the separately committed `chore/product-layer-cleanup` dependency is
absent, `just check` may exit 1 only for these recorded baseline blockers:

- dprint: `docs_pgrep/plan/content-foundry-and-verifier-design.md`
- dprint: `docs_pgrep/plan/login-gate-beta-handoff.md`
- dprint: `docs_pgrep/plan/deferred-todos.md`
- dprint: `docs_pgrep/reference/dev-harness.md`
- dprint: `docs_pgrep/reference/content-and-dependencies.md`
- Ruff format: `qt/tests/test_mediasrv.py`
- mypy return type: `qt/aqt/mediasrv.py`

Do not duplicate those fixes on this branch. Step 3 is complete when the
standalone gates and allowed blockers are executed and recorded; Step 5 proves
the integrated gate.

- [x] **Step 4: Inspect and commit the documentation**

Run: `git status --short --branch`

Expected: only the intended lifecycle CLI, tests, recipes, sync guard, and docs
are changed across this branch. Commit the two lifecycle docs without amending
earlier task commits.

- [x] **Step 5: Verify the integrated review branch**

After the controller merges `chore/worktree-lifecycle` into the existing
disposable `review` branch that already contains `chore/product-layer-cleanup`,
run `just check`.

Expected: exit 0.

Evidence: review merge `97ead1ab1`; `just check` exited 0 with
`Build succeeded in 1.02s.`
