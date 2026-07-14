# pgrep staging pipeline

The one idea that makes this simple: every pgrep screen and the dev gallery are a
single web app, served by the running app at `http://127.0.0.1:40000`. The desktop
window, the phone, and a browser tab all render the same pages. So the loop is
always the same four moves: build the web, look at it, verify, ship.

This is the curated workflow. For the exhaustive tool reference, see
`dev-harness.md`. The browser-first develop loop is implemented per
`docs_pgrep/plan/dev-pipeline-design.md`. Run `just` to see every command grouped by
this lifecycle.

## Quick start

```bash
# develop: one terminal, then browse http://127.0.0.1:40000 (or /pgrep-lab)
just dev

# optional: product window onto the same serve; phone via Tailscale
just dev-window
just serve-tail

# see it as a user, then run the gate before shipping
just preview
just verify

# review many branches at once (dashboard at http://127.0.0.1:40100)
just review
just review-sync   # combine mergeable branches into one "review" instance (loops)
```

## Stage 1: Develop (the fast loop)

One terminal plus a browser tab (and optionally a phone).

- `just dev` is the headless serve on `:40000` (no desktop window). AI is on by
  default (`just dev --ai off` to verify the offline path). The web watcher is
  bundled, so edits rebuild and browser/phone tabs reload automatically.
- Browser at `http://127.0.0.1:40000` (redirects to `/pgrep`) or `/pgrep-lab` for
  the gallery. pgrep endpoints already answer from a local browser.
- `just dev-window` shows the real product window onto the same serve (starts
  `dev` if nothing is running). Close the window anytime; the serve keeps going.
- `just serve-tail` exposes that serve to a phone on your Tailscale tailnet (no
  LAN bind; full API stays locked). Needs Tailscale installed and `just dev`
  already running.

### Reviewing several branches at once

You work across many worktrees, so `just review` serves a live dashboard (default
`http://127.0.0.1:40100`) that lists every worktree, shows each one's status, and
gives you Start and Stop buttons. Starting a branch launches a **headless**
instance on its own ports (`40000+n`) and an isolated profile, bound to
`127.0.0.1` (full API locked). When a branch is up, the dashboard links to its
app and lab in a browser tab. Leave `just review` running; closing it stops the
instances it started.

For a single combined view, `just review-sync` rebuilds a throwaway `review` branch
by merging every cleanly-mergeable feature branch onto main (conflicting ones are
skipped and reported), then keeps re-merging on an interval
(`PGREP_REVIEW_INTERVAL`, default 600s). After each merge it rebuilds the web in
the review worktree so a running instance's browser tab refreshes. Python/backend
changes still need a Stop/Start on that row. You can also drive it from a
background agent instead of leaving a terminal open.

## Stage 2: Preview (see it as a user)

- `just preview` opens the clean product surface with dev mode **off** (real
  backups and integrity checks, exactly like the shipped app) on your normal
  profile. This is what a user actually sees, and the pre-ship barrier.
- `just preview-fresh` does the same on a throwaway first-time-user profile. Delete
  the folder (default `/tmp/pgrep-newuser`) to reset, or set `PGREP_FRESH_BASE`.
- `just preview-optimized` is the same faithful product, release-compiled, to feel
  true performance.
- To fill it with realistic data: `just serve-sync` once, then inject a profile at
  `/pgrep-lab/demo`.

## Stage 3: Verify (the gate)

- `just verify` runs the full build, lint, and unit tests, then the Playwright
  end-to-end suite against the real UI. This is the one command to run before you
  ship.
- Add `just bench` (engine latency) or `just crash-test` (data safety) if you
  touched performance or the review and data path.
- Add `just ios-smoke` if you changed the shared engine or a surface the phone
  uses.

## Stage 4: Ship (prod)

- `just ship` builds the real installer artifact (`.dmg` / `.msi` / `.tar.zst`).
- Preview it first with `just preview` (or `just preview-optimized` for a
  perf-representative run); the phone ships via TestFlight or sideload.

## Reach for these while iterating

- `just check` is the build, lint, and unit gate on its own (it is inside
  `verify`).
- `just test-rust`, `just test-py`, `just test-ts` run one stack at a time.
- `just format`, `just format-fix`, `just lint`, `just lint-fix` are formatting and
  lint only.
- `just smoke` is the fastest "did I break the build" check (import plus Rust).
- `just ai-deps` once per checkout, then `just dev` (AI on by default) to exercise
  the tutor and generation. Use `just dev --ai off` to verify the offline path.

## You can ignore these day to day

They are CI plumbing or one-off maintenance, hidden from `just --list` as
`[private]` but still present: `wheels`, `minilints`, `fix-minilints`,
`ftl-deprecate`, `complexipy-diff`, and the coverage helpers. `ci`, `ftl-sync`,
`build`, and `coverage` stay public but are rarely part of the build loop.
