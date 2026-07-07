# pgrep UI/UX pass and decomposition tutor, design

Date: 2026-07-06. Status: approved for planning. Author: pair session.

This spec captures a batch of desktop and iOS UI/UX fixes plus one feature
redesign (the wrong-answer ladder becomes a decomposition tutor). It is written
to be split into small, mostly independent branches that can run in parallel.

## Context

pgrep is a Physics GRE study app forked from Anki: a Svelte/TypeScript web
frontend served through the Qt app (`ts/routes/pgrep/**`, `ts/lib/components/**`),
a Python/Rust engine (`pylib/anki/pgrep/**`, `rslib/**`), and a native iOS app
(`mobile/ios/**`) sharing the Rust engine over the C FFI. A walkthrough surfaced
several bugs and UX gaps, and the productive-failure study feature needs a
redesign. All items below were confirmed with the product owner.

## Workstreams

Each workstream is independently shippable unless a dependency is noted.

### WS1. Desktop rendering bugs

- 1a. Card reveal duplicates the question and prints the source inline.
  - Fix `ts/lib/components/CardFace.svelte` so the front shows once on reveal
    (front, then answer, not front, front, answer).
  - Extract the "Source: ..." trailer from the answer HTML and render it as a
    small source tag/chip beneath the answer, not as body text.
  - Acceptance: on reveal, the question appears once and the source shows as a
    tag; math still renders.
- 1b. Exam mode shows raw LaTeX.
  - In `ts/routes/pgrep/study/exam/+page.svelte`, run `renderMath` (from
    `$lib/pgrep/math`) on the stem, each choice, and the blind-review text, the
    way `ts/routes/pgrep/study/+page.svelte` already does for Problems.
  - Acceptance: exam stems, choices, and review render typeset math.

### WS2. Desktop nav and shell

- 2a. Re-clicking the active tab resets that surface.
  - In `ts/lib/components/NavRail.svelte` (and the layout), when the clicked
    destination equals the current route, reset the surface to its default
    state instead of a no-op (Study returns to its launcher, etc.). Prefer a
    SvelteKit invalidation/re-init over a full reload.
  - Acceptance: while in an in-progress Study session, clicking Study returns to
    the launcher; same principle for other surfaces.
- 2b. Collapsed restore button overlaps the "X left" session counter.
  - The counter lives in `ts/lib/components/StudyFrame.svelte` `.bar` (`.count`
    at padding 20/28); the restore button is fixed at top:14/left:14. Reposition
    so they never collide (shift the counter when the rail is collapsed, or move
    the restore control).
  - Acceptance: in a session with the rail collapsed, the restore control and
    the counter do not overlap at any width.
- 2c/2d. Hide the sidebar anytime, with a reliable restore.
  - Add an always-available collapse toggle in the rail (today the chevron only
    renders while `learning || narrow`; make it available in the normal state
    too) in `ts/lib/components/NavRail.svelte`.
  - When collapsed, keep the persistent top-left expand button AND make the
    left-edge handle always faintly visible (not opacity 0 until hover) and more
    prominent on hover, in `ts/routes/pgrep/+layout.svelte`.
  - Acceptance: the user can hide the rail on any surface and always sees a way
    to bring it back (button + faint edge handle).

### WS3. Library layout

- Restructure `ts/routes/pgrep/library/+page.svelte` from the current left/right
  split to a vertical stack: the authoring card full-width on top, the "Matching
  cards" results below it.
- Acceptance: authoring is wide on top; results render beneath; generation and
  refusal behavior unchanged.

### WS4. Study ladder becomes a decomposition tutor (largest)

Replaces the current static Nudge/Break-it-down/Sibling/Reveal ladder in the
Problems door with a gated, generative tutor. No nudge.

Content pipeline (batch, offline):

- Add a generator (a `content/tools/` script + a `just` recipe) that, for each
  problem, produces 2 to 3 subproblems (count by complexity) via the API, each
  with: a multiple-choice question with a correct key and distractors, a model
  "explain why" rationale, and a named source. Generate several numeric variants
  per subproblem so a repeat never carries the same numbers.
- Store the decompositions with the content set and load them into the engine so
  runtime never calls the API to fetch them.

Runtime (Problems door, on a miss):

- Skip straight to decomposition (no nudge). Present the subproblems in order.
- Per subproblem: the learner picks an MCQ answer and writes an "explain why".
  - MCQ must be correct to advance (unlimited retries).
  - With AI on, the "explain why" is graded by the AI with a lenient
    "good enough" bar plus feedback; it must pass to advance.
  - With AI off, the "explain why" step is skipped; only the MCQ gates.
  - No skip/next control lets the learner breeze through. This is forced
    learning.
- After all subproblems are satisfied, move to the next problem. The missed
  original re-enters the same session's rotation and returns later with a
  different numeric variant. The original's answer is never revealed outright.

