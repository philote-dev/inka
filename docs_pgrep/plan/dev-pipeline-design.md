# Dev pipeline redesign

Date: 2026-07-07. Branch: `feat/dev-pipeline`. A browser-first development workflow
and a clean, grouped command set for pgrep, with no dead recipes. This is the design;
build it in phases below.

## Goals

- Develop in the browser (and phone), not in a desktop window. The window returns only
  when you want it.
- A concise, consistently named command set grouped by lifecycle, so `just --list`
  reads as a story.
- No dead code: cut what will never be used, hide pure plumbing, keep the rest.
- Secure phone preview with no LAN exposure and the full backend API kept locked.

## Mental model (unchanged, stated for grounding)

Every pgrep screen and the dev gallery are one SvelteKit web app served by the running
app at `http://127.0.0.1:40000`. The desktop window, the phone, and a browser tab are
three views onto the same server. Three environment knobs drive everything:

- `PGREP_SURFACE_MODE`: `exclusive` (product), `hosted` (product + Anki hatch), `off`
  (stock Anki).
- `ANKIDEV` ("dev mode"): dev conveniences on/off. Notably, dev mode **skips automatic
  backups and the integrity check on close** (`qt/aqt/main.py`), so faithful runs need
  it off.
- `ANKI_BASE`: which profile/data dir (normal vs a throwaway first-run profile).

Key fact confirmed in code: pgrep bridge endpoints (`/_anki/pgrep*`) are already
reachable from a local browser (same-origin + `application/binary` content type), so
local browser development needs no API change. The full backend API stays gated behind
the bearer token / `ANKI_API_HOST=0.0.0.0`.

## Final command set

Grouped, with the previous name where it changed.

### develop

- `dev` (was `run` for browser use): headless serve on `:40000`, no window, live-reload
  to browser and phone. Serves both `/pgrep` and `/pgrep-lab`. Dev mode on. Folds in the
  watcher (so standalone `web-watch` retires) and the AI run (so `dev-ai`/`run-ai`
  retire).
  - AI flag: `--ai on|off`, **default on** (the product ships AI on, so dev matches).
    `just dev --ai off` runs the degraded/offline path for verification. If the key or
    `ai-deps` are missing, `dev` warns ("AI off: no key/deps, run `just ai-deps`") and
    starts anyway, so a fresh checkout is never blocked.
- `dev-window` (new): show the real product window onto the running `dev` server, native
  chrome, live-reloads with edits. For working on window-only properties.
- `serve-tail` (was `review-lan`): expose `dev` to your phone over Tailscale Serve.
- `serve-sync` (was `sync-server`): local sync server for testing sync/demo.

### review

- `review`: dashboard for many branches; instances run headless, viewed in browser tabs,
  bound to `127.0.0.1`.
- `review-sync` (was `sync-review` + `review-loop`): loops, keeps the combined branch
  fresh; its instance auto-rebuilds so a browser refresh shows updates.

### preview (faithful, dev mode off)

- `preview` (was `stage`): the product as users get it (exclusive, dev off), your
  profile.
- `preview-fresh` (was `fresh`): same, brand-new-user throwaway profile.
- `preview-optimized` (was `run-optimized`): same faithful product window, release
  compiled, to feel true performance.

### verify

- `verify`: full gate (build + lint + unit + e2e).
- `check`: fast gate (build + lint + unit).
- `smoke`: fastest sanity (import + Rust).

### ship

- `ship` (new): build the real installer artifact (wraps `./tools/build-installer`).

### quality

`test`, `test-rust`, `test-py`, `test-ts`, `test-e2e`, `lint`, `lint-fix` (was
`fix-lint`), `format` (was `fmt`), `format-fix` (was `fix-fmt`), `bench`, `crash-test`,
`coverage`.

### content

`ai-deps` (was `pgrep-ai-deps`), `gen-decompositions`, `audit-bundle-ai`, `eval-public`.

### ios

`ios-run`, `ios-smoke`, `ios-xcframework`, `ios-manifold`, `ios-mathjax`,
`ios-sync-proof`.

### build / misc (public)

`build`, `rebuild-web`, `ftl-sync`, `ci`, `clean`.

### private (plumbing, hidden from `--list`)

`wheels`, `_review-instance` (was `run-instance`), `minilints`, `fix-minilints`,
`ftl-deprecate`, `complexipy-diff`, and the existing `_*` helpers.

### cut

`run`, `run-ai`, `web-watch`, `review-lan`, `candidate`, `review-sync-loop`,
`pgrep-demo-sync`, `docs`, `docs-serve`, `docs-rust`.

## Directory-driven dev

`dev` and `dev-window` serve whatever worktree you run them in: in a feature worktree
they serve that feature; in `.worktrees/review` they serve the combined branch. `dev`
uses `:40000`, so run one at a time (single-branch focus). Running several branches at
once is what `review` is for (it assigns offset ports per instance).

## What we build (three pieces)

### 1. Headless `dev` + browser/phone live-reload (DONE)

