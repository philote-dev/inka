# pgrep deferred to-dos

Single-line backlog for work deferred after the 2026-07-06 UI/UX and
decomposition-tutor pass. Checkboxes are the source of truth. Items marked
[demo] are natural stop-and-review checkpoints. Keep lines short.

## A. Finish the decomposition tutor (headline feature)

- [ ] A1. Generate tutor data for the remaining problems (40/137 done) `just gen-decompositions --apply` [demo]
- [ ] A2. Port iOS Problems flow from old ladder to the decomposition tutor [demo]

## B. Copy cleanup stragglers (WS6)

- [ ] B1. Sweep any pages no workstream touched for gratuitous subtitles/helper text

## C. L5.9 UX punch-list (verify each; some may be stale)

- [ ] C1. Progress "Scores" tab missing the Memory card
- [ ] C2. Settings sync URL not persisted + default port mismatch (8080)
- [ ] C3. Theme-token leak on armed reset button (raw #fff)
- [ ] C4. Study topic chip shows raw slug instead of human label
- [ ] C5. Silent exam-answer failure (add quiet retry or non-blocking notice)
- [ ] C6. Home manifold hero is decorative, wire to live scores/coverage read-model
- [ ] C7. Exam figures not served (pass stem figure through exam read model)
- [ ] C8. Diagnostic quick-checks hardcoded in frontend + no LaTeX
- [ ] C9. Gold-set gate hardening (cut refusal/malformed-MCQ rate, rerun batch)
- [ ] C10. Optional Bragg diffraction figure for p4-prob-0136

## E. Exterior UI / chrome fixes (2026-07-06 pass 2)

- [x] E1. Desktop: retitle main window, drop "User 1 - pgrep" -> "pgrep" (main.py)
- [x] E2. Desktop: exclusive default strips File/View/Tools/Help; Edit only; About rebranded. Dev keeps hosted (hatch); PGREP_SURFACE_MODE overrides. Note: app-menu name shows the process in dev, becomes "pgrep" when packaged
- [x] E2b. Desktop: added pgrep's own menus: Settings (Cmd+,) in app menu + a Go menu (Home/Study/Progress/Library, Cmd+1..4) that navigates the surface
- [ ] E3. Desktop: trim redundant copy on Home "Today" band + Study launcher
- [ ] E4. Desktop + iOS: responsive score tiles (no full-width stack, no forced scroll)
- [ ] E5. Desktop: give "Today" its own icon, distinct from the Diagnostic pulse
- [ ] E6. iOS: remove the redundant "pgrep" greeting on Home
- [ ] E7. iOS: add a Today icon for parity (distinct from diagnostic)

## D. L6 ship track (out of scope for now)

- [ ] D1. Exclusive-takeover flip
- [ ] D2. Final identity / app icon
- [ ] D3. Signed installer + phone build
- [ ] D4. Hardening (crash test, benchmark)
- [ ] D5. Submission recording
