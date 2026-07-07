# pgrep to-dos

Two buckets. **Finish the app** is everything a learner still sees or does that
is incomplete. **Ship the app** is turning it into an installable product.
Checkboxes are the source of truth. `[demo]` marks natural stop-and-review points.

## 1. Finish the app (learner-facing)

Content and features:

- [ ] Generate decomposition tutor data for every problem (only 40/137 today, so most misses do not open the tutor) `just gen-decompositions --apply` [demo]
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

- [ ] First-run login gate: a pgrep sign-in with a configurable server URL and a "continue offline" escape, reusing the existing sync sign-in. Best after the hosting decision (see `hosting-roadmap.md`)
- [ ] pgrep's own card template, to migrate off Anki's stock `Basic` note type (touches the seeder, card sets, and generation)

## Done

- [x] Standalone desktop chrome: window titled "pgrep", Anki admin menus hidden, exclusive surface is the default (the takeover flip); dev keeps the hatch via `PGREP_SURFACE_MODE=hosted`
- [x] Native pgrep menus: Settings (Cmd+,) and a Go menu (Home/Study/Progress/Library, Cmd+1..4)
- [x] Home (desktop + iOS): compact responsive score tiles, one-action Today band, play icon, removed the greeting and the "shown honestly" subtitle
- [x] Study launcher copy tightened; iOS/desktop session copy aligned; ranges read "X to Y"
- [x] Decomposition tutor engine and desktop UI (gated MCQ + AI-graded explanation, re-queues the missed problem)
- [x] Earlier passes: card-reveal and exam render bugs, desktop nav/shell, Library vertical layout, reset clears the demo profile, iOS parity (real 3D manifold, fuller Settings)
- [x] UI-polish audit (2026-07-06): Progress Memory card present, Settings sync URL persisted with 8090 aligned, reset button uses a token, Study chip shows a human label, Home manifold reads a live backend, exam figures served, diagnostic quick-checks are backend + LaTeX