- B1: run the app with the main window hidden so it serves `:40000` with no window
  (`PGREP_HEADLESS`, gated in `main.loadProfile`). Also: `setQuitOnLastWindowClosed(False)`
  so a stray dialog cannot kill the serve; auto-sync skipped in headless (it otherwise
  pops a network dialog against an absent server); a `/` -> `/pgrep` redirect in
  `mediasrv`; and the `--ai on|off` flag (default on, warn-and-continue when no key).
- B2: dev-only live-reload by **polling**, not SSE (waitress has a small WSGI thread
  pool, so held-open SSE connections would starve it). `mediasrv` injects a tiny client
  into the SvelteKit shell only when headless+dev; it polls `GET /_anki/pgrepDevReloadToken`
  (the built shell's mtime) each second and reloads on change. Reaches browser and phone.
- Watcher: bundled into `dev` (one command, one terminal). `web-watch` is now
  headless-aware: under `PGREP_HEADLESS` it skips its initial build (dev already built)
  and skips the Qt-webview reload (browser tabs poll instead), so it never runs `ninja`
  at the same time as `dev`'s own build. `web-watch` is private plumbing.

### 2. `dev-window` (DONE)

- Dev-only GET `/_anki/pgrepDevShowWindow` shows the running `dev` process's real
  product window on the Qt main thread. `just dev-window` pings it, starting `dev` in
  the background if nothing is on `:40000`. Same server, so it live-reloads with edits.
  Closing the window hides it without stopping the serve.

### 3. `serve-tail` + dev-gated origin allowlist (DONE)

- Dev-gated allowlist: `PGREP_DEV_ALLOWED_ORIGIN` env, or `out/dev-allowed-origin`
  (written by `serve-tail`). Relaxes only the Host/Origin localhost guard in
  `mediasrv.handle_request`, never `_have_api_access`, so only pgrep endpoints stay
  reachable. Gated behind `ANKIDEV`.
- `serve-tail` wraps `tailscale serve <port>`, writes the `*.ts.net` origin, prints the
  phone URL. Server stays on `127.0.0.1`.
- `serve-sync` is the renamed sync server (`sync-server` alias kept briefly).

## Review tightening (DONE)

- Bind review instances to `127.0.0.1` (no `ANKI_API_HOST=0.0.0.0`); browser tabs at
  `127.0.0.1:4000N` reach pgrep endpoints anyway, and the full API stays locked.
- Run review instances headless (`PGREP_HEADLESS=1`); view them in browser tabs.
- `review-sync` loops and, after each merge, runs `./ninja qt` in the review worktree
  so a refresh (via the live-reload token) shows UI updates. Python/backend changes
  still need a Stop/Start on the dashboard.
- `run-instance` demoted to `_review-instance`.

## Worktree lifecycle and disk policy

Implementation details and tests are tracked in
[`worktree-lifecycle-plan.md`](worktree-lifecycle-plan.md).

Worktrees are an isolation tool, not the default location for every feature.
Choose them by concurrency, not by language:

- Develop one active task in a normal local branch in the primary checkout. This
  applies equally to UI, Python, Rust, content tooling, and documentation and
  reuses one warm `out/` build tree.
- Use a worktree when two branches must remain checked out simultaneously,
  parallel agents need isolated files, unfinished work must stay parked while
  another task proceeds, or branches must run side by side in `just review`.
- Keep the combined `review` checkout disposable. `review-sync` may recreate it
  whenever combined review is needed.
- When no local task is active, return the primary checkout to clean `main`.

Build outputs, not Git objects or source copies, drive worktree disk usage. A
fully built checkout currently consumes roughly 4–8 GiB, primarily under
`out/rust`; Rust incremental artifacts alone can exceed 2 GiB. The lifecycle
commands therefore separate source preservation from disposable build cleanup:

- `worktree-status` reports every checkout's branch, dirty/clean state, merge
  state relative to `main`, active-process state, and total/build-output size.
- `worktree-trim` removes only disposable build outputs from explicitly selected,
  stopped worktrees. It preserves `out/node_modules`, `out/pyenv`, and
  `out/download` by using the existing `clean keep-env` behavior. It never edits
  tracked or untracked source files and refuses to trim a running checkout.
  Command text and process CWDs are both checked, so relative commands running
  inside a checkout are detected. Trimming the conventional review checkout
  also holds the shared review-operation lock.
- `worktree-prune` is a dry run unless passed `--apply`. It may remove only
  stopped worktrees whose source tree is clean and whose branch is fully merged
  into `main`, and refuses ignored private data such as `content/`, corpora,
  gold/held-out sets, `.ssh`, environment files, keys, tokens, or credentials
  at any depth, including CamelCase/compact forms under `out/`. Applying it
  rejects symbolic branch refs, revalidates the exact branch OID and direct
  checkout branch, removes the worktree without force, compare-deletes that
  same direct ref with `--no-deref`, and runs `git worktree prune`. The primary
  checkout is never eligible.
- `worktree-prune` reports the `review` branch as ineligible and directs users
  to the lock-protected `review-clean`.
- `review-clean` explicitly removes only the stopped, clean `review` branch at
  the conventional normalized path `<primary>/.worktrees/review`, then deletes
  the local branch. A `review` checkout anywhere else is not considered
  disposable. If the conventional checkout is running, it refuses and tells the
  user to stop the row first.

`review-sync` does not delete or trim feature worktrees. Before rebuilding it
checks available disk space and prints a prominent warning below 30 GiB with the
exact `worktree-status`, `worktree-trim`, and `review-clean` commands. It refuses
to start a new review build below 10 GiB so an automated loop cannot fill the
disk, while leaving all source state untouched. Sync and `review-clean` share
the atomic `<git-common-dir>/pgrep-review-operation.lock`, so reset/merge/build
cannot overlap cleanup. An existing or stale lock fails closed and reports its
owner plus manual recovery guidance. Unique owner tokens make release
compare-and-remove: cleanup cannot unlink a manually reacquired lock.

Trim, apply-prune, and review cleanup also hold path-hashed locks under the Git
common directory from destructive preflight through their final mutation. The
global acquisition order is shared review-operation lock first, followed by
per-worktree locks in normalized path order.
Destructive checks inspect current-user CWDs with `lsof` on macOS and
`/proc/<pid>/cwd` on Linux and fail closed if inspection is unavailable. These
guards serialize cooperating lifecycle/review commands and block visible local
writers; an uncooperative external writer that ignores the locks remains
outside what a local CLI can make atomic.

Worktree discovery and ignored-path enumeration capture NUL-delimited output as
bytes and use filesystem decoding, and shell commands derive the primary root
from Git's absolute common directory. Process attribution is keyed by normalized
path instead of mutable branch metadata. Whitespace, embedded newlines, and
non-UTF-8 Unix pathname bytes are therefore not parsed as separators.

The expected branch lifecycle is: create a normal branch or concurrency-driven
worktree, develop and verify, merge to `main`, remove any worktree, delete the
merged local branch, then prune registrations. Dirty or unmerged work is never
deleted automatically.

## Mechanical justfile work

- Apply `[group('...')]` headings in the lifecycle order above.
- Apply `[private]` to the plumbing list.
- Apply the renames; add temporary `alias`es (`stage` -> `preview`, etc.) for muscle
  memory, to be removed later.
- Remove the cut recipes.

## Doc updates

Update references to removed recipes (notably `just run`) in `CLAUDE.md`, `AGENTS.md`,
and `docs_pgrep/reference/staging-pipeline.md` to `dev` / `preview`.

## Security notes

- Local browser dev: no change needed; pgrep endpoints already same-origin allowed.
- Phone: Tailscale keeps the bind on `127.0.0.1`; the allowlist relaxes only the network
  guard for one trusted origin, dev-gated. Full API never exposed.
- Review: instances bound to `127.0.0.1`, full API locked.

## Product ships with AI on (DONE)

Desktop first-run default is AI **on** via `ensure_first_run_defaults` in
`pylib/anki/pgrep/ai_config.py` (pure `ai_enabled` stays off for bare collections
and tests). iOS companion stays AI off. Proof line in
`docs_pgrep/proofs/submission-proofs.md` updated to match; AI-off/offline
capability remains proven.

## Phased implementation

1. Phase A (mechanical, low risk): justfile groups, renames, privates, cuts, aliases;
   doc updates. Ship and verify the list reads right. DONE.
2. Phase B: headless `dev` + live-reload, with the `--ai on|off` flag (default on). DONE.
3. Phase C: `dev-window`. DONE.
4. Phase D: `serve-tail` + the dev-gated origin allowlist. DONE.
5. Phase E: review tightening (127.0.0.1, headless instances, merged looping
   `review-sync` with auto-rebuild, demote `run-instance`). DONE.
6. Product default AI on (app-level + proof update). DONE (desktop already
   first-run on; docs/proofs aligned; iOS stays off).

Per the worktrees rule this work lives on `feat/dev-pipeline` and merges to `main` when
each phase is green (`just check`, later `just verify`).

## Decisions locked this session

- Browser-first develop; window only via `dev-window` (work) or `preview` (faithful).
- `dev` is headless; live-reload reaches browser and phone.
- Phone via Tailscale Serve + dev-gated origin allowlist, not `0.0.0.0`.
- `preview`/`preview-fresh` are dev-off (faithful); the third is `preview-optimized`.
- Names: `serve-tail`, `serve-sync`, `review-sync` (looping), `lint-fix`, `format`,
  `format-fix`, `ai-deps`.
- `ai-deps` stays an explicit command, run once per checkout (`out/pyenv` is
  per-worktree), no auto-install magic.
- `dev --ai on|off`, default on; graceful warn-and-continue when key/deps absent.
- The shipped desktop product defaults AI on (first-run); iOS stays off. Docs/proofs
  aligned.
- Cut `pgrep-demo-sync`: the lab injector plus a normal sync covers the demo path.
