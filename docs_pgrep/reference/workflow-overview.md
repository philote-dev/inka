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

The browser-first develop loop is implemented on `feat/dev-pipeline` per
`docs_pgrep/plan/dev-pipeline-design.md`. Run `just` to see all commands grouped by
this lifecycle.

- Develop: `just dev` (headless serve + live-reload), optional `just dev-window`
  and `just serve-tail` (phone via Tailscale). Tune at
  `http://127.0.0.1:40000/pgrep-lab`.
- Preview as a user: `just preview` (faithful, dev mode off, the pre-ship barrier),
  `just preview-fresh` (throwaway first-run profile), `just preview-optimized`
  (release-compiled).
- Verify: `just verify` (build + lint + unit + e2e); `just check` is the faster subset.
- Ship: `just ship` builds the real `.dmg` / `.msi` / `.tar.zst`.

## Build modes and release channels (the professional model)

- Build modes: dev (`just dev`), preview (`just preview`, dev off, the barrier),
  release (`just ship`).
- Channels: start with beta + stable, add nightly later. One updater and appcast carry
  them.
- Promotion is trunk-based: keep `main` green, tag a candidate, build the artifact once,
  test it, promote the same artifact from beta to stable. Never freeze main; hide
  unfinished work behind flags (`PGREP_SURFACE_MODE`, the AI toggle, `ANKIDEV`).

## Multi-branch review (tools/pgrep-review, tools/pgrep-sync-review)

- `just review` serves a live dashboard (default `http://127.0.0.1:40100`) listing every
  worktree with status and Start/Stop; instances run headless on `127.0.0.1`, and when
  up each links to its app and lab in a browser tab.
- Phone access: `just serve-tail` (Tailscale Serve, stays bound to `127.0.0.1`).
- `_review-instance <n>` (private plumbing) runs a worktree on offset ports (`40000+n`,
  `8080+n`) with an isolated profile and a unique `ANKI_SINGLE_INSTANCE_KEY`. That key is
  the fix that let multiple instances actually launch instead of forwarding to the
  already-running app; you normally drive it from the dashboard.
- `just review-sync` rebuilds a throwaway `review` branch by merging every cleanly
  mergeable feature branch onto main (conflicts skipped and reported), looping on an
  interval; after each merge it rebuilds the web so a running tab can refresh.
  Python/backend changes still need a Stop/Start on that row.

## Product shell (de-Anki) direction

- Branding sweep (strings, About, sync copy) is done in the `feat/l6-de-anki` worktree
  (`docs_pgrep/plan/production-de-anki-design.md`).
- Structural work:
  - `docs_pgrep/plan/structural-de-anki-design.md` (+ `structural-de-anki-plan.md`): the
    executed pass. Rebuild the exclusive menu bar, make Anki's profile chooser unreachable
    (one implicit account), and add the macOS unified title bar. (`interface-prune-design.md`
    is the superseded earlier draft.)
  - `docs_pgrep/plan/login-gate-beta-handoff.md`: the model-B first-run login gate. Page
    artifacts are built (`LoginGate.svelte`, the `/pgrep/login` route, a gallery fixture);
    the office-beta hookup wires the startup routing.
  - `docs_pgrep/plan/engine-prune-design.md`: the large, gated "own the engine"
    effort. Do it last; upstream-mergeability is the decision gate.
  - `docs_pgrep/plan/shell-profiles-login-handoff.md`: the original detailed handoff.
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
- Verify the app UI from the phone via `just serve-tail` (Tailscale, once built); agent
  monitoring is the separate iOS-app path.

## Skills (project-scoped)

- `p-demo`: light up the three scores with a demo stage, then clear it. Lives under
  `.claude/skills/` (local to this clone).
- Lab UI demos use the global `dev-gallery` skill: find `/pgrep-lab`, match an existing
  page, register in `LabNav` / `LAB_PAGES`. No project-specific lab-demo skill.
- Remaining to build: `pgrep-bridge-endpoint`, `pgrep-string`, `pgrep-surface`,
  `pgrep-screenshot`.

## State

- The command set was redesigned and renamed on `feat/dev-pipeline` (see
  `docs_pgrep/plan/dev-pipeline-design.md`): lifecycle groups in `just --list`,
  `preview` (replacing `stage`/`candidate`, now dev-off), a looping `review-sync`,
  `ship`, and the coming browser-first `dev` / `dev-window` / `serve-tail`. Old names
  still work as aliases during the transition.

## Open decisions and next steps

1. Commit and push the pending batch so the worktrees can pick it up.
2. Updater direction (A / B / C) and channel count (beta + stable, or add nightly).
3. Build the remaining skills (`pgrep-bridge-endpoint`, etc.).
4. Test a cloud agent plus Cursor iOS monitoring.
5. Execute the interface prune (in `feat/l6-structural-de-anki`); engine prune later,
   gated on the upstream decision.
