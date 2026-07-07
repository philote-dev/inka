# pgrep staging pipeline

The one idea that makes this simple: every pgrep screen and the dev gallery are a
single web app, served by the running app at `http://127.0.0.1:40000`. The desktop
window, the phone, and a browser tab all render the same pages. So the loop is
always the same four moves: build the web, look at it, verify, ship.

This is the curated workflow. For the exhaustive tool reference, see
`dev-harness.md`.

## Quick start

```bash
# develop: two terminals, then tune at http://127.0.0.1:40000/pgrep-lab
just run
just web-watch

# see it as a user, then run the gate before shipping
just stage
just verify

# review many branches at once (dashboard at http://127.0.0.1:40100)
just review
just sync-review   # combine mergeable branches into one "review" instance
```

## Stage 1: Develop (the fast loop)

Two terminals plus a browser tab.

- `just run` runs the app. It also serves the web at `:40000` and is the live
  bridge the gallery's data buttons need.
- `just web-watch` rebuilds and reloads on every save.
- Browser at `http://127.0.0.1:40000/pgrep-lab` to build and tune components in the
  gallery, or `/pgrep` for the real surfaces.

Edit under `ts/`, save, and the app's webview reloads. Refresh the browser tab to
pick up the same rebuild. This is your build-and-tune-in-the-gallery loop.

### Reviewing several branches at once

You work across many worktrees, so `just review` serves a live dashboard (default
`http://127.0.0.1:40100`) that lists every worktree, shows each one's status, and
gives you Start and Stop buttons. Starting a branch launches its app on its own
ports (`40000+n` for the web and lab, `8080+n` for debug) and an isolated profile,
so several run at once without clashing. When a branch is up, the dashboard links
straight to its dev lab. Leave `just review` running; closing it stops the
instances it started.

To launch one by hand from a worktree instead:

```
ANKI_SINGLE_INSTANCE_KEY=pgrep-inst-5 ANKI_API_HOST=0.0.0.0 ANKI_API_PORT=40005 QTWEBENGINE_REMOTE_DEBUGGING=8085 ANKI_BASE=/tmp/pgrep-inst-5 ./run
```

Each branch serves its own compiled lab, so they cannot feed one shared lab; you
view them side by side.

For a single combined view, `just sync-review` rebuilds a throwaway `review` branch
by merging every cleanly-mergeable feature branch onto main (conflicting ones are
skipped and reported). It then appears as its own row in the dashboard, so Start it
to see the combined work in one lab. `just review-loop` reruns the merge on an
interval to keep it fresh; restart the review instance from the dashboard to pick
up changes. You can also drive the loop with the `/loop` skill or a background
agent instead of leaving a terminal open.

## Stage 2: Stage (see it as a user)

- `just stage` opens the clean product surface (exclusive mode: no Anki menus, no
  dev lab) on your normal profile. This is what a user actually sees.
- `just fresh` does the same on a throwaway first-time-user profile. Delete the
  folder (default `/tmp/pgrep-newuser`) to reset, or set `PGREP_FRESH_BASE`.
- To fill it with realistic data: `just sync-server` once, then inject a profile at
  `/pgrep-lab/demo`, or `just pgrep-demo-sync` to prime and verify an account.

## Stage 3: Verify (the gate)

- `just verify` runs the full build, lint, and unit tests, then the Playwright
  end-to-end suite against the real UI. This is the one command to run before you
  ship.
- Add `just bench` (engine latency) or `just crash-test` (data safety) if you
  touched performance or the review and data path.
- Add `just ios-smoke` if you changed the shared engine or a surface the phone
  uses.

## Stage 4: Ship (prod)

- `just run-optimized` sanity-checks the release build (`just run` is a dev build,
  not prod).
- Package with the installer (`qt/installer/`), and the phone via TestFlight or
  sideload.

## Reach for these while iterating

- `just check` is the build, lint, and unit gate on its own (it is inside
  `verify`).
- `just test-rust`, `just test-py`, `just test-ts` run one stack at a time.
- `just fmt`, `just fix-fmt`, `just lint`, `just fix-lint` are formatting and lint
  only.
- `just smoke` is the fastest "did I break the build" check (import plus Rust).
- `just run-ai` (after `just pgrep-ai-deps` once) is for demoing the AI tutor and
  generation.

## You can ignore these day to day

They are CI plumbing or one-off maintenance, load-bearing in CI or the submission
but not part of the build loop: `ci`, `complexipy-diff`, `ftl-sync`,
`ftl-deprecate`, `minilints`, the `coverage` variants, and the docs-site recipes
(`docs`, `docs-serve`, `docs-rust`).
