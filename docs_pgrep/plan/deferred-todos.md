# pgrep to-dos

Two buckets. **Finish the app** is everything a learner still sees or does that
is incomplete. **Ship the app** is turning it into an installable product.
Checkboxes are the source of truth. `[demo]` marks natural stop-and-review points.

## 1. Finish the app (learner-facing)

Content and features:

- [ ] Content quality program (foundry / verifier / shadow / human ruler): see the
  status board in
  [`content-foundry-and-verifier-design.md`](content-foundry-and-verifier-design.md)
  — **next gate is WS10 (usage ledger + budgets)** before any paid shadow or
  foundry online run
- [ ] Generate / refresh decomposition tutor coverage where still missing (triple
  pool already raised coverage substantially; confirm remaining gaps after the
  calibrated gate) `just gen-decompositions --apply` [demo]
- [ ] Port the iOS Problems flow from the old ladder to the decomposition tutor [demo]
- [ ] Content quality: gold-set gate hardening (cut the refusal and malformed-MCQ rate, rerun the batch)
- [ ] Optional Bragg diffraction figure for problem p4-prob-0136

UI polish (audited 2026-07-06; most were already fixed in later L5.9 work):

- [ ] Exam-answer failure already shows "Something went wrong. Try again." (not silent). Optional: a quiet auto-retry so a dropped call self-heals
- [ ] Final copy sweep of any page we have not already trimmed (subjective, wants a review pass)

## 2. Ship the app (packaging and release)

- [ ] Final identity and app icon
- [ ] Signed installer plus the phone build
- [ ] Hardening: crash test and benchmark
- [ ] Record the submission and demo

## Deferred from the structural de-Anki pass

The `feat/l6-structural-de-anki` worktree rebuilds the exclusive menu bar (pgrep's own
app/Edit/Go menus, Anki's never built), makes Anki's profile chooser unreachable, and adds the
macOS unified title bar. Parked, not merged. It defers:

- [ ] iOS first-run login gate (desktop gate is hooked up; phone still signs in from Settings only) — see `login-gate-beta-handoff.md` Phase 6
- [ ] pgrep's own card template, to migrate off Anki's stock `Basic` note type (touches the seeder, card sets, and generation)
- [ ] Production credential source / self-serve signup — hosting decision (see `hosting-roadmap.md`)

## Done

- [x] In-app sync/export operation UI: progress, full-sync decisions, errors, and cancel live in the shell (`OperationCenter`); native Qt only for `PGREP_SURFACE_MODE=off`. Devices framing + last-synced on desktop and iOS Settings — see `in-app-sync-and-export-ui.md`
- [x] First-run login gate host hookup: `pgrepAuthStatus` / `pgrepSignIn` / `pgrepGateSkip`, shell overlay in `+layout.svelte`, skip in profile meta — see `login-gate-beta-handoff.md` (iOS first-run gate still later)
- [x] Standalone desktop chrome: window titled "pgrep", Anki admin menus hidden, exclusive surface is the default (the takeover flip); dev keeps the hatch via `PGREP_SURFACE_MODE=hosted`
- [x] Native pgrep menus: Settings (Cmd+,) and a Go menu (Home/Study/Progress/Library, Cmd+1..4)
- [x] Home (desktop + iOS): compact responsive score tiles, one-action Today band, play icon, removed the greeting and the "shown honestly" subtitle
- [x] Study launcher copy tightened; iOS/desktop session copy aligned; ranges read "X to Y"
- [x] Decomposition tutor engine and desktop UI (gated MCQ + AI-graded explanation, re-queues the missed problem)
- [x] Earlier passes: card-reveal and exam render bugs, desktop nav/shell, Library vertical layout, reset clears the demo profile, iOS parity (real 3D manifold, fuller Settings)
- [x] UI-polish audit (2026-07-06): Progress Memory card present, Settings sync URL persisted with 8090 aligned, reset button uses a token, Study chip shows a human label, Home manifold reads a live backend, exam figures served, diagnostic quick-checks are backend + LaTeX
