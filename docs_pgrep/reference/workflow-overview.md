# pgrep workflow and decisions overview

Date: 2026-07-07. A durable map of the dev, review, and ship workflow and the decisions
made this session, so it survives chat compaction. Detailed docs are linked; this is the
index.

## Mental model

Every pgrep screen and the dev lab are one SvelteKit web app, served by the running app at
`http://127.0.0.1:40000`. The desktop window, the iOS app, and a browser tab all render the
same pages. Surface modes (`qt/aqt/pgrep_host.py`) decide what a run shows: `exclusive`
(the product, default), `hosted` (product plus the Anki dev hatch), `off` (stock Anki).

## Staging pipeline (docs_pgrep/reference/staging-pipeline.md)

- Develop: `just run` + `just web-watch`, tune at `http://127.0.0.1:40000/pgrep-lab`.
- Stage as a user: `just stage` (dev build, product surface), `just fresh` (throwaway
  first-run profile).
- Candidate, the barrier: `just candidate` runs like the shipped app (dev mode off,
  exclusive). The gate between dev and shipping.
- Verify: `just verify` (build + lint + unit + e2e); `just check` is the faster subset.
- Ship: `just run-optimized` (release-optimized run), then `./tools/build-installer` for the
  real `.dmg` / `.msi` / `.tar.zst`.

## Build modes and release channels (the professional model)

- Build modes: dev (`just run`), candidate (`just candidate`), release
  (`./tools/build-installer`).
- Channels: start with beta + stable, add nightly later. One updater and appcast carry
  them.
- Promotion is trunk-based: keep `main` green, tag a candidate, build the artifact once,
  test it, promote the same artifact from beta to stable. Never freeze main; hide
  unfinished work behind flags (`PGREP_SURFACE_MODE`, the AI toggle, `ANKIDEV`).

## Multi-branch review (tools/pgrep-review, tools/pgrep-sync-review)

- `just review` serves a live dashboard (default `http://127.0.0.1:40100`) listing every
  worktree with status and Start/Stop buttons; when up, each links to its lab.
- `just review-lan` binds `0.0.0.0` so your phone on the same Wi-Fi can open it at
  `http://<mac-lan-ip>:40100/` (was `10.10.1.38`). Trusted networks only.
- `just run-instance <n>` runs a worktree on offset ports (`40000+n`, `8080+n`) with an
  isolated profile and a unique `ANKI_SINGLE_INSTANCE_KEY`. That key is the fix that let
  multiple instances actually launch instead of forwarding to the already-running app.
- `just sync-review` rebuilds a throwaway `review` branch by merging every cleanly
  mergeable feature branch onto main (conflicts skipped and reported); it shows as its own
  dashboard row. `just review-loop` reruns it on an interval.

## Product shell (de-Anki) direction

- Branding sweep (strings, About, sync copy) is done in the `feat/l6-de-anki` worktree
  (`docs_pgrep/plan/production-de-anki-design.md`).
- Structural work, specced but not built:
  - `docs_pgrep/plan/interface-prune-design.md`: remove Anki's menus, deck
    browser, add-ons, and the profile chooser; collapse to one implicit account; the
    model-B login gate.
  - `docs_pgrep/plan/engine-prune-design.md`: the large, gated "own the engine"
    effort. Do it last; upstream-mergeability is the decision gate.
  - `docs_pgrep/plan/shell-profiles-login-handoff.md`: the detailed handoff.
- Login model: a single implicit local account plus a sync sign-in (model B). Production
  path: self-hosted sync server (`anki-sync-server-enhanced`) on Hetzner or Fly.io,
  Cloudflare R2 backups, Firebase Auth for signup. About $10/month to launch.

## Updater (docs_pgrep/plan/updater-design.md)

- Options: A reuse and rebrand the existing GitHub-release updater (fast, recommended v1),
  B Sparkle + WinSparkle (signed appcast, background self-update, the gold standard), C
  fully custom.
- Decision still open (A / B / C). Channels carried by the updater (beta opt-in, stable
  default).

## Durable orchestrator + mobile (Cursor)

- Durability: push long work to Cloud Agents / cloud subagents (`/in-cloud`); they run for
  hours independent of the Mac. Fan out with `/multitask` or Build in Parallel. Recurring
  work via Automations (cron or event); `/loop` is local-only.
- Mobile: the Cursor iOS app shows and steers cloud agents only. A local Mac chat is
  invisible until handed off via `/remote-control`, Move to Cloud, or My Machines.
- Gotchas: Remote Control needs Cursor 3.9.8+, the Agents Window, a git-backed workspace, a
  paid plan, and (Teams) admin enablement. Cloud agents need standard (not Legacy) Privacy
  Mode, GitHub app access, and the branch pushed (uncommitted work is not carried).
- Verify the app UI from the phone via `just review-lan`; agent monitoring is the separate
  iOS-app path.

## Skills (.cursor/skills/, project-scoped)

- `pgrep-lab-demo`: add a reviewable feature or component demo to the dev lab.
- `p-demo`: light up the three scores with a demo stage, then clear it.
- Project-scoped on purpose: they hardcode pgrep paths, so they must not be used in other
  repos. A general discovery-based skill trades away the precision that makes them useful.
- Remaining to build: `pgrep-bridge-endpoint`, `pgrep-string`, `pgrep-surface`,
  `pgrep-screenshot`.
- Open: whether to adopt a `p-` prefix for all (for example `p-lab-demo`).

## State: committed vs pending

- Pushed to main (`0732eafc5`): the first pipeline batch (`stage`, `fresh`, `verify`,
  `run-instance`, `review`, `sync-review` recipes; `tools/pgrep-review` and
  `tools/pgrep-sync-review`; `staging-pipeline.md`; the three L6 design docs).
- Uncommitted: `just candidate`, the review dashboard LAN host config and `just
  review-lan`, the build-modes and channels doc additions, the `.cursor/skills/` skills,
  and this overview.

## Open decisions and next steps

1. Commit and push the pending batch so the worktrees can pick it up.
2. Updater direction (A / B / C) and channel count (beta + stable, or add nightly).
3. Skill naming convention (`p-` prefix) and build the remaining skills.
4. Test a cloud agent plus Cursor iOS monitoring.
5. Execute the interface prune (in `feat/l6-structural-de-anki`); engine prune later,
   gated on the upstream decision.