Touches: `ts/routes/pgrep/study/+page.svelte`, new subproblem components under
`ts/lib/components/`, backend handlers in `qt/aqt/pgrep.py` and
`pylib/anki/pgrep/**` (a decomposition module + an "explain why" grader that
reuses the existing AI layer and its source/refusal guarantees), and possibly
proto/backend wiring if a new RPC is needed.

Acceptance:

- A miss opens decomposition, not a hint list or an answer reveal.
- Each subproblem requires a correct MCQ and (AI on) an approved explanation.
- The learner cannot advance by pressing a button alone.
- The missed problem recurs the same session with different numbers.
- With AI off, the ladder runs MCQ-only and the app still works.

### WS5. iOS parity

In `mobile/ios/**`:

- 5a. Home shows only "Start today's session"; move "Practice problems" and
  "Take a timed exam" into the Study tab (add them there if absent).
- 5b. The three scores render compactly on Home, above the fold (no scroll on a
  standard device).
- 5c. Home shows the real 3D manifold by hosting the existing WebGL manifold in
  a `WKWebView`, not a 2D fallback.
- 5d. Progress drops the "Progress" title and the "Coverage gates Readiness ..."
  subtitle.
- 5e. Settings becomes more complete: target retention, test date, diagnostic
  re-run, theme, export, reset (match the desktop Settings surface where it
  makes sense on mobile).
- Acceptance: iOS Home matches the desktop information model (session entry +
  clean scores + real manifold), Study holds the practice/exam entries, Progress
  is header-light, Settings is fuller.

### WS6. Copy cleanup (global)

- Remove the Home subtitle "Memory, performance, and readiness, shown honestly."
- Sweep every pgrep surface for unnecessary subtitles and helper text; keep the
  voice cogent and concise. Distribute the per-page trims into the workstream
  that already edits that page to avoid merge conflicts; a small dedicated pass
  covers pages no other workstream touches.
- Acceptance: no gratuitous subtitles remain; each surface reads cleanly.

### WS7. Reset also clears the demo profile

- `pylib/anki/pgrep/settings.py` `reset_progress` currently forgets only
  `pgrep::seeded` cards, so the dev demo profile's Memory survives a Reset.
  Extend Reset to also clear the demo profile (its `pgrep::demo` cards and
  attempts) so all three scores reset consistently.
- Acceptance: after Reset with a demo profile present, all three scores abstain.

## Parallelization and branch strategy

One concern per branch, each in `.worktrees/<branch>` off the latest `main`,
merged back when green (per the repo worktree rules). Copy cleanup (WS6) is
folded into each page-owning branch to avoid conflicts.

Conflict map (files that more than one workstream could touch):

- `ts/routes/pgrep/study/+page.svelte`: WS2 (re-click reset for Study) and WS4
  (Problems flow). Resolve by doing the Study reset hook inside the WS4 branch,
  or by landing WS2 first and rebasing WS4. WS4 owns this file.
- Shell files (`+layout.svelte`, `NavRail.svelte`, `StudyFrame.svelte`): WS2
  only.
- `CardFace.svelte`: WS1 only.
- `library/+page.svelte`: WS3 only.
- `exam/+page.svelte`: WS1 only.
- `settings.py`: WS7 only.
- `mobile/ios/**`: WS5 only.

Parallel groups:

- Wave 1 (fully independent, run together): WS1 (bugs), WS3 (Library), WS5 (iOS),
  WS7 (Reset). Each carries its own copy trims for the pages it touches.
- Wave 1 also: WS2 (desktop nav). Independent of the above; only shares the
  Study file lightly, handled by giving WS4 ownership of that file.
- Wave 2 (after WS2 merges, to keep the Study file clean): WS4 (decomposition
  tutor), the largest, on its own branch with the content pipeline.

Rationale: WS4 is the deepest and most conflict-prone on the Study file, so it
lands last and rebases on a clean `main` that already has WS2's nav changes.
Everything else is genuinely parallel.

## Risks and open items

- WS4 content generation cost and quality: pre-generating subproblem variants for
  the whole bank uses the API; quality must clear the same source/refusal bar as
  the card and problem generators. Reuse the existing gold-set gate style checks.
- WS4 "explain why" grader latency with AI on: keep it a single lenient call with
  feedback; cache nothing sensitive.
- WS5c WKWebView manifold: confirm the manifold route renders standalone in a
  webview and reads the synced scores; watch performance on device.
- Verification: each branch must pass `just check`; WS5 must also build the
  xcframework and run the iOS tests. Re-run `just pgrep-ai-deps` after any full
  rebuild before demoing AI.

## Non-goals

- No change to the scoring models, the Rust `PointsAtStake` selector, or the sync
  engine.
- No new top-level surfaces; this is polish plus one feature redesign.
